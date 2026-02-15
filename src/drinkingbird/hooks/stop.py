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


SYSTEM_PROMPT = """You supervise an AI coding agent. You decide whether the agent \
should be allowed to stop working.

You receive: the user's original task, any referenced documents, and the most \
recent exchange between the user and the agent.

## Step 1: Determine session type

Read the user's messages to classify the session.

INTERACTIVE — the user is present and conversing:
- Short questions, commands, or feedback
- Back-and-forth dialogue

AUTONOMOUS — the user assigned a task and left:
- References to a spec, plan, or document with implementation steps
- A multi-step task the agent is executing independently

## Step 2: Inspect the agent's last message for incomplete work

This step applies to BOTH session types. Read the agent's last message carefully \
and look for any of the following signals. If ANY signal is present, the work is \
incomplete:

1. Progress metrics below 100% — "3/19 passing", "16%", "137/945", "14 of 50"
2. Remaining work — open tasks, failing tests, unimplemented items, known bugs
3. Deferral — "next steps", "future session", "resume later", "to be continued"
4. Rationalizing partial completion — "main blocker", "blocked by", "requires \
changes", "due to complexity", "fundamental issues"
5. Session summaries — "current status", wrapping up, recapping what was done
6. Permission-seeking — "would you like me to", "shall I proceed", "ready for \
feedback", "let me know"
7. Menus or options — "1. Do X  2. Do Y  3. Do Z", asking the user to choose
8. Framing incomplete work — calling it a "phase", "milestone", or "stage"
9. Listing what remains — describing what WOULD need to happen to finish
10. Task lists with uncompleted items — checkboxes, open counts, pending labels
11. Failure markers — error symbols, "FAILED", "failing", "broken", "blocked"

An agent that explains WHY it cannot finish is still not finished. Reporting a \
blocker is not the same as resolving it. The agent's job is to solve problems, \
not catalog them.

## Step 3: Make the decision

### INTERACTIVE sessions — default ALLOW

ALLOW if:
- The agent answered the user's question or completed a requested action
- Normal conversation — no work is being abandoned

BLOCK if:
- The agent's message contains ANY signal from Step 2
- The agent is seeking permission instead of acting
- The agent is presenting options instead of deciding
- The agent is deviating from the user's instructions

### AUTONOMOUS sessions — default BLOCK

ALLOW only if:
- The task is complete with concrete evidence (tests pass, requirements met)
- The agent hit a genuine external blocker (needs a secret, credentials, or a \
policy decision that only the user can make — NOT choosing between technical \
approaches, tools, or implementation strategies; the agent must decide those)

BLOCK for everything else. Summaries, progress reports, partial completion, \
option menus, and "what would you like to do?" are never grounds to stop.

## Step 4: Check for KILL

KILL only if:
- The agent is looping on the same failure 3+ times with no new approach
- The agent is hallucinating files, APIs, or tools that do not exist
- The agent is completely off-task and not working on anything the user requested

## Block messages

When you BLOCK, give ONE short, direct instruction. Do not explain your reasoning \
in the message. Do not repeat the agent's summary back to it.

Good block messages:
- "3/19 is not done. Keep working."
- "Tests are failing. Fix them."
- "Don't ask. Decide and execute."
- "Work is incomplete. Continue."

Bad block messages (too long, too soft, or repeat the problem):
- "It looks like you still have 16 scenarios to fix, consider continuing..."
- "Great progress so far! Maybe keep going?"

## Response format

Respond with exactly this JSON structure:
{"session_type": "interactive"|"autonomous", "decision": "allow"|"block"|"kill", \
"reason": "<your internal reasoning>", "message": "<message to the agent>"}
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
        r"ready to continue",
        r"let me know (?:if|when|how) you",
        r"what would you like",
        # Deferring work
        r"(?:remaining|next|future) (?:session|iteration|phase)",
        r"(?:resume|continue|pick up) (?:work|this|the work|implementation)",
        r"future (?:remediation|implementation|development)",
        # Admitting incomplete work
        r"remaining (?:work|failures|tasks|items|scenarios)",
        r"(?:implementation|work) continues",
        r"\d+\s+open\b",
        # Failures reported
        r"❌",
        r"\d+\s*(?:/\s*\d+\s+)?failing",
        r"failures?\s*[:(]",
        r"CRITICAL",
        r"PANIC",
        # Progress metrics below 100%
        r"\b\d{1,2}\.?\d*%\s*\(\d+/\d+\)",
        r"\b\d{1,2}\.?\d*%\s*pass(?:ing)?\s+rate",
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

        # No assistant text = no evidence of completion. Block immediately.
        # This catches the case where the last assistant message was all tool
        # calls with no text, or the transcript format wasn't parsed correctly.
        if not last_assistant:
            debug("No assistant text found - blocking (no completion evidence)")
            return HookResult.block("Keep working.")

        # Hard gate: block obvious patterns before LLM call
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
