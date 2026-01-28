"""Pre-Tool Hook - Blocks dangerous commands before execution."""

from __future__ import annotations

from typing import Any

from drinkingbird.hooks.base import DebugFn, Hook, HookResult
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

        # Get enabled categories from config
        enabled_categories = getattr(self.config, "categories", None)

        is_forbidden, reason = check_command(command, enabled_categories)

        if is_forbidden:
            debug(f"BLOCKED: {reason}")
            return HookResult.block(reason)

        return HookResult.allow("Command allowed")
