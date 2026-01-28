# tests/test_pause.py
"""Tests for pause/resume functionality."""

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from drinkingbird.cli import main
from drinkingbird.pause import (
    SENTINEL_NAME,
    create_sentinel,
    get_workspace_root,
    is_git_repo,
    is_paused,
    remove_sentinel,
)


class TestIsGitRepo:
    """Tests for is_git_repo function."""

    def test_git_repo_returns_true(self, tmp_path):
        """Test that directory with .git returns True."""
        (tmp_path / ".git").mkdir()
        assert is_git_repo(tmp_path) is True

    def test_non_git_returns_false(self, tmp_path):
        """Test that directory without .git returns False."""
        assert is_git_repo(tmp_path) is False

    def test_nested_in_git_repo(self, tmp_path):
        """Test that nested directory in git repo returns True."""
        (tmp_path / ".git").mkdir()
        nested = tmp_path / "src" / "deep"
        nested.mkdir(parents=True)
        assert is_git_repo(nested) is True


class TestGetWorkspaceRoot:
    """Tests for get_workspace_root function."""

    def test_returns_git_root(self, tmp_path):
        """Test that git root is returned."""
        (tmp_path / ".git").mkdir()
        nested = tmp_path / "src"
        nested.mkdir()
        os.chdir(nested)
        assert get_workspace_root() == tmp_path

    def test_returns_none_outside_git(self, tmp_path):
        """Test that None is returned outside git repo."""
        os.chdir(tmp_path)
        assert get_workspace_root() is None


class TestSentinel:
    """Tests for sentinel file operations."""

    def test_create_sentinel_with_metadata(self, tmp_path):
        """Test creating sentinel with JSON metadata."""
        sentinel = tmp_path / SENTINEL_NAME
        create_sentinel(sentinel, reason="Testing pause")

        assert sentinel.exists()
        data = json.loads(sentinel.read_text())
        assert "timestamp" in data
        assert data["reason"] == "Testing pause"
        assert "user" in data

    def test_create_sentinel_no_reason(self, tmp_path):
        """Test creating sentinel without reason."""
        sentinel = tmp_path / SENTINEL_NAME
        create_sentinel(sentinel)

        data = json.loads(sentinel.read_text())
        assert data["reason"] is None

    def test_remove_sentinel(self, tmp_path):
        """Test removing sentinel file."""
        sentinel = tmp_path / SENTINEL_NAME
        sentinel.write_text("{}")

        assert remove_sentinel(sentinel) is True
        assert not sentinel.exists()

    def test_remove_nonexistent_sentinel(self, tmp_path):
        """Test removing nonexistent sentinel returns False."""
        sentinel = tmp_path / SENTINEL_NAME
        assert remove_sentinel(sentinel) is False


class TestIsPaused:
    """Tests for is_paused function."""

    def test_not_paused_by_default(self, tmp_path, monkeypatch):
        """Test that bdb is not paused by default."""
        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", tmp_path / ".bdb" / SENTINEL_NAME)
        monkeypatch.setattr("drinkingbird.pause.get_workspace_root", lambda: None)

        paused, path = is_paused()
        assert paused is False
        assert path is None

    def test_global_sentinel_pauses(self, tmp_path, monkeypatch):
        """Test that global sentinel pauses bdb."""
        global_dir = tmp_path / ".bdb"
        global_dir.mkdir()
        sentinel = global_dir / SENTINEL_NAME
        sentinel.write_text("{}")

        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", sentinel)
        monkeypatch.setattr("drinkingbird.pause.get_workspace_root", lambda: None)

        paused, path = is_paused()
        assert paused is True
        assert path == str(sentinel)

    def test_local_sentinel_takes_precedence(self, tmp_path, monkeypatch):
        """Test that local sentinel takes precedence over global."""
        # Create both sentinels
        global_dir = tmp_path / "global" / ".bdb"
        global_dir.mkdir(parents=True)
        global_sentinel = global_dir / SENTINEL_NAME
        global_sentinel.write_text("{}")

        local_sentinel = tmp_path / "workspace" / SENTINEL_NAME
        local_sentinel.parent.mkdir()
        local_sentinel.write_text("{}")

        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", global_sentinel)
        monkeypatch.setattr("drinkingbird.pause.get_workspace_root", lambda: tmp_path / "workspace")

        paused, path = is_paused()
        assert paused is True
        assert path == str(local_sentinel)


