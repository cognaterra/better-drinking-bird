"""Tests for agent adapters."""

import json
from pathlib import Path

import pytest

from drinkingbird.adapters.claude_code import ClaudeCodeAdapter


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
