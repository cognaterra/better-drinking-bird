"""Pre-Tool Hook - Blocks dangerous commands before execution."""

from __future__ import annotations

from typing import Any

from drinkingbird.hooks.base import DebugFn, Hook, HookResult
from drinkingbird.safety.command_classifier import (
    classify_command,
    needs_llm_classification,
)
from drinkingbird.safety.patterns import check_command


class PreToolHook(Hook):
    """Hook that blocks dangerous tool calls."""

    event_name = "PreToolUse"

    def handle(self, hook_input: dict[str, Any], debug: DebugFn) -> HookResult:
        """Handle pre-tool hook event."""
        tool_name = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input", {})

        debug(f"PreToolUse: {tool_name}")

        # Only check Bash commands
        if tool_name != "Bash":
            return HookResult.allow("Not a Bash command")

        command = tool_input.get("command", "")
        debug(f"Command: {command[:200]}")

        # Check if command needs LLM classification (git history, obfuscation, etc.)
        if needs_llm_classification(command):
            debug("Command needs LLM classification")

            # Get transcript path for context
            transcript_path = hook_input.get("transcript_path")

            # Get fallback behavior from config
            fallback = getattr(self.config, "llm_fallback", "block")

            result = classify_command(
                command=command,
                transcript_path=transcript_path,
                llm_provider=self.llm_provider,
                debug=debug,
                fallback=fallback,
            )

            if result.is_blocked:
                debug(f"BLOCKED by classifier ({result.category}): {result.reason}")
                return HookResult.block(result.message)

            debug(f"ALLOWED by classifier: {result.reason}")
            return HookResult.allow(result.reason)

        # Fall through to existing regex-based checks
        enabled_categories = getattr(self.config, "categories", None)

        is_forbidden, reason = check_command(command, enabled_categories)

        if is_forbidden:
            debug(f"BLOCKED: {reason}")
            return HookResult.block(reason)

        return HookResult.allow("Command allowed")
