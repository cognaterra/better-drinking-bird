"""Tool Failure Hook - Provides recovery hints when tools fail."""

from __future__ import annotations

from typing import Any

from drinkingbird.hooks.base import DebugFn, Hook, HookResult


SYSTEM_PROMPT = """You are a coach for an AI coding agent that just hit an error.

A tool failed. Your job: give a quick hint and ENCOURAGE IT TO KEEP TRYING.

The agent WILL eventually find the right solution if it keeps experimenting.

If you recognize the command:
- Give ONE specific fix to try
- Example: "Try 'act refactor rename-function' instead of '--operation rename-function'"

If you don't recognize the command:
- Tell it to check --help or read the docs
- Encourage trying a different approach

KEEP IT SHORT (1-2 sentences). End with encouragement like "Try again!" or "Keep going!"

Respond with JSON:
{
  "advice": "Your hint + encouragement",
  "confidence": "high" | "medium" | "low"
}"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "advice": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
    },
    "required": ["advice", "confidence"],
    "additionalProperties": False,
}


class ToolFailureHook(Hook):
    """Hook that provides recovery hints when tools fail."""

    event_name = "PostToolUseFailure"

    def handle(self, hook_input: dict[str, Any], debug: DebugFn) -> HookResult:
        """Handle tool failure hook event."""
        tool_name = hook_input.get("tool_name", "Unknown")
        tool_input = hook_input.get("tool_input", {})
        tool_response = hook_input.get("tool_response", "")

        debug(f"Tool failure: {tool_name}")
        debug(f"Input: {str(tool_input)[:200]}")

        # Extract error message
        error_output = self._extract_error(tool_response)
        debug(f"Error: {error_output[:200]}")

        if not error_output.strip():
            debug("No error output, skipping")
            return HookResult.allow("No error output")

        # Check if we have an LLM provider
        if not self.llm_provider or not self.llm_provider.is_configured():
            return HookResult.with_context(
                "[HINT (low)]: Check command syntax and try again!"
            )

        # Build prompt
        command = tool_input.get("command", str(tool_input))
        user_prompt = f"""Tool: {tool_name}
Command/Input: {command}

Error Output:
{error_output[:2000]}"""

        debug("Calling LLM for advice...")
        response = self.llm_provider.call(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=RESPONSE_SCHEMA,
        )
        debug(f"LLM result: {response.content}")

        # Log generation to tracer
        if self.tracer:
            self.tracer.generation(
                name="generate_recovery_advice",
                model=response.model or self.llm_provider.model or "unknown",
                input_data={
                    "system_prompt": SYSTEM_PROMPT,
                    "user_prompt": user_prompt,
                },
                output_data=response.content,
                usage=response.usage.to_dict() if response.usage else None,
                metadata={
                    "tool_name": tool_name,
                    "response_schema": RESPONSE_SCHEMA,
                },
            )

        advice = response.content.get("advice", "Check command syntax and try again!")
        confidence = response.content.get("confidence", "low")

        # Check confidence threshold
        threshold = getattr(self.config, "confidence_threshold", "medium")
        confidence_order = ["low", "medium", "high"]

        if confidence_order.index(confidence) < confidence_order.index(threshold):
            debug(f"Confidence {confidence} below threshold {threshold}, skipping")
            return HookResult.allow("Confidence below threshold")

        return HookResult.with_context(f"[HINT ({confidence})]: {advice}")

    def _extract_error(self, tool_response: Any) -> str:
        """Extract error message from tool response."""
        if isinstance(tool_response, str):
            return tool_response
        if isinstance(tool_response, dict):
            for key in ["error", "stderr", "message", "output"]:
                if key in tool_response:
                    val = tool_response[key]
                    if isinstance(val, str):
                        return val
                    return str(val)
            return str(tool_response)
        return str(tool_response)
