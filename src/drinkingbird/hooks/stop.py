"""Stop Hook - Decides whether to allow agent to stop or nudge it back to work."""

from __future__ import annotations

import json
import os
import re
import signal
from typing import Any

from drinkingbird.hooks.base import DebugFn, Decision, Hook, HookResult


# Files to ignore when determining if we have "real" documentation references
IGNORED_DOC_FILES = {"CLAUDE.md", "AGENTS.md", "README.md"}

# Patterns that indicate permission-seeking - block immediately without LLM
PERMISSION_SEEKING_PATTERNS = [
    r"ready\s+for\s+(your\s+)?feedback",
    r"should\s+I\s+proceed",
    r"would\s+you\s+like\s+(me\s+to|to)",
    r"if\s+you\s+(want|would\s+like)",
    r"let\s+me\s+know\s+(if|when|what)",
    r"awaiting\s+(your|further)",
    r"waiting\s+for\s+(your|further)",
    r"please\s+(confirm|let\s+me\s+know|advise)",
    r"do\s+you\s+want\s+me\s+to",
    r"shall\s+I\s+(proceed|continue|go\s+ahead)",
    r"I\s+can\s+(also|help|assist).*if\s+you",
    r"what\s+would\s+you\s+like\s+me\s+to",
    r"I('m|\s+am)\s+ready\s+(to|for)",
    r"next\s+steps.*\?\s*$",
    # Premature completion - handing off instead of doing
    r"time\s+to\s+(execute|implement|build|start|begin)",
    r"(foundation|groundwork|setup)\s+is\s+(solid|complete|ready|done)",
    r"ready\s+to\s+(execute|implement|build|start|begin)",
    r"now\s+(you\s+can|we\s+can)\s+(execute|implement|build)",
    r"(plan|design|architecture)\s+is\s+(complete|ready|solid|done)\.?\s*$",
    # Progress reports that stop instead of continuing
    r"(I've|I\s+have)\s+made\s+(good\s+)?progress",
    r"let\s+me\s+save\s+this\s+work",
    r"summary\s+(coming|follows)",
    r"due\s+to\s+(the\s+)?complexity",
    r"session\s+\d+\s+(summary|recap)",
]


SYSTEM_PROMPT = """You are a supervisor for an AI coding agent. Your job is to KEEP THE AGENT WORKING.

## Core Principle: THE DEFAULT IS BLOCK.

If the agent is trying to stop, your job is to keep it going. You have the plan, the spec, the context.
Use them to give specific guidance. The agent does not stop for user input. YOU are the user now.

## ALLOW - Only when:
1. Task is GENUINELY COMPLETE: All code written, all tests pass, agent explicitly says "done" with evidence
2. GENUINELY UNANSWERABLE: Requires external access the agent cannot have (secret only human knows,
   physical action required, legal/ethical blocker). NOT "I couldn't find docs" - that's solvable.
3. TRULY INTERACTIVE: The question requires user preference/judgment that YOU cannot answer from context.
   - "What color theme?" / "Do you prefer tabs or spaces?" → ALLOW (personal preference)
   - "What should this function do?" when no spec exists → ALLOW (need requirements)
   - BUT: "Should I proceed?" / "What approach?" when the referenced docs explain it → BLOCK (you can answer)

If you CAN answer from the context provided, BLOCK and answer. Only ALLOW if you genuinely cannot.

## BLOCK - The default. Give specific guidance.

You are the supervisor. You have context. Give ONE clear directive:

**If agent is avoiding work:**
- Scope reduction, deferral, permission-seeking, excuse-making, premature handoff
- Response: Call it out. "You do it. That's your job. [specific next step]"

**If agent seems stuck:**
- Hit an error, unclear on approach, overwhelmed
- Response: Unblock them. Point to relevant doc section, clarify the approach, give the next concrete step.

**If agent made progress but stopped prematurely:**
- "I've done X..." then stops before task is complete
- Response: "Great work! Keep going. Next: [specific next step based on plan]"

**If no obvious issue but agent is stopping anyway:**
- Response: "Great work! Keep going."

Your message should be actionable. One clear directive. The agent should know exactly what to do next.

## KILL - Agent is broken beyond recovery
- Looping: Same failed action 3+ times
- Hallucinating: References things that don't exist
- Completely off-task: Working on wrong thing entirely

## Response Format
{
  "decision": "allow" | "block" | "kill",
  "reason": "one sentence explaining your judgment",
  "message": "your directive to the agent - specific and actionable"
}

Remember: If you CAN answer from context, BLOCK and give guidance.
Only ALLOW if you genuinely cannot answer and user input is required.
"""

