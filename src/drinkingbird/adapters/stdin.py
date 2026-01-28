"""Generic stdin/stdout adapter for Better Drinking Bird.

This is the "swiss army knife" adapter that works with any tool
that can pipe JSON through stdin/stdout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from drinkingbird.adapters.base import Adapter


class StdinAdapter(Adapter):
    """Generic stdin/stdout adapter.

    This adapter expects input in a standard JSON format and outputs
    in a standard JSON format. It can be used with any tool that
    supports piping:

        some_tool | bdb run --adapter stdin | handler

    Input format:
    {
        "event": "stop" | "pre_tool" | "tool_failure" | "pre_compact",
        "tool_name": "...",      // for tool events
        "tool_input": {...},     // for tool events
        "tool_response": "...",  // for failure events
        "transcript": "...",     // for stop events (inline or path)
        "cwd": "..."
    }

    Output format:
    {
        "action": "allow" | "block" | "kill",
        "message": "...",
        "context": "..."  // additional context to inject
    }
    """

    agent_name = "stdin"

    def parse_input(self, raw_input: dict[str, Any]) -> dict[str, Any]:
        """Parse generic stdin input.

        Normalizes various input formats to our standard.
        """
        # Map event names
        event_map = {
            "stop": "Stop",
            "pre_tool": "PreToolUse",
            "pre_tool_use": "PreToolUse",
            "tool_failure": "PostToolUseFailure",
            "post_tool_failure": "PostToolUseFailure",
            "pre_compact": "PreCompact",
            "compact": "PreCompact",
        }

        event_name = raw_input.get(
            "event",
            raw_input.get("hook_event_name", raw_input.get("type", "")),
        )
        normalized_event = event_map.get(event_name.lower(), event_name)

        # Handle transcript - could be inline or path
        transcript = raw_input.get(
            "transcript",
            raw_input.get("transcript_path", raw_input.get("messages", "")),
        )

        # If transcript is a list, it's inline messages
        if isinstance(transcript, list):
            # Write to temp file for consistency
            import json
            import tempfile

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".jsonl", delete=False
            ) as f:
                for msg in transcript:
                    f.write(json.dumps(msg) + "\n")
                transcript = f.name

        return {
            "hook_event_name": normalized_event,
            "tool_name": raw_input.get(
                "tool_name", raw_input.get("tool", "")
            ),
            "tool_input": raw_input.get(
                "tool_input", raw_input.get("input", {})
            ),
            "tool_response": raw_input.get(
                "tool_response", raw_input.get("response", raw_input.get("error", ""))
            ),
            "transcript_path": transcript if isinstance(transcript, str) else "",
            "cwd": raw_input.get("cwd", raw_input.get("working_dir", "")),
        }

    def format_output(self, result: dict[str, Any], hook_event: str) -> dict[str, Any]:
        """Format output for generic consumers.

        Returns a simple, consistent format that any tool can parse.
        """
        output: dict[str, Any] = {"action": "allow"}

        if result.get("decision") == "block":
            output["action"] = "block"
            output["message"] = result.get("reason", "Blocked by supervisor")

        if "hookSpecificOutput" in result:
            context = result["hookSpecificOutput"].get("additionalContext", "")
            if context:
                output["context"] = context

        return output

    def get_install_config(self) -> dict[str, Any]:
        """Get generic installation config.

        Since this is a generic adapter, we just return documentation.
        """
        return {
            "description": "Generic stdin/stdout adapter",
            "usage": "your_tool | bdb run --adapter stdin | your_handler",
            "input_format": {
                "event": "stop | pre_tool | tool_failure | pre_compact",
                "tool_name": "string (for tool events)",
                "tool_input": "object (for tool events)",
                "tool_response": "string (for failure events)",
                "transcript": "string or array (for stop events)",
                "cwd": "string",
            },
            "output_format": {
                "action": "allow | block | kill",
                "message": "string (if blocking)",
                "context": "string (additional context)",
            },
        }

    def get_config_path(self) -> Path:
        """No config path for generic adapter."""
        return Path("/dev/null")

    def install(self, bdb_path: Path) -> bool:
        """Generic adapter doesn't install anywhere.

        Print usage instructions instead.
        """
        print("Generic stdin/stdout adapter - no installation needed.")
        print()
        print("Usage:")
        print(f"    your_tool | {bdb_path} run --adapter stdin | your_handler")
        print()
        print("Or pipe JSON directly:")
        print(f"    echo '{{\"event\": \"stop\", ...}}' | {bdb_path} run --adapter stdin")
        print()
        return True

    def uninstall(self) -> bool:
        """Generic adapter doesn't install anywhere, so nothing to uninstall."""
        print("Generic stdin/stdout adapter - no hooks installed.")
        return False
