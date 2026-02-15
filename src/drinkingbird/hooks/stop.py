"""Stop Hook - Decides whether to allow agent to stop or nudge it back to work."""

from __future__ import annotations

import json
import os
import re
import signal
from typing import Any

from drinkingbird.hooks.base import DebugFn, Decision, Hook, HookResult

# Standard project files that don't count as implementation specs
IGNORED_DOC_FILES = {"CLAUDE.md", "AGENTS.md", "README.md"}


SYSTEM_PROMPT = """You supervise an AI coding agent. Decide if it should stop.

## Step 1: Determine session type from USER INPUT

Look at ORIGINAL INTENT and the user's messages:

**INTERACTIVE** - user is present, conversing:
- Questions, short commands, feedback
- Back-and-forth dialogue

**AUTONOMOUS** - user assigned a task and left:
- User referenced a spec/plan document with implementation steps
- Agent executing a multi-step plan independently

## Step 2: Check for incomplete work (BOTH session types)

BLOCK if the agent's own output admits the work is not done. Look for:
- "remaining work", "remaining failures", "next steps", "future session", "next session"
- Progress metrics short of the target (e.g., 137/945, 14.5%)
- "implementation continues", "work continues", "to be completed", "ready to continue"
- Framing partial progress as a "summary" or "session summary"
- Deferring tasks: "remaining for future", "resume work", instructions for how to continue later
- Listing incomplete tasks with labels like "⏸️", "TODO", "pending"

This rule applies regardless of session type. An agent that says there is remaining work is not done. An agent that tells the user how to resume later is avoiding work now.

## Step 3: Branch based on session type

### If INTERACTIVE → default is ALLOW

ALLOW unless the agent is:
- Permission-seeking ("shall I proceed?", "ready for feedback")
- Presenting menus of options ("1. Merge 2. Create PR 3. Keep as-is")
- Avoiding work ("due to complexity", "in a future session")
- Deviating from user intent/instructions
- Reporting incomplete work (caught by Step 2)

Otherwise ALLOW. Normal conversation, answering questions, saying "user needs to deploy" = ALLOW.

If you BLOCK: brief nudge only. Examples:
- Permission-seeking/menus: "State what's done and stop. Don't ask."
- Avoiding work / incomplete: "100% is the target. Keep going."

### If AUTONOMOUS → default is BLOCK

BLOCK unless the agent has:
- Completed the task WITH EVIDENCE (files changed, tests pass)
- Hit a genuine blocker (needs secret, external access, user decision)

Presenting menus ("Which option?", "What would you like to do?") is NOT completion.
Summaries with "remaining work" or progress below target are NOT completion.
Otherwise BLOCK. Keep the agent working.

If you BLOCK:
- For menus/permission-seeking: "State what's done and stop. Don't ask."
- Otherwise: ONE specific directive from the spec document.

## Step 4: Check for KILL

KILL only if:
- Looping on same failure 3+ times
- Hallucinating nonexistent things
- Completely off-task

## Response
{"session_type": "interactive"|"autonomous", "decision": "allow"|"block"|"kill", "reason": "...", "message": "..."}
"""

# Response schema for structured output
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "session_type": {
            "type": "string",
            "enum": ["interactive", "autonomous"],
        },
        "decision": {
            "type": "string",
            "enum": ["allow", "block", "kill"],
        },
        "reason": {"type": "string"},
        "message": {"type": "string"},
    },
    "required": ["session_type", "decision", "reason", "message"],
    "additionalProperties": False,
}


