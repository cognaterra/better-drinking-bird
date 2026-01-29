"""Tests for agent adapters."""

import json
from pathlib import Path

import pytest

from drinkingbird.adapters.claude_code import ClaudeCodeAdapter
from drinkingbird.adapters.kilo_code import KiloCodeAdapter
from drinkingbird.adapters.cline import ClineAdapter


class TestClaudeCodeAdapter:
    """Tests for ClaudeCodeAdapter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = ClaudeCodeAdapter()

    def test_agent_name(self):
        """Test adapter has correct agent name."""
        assert self.adapter.agent_name == "claude-code"

    def test_get_config_path(self):
        """Test config path points to Claude settings."""
        path = self.adapter.get_config_path()

        assert path == Path.home() / ".claude" / "settings.json"


class TestClaudeCodeAdapterParseInput:
    """Tests for input parsing."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = ClaudeCodeAdapter()

    def test_parse_input_passthrough(self):
        """Test that input is passed through unchanged."""
        raw = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        }

        result = self.adapter.parse_input(raw)

        assert result == raw

    def test_parse_input_preserves_all_fields(self):
        """Test that all fields are preserved."""
        raw = {
            "hook_event_name": "Stop",
            "transcript_path": "/tmp/transcript.json",
            "cwd": "/home/user/project",
            "custom_field": "value",
        }

        result = self.adapter.parse_input(raw)

        assert result["hook_event_name"] == "Stop"
        assert result["transcript_path"] == "/tmp/transcript.json"
        assert result["cwd"] == "/home/user/project"
        assert result["custom_field"] == "value"


class TestClaudeCodeAdapterFormatOutput:
    """Tests for output formatting."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = ClaudeCodeAdapter()

    def test_format_output_passthrough(self):
        """Test that output is passed through unchanged."""
        result = {"decision": "block", "reason": "Dangerous command"}

        output = self.adapter.format_output(result, "PreToolUse")

        assert output == result

    def test_format_output_context(self):
        """Test formatting context injection output."""
        result = {"hookSpecificOutput": {"additionalContext": "Remember X"}}

        output = self.adapter.format_output(result, "Stop")

        assert output["hookSpecificOutput"]["additionalContext"] == "Remember X"


class TestClaudeCodeAdapterInstallConfig:
    """Tests for install configuration structure."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = ClaudeCodeAdapter()
        self.config = self.adapter.get_install_config()

    def test_has_hooks_key(self):
        """Test config has hooks key."""
        assert "hooks" in self.config

    def test_has_all_hook_events(self):
        """Test config has all expected hook events."""
        hooks = self.config["hooks"]

        assert "Stop" in hooks
        assert "PreToolUse" in hooks
        assert "PostToolUseFailure" in hooks
        assert "PreCompact" in hooks

    def test_hook_entries_have_hooks_array(self):
        """Test each hook entry has a hooks array."""
        for event_name, entries in self.config["hooks"].items():
            for entry in entries:
                assert "hooks" in entry, f"{event_name} entry missing hooks array"
                assert isinstance(entry["hooks"], list)

    def test_hook_commands_have_type(self):
        """Test each hook command has type field."""
        for event_name, entries in self.config["hooks"].items():
            for entry in entries:
                for hook in entry["hooks"]:
                    assert "type" in hook, f"{event_name} hook missing type"
                    assert hook["type"] == "command"

    def test_hook_commands_have_command(self):
        """Test each hook command has command field."""
        for event_name, entries in self.config["hooks"].items():
            for entry in entries:
                for hook in entry["hooks"]:
                    assert "command" in hook, f"{event_name} hook missing command"
                    assert "bdb run" in hook["command"]

    def test_hook_commands_have_timeout(self):
        """Test each hook command has timeout field."""
        for event_name, entries in self.config["hooks"].items():
            for entry in entries:
                for hook in entry["hooks"]:
                    assert "timeout" in hook, f"{event_name} hook missing timeout"
                    assert isinstance(hook["timeout"], int)

    def test_pre_tool_use_has_matcher(self):
        """Test PreToolUse has Bash matcher."""
        pre_tool = self.config["hooks"]["PreToolUse"][0]

        assert "matcher" in pre_tool
        assert pre_tool["matcher"] == "Bash"

    def test_stop_timeout(self):
        """Test Stop hook has appropriate timeout."""
        stop_hook = self.config["hooks"]["Stop"][0]["hooks"][0]

        assert stop_hook["timeout"] == 30000

    def test_pre_tool_use_timeout(self):
        """Test PreToolUse hook has appropriate timeout."""
        hook = self.config["hooks"]["PreToolUse"][0]["hooks"][0]

        assert hook["timeout"] == 5000

    def test_post_tool_use_failure_timeout(self):
        """Test PostToolUseFailure hook has appropriate timeout."""
        hook = self.config["hooks"]["PostToolUseFailure"][0]["hooks"][0]

        assert hook["timeout"] == 15000

    def test_pre_compact_timeout(self):
        """Test PreCompact hook has appropriate timeout."""
        hook = self.config["hooks"]["PreCompact"][0]["hooks"][0]

        assert hook["timeout"] == 5000


