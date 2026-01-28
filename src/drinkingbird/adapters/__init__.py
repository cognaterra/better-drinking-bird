"""Agent adapters for Better Drinking Bird."""

from drinkingbird.adapters.base import Adapter
from drinkingbird.adapters.claude_code import ClaudeCodeAdapter
from drinkingbird.adapters.cursor import CursorAdapter
from drinkingbird.adapters.copilot import CopilotAdapter
from drinkingbird.adapters.stdin import StdinAdapter

__all__ = [
    "Adapter",
    "ClaudeCodeAdapter",
    "CursorAdapter",
    "CopilotAdapter",
    "StdinAdapter",
]
