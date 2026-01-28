"""GitHub Copilot adapter for Better Drinking Bird."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from drinkingbird.adapters.base import Adapter


class CopilotAdapter(Adapter):
    """Adapter for GitHub Copilot CLI hooks.

    GitHub Copilot CLI has a hooks system that executes shell commands
    at key points during agent execution.
    """

    agent_name = "copilot"

    def parse_input(self, raw_input: dict[str, Any]) -> dict[str, Any]:
        """Parse Copilot hook input.

        Copilot provides input in its own format.
        We normalize to our common format.
        """
        # Map Copilot event names to our standard names
        event_map = {
            "stop": "Stop",
            "pre_tool": "PreToolUse",
            "post_tool_failure": "PostToolUseFailure",
            "pre_compact": "PreCompact",
        }

        event_name = raw_input.get("hook_type", raw_input.get("hook_event_name", ""))
        normalized_event = event_map.get(event_name, event_name)

        return {
            "hook_event_name": normalized_event,
            "tool_name": raw_input.get("tool_name", raw_input.get("tool", "")),
            "tool_input": raw_input.get("tool_input", raw_input.get("input", {})),
            "tool_response": raw_input.get("tool_response", raw_input.get("output", "")),
            "transcript_path": raw_input.get("transcript_path", raw_input.get("session_file", "")),
            "cwd": raw_input.get("cwd", raw_input.get("working_dir", "")),
        }

    def format_output(self, result: dict[str, Any], hook_event: str) -> dict[str, Any]:
        """Format output for Copilot.

        Copilot expects responses in a specific format.
        """
        # Check if this is a block decision
        if result.get("decision") == "block":
            return {
                "action": "block",
                "message": result.get("reason", "Blocked by supervisor"),
            }

        # Check if this is context injection
        if "hookSpecificOutput" in result:
            return {
                "action": "continue",
                "context": result["hookSpecificOutput"].get("additionalContext", ""),
            }

        # Default allow
        return {"action": "continue"}

    def get_install_config(self) -> dict[str, Any]:
        """Get Copilot hook configuration."""
        return {
            "hooks": {
                "stop": "bdb run --adapter copilot",
                "pre_tool": "bdb run --adapter copilot",
                "post_tool_failure": "bdb run --adapter copilot",
                "pre_compact": "bdb run --adapter copilot",
            }
        }

    def get_config_path(self) -> Path:
        """Get path to Copilot hooks configuration."""
        return Path.home() / ".copilot" / "hooks.yaml"

    def install(self, bdb_path: Path) -> bool:
        """Install BDB hooks for Copilot."""
        import yaml

        config_path = self.get_config_path()

        # Read existing config
        existing = {}
        if config_path.exists():
            try:
                with open(config_path) as f:
                    existing = yaml.safe_load(f) or {}
            except yaml.YAMLError:
                pass

        # Get install config
        install_config = self.get_install_config()

        # Update commands with actual bdb path
        for hook_name in install_config["hooks"]:
            install_config["hooks"][hook_name] = f"{bdb_path} run --adapter copilot"

        # Merge hooks
        existing_hooks = existing.get("hooks", {})
        existing_hooks.update(install_config["hooks"])
        existing["hooks"] = existing_hooks

        # Write back
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            yaml.dump(existing, f, default_flow_style=False)

        return True
