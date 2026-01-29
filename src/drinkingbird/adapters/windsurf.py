"""Windsurf adapter for Better Drinking Bird."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from drinkingbird.adapters.base import Adapter


class WindsurfAdapter(Adapter):
    """Adapter for Windsurf (Codeium) Cascade hooks.

    Windsurf has a hook system with pre/post events for various actions.
    Key difference: Windsurf uses exit codes for blocking (0=allow, 2=block)
    rather than JSON responses.

    Supported hooks:
    - pre_run_command / post_run_command: Bash command execution
    - post_cascade_response: When agent finishes responding (used for stop detection)

    Note: Windsurf doesn't have memory compaction, so PreCompact is not supported.
    """

    agent_name = "windsurf"
    supports_local = True

    # Flag to signal CLI should use exit codes
    uses_exit_codes = True

    def get_local_config_path(self, workspace: Path) -> Path:
        """Get path to local Windsurf hooks configuration."""
        return workspace / ".windsurf" / "hooks.json"

    def parse_input(self, raw_input: dict[str, Any]) -> dict[str, Any]:
        """Parse Windsurf hook input.

        Windsurf provides:
        - agent_action_name: The hook event (e.g., "pre_run_command")
        - trajectory_id: Conversation identifier
        - execution_id: Single turn identifier
        - timestamp: ISO 8601 timestamp
        - tool_info: Event-specific data
        """
        # Map Windsurf event names to BDB standard names
        event_map = {
            "pre_run_command": "PreToolUse",
            "post_run_command": "PostToolUseFailure",
            "post_cascade_response": "Stop",
        }

        event_name = raw_input.get("agent_action_name", "")
        normalized_event = event_map.get(event_name, event_name)

        tool_info = raw_input.get("tool_info", {})

        # Build normalized input
        result: dict[str, Any] = {
            "hook_event_name": normalized_event,
            "trajectory_id": raw_input.get("trajectory_id", ""),
            "execution_id": raw_input.get("execution_id", ""),
            "timestamp": raw_input.get("timestamp", ""),
        }

        # Map tool_info fields based on event type
        if event_name == "pre_run_command":
            result["tool_name"] = "Bash"
            result["tool_input"] = {
                "command": tool_info.get("command_line", ""),
            }
            result["cwd"] = tool_info.get("cwd", "")

        elif event_name == "post_run_command":
            result["tool_name"] = "Bash"
            result["tool_input"] = {
                "command": tool_info.get("command_line", ""),
            }
            result["tool_response"] = tool_info.get("output", "")
            result["exit_code"] = tool_info.get("exit_code", 0)
            result["cwd"] = tool_info.get("cwd", "")

        elif event_name == "post_cascade_response":
            # For stop detection, we use the response content
            result["response"] = tool_info.get("response", "")

        return result

    def format_output(self, result: dict[str, Any], hook_event: str) -> dict[str, Any]:
        """Format output for Windsurf.

        Windsurf uses exit codes for blocking decisions:
        - Exit 0: Allow action to proceed
        - Exit 2: Block action

        Since show_output is enabled, stdout is shown to the user.
        We output the human-readable message instead of JSON.
        """
        output: dict[str, Any] = {
            "_windsurf_exit_code": 2 if result.get("decision") == "block" else 0,
        }

        # For blocking, include the message to show the user
        if result.get("decision") == "block":
            message = result.get("message") or result.get("reason") or "Blocked by supervisor"
            output["_windsurf_message"] = message

        return output

    def get_install_config(self) -> dict[str, Any]:
        """Get Windsurf hook configuration."""
        return {
            "hooks": {
                "pre_run_command": [
                    {
                        "command": "bdb run --adapter windsurf",
                        "show_output": True,
                    }
                ],
                "post_run_command": [
                    {
                        "command": "bdb run --adapter windsurf",
                        "show_output": True,
                    }
                ],
                "post_cascade_response": [
                    {
                        "command": "bdb run --adapter windsurf",
                        "show_output": True,
                    }
                ],
            }
        }

    def get_config_path(self) -> Path:
        """Get path to global Windsurf hooks configuration."""
        return Path.home() / ".codeium" / "windsurf" / "hooks.json"

    def install(
        self,
        bdb_path: Path,
        scope: str = "global",
        workspace: Path | None = None,
    ) -> bool:
        """Install BDB hooks for Windsurf."""
        import json

        config_path = self.get_effective_config_path(scope, workspace)

        # Read existing config
        existing: dict[str, Any] = {}
        if config_path.exists():
            try:
                existing = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                pass

        # Get install config
        install_config = self.get_install_config()

        # Update commands with actual bdb path
        for hook_name, hook_list in install_config["hooks"].items():
            for hook_config in hook_list:
                hook_config["command"] = f"{bdb_path} run --adapter windsurf"

        # Merge hooks - Windsurf uses arrays, so we need to handle differently
        existing_hooks = existing.get("hooks", {})

        for hook_name, new_hooks in install_config["hooks"].items():
            if hook_name not in existing_hooks:
                existing_hooks[hook_name] = []

            # Remove any existing bdb hooks
            existing_hooks[hook_name] = [
                h for h in existing_hooks[hook_name]
                if not isinstance(h, dict) or "bdb" not in h.get("command", "")
            ]

            # Add our hooks
            existing_hooks[hook_name].extend(new_hooks)

        existing["hooks"] = existing_hooks

        # Write back
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(existing, indent=2))

        return True

    def uninstall(self, scope: str = "global", workspace: Path | None = None) -> bool:
        """Uninstall BDB hooks from Windsurf."""
        import json

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

        # Remove hooks that contain "bdb" in the command
        found_bdb = False
        for hook_name in list(existing_hooks.keys()):
            hook_list = existing_hooks[hook_name]
            if isinstance(hook_list, list):
                original_len = len(hook_list)
                existing_hooks[hook_name] = [
                    h for h in hook_list
                    if not isinstance(h, dict) or "bdb" not in h.get("command", "")
                ]
                if len(existing_hooks[hook_name]) < original_len:
                    found_bdb = True

                # Remove empty arrays
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
