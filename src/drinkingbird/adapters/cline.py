"""Cline adapter for Better Drinking Bird."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

from drinkingbird.adapters.base import Adapter


class ClineAdapter(Adapter):
    """Adapter for Cline hooks.

    Cline uses executable scripts in a hooks directory rather than
    JSON configuration. Each hook is a separate script file.
    """

    agent_name = "cline"
    supports_local = True

    def get_local_config_path(self, workspace: Path) -> Path:
        """Get path to local Cline hooks directory."""
        return workspace / ".cline" / "hooks"

    # Map Cline event names to BDB standard names
    EVENT_MAP = {
        "TaskComplete": "Stop",
        "TaskStart": "SessionStart",
        "TaskCancel": "Stop",
        "PreToolUse": "PreToolUse",
        "PostToolUse": "PostToolUse",
    }

    # Map Cline tool names to BDB tool names
    TOOL_MAP = {
        "execute_command": "Bash",
        "run_terminal_command": "Bash",
    }

    def parse_input(self, raw_input: dict[str, Any]) -> dict[str, Any]:
        """Parse Cline hook input.

        Cline provides:
        - hookName: Event type (TaskComplete, PreToolUse, etc.)
        - taskId: Task identifier
        - workspaceRoots: List of workspace paths
        - toolName: Tool being used (for tool hooks)
        - toolInput: Input to the tool
        """
        hook_name = raw_input.get("hookName", "")
        normalized_event = self.EVENT_MAP.get(hook_name, hook_name)

        # Map tool names
        tool_name = raw_input.get("toolName", "")
        normalized_tool = self.TOOL_MAP.get(tool_name, tool_name)

        # Extract tool input
        tool_input = raw_input.get("toolInput", {})
        if isinstance(tool_input, str):
            tool_input = {"command": tool_input}

        return {
            "hook_event_name": normalized_event,
            "tool_name": normalized_tool,
            "tool_input": tool_input,
            "tool_response": raw_input.get("toolOutput", ""),
            "cwd": raw_input.get("workspaceRoots", ["."])[0] if raw_input.get("workspaceRoots") else ".",
            "task_id": raw_input.get("taskId", ""),
        }

    def format_output(self, result: dict[str, Any], hook_event: str) -> dict[str, Any]:
        """Format output for Cline.

        Cline expects:
        - cancel: true to block the action
        - reason: explanation (shown to user/agent)
        - contextModification: text to inject into conversation
        """
        output: dict[str, Any] = {}

        # Handle block decision
        if result.get("decision") == "block":
            output["cancel"] = True
            output["reason"] = result.get("reason", result.get("message", "Blocked by supervisor"))

        # Handle context injection
        hook_output = result.get("hookSpecificOutput", {})
        if hook_output.get("additionalContext"):
            output["contextModification"] = hook_output["additionalContext"]

        return output

    def get_install_config(self) -> dict[str, Any]:
        """Get Cline hook configuration.

        Returns the hook types to install. Actual installation creates
        executable scripts rather than JSON config.
        """
        return {
            "hooks": ["TaskComplete", "PreToolUse", "PostToolUse"]
        }

    def get_config_path(self) -> Path:
        """Get path to Cline hooks directory."""
        return Path.home() / "Documents" / "Cline" / "Hooks"

    def install(
        self,
        bdb_path: Path,
        scope: str = "global",
        workspace: Path | None = None,
    ) -> bool:
        """Install BDB hooks for Cline.

        Creates executable wrapper scripts in the Cline hooks directory.
        """
        hooks_dir = self.get_effective_config_path(scope, workspace)
        hooks_dir.mkdir(parents=True, exist_ok=True)

        # Script template
        script_template = '''#!/bin/bash
# Better Drinking Bird hook for Cline
# Auto-generated - do not edit
exec {bdb_path} run --adapter cline
'''

        install_config = self.get_install_config()
        for hook_name in install_config["hooks"]:
            script_path = hooks_dir / hook_name
            script_content = script_template.format(bdb_path=bdb_path)

            # Write script
            script_path.write_text(script_content)

            # Make executable (chmod +x)
            current_mode = script_path.stat().st_mode
            script_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        return True

    def uninstall(self, scope: str = "global", workspace: Path | None = None) -> bool:
        """Uninstall BDB hooks from Cline.

        Removes bdb hook scripts from the Cline hooks directory.
        """
        hooks_dir = self.get_effective_config_path(scope, workspace)

        if not hooks_dir.exists():
            return False

        install_config = self.get_install_config()
        found_bdb = False

        for hook_name in install_config["hooks"]:
            script_path = hooks_dir / hook_name
            if script_path.exists():
                content = script_path.read_text()
                if "bdb" in content:
                    script_path.unlink()
                    found_bdb = True

        return found_bdb