class TestClaudeCodeAdapterInstall:
    """Tests for the install method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = ClaudeCodeAdapter()

    def test_install_creates_new_config(self, tmp_path):
        """Test install creates config when none exists."""
        config_path = tmp_path / ".claude" / "settings.json"
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/usr/local/bin/bdb")

        result = self.adapter.install(bdb_path)

        assert result is True
        assert config_path.exists()

        config = json.loads(config_path.read_text())
        assert "hooks" in config

    def test_install_creates_parent_directories(self, tmp_path):
        """Test install creates parent directories if needed."""
        config_path = tmp_path / "deep" / "nested" / ".claude" / "settings.json"
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/usr/local/bin/bdb")

        self.adapter.install(bdb_path)

        assert config_path.exists()

    def test_install_updates_command_path(self, tmp_path):
        """Test install updates command with actual bdb path."""
        config_path = tmp_path / "settings.json"
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/home/user/.local/bin/bdb")

        self.adapter.install(bdb_path)

        config = json.loads(config_path.read_text())
        stop_hook = config["hooks"]["Stop"][0]["hooks"][0]

        assert stop_hook["command"] == "/home/user/.local/bin/bdb run"

    def test_install_preserves_existing_settings(self, tmp_path):
        """Test install preserves non-hook settings."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({
            "includeCoAuthoredBy": False,
            "permissions": {"allow": ["Read"]},
            "customSetting": "value",
        }))
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/usr/local/bin/bdb")

        self.adapter.install(bdb_path)

        config = json.loads(config_path.read_text())

        assert config["includeCoAuthoredBy"] is False
        assert config["permissions"] == {"allow": ["Read"]}
        assert config["customSetting"] == "value"

    def test_install_preserves_non_bdb_hooks(self, tmp_path):
        """Test install preserves hooks that aren't from bdb."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "PreCompact": [
                    {
                        "matcher": "auto",
                        "hooks": [
                            {"type": "command", "command": "exit 2"}
                        ]
                    }
                ],
                "Stop": [
                    {
                        "hooks": [
                            {"type": "command", "command": "my-custom-hook"}
                        ]
                    }
                ]
            }
        }))
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/usr/local/bin/bdb")

        self.adapter.install(bdb_path)

        config = json.loads(config_path.read_text())

        # Should have both the custom hook and the bdb hook
        pre_compact_hooks = config["hooks"]["PreCompact"]
        assert len(pre_compact_hooks) == 2

        # First should be the preserved custom hook
        assert pre_compact_hooks[0]["hooks"][0]["command"] == "exit 2"

        # Second should be the bdb hook
        assert "bdb" in pre_compact_hooks[1]["hooks"][0]["command"]

    def test_install_removes_existing_bdb_hooks(self, tmp_path):
        """Test install removes old bdb hooks before adding new ones."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/old/path/bdb run",
                                "timeout": 10000
                            }
                        ]
                    }
                ]
            }
        }))
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/new/path/bdb")

        self.adapter.install(bdb_path)

        config = json.loads(config_path.read_text())

        # Should only have one Stop hook (the new one)
        assert len(config["hooks"]["Stop"]) == 1
        assert config["hooks"]["Stop"][0]["hooks"][0]["command"] == "/new/path/bdb run"

    def test_install_handles_malformed_json(self, tmp_path):
        """Test install handles existing malformed JSON gracefully."""
        config_path = tmp_path / "settings.json"
        config_path.write_text("{ invalid json }")
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/usr/local/bin/bdb")

        result = self.adapter.install(bdb_path)

        assert result is True
        config = json.loads(config_path.read_text())
        assert "hooks" in config

    def test_install_handles_empty_hooks_section(self, tmp_path):
        """Test install handles empty hooks section."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({"hooks": {}}))
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/usr/local/bin/bdb")

        self.adapter.install(bdb_path)

        config = json.loads(config_path.read_text())

        assert "Stop" in config["hooks"]
        assert "PreToolUse" in config["hooks"]
        assert "PostToolUseFailure" in config["hooks"]
        assert "PreCompact" in config["hooks"]

    def test_install_all_hooks_have_correct_structure(self, tmp_path):
        """Test that all installed hooks have the correct nested structure."""
        config_path = tmp_path / "settings.json"
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/usr/local/bin/bdb")

        self.adapter.install(bdb_path)

        config = json.loads(config_path.read_text())

        for event_name, entries in config["hooks"].items():
            for i, entry in enumerate(entries):
                assert "hooks" in entry, (
                    f"{event_name}[{i}] missing 'hooks' array"
                )
                assert isinstance(entry["hooks"], list), (
                    f"{event_name}[{i}]['hooks'] is not a list"
                )
                for j, hook in enumerate(entry["hooks"]):
                    assert "type" in hook, (
                        f"{event_name}[{i}]['hooks'][{j}] missing 'type'"
                    )
                    assert "command" in hook, (
                        f"{event_name}[{i}]['hooks'][{j}] missing 'command'"
                    )


class TestClaudeCodeAdapterUninstall:
    """Tests for the uninstall method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = ClaudeCodeAdapter()

    def test_uninstall_removes_bdb_hooks(self, tmp_path):
        """Test uninstall removes bdb hooks."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "/usr/bin/bdb run"}]}
                ],
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "bdb run"}]}
                ],
            }
        }))
        self.adapter.get_config_path = lambda: config_path

        result = self.adapter.uninstall()

        assert result is True
        config = json.loads(config_path.read_text())
        assert "hooks" not in config or not config.get("hooks")

    def test_uninstall_preserves_non_bdb_hooks(self, tmp_path):
        """Test uninstall preserves hooks that aren't from bdb."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "/usr/bin/bdb run"}]},
                    {"hooks": [{"type": "command", "command": "my-custom-hook"}]},
                ],
            }
        }))
        self.adapter.get_config_path = lambda: config_path

        result = self.adapter.uninstall()

        assert result is True
        config = json.loads(config_path.read_text())
        assert "Stop" in config["hooks"]
        assert len(config["hooks"]["Stop"]) == 1
        assert config["hooks"]["Stop"][0]["hooks"][0]["command"] == "my-custom-hook"

    def test_uninstall_preserves_other_settings(self, tmp_path):
        """Test uninstall preserves non-hook settings."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({
            "includeCoAuthoredBy": True,
            "permissions": {"allow": ["Read"]},
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "bdb run"}]}
                ],
            }
        }))
        self.adapter.get_config_path = lambda: config_path

        self.adapter.uninstall()

        config = json.loads(config_path.read_text())
        assert config["includeCoAuthoredBy"] is True
        assert config["permissions"] == {"allow": ["Read"]}

    def test_uninstall_returns_false_if_no_bdb_hooks(self, tmp_path):
        """Test uninstall returns False if no bdb hooks found."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "other-hook"}]}
                ],
            }
        }))
        self.adapter.get_config_path = lambda: config_path

        result = self.adapter.uninstall()

        assert result is False

    def test_uninstall_returns_false_if_no_config_file(self, tmp_path):
        """Test uninstall returns False if config file doesn't exist."""
        config_path = tmp_path / "settings.json"
        self.adapter.get_config_path = lambda: config_path

        result = self.adapter.uninstall()

        assert result is False

    def test_uninstall_returns_false_if_no_hooks_section(self, tmp_path):
        """Test uninstall returns False if config has no hooks section."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({"includeCoAuthoredBy": True}))
        self.adapter.get_config_path = lambda: config_path

        result = self.adapter.uninstall()

        assert result is False

    def test_uninstall_handles_malformed_json(self, tmp_path):
        """Test uninstall handles malformed JSON gracefully."""
        config_path = tmp_path / "settings.json"
        config_path.write_text("{ invalid json }")
        self.adapter.get_config_path = lambda: config_path

        result = self.adapter.uninstall()

        assert result is False

    def test_uninstall_removes_empty_hook_types(self, tmp_path):
        """Test uninstall removes hook types that become empty."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "bdb run"}]}
                ],
                "PreToolUse": [
                    {"hooks": [{"type": "command", "command": "other-hook"}]}
                ],
            }
        }))
        self.adapter.get_config_path = lambda: config_path

        self.adapter.uninstall()

        config = json.loads(config_path.read_text())
        assert "Stop" not in config["hooks"]
        assert "PreToolUse" in config["hooks"]


