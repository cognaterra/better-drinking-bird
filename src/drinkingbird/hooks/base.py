"""Base hook interface for Better Drinking Bird."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class Decision(str, Enum):
    """Hook decision types."""

    ALLOW = "allow"
    BLOCK = "block"
    KILL = "kill"


@dataclass
class HookResult:
    """Result from a hook execution.

    Attributes:
        decision: The decision (allow, block, kill)
        reason: Explanation for the decision
        message: Message to send back to the agent (for blocks)
        additional_context: Extra context to inject (for some hooks)
    """

    decision: Decision = Decision.ALLOW
    reason: str = ""
    message: str = ""
    additional_context: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        result: dict[str, Any] = {}

        if self.decision == Decision.BLOCK:
            result["decision"] = "block"
            result["reason"] = self.message or self.reason

        elif self.additional_context:
            # For hooks that inject context (tool_failure, pre_compact)
            result["hookSpecificOutput"] = {
                "additionalContext": self.additional_context
            }

        return result

    @classmethod
    def allow(cls, reason: str = "") -> HookResult:
        """Create an allow result."""
        return cls(decision=Decision.ALLOW, reason=reason)

    @classmethod
    def block(cls, message: str, reason: str = "") -> HookResult:
        """Create a block result."""
        return cls(
            decision=Decision.BLOCK,
            reason=reason or message,
            message=message,
        )

    @classmethod
    def kill(cls, reason: str) -> HookResult:
        """Create a kill result."""
        return cls(decision=Decision.KILL, reason=reason)

    @classmethod
    def with_context(cls, context: str) -> HookResult:
        """Create a result that injects additional context."""
        return cls(decision=Decision.ALLOW, additional_context=context)


# Type alias for debug logging function
DebugFn = Callable[[str], None]


class Hook(ABC):
    """Abstract base class for hooks."""

    # Hook event name that this hook handles
    event_name: str = ""

    def __init__(self, config: Any, llm_provider: Any = None):
        """Initialize hook with configuration.

        Args:
            config: Hook-specific configuration
            llm_provider: LLM provider for hooks that need it
        """
        self.config = config
        self.llm_provider = llm_provider

    @abstractmethod
    def handle(self, hook_input: dict[str, Any], debug: DebugFn) -> HookResult:
        """Handle the hook event.

        Args:
            hook_input: Input data from the agent
            debug: Debug logging function

        Returns:
            HookResult indicating what to do
        """
        pass

    def is_enabled(self) -> bool:
        """Check if this hook is enabled."""
        return getattr(self.config, "enabled", True)
