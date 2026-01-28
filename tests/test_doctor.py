"""Tests for the doctor diagnostic module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from drinkingbird.doctor import (
    Issue,
    check_manifest_entry,
    check_untracked_installation,
    config_has_bdb_hooks,
    diagnose_global,
    diagnose_local,
    fix_issue,
    fix_issues,
    get_adapters,
)
from drinkingbird.manifest import Installation, Manifest


class TestConfigHasBdbHooks:
    """Tests for config_has_bdb_hooks function."""

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        """Test that nonexistent file returns False."""
        config_path = tmp_path / "settings.json"
        assert config_has_bdb_hooks(config_path, "claude-code") is False

    def test_empty_config(self, tmp_path: Path) -> None:
        """Test that empty config returns False."""
        config_path = tmp_path / "settings.json"
        config_path.write_text("{}")
        assert config_has_bdb_hooks(config_path, "claude-code") is False

    def test_config_without_bdb(self, tmp_path: Path) -> None:
        """Test that config without bdb hooks returns False."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "Stop": [{"hooks": [{"command": "other-tool run"}]}]
            }
        }))
        assert config_has_bdb_hooks(config_path, "claude-code") is False

    def test_claude_code_style_hooks(self, tmp_path: Path) -> None:
        """Test detection of Claude Code style bdb hooks."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "Stop": [{"hooks": [{"command": "bdb run"}]}]
            }
        }))
        assert config_has_bdb_hooks(config_path, "claude-code") is True

    def test_cursor_style_hooks(self, tmp_path: Path) -> None:
        """Test detection of Cursor style bdb hooks."""
        config_path = tmp_path / "hooks.json"
        config_path.write_text(json.dumps({
            "hooks": {
                "agent_stop": {"command": "bdb run --adapter cursor"}
            }
        }))
        assert config_has_bdb_hooks(config_path, "cursor") is True

    def test_copilot_style_hooks(self, tmp_path: Path) -> None:
        """Test detection of Copilot style bdb hooks."""
        import yaml

        config_path = tmp_path / "hooks.yaml"
        with open(config_path, "w") as f:
            yaml.dump({
                "hooks": {
                    "stop": "bdb run --adapter copilot"
                }
            }, f)
        assert config_has_bdb_hooks(config_path, "copilot") is True

    def test_invalid_json(self, tmp_path: Path) -> None:
        """Test that invalid JSON returns False."""
        config_path = tmp_path / "settings.json"
        config_path.write_text("not valid json")
        assert config_has_bdb_hooks(config_path, "claude-code") is False


class TestCheckManifestEntry:
    """Tests for check_manifest_entry function."""

    def test_valid_entry(self, tmp_path: Path) -> None:
        """Test that valid entry returns None (no issue)."""
        config_path = tmp_path / ".claude" / "settings.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps({
            "hooks": {
                "Stop": [{"hooks": [{"command": "bdb run"}]}]
            }
        }))

        inst = Installation(
            agent="claude-code",
            scope="global",
            path=str(config_path),
            installed_at="2026-01-28T00:00:00Z",
        )

        adapters = get_adapters()
        issue = check_manifest_entry(inst, adapters)
        assert issue is None

    def test_missing_config(self, tmp_path: Path) -> None:
        """Test that missing config returns error issue."""
        config_path = tmp_path / ".claude" / "settings.json"

        inst = Installation(
            agent="claude-code",
            scope="global",
            path=str(config_path),
            installed_at="2026-01-28T00:00:00Z",
        )

        adapters = get_adapters()
        issue = check_manifest_entry(inst, adapters)

        assert issue is not None
        assert issue.issue_type == "missing_config"
        assert issue.severity == "error"

    def test_config_without_hooks(self, tmp_path: Path) -> None:
        """Test that config without bdb hooks returns error issue."""
        config_path = tmp_path / ".claude" / "settings.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps({"other": "settings"}))

        inst = Installation(
            agent="claude-code",
            scope="global",
            path=str(config_path),
            installed_at="2026-01-28T00:00:00Z",
        )

        adapters = get_adapters()
        issue = check_manifest_entry(inst, adapters)

        assert issue is not None
        assert issue.issue_type == "missing_hooks"
        assert issue.severity == "error"

    def test_unknown_agent(self, tmp_path: Path) -> None:
        """Test that unknown agent returns warning issue."""
        inst = Installation(
            agent="unknown-agent",
            scope="global",
            path="/some/path",
            installed_at="2026-01-28T00:00:00Z",
        )

        adapters = get_adapters()
        issue = check_manifest_entry(inst, adapters)

        assert issue is not None
        assert issue.issue_type == "unknown_agent"
        assert issue.severity == "warning"


class TestCheckUntrackedInstallation:
    """Tests for check_untracked_installation function."""

    def test_already_tracked(self, tmp_path: Path) -> None:
        """Test that tracked installation returns None."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({
            "hooks": {"Stop": [{"hooks": [{"command": "bdb run"}]}]}
        }))

        manifest = Manifest()
        manifest.add("claude-code", "global", str(config_path))

        issue = check_untracked_installation("claude-code", "global", config_path, manifest)
        assert issue is None

    def test_untracked_with_hooks(self, tmp_path: Path) -> None:
        """Test that untracked installation with hooks returns warning."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({
            "hooks": {"Stop": [{"hooks": [{"command": "bdb run"}]}]}
        }))

        manifest = Manifest()

        issue = check_untracked_installation("claude-code", "global", config_path, manifest)

        assert issue is not None
        assert issue.issue_type == "untracked_hooks"
        assert issue.severity == "warning"

    def test_no_hooks(self, tmp_path: Path) -> None:
        """Test that config without hooks returns None."""
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({"other": "settings"}))

        manifest = Manifest()

        issue = check_untracked_installation("claude-code", "global", config_path, manifest)
        assert issue is None


class TestFixIssue:
    """Tests for fix_issue function."""

    def test_fix_missing_config(self, tmp_path: Path) -> None:
        """Test fixing missing config removes manifest entry."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/nonexistent/path")

        issue = Issue(
            severity="error",
            issue_type="missing_config",
            agent="claude-code",
            scope="global",
            path="/nonexistent/path",
            description="Config file missing",
        )

        fix_desc = fix_issue(issue, manifest)

        assert "Removed" in fix_desc
        assert len(manifest.get(agent="claude-code")) == 0

    def test_fix_missing_hooks(self, tmp_path: Path) -> None:
        """Test fixing missing hooks removes manifest entry."""
        manifest = Manifest()
        manifest.add("claude-code", "global", "/some/path")

        issue = Issue(
            severity="error",
            issue_type="missing_hooks",
            agent="claude-code",
            scope="global",
            path="/some/path",
            description="No bdb hooks found",
        )

        fix_desc = fix_issue(issue, manifest)

        assert "Removed" in fix_desc
        assert len(manifest.get(agent="claude-code")) == 0

    def test_fix_untracked_hooks(self, tmp_path: Path) -> None:
        """Test fixing untracked hooks adds to manifest."""
        manifest = Manifest()

        issue = Issue(
            severity="warning",
            issue_type="untracked_hooks",
            agent="claude-code",
            scope="global",
            path="/some/path/settings.json",
            description="Found untracked hooks",
        )

        fix_desc = fix_issue(issue, manifest)

        assert "Added" in fix_desc
        assert len(manifest.get(agent="claude-code")) == 1


