"""Hook implementations for Better Drinking Bird."""

from drinkingbird.hooks.base import Hook, HookResult
from drinkingbird.hooks.stop import StopHook
from drinkingbird.hooks.pre_tool import PreToolHook
from drinkingbird.hooks.tool_failure import ToolFailureHook
from drinkingbird.hooks.pre_compact import PreCompactHook

__all__ = [
    "Hook",
    "HookResult",
    "StopHook",
    "PreToolHook",
    "ToolFailureHook",
    "PreCompactHook",
]
