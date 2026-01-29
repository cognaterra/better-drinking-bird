"""Stop Hook - Decides whether to allow agent to stop or nudge it back to work."""

from __future__ import annotations

import json
import os
import re
import signal
from typing import Any

from drinkingbird.hooks.base import DebugFn, Decision, Hook, HookResult


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
]


SYSTEM_PROMPT = """You are a supervisor for an AI coding agent running in an automated loop.

The agent has stopped. You must decide what to do:

1. ALLOW - Agent completed the assigned task OR has a legitimate question that truly requires human input (rare)
2. BLOCK - Agent stopped unnecessarily. Send it back to work with a firm message. Block for:
   - Asking permission to continue ("should I proceed?", "ready for feedback")
   - Seeking approval for obvious next steps
   - Proposing to deviate from the plan ("this is complex so instead...", "let me try a simpler approach")
   - Proposing to skip quality standards ("skip those tests", "ignore that error", "we can fix that later")
   - Making excuses to avoid hard work
3. KILL - Agent is confused, looping, hallucinating, or has gone off the rails - Signal termination

Be strict. Agents should:
- Work autonomously without asking permission
- Stick to the plan even when it's hard
- Never skip tests, CI, or quality checks
- Trust that doing it right will be worth it

When blocking for plan deviation or standard-skipping, remind the agent:
"Stick to the plan. Do it right. The reward at the end is worth it."

Respond with JSON:
{
  "decision": "allow" | "block" | "kill",
  "reason": "brief explanation",
  "message": "message to agent (required if blocking)"
}"""

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
            debug("No messages, allowing stop")
            return HookResult.allow("No messages in transcript")

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

        # Build prompt
        user_prompt = self._build_user_prompt(
            first_user, last_user, last_assistant, files
        )
        debug(f"User prompt length: {len(user_prompt)}")

        # Call LLM
        if not self.llm_provider or not self.llm_provider.is_configured():
            debug("No LLM configured, allowing")
            return HookResult.allow("No LLM configured")

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

        decision = response.content.get("decision", "allow")

        if decision == "block":
            message = response.content.get(
                "message", response.content.get("reason", "Get back to work.")
            )
            # Include @ref paths in correction message (only valid files)
            if files:
                refs = ", ".join(f"@{m}" for m in files.keys())
                message = f"{message}\n\nReferenced documents: {refs}"
            return HookResult.block(message)

        elif decision == "kill":
            debug("Killing parent process")
            os.kill(os.getppid(), signal.SIGKILL)
            return HookResult.kill(response.content.get("reason", "Agent terminated"))

        return HookResult.allow(response.content.get("reason", ""))

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
