"""Claude Code adapter for Better Drinking Bird."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from drinkingbird.adapters.base import Adapter


class ClaudeCodeAdapter(Adapter):
    """Adapter for Claude Code hooks."""

    agent_name = "claude-code"

    def parse_input(self, raw_input: dict[str, Any]) -> dict[str, Any]:
        """Parse Claude Code hook input.

        Claude Code provides input as JSON with fields like:
        - hook_event_name: The event type (Stop, PreToolUse, etc.)
        - tool_name: Name of the tool (for tool hooks)
        - tool_input: Input to the tool
        - transcript_path: Path to conversation transcript
        - cwd: Current working directory
        """
        # Claude Code input is already in our expected format
        return raw_input

    def format_output(self, result: dict[str, Any], hook_event: str) -> dict[str, Any]:
        """Format output for Claude Code.

        Claude Code expects:
        - For blocks: {"decision": "block", "reason": "message"}
        - For context injection: {"hookSpecificOutput": {"additionalContext": "..."}}
        """
        # Result is already in Claude Code format
        return result

    def get_install_config(self) -> dict[str, Any]:
        """Get Claude Code hook configuration."""
        return {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "bdb run",
                                "timeout": 30000,
                            }
                        ]
                    }
                ],
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "bdb run",
                                "timeout": 5000,
                            }
                        ]
                    }
                ],
                "PostToolUseFailure": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "bdb run",
                                "timeout": 15000,
                            }
                        ]
                    }
                ],
                "PreCompact": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "bdb run",
                                "timeout": 5000,
                            }
                        ]
                    }
                ],
            }
        }

    def get_config_path(self) -> Path:
        """Get path to Claude Code settings."""
        return Path.home() / ".claude" / "settings.json"

    def install(self, bdb_path: Path) -> bool:
        """Install BDB hooks for Claude Code."""
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
            for hook_entry in hook_list:
                for hook in hook_entry.get("hooks", []):
                    hook["command"] = str(bdb_path) + " run"

        # Merge hooks - add our hooks to existing ones
        existing_hooks = existing.get("hooks", {})
        for hook_name, hook_list in install_config["hooks"].items():
            if hook_name not in existing_hooks:
                existing_hooks[hook_name] = []

            # Remove any existing bdb hooks (check nested structure)
            def has_bdb(entry: dict) -> bool:
                for hook in entry.get("hooks", []):
                    if "bdb" in hook.get("command", ""):
                        return True
                return False

            existing_hooks[hook_name] = [
                h for h in existing_hooks[hook_name]
                if not has_bdb(h)
            ]

            # Add our hooks
            existing_hooks[hook_name].extend(hook_list)

        existing["hooks"] = existing_hooks

        # Write back
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(existing, indent=2))

        return True

    def uninstall(self) -> bool:
        """Uninstall BDB hooks from Claude Code."""
        config_path = self.get_config_path()

        if not config_path.exists():
            return False

        try:
            existing = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            return False

        existing_hooks = existing.get("hooks", {})
        if not existing_hooks:
            return False

        # Check for bdb hooks in nested structure
        def has_bdb(entry: dict) -> bool:
            for hook in entry.get("hooks", []):
                if "bdb" in hook.get("command", ""):
                    return True
            return False

        found_bdb = False
        for hook_name in list(existing_hooks.keys()):
            hook_list = existing_hooks[hook_name]
            if isinstance(hook_list, list):
                original_len = len(hook_list)
                existing_hooks[hook_name] = [h for h in hook_list if not has_bdb(h)]
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
