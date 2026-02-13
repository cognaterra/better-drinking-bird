# tests/test_mode.py
"""Tests for mode functionality."""

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from drinkingbird.cli import main
from drinkingbird.mode import (
    MODE_FILE,
    Mode,
    clear_mode,
    get_mode,
    get_mode_info,
    get_workspace_root,
    set_mode,
)


class TestGetMode:
    """Tests for get_mode function."""

    def test_default_when_no_file(self, tmp_path, monkeypatch):
        """Test that default mode is returned when no file exists."""
        monkeypatch.setattr("drinkingbird.mode.GLOBAL_MODE_PATH", tmp_path / ".bdb" / MODE_FILE)
        monkeypatch.setattr("drinkingbird.mode.get_workspace_root", lambda: None)

        assert get_mode() == Mode.DEFAULT

    def test_reads_global_mode(self, tmp_path, monkeypatch):
        """Test that global mode file is read."""
        global_dir = tmp_path / ".bdb"
        global_dir.mkdir()
        mode_file = global_dir / MODE_FILE
        mode_file.write_text(json.dumps({"mode": "interactive"}))

        monkeypatch.setattr("drinkingbird.mode.GLOBAL_MODE_PATH", mode_file)
        monkeypatch.setattr("drinkingbird.mode.get_workspace_root", lambda: None)

        assert get_mode() == Mode.INTERACTIVE

    def test_local_takes_precedence(self, tmp_path, monkeypatch):
        """Test that local mode takes precedence over global."""
        # Create global mode file
        global_dir = tmp_path / "global" / ".bdb"
        global_dir.mkdir(parents=True)
        global_mode = global_dir / MODE_FILE
        global_mode.write_text(json.dumps({"mode": "auto"}))

        # Create local mode file
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        local_bdb = workspace / ".bdb"
        local_bdb.mkdir()
        local_mode = local_bdb / MODE_FILE
        local_mode.write_text(json.dumps({"mode": "interactive"}))

        monkeypatch.setattr("drinkingbird.mode.GLOBAL_MODE_PATH", global_mode)
        monkeypatch.setattr("drinkingbird.mode.get_workspace_root", lambda: workspace)

        assert get_mode() == Mode.INTERACTIVE

    def test_invalid_mode_file_returns_default(self, tmp_path, monkeypatch):
        """Test that invalid mode file returns default."""
        global_dir = tmp_path / ".bdb"
        global_dir.mkdir()
        mode_file = global_dir / MODE_FILE
        mode_file.write_text("not json")

        monkeypatch.setattr("drinkingbird.mode.GLOBAL_MODE_PATH", mode_file)
        monkeypatch.setattr("drinkingbird.mode.get_workspace_root", lambda: None)

        assert get_mode() == Mode.DEFAULT


class TestSetMode:
    """Tests for set_mode function."""

    def test_set_global_mode(self, tmp_path, monkeypatch):
        """Test setting global mode."""
        global_mode = tmp_path / ".bdb" / MODE_FILE
        monkeypatch.setattr("drinkingbird.mode.GLOBAL_MODE_PATH", global_mode)

        path = set_mode(Mode.INTERACTIVE, use_global=True)

        assert path == global_mode
        assert global_mode.exists()
        data = json.loads(global_mode.read_text())
        assert data["mode"] == "interactive"
        assert "timestamp" in data
        assert "user" in data

    def test_set_local_mode(self, tmp_path, monkeypatch):
        """Test setting local mode in git repo."""
        workspace = tmp_path / "workspace"
        (workspace / ".git").mkdir(parents=True)
        os.chdir(workspace)

        # Don't need to mock get_workspace_root since we're in a real git-like dir
        path = set_mode(Mode.INTERACTIVE, use_global=False)

        expected = workspace / ".bdb" / MODE_FILE
        assert path == expected
        assert expected.exists()

    def test_set_local_fails_outside_git(self, tmp_path, monkeypatch):
        """Test that setting local mode fails outside git repo."""
        os.chdir(tmp_path)
        monkeypatch.setattr("drinkingbird.mode.get_workspace_root", lambda: None)

        with pytest.raises(ValueError, match="Not in a git repository"):
            set_mode(Mode.INTERACTIVE, use_global=False)


class TestClearMode:
    """Tests for clear_mode function."""

    def test_clear_global_mode(self, tmp_path, monkeypatch):
        """Test clearing global mode."""
        global_dir = tmp_path / ".bdb"
        global_dir.mkdir()
        global_mode = global_dir / MODE_FILE
        global_mode.write_text("{}")

        monkeypatch.setattr("drinkingbird.mode.GLOBAL_MODE_PATH", global_mode)

        path = clear_mode(use_global=True)

        assert path == global_mode
        assert not global_mode.exists()

    def test_clear_nonexistent_returns_none(self, tmp_path, monkeypatch):
        """Test that clearing nonexistent file returns None."""
        monkeypatch.setattr("drinkingbird.mode.GLOBAL_MODE_PATH", tmp_path / ".bdb" / MODE_FILE)

        path = clear_mode(use_global=True)

        assert path is None


