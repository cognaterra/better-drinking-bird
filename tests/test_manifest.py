"""Tests for the installation manifest module."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from drinkingbird.manifest import Installation, Manifest


class TestInstallation:
    """Tests for Installation dataclass."""

    def test_to_dict(self) -> None:
        """Test converting installation to dictionary."""
        inst = Installation(
            agent="claude-code",
            scope="global",
            path="/home/user/.claude/settings.json",
            installed_at="2026-01-28T12:00:00+00:00",
        )

        result = inst.to_dict()

        assert result == {
            "agent": "claude-code",
            "scope": "global",
            "path": "/home/user/.claude/settings.json",
            "installed_at": "2026-01-28T12:00:00+00:00",
        }

    def test_from_dict(self) -> None:
        """Test creating installation from dictionary."""
        data = {
            "agent": "cursor",
            "scope": "local",
            "path": "/project/.cursor/hooks.json",
            "installed_at": "2026-01-28T13:00:00+00:00",
        }

        inst = Installation.from_dict(data)

        assert inst.agent == "cursor"
        assert inst.scope == "local"
        assert inst.path == "/project/.cursor/hooks.json"
        assert inst.installed_at == "2026-01-28T13:00:00+00:00"


class TestManifest:
    """Tests for Manifest class."""

    def test_load_empty(self, tmp_path: Path) -> None:
        """Test loading from non-existent file returns empty manifest."""
        manifest_path = tmp_path / "manifest.json"

        manifest = Manifest.load(manifest_path)

        assert manifest.version == 1
        assert manifest.installations == []

    def test_load_existing(self, tmp_path: Path) -> None:
        """Test loading from existing file."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({
            "version": 1,
            "installations": [
                {
                    "agent": "claude-code",
                    "scope": "global",
                    "path": "/home/user/.claude/settings.json",
                    "installed_at": "2026-01-28T12:00:00+00:00",
                }
            ],
        }))

        manifest = Manifest.load(manifest_path)

        assert manifest.version == 1
        assert len(manifest.installations) == 1
        assert manifest.installations[0].agent == "claude-code"

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        """Test loading invalid JSON returns empty manifest."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text("not valid json")

        manifest = Manifest.load(manifest_path)

        assert manifest.installations == []

    def test_save(self, tmp_path: Path) -> None:
        """Test saving manifest to file."""
        manifest_path = tmp_path / "manifest.json"
        manifest = Manifest()
        manifest.add("claude-code", "global", "/path/to/config")

        manifest.save(manifest_path)

        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["version"] == 1
        assert len(data["installations"]) == 1
        assert data["installations"][0]["agent"] == "claude-code"

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Test save creates parent directories."""
        manifest_path = tmp_path / "subdir" / "nested" / "manifest.json"
        manifest = Manifest()

        manifest.save(manifest_path)

        assert manifest_path.exists()

    def test_add_installation(self) -> None:
        """Test adding an installation."""
        manifest = Manifest()

        manifest.add("claude-code", "global", "/path/to/config")

        assert len(manifest.installations) == 1
        assert manifest.installations[0].agent == "claude-code"
        assert manifest.installations[0].scope == "global"
        assert manifest.installations[0].path == "/path/to/config"
        assert manifest.installations[0].installed_at  # Should have timestamp

    def test_add_replaces_existing(self) -> None:
        """Test adding same agent+scope+path replaces existing."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/path/to/config")
        first_timestamp = manifest.installations[0].installed_at

        manifest.add("claude-code", "global", "/path/to/config")

        assert len(manifest.installations) == 1
        # Timestamp should be updated
        assert manifest.installations[0].installed_at != first_timestamp

    def test_add_different_scope_keeps_both(self) -> None:
        """Test adding same agent with different scope keeps both."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/home/.claude/settings.json")
        manifest.add("claude-code", "local", "/project/.claude/settings.local.json")

        assert len(manifest.installations) == 2

    def test_remove_by_agent(self) -> None:
        """Test removing installations by agent."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/path1")
        manifest.add("cursor", "global", "/path2")

        removed = manifest.remove(agent="claude-code")

        assert len(removed) == 1
        assert removed[0].agent == "claude-code"
        assert len(manifest.installations) == 1
        assert manifest.installations[0].agent == "cursor"

    def test_remove_by_scope(self) -> None:
        """Test removing installations by scope."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/path1")
        manifest.add("claude-code", "local", "/path2")

        removed = manifest.remove(scope="local")

        assert len(removed) == 1
        assert removed[0].scope == "local"
        assert len(manifest.installations) == 1

    def test_remove_by_path(self) -> None:
        """Test removing installations by path."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/path1")
        manifest.add("claude-code", "global", "/path2")

        removed = manifest.remove(path="/path1")

        assert len(removed) == 1
        assert removed[0].path == "/path1"
        assert len(manifest.installations) == 1

    def test_remove_all(self) -> None:
        """Test removing all installations."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/path1")
        manifest.add("cursor", "global", "/path2")

        removed = manifest.remove()

        assert len(removed) == 2
        assert len(manifest.installations) == 0

    def test_get_all(self) -> None:
        """Test getting all installations."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/path1")
        manifest.add("cursor", "global", "/path2")

        results = manifest.get()

        assert len(results) == 2

    def test_get_by_agent(self) -> None:
        """Test getting installations by agent."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/path1")
        manifest.add("claude-code", "local", "/path2")
        manifest.add("cursor", "global", "/path3")

        results = manifest.get(agent="claude-code")

        assert len(results) == 2
        assert all(r.agent == "claude-code" for r in results)

    def test_get_by_scope(self) -> None:
        """Test getting installations by scope."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/path1")
        manifest.add("cursor", "local", "/path2")

        results = manifest.get(scope="local")

        assert len(results) == 1
        assert results[0].scope == "local"

    def test_get_by_agent_and_scope(self) -> None:
        """Test getting installations by agent and scope."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/path1")
        manifest.add("claude-code", "local", "/path2")
        manifest.add("cursor", "global", "/path3")

        results = manifest.get(agent="claude-code", scope="global")

        assert len(results) == 1
        assert results[0].agent == "claude-code"
        assert results[0].scope == "global"

    def test_get_agents(self) -> None:
        """Test getting unique agent names."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/path1")
        manifest.add("claude-code", "local", "/path2")
        manifest.add("cursor", "global", "/path3")

        agents = manifest.get_agents()

        assert agents == ["claude-code", "cursor"]

    def test_get_agents_empty(self) -> None:
        """Test getting agents from empty manifest."""
        manifest = Manifest()

        agents = manifest.get_agents()

        assert agents == []
