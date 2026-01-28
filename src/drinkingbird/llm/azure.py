"""Azure OpenAI LLM provider for Better Drinking Bird."""

from __future__ import annotations

import json
from typing import Any

import httpx

from drinkingbird.llm.base import LLMProvider, LLMResponse, TokenUsage


class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI API provider.

    Azure OpenAI uses deployment names for API calls, but we track the actual
    model name for Langfuse cost attribution.
    """

    DEFAULT_API_VERSION = "2024-08-01-preview"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int = 30,
        deployment: str | None = None,
        api_version: str | None = None,
    ):
        """Initialize Azure OpenAI provider.

        Args:
            api_key: Azure OpenAI API key
            model: The actual model name (e.g., "gpt-4o-mini") for cost tracking
            base_url: Azure endpoint (e.g., "https://your-resource.openai.azure.com")
            timeout: Request timeout in seconds
            deployment: Azure deployment name (used in API calls)
            api_version: Azure API version
        """
        super().__init__(
            api_key=api_key,
            model=model,  # Actual model for Langfuse cost tracking
            base_url=base_url,
            timeout=timeout,
        )
        self.deployment = deployment
        self.api_version = api_version or self.DEFAULT_API_VERSION

    def is_configured(self) -> bool:
        """Check if the provider is properly configured."""
        return bool(self.api_key and self.base_url and self.deployment)

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
    ) -> LLMResponse:
        """Make an Azure OpenAI API call with structured output."""
        if not self.api_key:
            return LLMResponse(
                content={"error": "No API key configured"},
                raw_response=None,
            )

        if not self.base_url:
            return LLMResponse(
                content={"error": "No base_url configured (Azure endpoint required)"},
                raw_response=None,
            )

        if not self.deployment:
            return LLMResponse(
                content={"error": "No deployment configured"},
                raw_response=None,
            )

        request_body = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": response_schema,
                },
            },
            "temperature": 0,
        }

        # Azure OpenAI URL format
        url = (
            f"{self.base_url.rstrip('/')}/openai/deployments/{self.deployment}"
            f"/chat/completions?api-version={self.api_version}"
        )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    url,
                    json=request_body,
                    headers={
                        "Content-Type": "application/json",
                        "api-key": self.api_key,
                    },
                )
                response.raise_for_status()
                result = response.json()

                content_str = result["choices"][0]["message"]["content"]
                content = json.loads(content_str)

                # Extract token usage
                usage = None
                if "usage" in result:
                    usage = TokenUsage(
                        input=result["usage"].get("prompt_tokens", 0),
                        output=result["usage"].get("completion_tokens", 0),
                    )

                # Use configured model for Langfuse cost tracking
                # Azure returns deployment name, not the actual model
                actual_model = self.model or result.get("model", self.deployment)

                return LLMResponse(
                    content=content,
                    raw_response=result,
                    model=actual_model,
                    usage=usage,
                )

        except httpx.HTTPStatusError as e:
            return LLMResponse(
                content={"error": f"HTTP error: {e.response.status_code}"},
                raw_response=None,
            )
        except httpx.TimeoutException:
            return LLMResponse(
                content={"error": "Request timed out"},
                raw_response=None,
            )
        except json.JSONDecodeError as e:
            return LLMResponse(
                content={"error": f"Invalid JSON response: {e}"},
                raw_response=None,
            )
        except Exception as e:
            return LLMResponse(
                content={"error": f"Request failed: {e}"},
                raw_response=None,
            )
