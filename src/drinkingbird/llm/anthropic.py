"""Anthropic LLM provider for Better Drinking Bird."""

from __future__ import annotations

import json
from typing import Any

import httpx

from drinkingbird.llm.base import LLMProvider, LLMResponse, TokenUsage


class AnthropicProvider(LLMProvider):
    """Anthropic API provider."""

    DEFAULT_MODEL = "claude-3-5-haiku-20241022"
    DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int = 30,
    ):
        super().__init__(
            api_key=api_key,
            model=model or self.DEFAULT_MODEL,
            base_url=base_url or self.DEFAULT_BASE_URL,
            timeout=timeout,
        )

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
    ) -> LLMResponse:
        """Make an Anthropic API call with structured output."""
        if not self.api_key:
            return LLMResponse(
                content={"error": "No API key configured"},
                raw_response=None,
            )

        # Build JSON instruction for structured output
        schema_instruction = (
            f"\n\nRespond with valid JSON matching this schema:\n"
            f"{json.dumps(response_schema, indent=2)}"
        )

        request_body = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system_prompt + schema_instruction,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/messages",
                    json=request_body,
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": self.api_key,
                        "anthropic-version": self.API_VERSION,
                    },
                )
                response.raise_for_status()
                result = response.json()

                # Extract text content from response
                content_blocks = result.get("content", [])
                text_content = ""
                for block in content_blocks:
                    if block.get("type") == "text":
                        text_content += block.get("text", "")

                # Parse JSON from response
                content = json.loads(text_content)

                # Extract token usage
                usage = None
                if "usage" in result:
                    usage = TokenUsage(
                        input=result["usage"].get("input_tokens", 0),
                        output=result["usage"].get("output_tokens", 0),
                    )

                # Get actual model used
                actual_model = result.get("model", self.model)

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