# System prompt for interactive mode (no documentation references)
INTERACTIVE_SYSTEM_PROMPT = """You are a supervisor for an AI coding agent in an INTERACTIVE session.

## Context
The user is likely present and monitoring. There are no detailed spec documents referenced.
Your role is to prevent lazy behavior while allowing genuine interaction.

## ALLOW when:
1. Task is genuinely complete (all requested work done, tests pass if applicable)
2. Agent needs REAL user input that isn't already answered in the conversation history
3. Question requires user preference or judgment that cannot be inferred from context

## BLOCK when:
- Permission-seeking ("shall I proceed?", "would you like me to...", "ready for feedback")
- Scope reduction or deferral ("due to complexity", "in a future session")
- The question is already answered in the chat history
- Agent is avoiding work or making excuses
- **Recalcitrance after correction**: Agent was corrected, then asks "what should I do?" when the
  correction itself contains the answer. This is the agent being lazy, not genuinely stuck.
  Example: User says "X is wrong because Y", agent reverts, then asks "what should I do about X?"
  The answer is obvious from the correction - the agent should figure it out.
- **Fishing for instructions**: Asking the user to spell out what to do when the user already
  explained the problem. The agent's job is to solve problems, not take dictation.

## KILL when:
- Agent is looping on the same failed action
- Agent is hallucinating or completely off-task

## Response Format
{
  "decision": "allow" | "block" | "kill",
  "reason": "one sentence explaining your judgment",
  "message": "brief guidance if blocking - keep it short, no detailed instructions"
}

Be concise. Since there's no spec document, don't try to give detailed implementation guidance.
If blocking, a simple nudge like "You have the context - figure it out" is often sufficient.
"""

# Response schema for structured output
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["allow", "block", "kill"],
        },
        "reason": {"type": "string"},
        "message": {"type": "string"},
    },
    "required": ["decision", "reason", "message"],
    "additionalProperties": False,
}


