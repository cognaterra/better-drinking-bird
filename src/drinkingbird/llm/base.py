"""Base LLM provider interface for Better Drinking Bird."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class TokenUsage:
    """Token usage from an LLM call."""

    input: int = 0
    output: int = 0

    @property
    def total(self) -> int:
        """Total tokens used."""
        return self.input + self.output

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary for tracing."""
        return {"input": self.input, "output": self.output, "total": self.total}


@dataclass
class LLMResponse:
    """Response from an LLM call."""

    content: dict[str, Any]
    raw_response: dict[str, Any] | None = None
    model: str | None = None
    usage: TokenUsage | None = None

    @property
    def success(self) -> bool:
        """Check if the response was successful."""
        return self.raw_response is not None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int = 30,
    ):
        """Initialize LLM provider.

        Args:
            api_key: API key for the provider
            model: Model to use
            base_url: Base URL for API calls (for custom endpoints)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self._api_key_env: str | None = None

    @abstractmethod
    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
    ) -> LLMResponse:
        """Make an LLM call with structured output.

        Args:
            system_prompt: System prompt for the LLM
            user_prompt: User prompt for the LLM
            response_schema: JSON schema for the expected response

        Returns:
            LLMResponse with parsed content
        """
        pass

    def is_configured(self) -> bool:
        """Check if the provider is properly configured.

        Re-checks the env var on every call in case the key wasn't
        available at init time (e.g. worktree subprocess that didn't
        source .zshrc when the Supervisor was created).
        """
        if self.api_key:
            return True
        if self._api_key_env:
            key = os.environ.get(self._api_key_env)
            if not key:
                # Hook subprocesses don't source shell profiles.
                # Fall back to parsing .zshrc/.bashrc directly.
                from drinkingbird.config import LLMConfig
                key = LLMConfig._resolve_key_from_shell(self._api_key_env)
            if key:
                self.api_key = key
                return True
        return False