class StopHook(Hook):
    """Hook that decides whether to allow agent to stop."""

    event_name = "Stop"

    # Regex patterns that always BLOCK regardless of LLM judgment.
    # These catch common work-avoidance patterns in the assistant's last message.
    PRECHECK_BLOCK_PATTERNS = [
        # Permission-seeking
        r"(?:shall i|should i|would you like me to|want me to) (?:proceed|continue|start|go ahead)",
        r"ready for (?:your )?feedback",
        r"let me know (?:if|when|how) you",
        # Deferring work
        r"(?:remaining|next|future) (?:session|iteration|phase)",
        r"(?:resume|continue|pick up) (?:work|this|the work|implementation)",
        r"ready to continue in",
        r"future (?:remediation|implementation|development)",
        # Admitting incomplete work
        r"remaining (?:work|failures|tasks|items|scenarios)",
        r"(?:implementation|work) continues",
        # Failures reported — anything failing is not complete
        r"❌",
        r"\d+\s*(?:/\s*\d+\s+)?failing",
        r"failures?\s*[:(]",
        r"CRITICAL",
        r"PANIC",
    ]

    def _precheck_assistant(self, text: str, debug: DebugFn) -> str | None:
        """Check assistant text against hard-coded block patterns.

        Returns a block message if matched, None otherwise.
        """
        if not text:
            return None
        for pattern in self.PRECHECK_BLOCK_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                debug(f"Precheck matched: {pattern}")
                return "Keep going."
        return None

    def handle(self, hook_input: dict[str, Any], debug: DebugFn) -> HookResult:
        """Handle stop hook event."""
        debug(f"Stop hook: LLM configured: {self.llm_provider is not None}")

        transcript_path = hook_input.get("transcript_path", "")
        cwd = hook_input.get("cwd", os.getcwd())
        conversation_depth = getattr(self.config, "conversation_depth", 1)

        # Parse transcript
        messages = self._parse_transcript(transcript_path, debug)
        debug(f"Parsed {len(messages)} messages")

        if not messages:
            debug("No messages - blocking with default message")
            return HookResult.block("Great work! Keep going.")

        # Extract relevant messages based on depth
        first_user, last_user = self._extract_user_messages(messages)
        last_assistant = self._extract_last_assistant(messages)

        # Hard gate: block obvious patterns before LLM call
        if last_assistant:
            block_msg = self._precheck_assistant(last_assistant, debug)
            if block_msg:
                debug(f"Precheck BLOCK: {block_msg}")
                return HookResult.block(block_msg)

        debug(f"First user: {first_user[:100] if first_user else None}...")
        debug(f"Last assistant: {last_assistant[:100] if last_assistant else None}...")

        # Extract @mentions from ALL user messages (deduplicated)
        all_user_messages = self._extract_all_user_messages(messages)
        all_mentions: list[str] = []
        seen: set[str] = set()
        for user_msg in all_user_messages:
            for mention in self._extract_mentions(user_msg):
                if mention not in seen:
                    all_mentions.append(mention)
                    seen.add(mention)

        files = self._read_mentioned_files(all_mentions, cwd, debug)

        # Build prompt
        user_prompt = self._build_user_prompt(
            first_user, last_user, last_assistant, files
        )
        debug(f"User prompt length: {len(user_prompt)}")

        # Call LLM - if not configured, still BLOCK by default
        if not self.llm_provider or not self.llm_provider.is_configured():
            debug("No LLM configured - blocking with default message")
            return HookResult.block("Great work! Keep going.")

        debug("Calling LLM...")
        response = self.llm_provider.call(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=RESPONSE_SCHEMA,
        )
        debug(f"LLM response: {response.content}")

        # Log generation to tracer
        if self.tracer:
            self.tracer.generation(
                name="evaluate_stop_decision",
                model=response.model or self.llm_provider.model or "unknown",
                input_data={
                    "system_prompt": SYSTEM_PROMPT,
                    "user_prompt": user_prompt,
                },
                output_data=response.content,
                usage=response.usage.to_dict() if response.usage else None,
                metadata={"response_schema": RESPONSE_SCHEMA},
            )

        session_type = response.content.get("session_type", "autonomous")
        decision = response.content.get("decision", "block")  # Default to BLOCK
        reason = response.content.get("reason", "")
        message = response.content.get("message", "")

        debug(f"Session type: {session_type}, Decision: {decision}")

        if decision == "kill":
            debug("Killing parent process")
            os.kill(os.getppid(), signal.SIGKILL)
            return HookResult.kill(reason or "Agent terminated")

        if decision == "allow":
            debug(f"ALLOW: {reason}")
            return HookResult.allow(reason)

        # decision == "block"
        if not message:
            message = "Keep going."
        # Only include real spec documents, not standard project files
        real_docs = [m for m in files.keys() if os.path.basename(m) not in IGNORED_DOC_FILES]
        if real_docs:
            refs = ", ".join(f"@{m}" for m in real_docs)
            message = f"{message}\n\nReferenced documents: {refs}"
        return HookResult.block(message)

    def _parse_transcript(
        self, transcript_path: str, debug: DebugFn
    ) -> list[dict]:
        """Parse JSONL transcript file into list of messages."""
        messages = []
        if not transcript_path:
            debug("No transcript path provided")
            return messages

        try:
            with open(transcript_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            msg = json.loads(line)
                            messages.append(msg)
                        except json.JSONDecodeError as e:
                            debug(f"Failed to parse transcript line: {e}")
                            continue
        except FileNotFoundError:
            debug(f"Transcript file not found: {transcript_path}")
        except PermissionError:
            debug(f"Permission denied reading transcript: {transcript_path}")

        return messages

    def _extract_all_user_messages(self, messages: list[dict]) -> list[str]:
        """Extract all user messages from transcript."""
        user_messages = []
        for msg in messages:
            # Claude Code format: type="user", message={role, content, ...}
            if msg.get("type") == "user":
                inner_msg = msg.get("message", {})
                if isinstance(inner_msg, dict):
                    content = inner_msg.get("content", "")
                    if isinstance(content, str):
                        user_messages.append(content)
                    elif isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif isinstance(block, str):
                                text_parts.append(block)
                        user_messages.append("\n".join(text_parts))
                elif isinstance(inner_msg, str):
                    user_messages.append(inner_msg)
            # API format: role="user" at top level
            elif msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_parts.append(block)
                    content = "\n".join(text_parts)
                user_messages.append(content)
        return user_messages

    def _extract_user_messages(
        self, messages: list[dict]
    ) -> tuple[str | None, str | None]:
        """Extract first and last user messages from transcript."""
        user_messages = self._extract_all_user_messages(messages)
        first_user = user_messages[0] if user_messages else None
        last_user = user_messages[-1] if user_messages else None
        return first_user, last_user

    def _extract_last_assistant(self, messages: list[dict]) -> str | None:
        """Extract the last assistant message from transcript."""
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_parts.append(block)
                    return "\n".join(text_parts)
                elif isinstance(content, dict):
                    if content.get("type") == "text":
                        return content.get("text", "")
                    return str(content)
                return str(content)
            elif msg.get("type") == "assistant":
                # Claude Code format: type="assistant", message={role, content, ...}
                message = msg.get("message", {})
                if isinstance(message, dict):
                    content = message.get("content", "")
                    if isinstance(content, str):
                        return content
                    elif isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif isinstance(block, str):
                                text_parts.append(block)
                        return "\n".join(text_parts)
                    elif isinstance(content, dict):
                        if content.get("type") == "text":
                            return content.get("text", "")
                        return str(content)
                return message if isinstance(message, str) else str(message)
        return None

    def _extract_mentions(self, text: str) -> list[str]:
        """Extract @path/to/file mentions from text."""
        if not text:
            return []
        pattern = r"@([\w./-]+)"
        return re.findall(pattern, text)

    def _read_mentioned_files(
        self, mentions: list[str], cwd: str, debug: DebugFn
    ) -> dict[str, str]:
        """Read contents of mentioned files, resolving relative paths.

        Logs when files can't be found or read.
        """
        files = {}
        for mention in mentions:
            if not os.path.isabs(mention):
                path = os.path.join(cwd, mention)
            else:
                path = mention

            if not os.path.isfile(path):
                debug(f"Referenced file not found: {mention} (resolved: {path})")
                continue

            try:
                with open(path, "r") as f:
                    files[mention] = f.read()
            except (PermissionError, IsADirectoryError) as e:
                debug(f"Cannot read referenced file {mention}: {e}")
                continue
        return files

    def _build_user_prompt(
        self,
        first_user: str | None,
        last_user: str | None,
        last_assistant: str | None,
        files: dict[str, str],
    ) -> str:
        """Build the user prompt for the LLM."""
        parts = []

        first_user = (first_user or "").strip() or "[No user message found]"
        parts.append("=== ORIGINAL INTENT ===")
        parts.append(first_user)

        if files:
            parts.append("\n=== REFERENCED FILES ===")
            for path, content in files.items():
                parts.append(f"\n--- @{path} ---")
                if len(content) > 10000:
                    content = content[:10000] + "\n... [truncated]"
                parts.append(content)

        last_user = (last_user or "").strip()
        last_assistant = (last_assistant or "").strip()

        if last_user and last_user != first_user:
            parts.append("\n=== RECENT EXCHANGE ===")
            parts.append(f"User: {last_user}")

        if last_assistant:
            if not last_user or last_user == first_user:
                parts.append("\n=== RECENT EXCHANGE ===")
            parts.append(f"Assistant: {last_assistant}")

        result = "\n".join(parts)
        return result if result.strip() else "[No context available]"
