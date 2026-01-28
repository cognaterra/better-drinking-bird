"""Base LLM provider interface for Better Drinking Bird."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    """Response from an LLM call."""

    content: dict[str, Any]
    raw_response: dict[str, Any] | None = None

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
        """Check if the provider is properly configured."""
        return self.api_key is not None