class TestKiloCodeAdapter:
    """Tests for KiloCodeAdapter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = KiloCodeAdapter()

    def test_agent_name(self):
        """Test agent name is correct."""
        assert self.adapter.agent_name == "kilo-code"

    def test_config_path(self):
        """Test config path points to kilocode settings."""
        path = self.adapter.get_config_path()
        assert path == Path.home() / ".kilocode" / "settings.json"

    def test_parse_input_passthrough(self):
        """Test input is passed through unchanged."""
        raw = {
            "hook_event_name": "Stop",
            "transcript_path": "/tmp/transcript.jsonl",
            "cwd": "/project",
        }
        result = self.adapter.parse_input(raw)
        assert result == raw

    def test_format_output_passthrough(self):
        """Test output is passed through unchanged."""
        result = {"decision": "block", "reason": "test"}
        output = self.adapter.format_output(result, "Stop")
        assert output == result

    def test_install_config_has_all_hooks(self):
        """Test install config includes all hook types."""
        config = self.adapter.get_install_config()
        assert "hooks" in config
        assert "Stop" in config["hooks"]
        assert "PreToolUse" in config["hooks"]
        assert "PostToolUseFailure" in config["hooks"]
        assert "PreCompact" in config["hooks"]


class TestClineAdapter:
    """Tests for ClineAdapter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = ClineAdapter()

    def test_agent_name(self):
        """Test agent name is correct."""
        assert self.adapter.agent_name == "cline"

    def test_config_path(self):
        """Test config path points to Cline hooks directory."""
        path = self.adapter.get_config_path()
        assert path == Path.home() / "Documents" / "Cline" / "Hooks"

    def test_parse_input_maps_task_complete_to_stop(self):
        """Test TaskComplete is mapped to Stop."""
        raw = {
            "hookName": "TaskComplete",
            "taskId": "abc123",
            "workspaceRoots": ["/project"],
        }
        result = self.adapter.parse_input(raw)
        assert result["hook_event_name"] == "Stop"

    def test_parse_input_maps_pre_tool_use(self):
        """Test PreToolUse passes through."""
        raw = {
            "hookName": "PreToolUse",
            "toolName": "execute_command",
            "toolInput": {"command": "git status"},
        }
        result = self.adapter.parse_input(raw)
        assert result["hook_event_name"] == "PreToolUse"
        assert result["tool_name"] == "Bash"
        assert result["tool_input"]["command"] == "git status"

    def test_format_output_block(self):
        """Test block decision is formatted for Cline."""
        result = {"decision": "block", "reason": "Get back to work"}
        output = self.adapter.format_output(result, "Stop")
        assert output["cancel"] is True
        assert output["reason"] == "Get back to work"

    def test_format_output_allow(self):
        """Test allow decision returns empty or minimal response."""
        result = {}
        output = self.adapter.format_output(result, "Stop")
        assert output.get("cancel") is not True

    def test_format_output_context(self):
        """Test context injection uses contextModification."""
        result = {
            "hookSpecificOutput": {
                "additionalContext": "Remember the plan"
            }
        }
        output = self.adapter.format_output(result, "PreCompact")
        assert output["contextModification"] == "Remember the plan"