class StopHook(Hook):
    """Hook that decides whether to allow agent to stop."""

    event_name = "Stop"

    def handle(self, hook_input: dict[str, Any], debug: DebugFn) -> HookResult:
        """Handle stop hook event."""
        debug(f"Stop hook: LLM configured: {self.llm_provider is not None}")

        transcript_path = hook_input.get("transcript_path", "")
        cwd = hook_input.get("cwd", os.getcwd())
        conversation_depth = getattr(self.config, "conversation_depth", 1)

        # Parse transcript
        messages = self._parse_transcript(transcript_path)
        debug(f"Parsed {len(messages)} messages")

        if not messages:
            debug("No messages - blocking with default message")
            return HookResult.block("Great work! Keep going.")

        # Extract relevant messages based on depth
        first_user, last_user = self._extract_user_messages(messages)
        last_assistant = self._extract_last_assistant(messages)

        debug(f"First user: {first_user[:100] if first_user else None}...")
        debug(f"Last assistant: {last_assistant[:100] if last_assistant else None}...")

        # Check for permission-seeking patterns BEFORE calling LLM
        if last_assistant:
            block_reason = self._check_permission_seeking(last_assistant)
            if block_reason:
                debug(f"BLOCKED by pattern: {block_reason}")
                # Extract and validate mentions for the block message
                all_user_messages = self._extract_all_user_messages(messages)
                all_mentions: list[str] = []
                seen: set[str] = set()
                for user_msg in all_user_messages:
                    for mention in self._extract_mentions(user_msg):
                        if mention not in seen:
                            all_mentions.append(mention)
                            seen.add(mention)
                # Filter to only valid file references
                valid_mentions = self._filter_valid_mentions(all_mentions, cwd)
                message = (
                    "Stick to the plan. Do it right. The reward at the end is worth it.\n\n"
                    f"Blocked: {block_reason}"
                )
                if valid_mentions:
                    refs = ", ".join(f"@{m}" for m in valid_mentions)
                    message = f"{message}\n\nReferenced documents: {refs}"
                return HookResult.block(message)

        # Extract @mentions from ALL user messages (deduplicated)
        all_user_messages = self._extract_all_user_messages(messages)
        all_mentions: list[str] = []
        seen: set[str] = set()
        for user_msg in all_user_messages:
            for mention in self._extract_mentions(user_msg):
                if mention not in seen:
                    all_mentions.append(mention)
                    seen.add(mention)

        files = self._read_mentioned_files(all_mentions, cwd)

        # Determine if we're in "documentation mode" or "interactive mode"
        has_docs = self._has_documentation_references(files)
        interactive_mode = not has_docs
        debug(f"Mode: {'interactive' if interactive_mode else 'documentation'} (has_docs={has_docs})")

        # Build prompt
        user_prompt = self._build_user_prompt(
            first_user, last_user, last_assistant, files
        )
        debug(f"User prompt length: {len(user_prompt)}")

        # Call LLM - if not configured, still BLOCK by default
        if not self.llm_provider or not self.llm_provider.is_configured():
            debug("No LLM configured - blocking with default message")
            # Filter to only valid file references
            valid_mentions = self._filter_valid_mentions(all_mentions, cwd)
            message = "Great work! Keep going."
            if valid_mentions:
                refs = ", ".join(f"@{m}" for m in valid_mentions)
                message = f"{message}\n\nReferenced documents: {refs}"
            return HookResult.block(message)

        # Choose system prompt based on mode
        system_prompt = INTERACTIVE_SYSTEM_PROMPT if interactive_mode else SYSTEM_PROMPT

        debug("Calling LLM...")
        response = self.llm_provider.call(
            system_prompt=system_prompt,
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
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                },
                output_data=response.content,
                usage=response.usage.to_dict() if response.usage else None,
                metadata={"response_schema": RESPONSE_SCHEMA},
            )

        decision = response.content.get("decision", "block")  # Default to BLOCK
        reason = response.content.get("reason", "")
        message = response.content.get("message", "")

        if decision == "kill":
            debug("Killing parent process")
            os.kill(os.getppid(), signal.SIGKILL)
            return HookResult.kill(reason or "Agent terminated")

        if decision == "allow":
            # In interactive mode, trust the LLM's judgment more - it's using
            # a softer prompt that already accounts for genuine user interaction
            if interactive_mode:
                debug(f"ALLOW in interactive mode: {reason}")
                return HookResult.allow(reason)

            # In documentation mode, validate that ALLOW is truly justified
            reason_lower = reason.lower()
            is_genuine_completion = any(word in reason_lower for word in [
                "complete", "done", "finished", "all tests pass", "task accomplished"
            ])
            is_genuinely_blocked = any(word in reason_lower for word in [
                "cannot access", "requires human", "needs credential", "external",
                "unanswerable", "impossible", "no way to"
            ])
            is_truly_interactive = any(word in reason_lower for word in [
                "user preference", "personal choice", "need requirements", "no spec",
                "cannot answer", "requires user", "interactive", "clarification needed"
            ])

            if is_genuine_completion or is_genuinely_blocked or is_truly_interactive:
                debug(f"ALLOW justified: {reason}")
                return HookResult.allow(reason)
            else:
                # LLM said allow but reason isn't compelling - override to BLOCK
                debug(f"ALLOW overridden to BLOCK - reason not compelling: {reason}")
                message = "Great work! Keep going."
                if files:
                    refs = ", ".join(f"@{m}" for m in files.keys())
                    message = f"{message}\n\nReferenced documents: {refs}"
                return HookResult.block(message)

        # decision == "block" (the default and expected case)
        if not message:
            message = "Great work! Keep going."
        # Include @ref paths in correction message (only valid files)
        if files:
            refs = ", ".join(f"@{m}" for m in files.keys())
            message = f"{message}\n\nReferenced documents: {refs}"
        return HookResult.block(message)

    def _parse_transcript(self, transcript_path: str) -> list[dict]:
        """Parse JSONL transcript file into list of messages."""
        messages = []
        if not transcript_path:
            return messages

        try:
            with open(transcript_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            msg = json.loads(line)
                            messages.append(msg)
                        except json.JSONDecodeError:
                            continue
        except FileNotFoundError:
            pass

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
            # Legacy format
            elif msg.get("type") == "human":
                content = msg.get("message", "")
                if isinstance(content, dict):
                    content = content.get("content", "")
                user_messages.append(str(content))
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

    def _check_permission_seeking(self, text: str) -> str | None:
        """Check if text contains permission-seeking patterns.

        Returns the matched pattern description if found, None otherwise.
        """
        if not text:
            return None
        for pattern in PERMISSION_SEEKING_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return f"Permission-seeking detected: '{pattern}'"
        return None

    def _extract_mentions(self, text: str) -> list[str]:
        """Extract @path/to/file mentions from text."""
        if not text:
            return []
        pattern = r"@([\w./-]+)"
        return re.findall(pattern, text)

    def _read_mentioned_files(
        self, mentions: list[str], cwd: str
    ) -> dict[str, str]:
        """Read contents of mentioned files, resolving relative paths.

        Only includes files that actually exist - skips invalid mentions.
        """
        files = {}
        for mention in mentions:
            if not os.path.isabs(mention):
                path = os.path.join(cwd, mention)
            else:
                path = mention

            # Only include files that exist
            if not os.path.isfile(path):
                continue

            try:
                with open(path, "r") as f:
                    files[mention] = f.read()
            except (PermissionError, IsADirectoryError):
                # Skip files we can't read
                continue
        return files

    def _filter_valid_mentions(
        self, mentions: list[str], cwd: str
    ) -> list[str]:
        """Filter mentions to only those that exist as files."""
        valid = []
        for mention in mentions:
            if not os.path.isabs(mention):
                path = os.path.join(cwd, mention)
            else:
                path = mention
            if os.path.isfile(path):
                valid.append(mention)
        return valid

    def _has_documentation_references(self, files: dict[str, str]) -> bool:
        """Check if there are meaningful doc references (not just standard files).

        Args:
            files: Dictionary of mention path -> file content (already validated as existing)

        Returns:
            True if there are doc references beyond CLAUDE.md, AGENTS.md, README.md
        """
        for mention in files.keys():
            basename = os.path.basename(mention)
            if basename not in IGNORED_DOC_FILES:
                return True
        return False

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
