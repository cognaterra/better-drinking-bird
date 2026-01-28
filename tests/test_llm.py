"""Tests for LLM providers."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from drinkingbird.llm.openai import OpenAIProvider


class TestOpenAIProvider:
    """Tests for OpenAI provider."""

    def test_request_body_no_temperature(self):
        """Request body should not include temperature parameter."""
        provider = OpenAIProvider(api_key="test-key", model="gpt-4o-mini")

        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "choices": [{"message": {"content": '{"status": "ok"}'}}],
                "model": "gpt-4o-mini",
            }
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )

            provider.call(
                system_prompt="Test",
                user_prompt="Test",
                response_schema={
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                    "additionalProperties": False,
                },
            )

            # Get the request body that was sent
            call_args = mock_client.return_value.__enter__.return_value.post.call_args
            request_body = call_args.kwargs["json"]

            assert "temperature" not in request_body

    def test_http_error_includes_api_message(self):
        """HTTP errors should include the actual API error message."""
        provider = OpenAIProvider(api_key="test-key", model="gpt-4o-mini")

        with patch("httpx.Client") as mock_client:
            # Create a mock HTTP error response
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {
                "error": {
                    "message": "Invalid model specified",
                    "type": "invalid_request_error",
                }
            }

            error = httpx.HTTPStatusError(
                "Bad Request", request=MagicMock(), response=mock_response
            )
            mock_client.return_value.__enter__.return_value.post.side_effect = error

            result = provider.call(
                system_prompt="Test",
                user_prompt="Test",
                response_schema={
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                    "additionalProperties": False,
                },
            )

            assert result.content["error"] == "Invalid model specified"

    def test_http_error_fallback_to_text(self):
        """HTTP errors should fall back to response text if JSON parsing fails."""
        provider = OpenAIProvider(api_key="test-key", model="gpt-4o-mini")

        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.json.side_effect = json.JSONDecodeError("", "", 0)
            mock_response.text = "Internal Server Error"

            error = httpx.HTTPStatusError(
                "Server Error", request=MagicMock(), response=mock_response
            )
            mock_client.return_value.__enter__.return_value.post.side_effect = error

            result = provider.call(
                system_prompt="Test",
                user_prompt="Test",
                response_schema={
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                    "additionalProperties": False,
                },
            )

            assert result.content["error"] == "Internal Server Error"

    def test_no_api_key_returns_error(self):
        """Provider should return error when no API key is configured."""
        provider = OpenAIProvider(api_key=None)

        result = provider.call(
            system_prompt="Test",
            user_prompt="Test",
            response_schema={
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
                "additionalProperties": False,
            },
        )

        assert "error" in result.content
        assert "No API key" in result.content["error"]