class TestWindsurfAdapter:
    """Tests for WindsurfAdapter."""

    def setup_method(self):
        """Set up test fixtures."""
        from drinkingbird.adapters.windsurf import WindsurfAdapter
        self.adapter = WindsurfAdapter()

    def test_agent_name(self):
        """Test agent name is correct."""
        assert self.adapter.agent_name == "windsurf"

    def test_supports_local(self):
        """Test adapter supports local installation."""
        assert self.adapter.supports_local is True

    def test_uses_exit_codes(self):
        """Test adapter uses exit codes for blocking."""
        assert self.adapter.uses_exit_codes is True

    def test_config_path(self):
        """Test config path points to Codeium windsurf hooks."""
        path = self.adapter.get_config_path()
        assert path == Path.home() / ".codeium" / "windsurf" / "hooks.json"

    def test_local_config_path(self, tmp_path):
        """Test local config path."""
        path = self.adapter.get_local_config_path(tmp_path)
        assert path == tmp_path / ".windsurf" / "hooks.json"


class TestWindsurfAdapterParseInput:
    """Tests for Windsurf input parsing."""

    def setup_method(self):
        """Set up test fixtures."""
        from drinkingbird.adapters.windsurf import WindsurfAdapter
        self.adapter = WindsurfAdapter()

    def test_parse_pre_run_command(self):
        """Test pre_run_command is mapped to PreToolUse."""
        raw = {
            "agent_action_name": "pre_run_command",
            "trajectory_id": "traj-123",
            "execution_id": "exec-456",
            "timestamp": "2026-01-29T10:00:00Z",
            "tool_info": {
                "command_line": "git status",
                "cwd": "/project",
            },
        }
        result = self.adapter.parse_input(raw)

        assert result["hook_event_name"] == "PreToolUse"
        assert result["tool_name"] == "Bash"
        assert result["tool_input"]["command"] == "git status"
        assert result["cwd"] == "/project"
        assert result["trajectory_id"] == "traj-123"

    def test_parse_post_run_command(self):
        """Test post_run_command is mapped to PostToolUseFailure."""
        raw = {
            "agent_action_name": "post_run_command",
            "trajectory_id": "traj-123",
            "execution_id": "exec-456",
            "timestamp": "2026-01-29T10:00:00Z",
            "tool_info": {
                "command_line": "npm test",
                "cwd": "/project",
                "output": "Error: test failed",
                "exit_code": 1,
            },
        }
        result = self.adapter.parse_input(raw)

        assert result["hook_event_name"] == "PostToolUseFailure"
        assert result["tool_name"] == "Bash"
        assert result["tool_input"]["command"] == "npm test"
        assert result["tool_response"] == "Error: test failed"
        assert result["exit_code"] == 1

    def test_parse_post_cascade_response(self):
        """Test post_cascade_response is mapped to Stop."""
        raw = {
            "agent_action_name": "post_cascade_response",
            "trajectory_id": "traj-123",
            "execution_id": "exec-456",
            "timestamp": "2026-01-29T10:00:00Z",
            "tool_info": {
                "response": "I've completed the task. Would you like me to proceed?",
            },
        }
        result = self.adapter.parse_input(raw)

        assert result["hook_event_name"] == "Stop"
        assert result["response"] == "I've completed the task. Would you like me to proceed?"

    def test_parse_unknown_event_passthrough(self):
        """Test unknown events pass through unchanged."""
        raw = {
            "agent_action_name": "unknown_event",
            "trajectory_id": "traj-123",
        }
        result = self.adapter.parse_input(raw)

        assert result["hook_event_name"] == "unknown_event"