class TestSupervisorModeIntegration:
    """Integration tests for mode in supervisor."""

    def test_interactive_mode_allows_stop(self, tmp_path, monkeypatch):
        """Test that interactive mode allows Stop hook."""
        from drinkingbird.supervisor import Supervisor

        # Set up interactive mode
        global_dir = tmp_path / ".bdb"
        global_dir.mkdir()
        mode_file = global_dir / MODE_FILE
        mode_file.write_text(json.dumps({"mode": "interactive"}))

        monkeypatch.setattr("drinkingbird.mode.GLOBAL_MODE_PATH", mode_file)
        monkeypatch.setattr("drinkingbird.mode.get_workspace_root", lambda: None)
        # Also patch in supervisor module
        monkeypatch.setattr("drinkingbird.supervisor.get_mode", lambda: Mode.INTERACTIVE)

        # Ensure not paused
        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", tmp_path / "no-pause")
        monkeypatch.setattr("drinkingbird.pause.get_workspace_root", lambda: None)

        supervisor = Supervisor(log_dir=tmp_path)
        result = supervisor.handle({"hook_event_name": "Stop"})

        assert result.decision.value == "allow"
        assert "interactive" in result.reason.lower()

    def test_interactive_mode_still_blocks_dangerous_commands(self, tmp_path, monkeypatch):
        """Test that interactive mode still runs PreToolUse hook."""
        from drinkingbird.supervisor import Supervisor

        # Set up interactive mode
        global_dir = tmp_path / ".bdb"
        global_dir.mkdir()
        mode_file = global_dir / MODE_FILE
        mode_file.write_text(json.dumps({"mode": "interactive"}))

        monkeypatch.setattr("drinkingbird.mode.GLOBAL_MODE_PATH", mode_file)
        monkeypatch.setattr("drinkingbird.mode.get_workspace_root", lambda: None)
        monkeypatch.setattr("drinkingbird.supervisor.get_mode", lambda: Mode.INTERACTIVE)

        # Ensure not paused
        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", tmp_path / "no-pause")
        monkeypatch.setattr("drinkingbird.pause.get_workspace_root", lambda: None)

        supervisor = Supervisor(log_dir=tmp_path)
        result = supervisor.handle({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard"},
        })

        # Should still block dangerous git commands
        assert result.decision.value == "block"


class TestModeCLI:
    """Tests for mode CLI command."""

    def test_mode_show_default(self, tmp_path, monkeypatch):
        """Test showing default mode."""
        monkeypatch.setattr("drinkingbird.mode.GLOBAL_MODE_PATH", tmp_path / ".bdb" / MODE_FILE)
        monkeypatch.setattr("drinkingbird.mode.get_workspace_root", lambda: None)

        runner = CliRunner()
        result = runner.invoke(main, ["mode"])

        assert result.exit_code == 0
        assert "default" in result.output.lower()

    def test_mode_set_interactive(self, tmp_path, monkeypatch):
        """Test setting interactive mode."""
        (tmp_path / ".git").mkdir()
        os.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(main, ["mode", "interactive"])

        assert result.exit_code == 0
        assert "interactive" in result.output.lower()
        assert (tmp_path / ".bdb" / MODE_FILE).exists()

    def test_mode_set_global(self, tmp_path, monkeypatch):
        """Test setting global mode."""
        global_mode = tmp_path / ".bdb" / MODE_FILE
        monkeypatch.setattr("drinkingbird.mode.GLOBAL_MODE_PATH", global_mode)
        monkeypatch.setattr("drinkingbird.cli.GLOBAL_MODE_PATH", global_mode)

        runner = CliRunner()
        result = runner.invoke(main, ["mode", "--global", "auto"])

        assert result.exit_code == 0
        assert global_mode.exists()

    def test_mode_clear(self, tmp_path, monkeypatch):
        """Test clearing mode."""
        (tmp_path / ".git").mkdir()
        os.chdir(tmp_path)

        # First set a mode
        mode_file = tmp_path / ".bdb" / MODE_FILE
        mode_file.parent.mkdir(parents=True)
        mode_file.write_text(json.dumps({"mode": "interactive"}))

        runner = CliRunner()
        result = runner.invoke(main, ["mode", "--clear"])

        assert result.exit_code == 0
        assert not mode_file.exists()
