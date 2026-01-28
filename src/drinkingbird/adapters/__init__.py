"""Agent adapters for Better Drinking Bird."""

from drinkingbird.adapters.base import Adapter
from drinkingbird.adapters.claude_code import ClaudeCodeAdapter
from drinkingbird.adapters.cline import ClineAdapter
from drinkingbird.adapters.copilot import CopilotAdapter
from drinkingbird.adapters.cursor import CursorAdapter
from drinkingbird.adapters.kilo_code import KiloCodeAdapter
from drinkingbird.adapters.stdin import StdinAdapter

__all__ = [
    "Adapter",
    "ClaudeCodeAdapter",
    "ClineAdapter",
    "CopilotAdapter",
    "CursorAdapter",
    "KiloCodeAdapter",
    "StdinAdapter",
]