class TestWindsurfAdapterFormatOutput:
    """Tests for Windsurf output formatting."""

    def setup_method(self):
        """Set up test fixtures."""
        from drinkingbird.adapters.windsurf import WindsurfAdapter
        self.adapter = WindsurfAdapter()

    def test_format_output_block_sets_exit_code_2(self):
        """Test block decision sets exit code 2."""
        result = {"decision": "block", "reason": "Dangerous command"}
        output = self.adapter.format_output(result, "PreToolUse")

        assert output["_windsurf_exit_code"] == 2
        assert output["decision"] == "block"

    def test_format_output_allow_sets_exit_code_0(self):
        """Test allow decision sets exit code 0."""
        result = {"decision": "allow"}
        output = self.adapter.format_output(result, "PreToolUse")

        assert output["_windsurf_exit_code"] == 0

    def test_format_output_no_decision_sets_exit_code_0(self):
        """Test no decision defaults to exit code 0."""
        result = {}
        output = self.adapter.format_output(result, "Stop")

        assert output["_windsurf_exit_code"] == 0

    def test_format_output_preserves_other_fields(self):
        """Test other fields are preserved."""
        result = {"decision": "block", "reason": "test", "custom": "value"}
        output = self.adapter.format_output(result, "PreToolUse")

        assert output["reason"] == "test"
        assert output["custom"] == "value"