class TestSupervisorPauseIntegration:
    """Integration tests for pause in supervisor."""

    def test_supervisor_allows_when_paused(self, tmp_path, monkeypatch):
        """Test that supervisor returns allow when paused."""
        from drinkingbird.supervisor import Supervisor

        # Create global sentinel
        global_dir = tmp_path / ".bdb"
        global_dir.mkdir()
        sentinel = global_dir / SENTINEL_NAME
        sentinel.write_text("{}")

        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", sentinel)
        monkeypatch.setattr("drinkingbird.pause.get_workspace_root", lambda: None)

        supervisor = Supervisor(log_dir=tmp_path)
        result = supervisor.handle({"hook_event_name": "Stop"})

        assert result.decision.value == "allow"
        assert "paused" in result.reason.lower()


class TestPauseCLI:
    """Tests for pause/resume CLI commands."""

    def test_pause_creates_local_sentinel_in_git_repo(self, tmp_path, monkeypatch):
        """Test that pause creates local sentinel in git repo."""
        (tmp_path / ".git").mkdir()
        os.chdir(tmp_path)

        # Mock global to avoid touching real ~/.bdb
        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", tmp_path / "global" / SENTINEL_NAME)

        runner = CliRunner()
        result = runner.invoke(main, ["pause"])

        assert result.exit_code == 0
        assert (tmp_path / SENTINEL_NAME).exists()

    def test_pause_creates_global_sentinel_outside_git(self, tmp_path, monkeypatch):
        """Test that pause creates global sentinel outside git repo."""
        os.chdir(tmp_path)
        global_sentinel = tmp_path / "global" / SENTINEL_NAME

        # Patch both pause module and cli module references
        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", global_sentinel)
        monkeypatch.setattr("drinkingbird.cli.GLOBAL_SENTINEL", global_sentinel)
        monkeypatch.setattr("drinkingbird.pause.get_workspace_root", lambda: None)
        monkeypatch.setattr("drinkingbird.cli.get_workspace_root", lambda: None)

        runner = CliRunner()
        result = runner.invoke(main, ["pause"])

        assert result.exit_code == 0
        assert global_sentinel.exists()

    def test_pause_with_global_flag(self, tmp_path, monkeypatch):
        """Test that --global forces global sentinel."""
        (tmp_path / ".git").mkdir()
        os.chdir(tmp_path)
        global_sentinel = tmp_path / "global" / SENTINEL_NAME

        # Patch both pause module and cli module references
        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", global_sentinel)
        monkeypatch.setattr("drinkingbird.cli.GLOBAL_SENTINEL", global_sentinel)

        runner = CliRunner()
        result = runner.invoke(main, ["pause", "--global"])

        assert result.exit_code == 0
        assert global_sentinel.exists()
        assert not (tmp_path / SENTINEL_NAME).exists()

    def test_pause_with_reason(self, tmp_path, monkeypatch):
        """Test that --reason is stored in sentinel."""
        os.chdir(tmp_path)
        global_sentinel = tmp_path / "global" / SENTINEL_NAME

        # Patch both pause module and cli module references
        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", global_sentinel)
        monkeypatch.setattr("drinkingbird.cli.GLOBAL_SENTINEL", global_sentinel)
        monkeypatch.setattr("drinkingbird.pause.get_workspace_root", lambda: None)
        monkeypatch.setattr("drinkingbird.cli.get_workspace_root", lambda: None)

        runner = CliRunner()
        result = runner.invoke(main, ["pause", "--reason", "Testing something"])

        assert result.exit_code == 0
        data = json.loads(global_sentinel.read_text())
        assert data["reason"] == "Testing something"

    def test_resume_removes_sentinel(self, tmp_path, monkeypatch):
        """Test that resume removes sentinel."""
        os.chdir(tmp_path)
        global_sentinel = tmp_path / "global" / SENTINEL_NAME
        global_sentinel.parent.mkdir(parents=True)
        global_sentinel.write_text("{}")

        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", global_sentinel)
        monkeypatch.setattr("drinkingbird.pause.get_workspace_root", lambda: None)

        runner = CliRunner()
        result = runner.invoke(main, ["resume"])

        assert result.exit_code == 0
        assert not global_sentinel.exists()

    def test_resume_when_not_paused(self, tmp_path, monkeypatch):
        """Test resume when not paused."""
        os.chdir(tmp_path)

        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", tmp_path / "global" / SENTINEL_NAME)
        monkeypatch.setattr("drinkingbird.pause.get_workspace_root", lambda: None)

        runner = CliRunner()
        result = runner.invoke(main, ["resume"])

        assert result.exit_code == 0
        assert "not paused" in result.output.lower()
