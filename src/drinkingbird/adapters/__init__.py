"""Agent adapters for Better Drinking Bird."""

from drinkingbird.adapters.base import Adapter
from drinkingbird.adapters.claude_code import ClaudeCodeAdapter
from drinkingbird.adapters.cline import ClineAdapter
from drinkingbird.adapters.copilot import CopilotAdapter
from drinkingbird.adapters.cursor import CursorAdapter
from drinkingbird.adapters.kilo_code import KiloCodeAdapter
from drinkingbird.adapters.stdin import StdinAdapter
from drinkingbird.adapters.windsurf import WindsurfAdapter

__all__ = [
    "Adapter",
    "ClaudeCodeAdapter",
    "ClineAdapter",
    "CopilotAdapter",
    "CursorAdapter",
    "KiloCodeAdapter",
    "StdinAdapter",
    "WindsurfAdapter",
]

# Canonical list of supported agents for CLI
SUPPORTED_AGENTS = [
    "claude-code",
    "cline",
    "copilot",
    "cursor",
    "kilo-code",
    "stdin",
    "windsurf",
]

# Mapping from agent name to adapter class
ADAPTER_MAP = {
    "claude-code": ClaudeCodeAdapter,
    "cline": ClineAdapter,
    "copilot": CopilotAdapter,
    "cursor": CursorAdapter,
    "kilo-code": KiloCodeAdapter,
    "stdin": StdinAdapter,
    "windsurf": WindsurfAdapter,
}
