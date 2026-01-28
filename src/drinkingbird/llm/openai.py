"""OpenAI LLM provider for Better Drinking Bird."""

from __future__ import annotations

import json
from typing import Any

import httpx

from drinkingbird.llm.base import LLMProvider, LLMResponse, TokenUsage


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    DEFAULT_MODEL = "gpt-4o-mini"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

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
        """Make an OpenAI API call with structured output."""
        if not self.api_key:
            return LLMResponse(
                content={"error": "No API key configured"},
                raw_response=None,
            )

        request_body = {
            "model": self.model,
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

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    json=request_body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
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

                # Get actual model used (may differ from requested)
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