class TestWindsurfAdapterInstallConfig:
    """Tests for Windsurf install configuration."""

    def setup_method(self):
        """Set up test fixtures."""
        from drinkingbird.adapters.windsurf import WindsurfAdapter
        self.adapter = WindsurfAdapter()
        self.config = self.adapter.get_install_config()

    def test_has_hooks_key(self):
        """Test config has hooks key."""
        assert "hooks" in self.config

    def test_has_expected_hook_events(self):
        """Test config has Windsurf hook events."""
        hooks = self.config["hooks"]

        assert "pre_run_command" in hooks
        assert "post_run_command" in hooks
        assert "post_cascade_response" in hooks

    def test_hooks_are_arrays(self):
        """Test each hook is an array (Windsurf format)."""
        for event_name, hook_list in self.config["hooks"].items():
            assert isinstance(hook_list, list), f"{event_name} should be a list"
            assert len(hook_list) > 0, f"{event_name} should have at least one hook"

    def test_hook_commands_have_required_fields(self):
        """Test each hook has command and show_output."""
        for event_name, hook_list in self.config["hooks"].items():
            for hook in hook_list:
                assert "command" in hook, f"{event_name} hook missing command"
                assert "bdb run --adapter windsurf" in hook["command"]
                assert "show_output" in hook, f"{event_name} hook missing show_output"


class TestWindsurfAdapterInstall:
    """Tests for Windsurf install method."""

    def setup_method(self):
        """Set up test fixtures."""
        from drinkingbird.adapters.windsurf import WindsurfAdapter
        self.adapter = WindsurfAdapter()

    def test_install_creates_new_config(self, tmp_path):
        """Test install creates config when none exists."""
        config_path = tmp_path / ".codeium" / "windsurf" / "hooks.json"
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/usr/local/bin/bdb")

        result = self.adapter.install(bdb_path)

        assert result is True
        assert config_path.exists()

        config = json.loads(config_path.read_text())
        assert "hooks" in config
        assert "pre_run_command" in config["hooks"]

    def test_install_updates_command_path(self, tmp_path):
        """Test install updates command with actual bdb path."""
        config_path = tmp_path / "hooks.json"
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/home/user/.local/bin/bdb")

        self.adapter.install(bdb_path)

        config = json.loads(config_path.read_text())
        hook = config["hooks"]["pre_run_command"][0]

        assert hook["command"] == "/home/user/.local/bin/bdb run --adapter windsurf"

    def test_install_preserves_existing_hooks(self, tmp_path):
        """Test install preserves non-bdb hooks."""
        config_path = tmp_path / "hooks.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "pre_run_command": [
                    {"command": "my-custom-hook", "show_output": True}
                ],
                "pre_read_code": [
                    {"command": "audit-logger", "show_output": False}
                ],
            }
        }))
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/usr/local/bin/bdb")

        self.adapter.install(bdb_path)

        config = json.loads(config_path.read_text())

        # Should have both custom and bdb hooks for pre_run_command
        assert len(config["hooks"]["pre_run_command"]) == 2
        assert config["hooks"]["pre_run_command"][0]["command"] == "my-custom-hook"
        assert "bdb" in config["hooks"]["pre_run_command"][1]["command"]

        # Should preserve unrelated hooks
        assert "pre_read_code" in config["hooks"]

    def test_install_removes_existing_bdb_hooks(self, tmp_path):
        """Test install removes old bdb hooks before adding new ones."""
        config_path = tmp_path / "hooks.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "pre_run_command": [
                    {"command": "/old/path/bdb run --adapter windsurf", "show_output": True}
                ],
            }
        }))
        self.adapter.get_config_path = lambda: config_path
        bdb_path = Path("/new/path/bdb")

        self.adapter.install(bdb_path)

        config = json.loads(config_path.read_text())

        # Should only have one hook with the new path
        assert len(config["hooks"]["pre_run_command"]) == 1
        assert "/new/path/bdb" in config["hooks"]["pre_run_command"][0]["command"]


