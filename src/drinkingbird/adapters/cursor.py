"""Cursor adapter for Better Drinking Bird."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from drinkingbird.adapters.base import Adapter


class CursorAdapter(Adapter):
    """Adapter for Cursor AI hooks.

    Cursor has a hook system similar to Claude Code, with script-based
    hooks that receive data via stdin and return responses via stdout.
    """

    agent_name = "cursor"

    def parse_input(self, raw_input: dict[str, Any]) -> dict[str, Any]:
        """Parse Cursor hook input.

        Cursor provides similar input format to Claude Code.
        We normalize to our common format.
        """
        # Map Cursor event names to our standard names
        event_map = {
            "agent_stop": "Stop",
            "pre_tool_use": "PreToolUse",
            "tool_failure": "PostToolUseFailure",
            "pre_compact": "PreCompact",
        }

        event_name = raw_input.get("event", raw_input.get("hook_event_name", ""))
        normalized_event = event_map.get(event_name, event_name)

        return {
            "hook_event_name": normalized_event,
            "tool_name": raw_input.get("tool_name", raw_input.get("tool", "")),
            "tool_input": raw_input.get("tool_input", raw_input.get("input", {})),
            "tool_response": raw_input.get("tool_response", raw_input.get("response", "")),
            "transcript_path": raw_input.get("transcript_path", raw_input.get("transcript", "")),
            "cwd": raw_input.get("cwd", raw_input.get("working_directory", "")),
        }

    def format_output(self, result: dict[str, Any], hook_event: str) -> dict[str, Any]:
        """Format output for Cursor.

        Cursor expects similar format to Claude Code.
        """
        # Cursor uses same format as Claude Code
        return result

    def get_install_config(self) -> dict[str, Any]:
        """Get Cursor hook configuration."""
        return {
            "hooks": {
                "agent_stop": {
                    "command": "bdb run --adapter cursor",
                    "timeout": 30,
                },
                "pre_tool_use": {
                    "command": "bdb run --adapter cursor",
                    "timeout": 5,
                    "tools": ["bash", "shell"],
                },
                "tool_failure": {
                    "command": "bdb run --adapter cursor",
                    "timeout": 15,
                },
                "pre_compact": {
                    "command": "bdb run --adapter cursor",
                    "timeout": 5,
                },
            }
        }

    def get_config_path(self) -> Path:
        """Get path to Cursor hooks configuration.

        Cursor stores hooks config in the workspace .cursor directory
        or in the global config.
        """
        # Check for global config first
        global_config = Path.home() / ".cursor" / "hooks.json"
        if global_config.parent.exists():
            return global_config

        # Fall back to current workspace
        return Path.cwd() / ".cursor" / "hooks.json"

    def install(self, bdb_path: Path) -> bool:
        """Install BDB hooks for Cursor."""
        import json

        config_path = self.get_config_path()

        # Read existing config
        existing = {}
        if config_path.exists():
            try:
                existing = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                pass

        # Get install config
        install_config = self.get_install_config()

        # Update commands with actual bdb path
        for hook_name, hook_config in install_config["hooks"].items():
            hook_config["command"] = f"{bdb_path} run --adapter cursor"

        # Merge - replace our hooks
        existing_hooks = existing.get("hooks", {})
        existing_hooks.update(install_config["hooks"])
        existing["hooks"] = existing_hooks

        # Write back
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(existing, indent=2))

        return True
