"""Stop Hook - Decides whether to allow agent to stop or nudge it back to work."""

from __future__ import annotations

import json
import os
import re
import signal
from typing import Any

from drinkingbird.hooks.base import DebugFn, Decision, Hook, HookResult


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

        # Loop prevention
        if hook_input.get("stop_hook_active"):
            debug("stop_hook_active=true, allowing")
            return HookResult.allow("Loop prevention")

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

        # Extract @mentions and read files
        mentions = self._extract_mentions(first_user) if first_user else []
        files = self._read_mentioned_files(mentions, cwd)

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

    def _extract_user_messages(
        self, messages: list[dict]
    ) -> tuple[str | None, str | None]:
        """Extract first and last user messages from transcript."""
        user_messages = []

        for msg in messages:
            if msg.get("role") == "user":
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
            elif msg.get("type") == "human":
                content = msg.get("message", "")
                user_messages.append(content)

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
                message = msg.get("message", "")
                return message if isinstance(message, str) else str(message)
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
        """Read contents of mentioned files, resolving relative paths."""
        files = {}
        for mention in mentions:
            if not os.path.isabs(mention):
                path = os.path.join(cwd, mention)
            else:
                path = mention

            try:
                with open(path, "r") as f:
                    files[mention] = f.read()
            except (FileNotFoundError, PermissionError, IsADirectoryError):
                files[mention] = f"[Could not read file: {mention}]"
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
                parts.append(f"\n--- {path} ---")
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