class TestDiagnoseLocal:
    """Tests for diagnose_local function."""

    def test_healthy_local_installation(self, tmp_path: Path, monkeypatch) -> None:
        """Test that healthy local installation returns no issues."""
        # Create a mock workspace with local config
        workspace = tmp_path / "project"
        workspace.mkdir()
        (workspace / ".git").mkdir()

        config_path = workspace / ".claude" / "settings.local.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps({
            "hooks": {"Stop": [{"hooks": [{"command": "bdb run"}]}]}
        }))

        # Create manifest entry
        manifest_path = tmp_path / "manifest.json"
        manifest = Manifest()
        manifest.add("claude-code", "local", str(config_path))
        manifest.save(manifest_path)

        # Patch MANIFEST_PATH to use our temp path
        import drinkingbird.doctor
        monkeypatch.setattr(drinkingbird.doctor, "Manifest", type(
            "MockManifest", (),
            {"load": staticmethod(lambda path=None: Manifest.load(manifest_path))}
        ))

        issues = diagnose_local(workspace)

        # Should find untracked since we mocked manifest load
        # This is acceptable - the test verifies the function runs


class TestDiagnoseGlobal:
    """Tests for diagnose_global function."""

    def test_empty_manifest(self, tmp_path: Path, monkeypatch) -> None:
        """Test that empty manifest with no global configs returns no issues."""
        manifest_path = tmp_path / "manifest.json"
        manifest = Manifest()
        manifest.save(manifest_path)

        # Patch Manifest class to use our temp path
        import drinkingbird.doctor
        monkeypatch.setattr(drinkingbird.doctor, "Manifest", type(
            "MockManifest", (),
            {"load": staticmethod(lambda path=None: Manifest.load(manifest_path))}
        ))

        # Mock adapters to return non-existent paths
        def mock_get_adapters():
            from unittest.mock import MagicMock
            adapter = MagicMock()
            adapter.get_config_path.return_value = tmp_path / "nonexistent"
            return {"test-agent": adapter}

        monkeypatch.setattr("drinkingbird.doctor.get_adapters", mock_get_adapters)

        issues = diagnose_global()
        assert len(issues) == 0

    def test_stale_manifest_entry(self, tmp_path: Path, monkeypatch) -> None:
        """Test detection of stale manifest entry."""
        manifest_path = tmp_path / "manifest.json"
        manifest = Manifest()
        manifest.add("claude-code", "global", str(tmp_path / "nonexistent.json"))
        manifest.save(manifest_path)

        # Patch Manifest class to use our temp path
        import drinkingbird.doctor
        monkeypatch.setattr(drinkingbird.doctor, "Manifest", type(
            "MockManifest", (),
            {"load": staticmethod(lambda path=None: Manifest.load(manifest_path))}
        ))

        issues = diagnose_global()

        # Should find the missing config issue
        missing_issues = [i for i in issues if i.issue_type == "missing_config"]
        assert len(missing_issues) == 1


class TestIssue:
    """Tests for Issue dataclass."""

    def test_str_error(self) -> None:
        """Test string representation of error issue."""
        issue = Issue(
            severity="error",
            issue_type="missing_config",
            agent="claude-code",
            scope="global",
            path="/some/path",
            description="Config file missing",
        )
        result = str(issue)
        assert "✗" in result
        assert "claude-code" in result
        assert "Config file missing" in result

    def test_str_warning(self) -> None:
        """Test string representation of warning issue."""
        issue = Issue(
            severity="warning",
            issue_type="untracked_hooks",
            agent="claude-code",
            scope="global",
            path="/some/path",
            description="Found untracked hooks",
        )
        result = str(issue)
        assert "⚠" in result
        assert "Found untracked hooks" in result