class TestWindsurfAdapterUninstall:
    """Tests for Windsurf uninstall method."""

    def setup_method(self):
        """Set up test fixtures."""
        from drinkingbird.adapters.windsurf import WindsurfAdapter
        self.adapter = WindsurfAdapter()

    def test_uninstall_removes_bdb_hooks(self, tmp_path):
        """Test uninstall removes bdb hooks."""
        config_path = tmp_path / "hooks.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "pre_run_command": [
                    {"command": "bdb run --adapter windsurf", "show_output": True}
                ],
                "post_cascade_response": [
                    {"command": "/usr/bin/bdb run --adapter windsurf", "show_output": True}
                ],
            }
        }))
        self.adapter.get_config_path = lambda: config_path

        result = self.adapter.uninstall()

        assert result is True
        config = json.loads(config_path.read_text())
        assert "hooks" not in config or not config.get("hooks")

    def test_uninstall_preserves_non_bdb_hooks(self, tmp_path):
        """Test uninstall preserves hooks that aren't from bdb."""
        config_path = tmp_path / "hooks.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "pre_run_command": [
                    {"command": "bdb run --adapter windsurf", "show_output": True},
                    {"command": "my-custom-hook", "show_output": True},
                ],
            }
        }))
        self.adapter.get_config_path = lambda: config_path

        result = self.adapter.uninstall()

        assert result is True
        config = json.loads(config_path.read_text())
        assert len(config["hooks"]["pre_run_command"]) == 1
        assert config["hooks"]["pre_run_command"][0]["command"] == "my-custom-hook"

    def test_uninstall_returns_false_if_no_bdb_hooks(self, tmp_path):
        """Test uninstall returns False if no bdb hooks found."""
        config_path = tmp_path / "hooks.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "pre_run_command": [
                    {"command": "other-hook", "show_output": True}
                ],
            }
        }))
        self.adapter.get_config_path = lambda: config_path

        result = self.adapter.uninstall()

        assert result is False

    def test_uninstall_returns_false_if_no_config_file(self, tmp_path):
        """Test uninstall returns False if config file doesn't exist."""
        config_path = tmp_path / "hooks.json"
        self.adapter.get_config_path = lambda: config_path

        result = self.adapter.uninstall()

        assert result is False


def test_adapter_exports():
    """Test all adapters are exported from package."""
    from drinkingbird import adapters

    assert hasattr(adapters, "KiloCodeAdapter")
    assert hasattr(adapters, "ClineAdapter")
    assert hasattr(adapters, "WindsurfAdapter")
    assert hasattr(adapters, "ADAPTER_MAP")
    assert hasattr(adapters, "SUPPORTED_AGENTS")


class TestCLI:
    """Tests for CLI adapter integration."""

    def setup_method(self):
        """Set up test fixtures."""
        from click.testing import CliRunner
        self.runner = CliRunner()

    def test_install_kilo_code_dry_run(self):
        """Test install command accepts kilo-code."""
        from drinkingbird.cli import main
        result = self.runner.invoke(main, ["install", "kilo-code", "--dry-run"])
        assert result.exit_code == 0
        assert "kilo-code" in result.output

    def test_install_cline_dry_run(self):
        """Test install command accepts cline."""
        from drinkingbird.cli import main
        result = self.runner.invoke(main, ["install", "cline", "--dry-run"])
        assert result.exit_code == 0
        assert "cline" in result.output

    def test_install_windsurf_dry_run(self):
        """Test install command accepts windsurf."""
        from drinkingbird.cli import main
        result = self.runner.invoke(main, ["install", "windsurf", "--dry-run"])
        assert result.exit_code == 0
        assert "windsurf" in result.output

    def test_windsurf_in_agents_list(self):
        """Test windsurf appears in agents list."""
        from drinkingbird.cli import main
        result = self.runner.invoke(main, ["agents"])
        assert result.exit_code == 0
        assert "windsurf" in result.output
        assert "Cascade hooks" in result.output
