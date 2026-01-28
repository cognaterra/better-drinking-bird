"""Kilo Code adapter for Better Drinking Bird."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from drinkingbird.adapters.base import Adapter


class KiloCodeAdapter(Adapter):
    """Adapter for Kilo Code hooks.

    Kilo Code uses the same hook system as Claude Code since it forked
    from the same codebase. The only difference is the config path.
    """

    agent_name = "kilo-code"

    def parse_input(self, raw_input: dict[str, Any]) -> dict[str, Any]:
        """Parse Kilo Code hook input.

        Kilo Code uses identical format to Claude Code.
        """
        return raw_input

    def format_output(self, result: dict[str, Any], hook_event: str) -> dict[str, Any]:
        """Format output for Kilo Code.

        Kilo Code uses identical format to Claude Code.
        """
        return result

    def get_install_config(self) -> dict[str, Any]:
        """Get Kilo Code hook configuration."""
        return {
            "hooks": {
                "Stop": [
                    {
                        "command": "bdb run --adapter kilo-code",
                        "timeout": 30000,
                    }
                ],
                "PreToolUse": [
                    {
                        "command": "bdb run --adapter kilo-code",
                        "timeout": 5000,
                        "matcher": "Bash",
                    }
                ],
                "PostToolUseFailure": [
                    {
                        "command": "bdb run --adapter kilo-code",
                        "timeout": 15000,
                    }
                ],
                "PreCompact": [
                    {
                        "command": "bdb run --adapter kilo-code",
                        "timeout": 5000,
                    }
                ],
            }
        }

    def get_config_path(self) -> Path:
        """Get path to Kilo Code settings."""
        return Path.home() / ".kilocode" / "settings.json"

    def install(self, bdb_path: Path) -> bool:
        """Install BDB hooks for Kilo Code."""
        config_path = self.get_config_path()

        # Read existing config
        existing = {}
        if config_path.exists():
            try:
                existing = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                pass

        # Get install config and update command path
        install_config = self.get_install_config()

        # Update commands with actual bdb path
        for hook_name, hook_list in install_config["hooks"].items():
            for hook in hook_list:
                hook["command"] = f"{bdb_path} run --adapter kilo-code"

        # Merge hooks - add our hooks to existing ones
        existing_hooks = existing.get("hooks", {})
        for hook_name, hook_list in install_config["hooks"].items():
            if hook_name not in existing_hooks:
                existing_hooks[hook_name] = []

            # Remove any existing bdb hooks
            existing_hooks[hook_name] = [
                h for h in existing_hooks[hook_name]
                if "bdb" not in h.get("command", "")
            ]

            # Add our hooks
            existing_hooks[hook_name].extend(hook_list)

        existing["hooks"] = existing_hooks

        # Write back
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(existing, indent=2))

        return True
