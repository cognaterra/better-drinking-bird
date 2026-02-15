"""Pre-Tool Hook - Blocks dangerous commands before execution."""

from __future__ import annotations

import re
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

    # File paths that agents must never modify.
    # These protect quality infrastructure from being weakened.
    PROTECTED_FILE_PATTERNS = [
        (r"(?:^|/)\.git/hooks/", "Do not modify git hooks. Fix the code, not the safety net."),
        (r"pre-commit", "Do not touch pre-commit. Fix the code, not the safety net."),
        (r"(?:^|/)\.github/workflows/", "Do not modify CI workflows. Fix the code, not the pipeline."),
    ]

    def _check_protected_paths(self, tool_name: str, tool_input: dict, debug: DebugFn) -> HookResult | None:
        """Block ANY tool interaction with protected paths.

        Scans every string value in tool_input for protected path patterns.
        Returns HookResult if blocked, None if allowed.
        """
        # Collect all string values from tool_input
        values_to_check: list[str] = []
        for v in tool_input.values():
            if isinstance(v, str):
                values_to_check.append(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        values_to_check.append(item)

        for value in values_to_check:
            for pattern, reason in self.PROTECTED_FILE_PATTERNS:
                if re.search(pattern, value):
                    debug(f"BLOCKED {tool_name} touching protected path: {value[:200]}")
                    return HookResult.block(reason)
        return None

    def handle(self, hook_input: dict[str, Any], debug: DebugFn) -> HookResult:
        """Handle pre-tool hook event."""
        tool_name = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input", {})

        debug(f"PreToolUse: {tool_name}")

        # Check ALL tools against protected paths — no exceptions
        result = self._check_protected_paths(tool_name, tool_input, debug)
        if result:
            return result

        # Only check Bash commands for command safety patterns
        if tool_name != "Bash":
            return HookResult.allow("Not a Bash command")

        command = tool_input.get("command", "")
        debug(f"Command: {command[:200]}")

        # Step 1: Check regex patterns FIRST for fast blocking
        enabled_categories = getattr(self.config, "categories", None)
        is_forbidden, reason = check_command(command, enabled_categories)

        if is_forbidden:
            debug(f"BLOCKED by pattern: {reason}")
            return HookResult.block(reason)

        # Step 2: If no pattern match, check if needs LLM classification
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
                debug(f"BLOCKED by LLM classifier ({result.category}): {result.reason}")
                return HookResult.block(result.message)

            debug(f"ALLOWED by LLM classifier: {result.reason}")
            return HookResult.allow(result.reason)

        # Step 3: No pattern match, no LLM needed - allow
        return HookResult.allow("Command allowed")
