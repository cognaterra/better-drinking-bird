"""Ollama LLM provider for Better Drinking Bird."""

from __future__ import annotations

import json
from typing import Any

import httpx

from drinkingbird.llm.base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    DEFAULT_MODEL = "llama3.2"
    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(
        self,
        api_key: str | None = None,  # Not used for Ollama
        model: str | None = None,
        base_url: str | None = None,
        timeout: int = 60,  # Longer timeout for local models
    ):
        super().__init__(
            api_key=api_key,
            model=model or self.DEFAULT_MODEL,
            base_url=base_url or self.DEFAULT_BASE_URL,
            timeout=timeout,
        )

    def is_configured(self) -> bool:
        """Ollama doesn't need an API key."""
        return True

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any],
    ) -> LLMResponse:
        """Make an Ollama API call with structured output."""
        # Build JSON instruction for structured output
        schema_instruction = (
            f"\n\nRespond with valid JSON only, matching this schema:\n"
            f"{json.dumps(response_schema, indent=2)}\n"
            f"Do not include any text before or after the JSON."
        )

        request_body = {
            "model": self.model,
            "prompt": f"{system_prompt}{schema_instruction}\n\nUser: {user_prompt}",
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
            },
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/api/generate",
                    json=request_body,
                )
                response.raise_for_status()
                result = response.json()

                # Extract response text
                response_text = result.get("response", "")

                # Parse JSON from response
                content = json.loads(response_text)

                return LLMResponse(content=content, raw_response=result)

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
        except httpx.ConnectError:
            return LLMResponse(
                content={"error": f"Cannot connect to Ollama at {self.base_url}"},
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
