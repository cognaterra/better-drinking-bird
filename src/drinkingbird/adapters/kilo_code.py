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
    supports_local = True

    def get_local_config_path(self, workspace: Path) -> Path:
        """Get path to local Kilo Code settings."""
        return workspace / ".kilocode" / "settings.local.json"

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

    def install(
        self,
        bdb_path: Path,
        scope: str = "global",
        workspace: Path | None = None,
    ) -> bool:
        """Install BDB hooks for Kilo Code."""
        config_path = self.get_effective_config_path(scope, workspace)

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

    def uninstall(self, scope: str = "global", workspace: Path | None = None) -> bool:
        """Uninstall BDB hooks from Kilo Code."""
        config_path = self.get_effective_config_path(scope, workspace)

        if not config_path.exists():
            return False

        try:
            existing = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            return False

        existing_hooks = existing.get("hooks", {})
        if not existing_hooks:
            return False

        # Remove bdb hooks
        found_bdb = False
        for hook_name in list(existing_hooks.keys()):
            hook_list = existing_hooks[hook_name]
            if isinstance(hook_list, list):
                original_len = len(hook_list)
                existing_hooks[hook_name] = [
                    h for h in hook_list if "bdb" not in h.get("command", "")
                ]
                if len(existing_hooks[hook_name]) < original_len:
                    found_bdb = True
                # Remove empty hook lists
                if not existing_hooks[hook_name]:
                    del existing_hooks[hook_name]

        if not found_bdb:
            return False

        # Update or remove hooks key
        if existing_hooks:
            existing["hooks"] = existing_hooks
        else:
            del existing["hooks"]

        # Write back
        config_path.write_text(json.dumps(existing, indent=2))
        return True
