# Pause/Resume & Config Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `bdb pause` and `bdb resume` CLI commands with sentinel files, and consolidate config from `~/.bdbrc` to `~/.bdb/config.yaml`.

**Architecture:** Sentinel-based pause system with local (workspace) and global (~/.bdb) sentinels. Local takes precedence. Config moves to `~/.bdb/config.yaml` with backwards-compatible fallback to legacy `~/.bdbrc`.

**Tech Stack:** Python, Click CLI, pytest, JSON for sentinel metadata, YAML for config

---

## Task 1: Create pause module with git repo detection

**Files:**
- Create: `src/drinkingbird/pause.py`
- Test: `tests/test_pause.py`

**Step 1: Write the failing tests**

```python
# tests/test_pause.py
"""Tests for pause/resume functionality."""

import json
import os
from pathlib import Path

import pytest

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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pause.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'drinkingbird.pause'"

**Step 3: Write minimal implementation**

```python
# src/drinkingbird/pause.py
"""Pause/resume functionality for Better Drinking Bird."""

from __future__ import annotations

import getpass
import json
import os
from datetime import datetime
from pathlib import Path

SENTINEL_NAME = ".bdb-paused"
GLOBAL_SENTINEL = Path.home() / ".bdb" / SENTINEL_NAME


def is_git_repo(path: Path) -> bool:
    """Check if path is inside a git repository."""
    current = path.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return True
        current = current.parent
    return False


def get_workspace_root() -> Path | None:
    """Get git repo root from cwd, or None if not in a repo."""
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def get_local_sentinel() -> Path | None:
    """Get local sentinel path if in git repo."""
    root = get_workspace_root()
    if root:
        return root / SENTINEL_NAME
    return None


def create_sentinel(path: Path, reason: str | None = None) -> None:
    """Create sentinel file with JSON metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "timestamp": datetime.now().isoformat(),
        "reason": reason,
        "user": getpass.getuser(),
    }
    path.write_text(json.dumps(data, indent=2))


def remove_sentinel(path: Path) -> bool:
    """Remove sentinel file. Returns True if removed."""
    if path.exists():
        path.unlink()
        return True
    return False


def get_pause_info(path: Path) -> dict | None:
    """Read sentinel metadata."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def is_paused() -> tuple[bool, str | None]:
    """Check if bdb is paused. Returns (paused, sentinel_path)."""
    # Check local first (if in git repo)
    local = get_local_sentinel()
    if local and local.exists():
        return True, str(local)

    # Check global
    if GLOBAL_SENTINEL.exists():
        return True, str(GLOBAL_SENTINEL)

    return False, None
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pause.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/drinkingbird/pause.py tests/test_pause.py
git commit -m "$(cat <<'EOF'
feat: add pause module with sentinel file support

Adds git repo detection and sentinel file operations for the
bdb pause/resume feature.
EOF
)"
```

---

## Task 2: Add pause check to supervisor

**Files:**
- Modify: `src/drinkingbird/supervisor.py:164-182`
- Test: `tests/test_pause.py` (add integration test)

**Step 1: Write the failing test**

Add to `tests/test_pause.py`:

```python
class TestSupervisorPauseIntegration:
    """Integration tests for pause in supervisor."""

    def test_supervisor_allows_when_paused(self, tmp_path, monkeypatch):
        """Test that supervisor returns allow when paused."""
        from drinkingbird.hooks import HookResult
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pause.py::TestSupervisorPauseIntegration -v`
Expected: FAIL (supervisor doesn't check pause yet)

**Step 3: Modify supervisor.py**

Add import at top:
```python
from drinkingbird.pause import is_paused
```

Modify `handle()` method - add after `self.debug(f"Handling event: {event_name}")`:

```python
    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Handle a hook event."""
        event_name = hook_input.get("hook_event_name", "")
        self.debug(f"Handling event: {event_name}")

        # Check if paused FIRST
        paused, sentinel_path = is_paused()
        if paused:
            self.debug(f"BDB paused via {sentinel_path}")
            return HookResult.allow("BDB is paused")

        # Get appropriate hook (rest of existing code...)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pause.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/drinkingbird/supervisor.py tests/test_pause.py
git commit -m "$(cat <<'EOF'
feat: bypass hooks when bdb is paused

Supervisor now checks for pause sentinel before processing hooks,
returning allow immediately when paused.
EOF
)"
```

---

## Task 3: Add pause and resume CLI commands

**Files:**
- Modify: `src/drinkingbird/cli.py`
- Test: `tests/test_pause.py` (add CLI tests)

**Step 1: Write the failing tests**

Add to `tests/test_pause.py`:

```python
from click.testing import CliRunner

from drinkingbird.cli import main


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

        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", global_sentinel)
        monkeypatch.setattr("drinkingbird.pause.get_workspace_root", lambda: None)

        runner = CliRunner()
        result = runner.invoke(main, ["pause"])

        assert result.exit_code == 0
        assert global_sentinel.exists()

    def test_pause_with_global_flag(self, tmp_path, monkeypatch):
        """Test that --global forces global sentinel."""
        (tmp_path / ".git").mkdir()
        os.chdir(tmp_path)
        global_sentinel = tmp_path / "global" / SENTINEL_NAME

        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", global_sentinel)

        runner = CliRunner()
        result = runner.invoke(main, ["pause", "--global"])

        assert result.exit_code == 0
        assert global_sentinel.exists()
        assert not (tmp_path / SENTINEL_NAME).exists()

    def test_pause_with_reason(self, tmp_path, monkeypatch):
        """Test that --reason is stored in sentinel."""
        os.chdir(tmp_path)
        global_sentinel = tmp_path / "global" / SENTINEL_NAME

        monkeypatch.setattr("drinkingbird.pause.GLOBAL_SENTINEL", global_sentinel)
        monkeypatch.setattr("drinkingbird.pause.get_workspace_root", lambda: None)

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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pause.py::TestPauseCLI -v`
Expected: FAIL (commands don't exist yet)

**Step 3: Add CLI commands to cli.py**

Add import:
```python
from drinkingbird.pause import (
    GLOBAL_SENTINEL,
    create_sentinel,
    get_local_sentinel,
    get_pause_info,
    get_workspace_root,
    is_paused,
    remove_sentinel,
)
```

Add commands after the `config` group:

```python
@main.command()
@click.option("--global", "use_global", is_flag=True, help="Use global sentinel (~/.bdb/)")
@click.option("--local", "use_local", is_flag=True, help="Use local sentinel (workspace root)")
@click.option("--reason", "-r", type=str, help="Reason for pausing")
def pause(use_global: bool, use_local: bool, reason: str | None) -> None:
    """Pause bdb hooks temporarily.

    Creates a sentinel file that causes bdb to bypass all hook checks.
    By default, creates local sentinel in git repos, global otherwise.
    """
    if use_global and use_local:
        click.echo("Cannot specify both --global and --local", err=True)
        sys.exit(1)

    # Determine which sentinel to use
    if use_global:
        sentinel = GLOBAL_SENTINEL
        location = "global"
    elif use_local:
        local = get_local_sentinel()
        if not local:
            click.echo("Not in a git repository. Use --global instead.", err=True)
            sys.exit(1)
        sentinel = local
        location = "local"
    else:
        # Default: local if in git repo, global otherwise
        local = get_local_sentinel()
        if local:
            sentinel = local
            location = "local"
        else:
            sentinel = GLOBAL_SENTINEL
            location = "global"

    create_sentinel(sentinel, reason)
    click.echo(f"BDB paused ({location}): {sentinel}")
    if reason:
        click.echo(f"Reason: {reason}")


@main.command()
@click.option("--global", "use_global", is_flag=True, help="Remove global sentinel")
@click.option("--local", "use_local", is_flag=True, help="Remove local sentinel")
def resume(use_global: bool, use_local: bool) -> None:
    """Resume bdb hooks.

    Removes the pause sentinel file. By default, removes whichever
    sentinel is currently active (local takes precedence).
    """
    if use_global and use_local:
        click.echo("Cannot specify both --global and --local", err=True)
        sys.exit(1)

    if use_global:
        sentinel = GLOBAL_SENTINEL
    elif use_local:
        local = get_local_sentinel()
        if not local:
            click.echo("Not in a git repository.", err=True)
            sys.exit(1)
        sentinel = local
    else:
        # Find active sentinel
        paused, path = is_paused()
        if not paused:
            click.echo("BDB is not paused.")
            return
        sentinel = Path(path)

    if remove_sentinel(sentinel):
        click.echo(f"BDB resumed: removed {sentinel}")
    else:
        click.echo("BDB is not paused.")
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pause.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/drinkingbird/cli.py tests/test_pause.py
git commit -m "$(cat <<'EOF'
feat: add bdb pause and bdb resume CLI commands

Pause creates sentinel file to bypass hooks, resume removes it.
Defaults to local sentinel in git repos, global otherwise.
EOF
)"
```

---

## Task 4: Consolidate config to ~/.bdb/config.yaml

**Files:**
- Modify: `src/drinkingbird/config.py`
- Modify: `tests/test_config.py`

**Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
class TestConfigPaths:
    """Tests for config path resolution."""

    def test_new_config_path(self):
        """Test that CONFIG_PATH points to ~/.bdb/config.yaml."""
        from drinkingbird.config import CONFIG_PATH
        assert CONFIG_PATH == Path.home() / ".bdb" / "config.yaml"

    def test_legacy_config_path(self):
        """Test that LEGACY_CONFIG_PATH points to ~/.bdbrc."""
        from drinkingbird.config import LEGACY_CONFIG_PATH
        assert LEGACY_CONFIG_PATH == Path.home() / ".bdbrc"


class TestLegacyConfigFallback:
    """Tests for backwards-compatible config loading."""

    def test_loads_from_new_path(self, tmp_path):
        """Test loading from new config path."""
        new_config = tmp_path / ".bdb" / "config.yaml"
        new_config.parent.mkdir()
        new_config.write_text("llm:\n  provider: anthropic")
        new_config.chmod(0o600)

        config = load_config(new_config)
        assert config.llm.provider == "anthropic"

    def test_falls_back_to_legacy(self, tmp_path, monkeypatch):
        """Test fallback to legacy path when new doesn't exist."""
        new_path = tmp_path / ".bdb" / "config.yaml"
        legacy_path = tmp_path / ".bdbrc"
        legacy_path.write_text("llm:\n  provider: ollama")
        legacy_path.chmod(0o600)

        monkeypatch.setattr("drinkingbird.config.CONFIG_PATH", new_path)
        monkeypatch.setattr("drinkingbird.config.LEGACY_CONFIG_PATH", legacy_path)

        config = load_config()
        assert config.llm.provider == "ollama"

    def test_new_path_takes_precedence(self, tmp_path, monkeypatch):
        """Test that new path takes precedence over legacy."""
        new_path = tmp_path / ".bdb" / "config.yaml"
        new_path.parent.mkdir()
        new_path.write_text("llm:\n  provider: anthropic")
        new_path.chmod(0o600)

        legacy_path = tmp_path / ".bdbrc"
        legacy_path.write_text("llm:\n  provider: ollama")
        legacy_path.chmod(0o600)

        monkeypatch.setattr("drinkingbird.config.CONFIG_PATH", new_path)
        monkeypatch.setattr("drinkingbird.config.LEGACY_CONFIG_PATH", legacy_path)

        config = load_config()
        assert config.llm.provider == "anthropic"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py::TestConfigPaths -v`
Expected: FAIL (CONFIG_PATH still points to ~/.bdbrc)

**Step 3: Modify config.py**

Update the path constants:
```python
CONFIG_PATH = Path.home() / ".bdb" / "config.yaml"
LEGACY_CONFIG_PATH = Path.home() / ".bdbrc"
```

Update `load_config()`:
```python
def load_config(path: Path | None = None) -> Config:
    """Load configuration from YAML file.

    Args:
        path: Path to config file. Defaults to ~/.bdb/config.yaml,
              falls back to ~/.bdbrc for backwards compatibility.

    Returns:
        Loaded Config object

    Raises:
        ConfigError: If config file has insecure permissions or is invalid
    """
    if path is not None:
        config_path = path
    elif CONFIG_PATH.exists():
        config_path = CONFIG_PATH
    elif LEGACY_CONFIG_PATH.exists():
        config_path = LEGACY_CONFIG_PATH
    else:
        # Return default config if no file exists
        return Config()

    if not config_path.exists():
        return Config()

    # Check permissions
    if not check_permissions(config_path):
        raise ConfigError(
            f"Config file {config_path} has insecure permissions. "
            f"Run: chmod 600 {config_path}"
        )

    # Load YAML
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}")

    # Merge with defaults
    merged = _deep_merge(DEFAULT_CONFIG, data)

    return Config.from_dict(merged)
```

Update `generate_template()` header comment:
```python
def generate_template() -> str:
    """Generate a template configuration file."""
    return """# Better Drinking Bird Configuration
# Location: ~/.bdb/config.yaml
# File permissions should be 600 (chmod 600 ~/.bdb/config.yaml)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/drinkingbird/config.py tests/test_config.py
git commit -m "$(cat <<'EOF'
feat: move config to ~/.bdb/config.yaml

Config now lives in ~/.bdb/config.yaml with backwards-compatible
fallback to ~/.bdbrc for existing installations.
EOF
)"
```

---

## Task 5: Update CLI init command for new config path

**Files:**
- Modify: `src/drinkingbird/cli.py`
- Test: Manual verification

**Step 1: Modify init command**

Update the `init` command to use new path and offer migration:

```python
@main.command()
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Overwrite existing config file",
)
def init(force: bool) -> None:
    """Initialize configuration file.

    Creates ~/.bdb/config.yaml with default settings and secure permissions.
    """
    from drinkingbird.config import LEGACY_CONFIG_PATH

    # Check for legacy config
    if LEGACY_CONFIG_PATH.exists() and not CONFIG_PATH.exists():
        click.echo(f"Found legacy config at {LEGACY_CONFIG_PATH}")
        if click.confirm("Move to new location (~/.bdb/config.yaml)?"):
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.move(str(LEGACY_CONFIG_PATH), str(CONFIG_PATH))
            click.echo(f"Moved config to {CONFIG_PATH}")
            return

    if CONFIG_PATH.exists() and not force:
        click.echo(f"Config file already exists: {CONFIG_PATH}")
        click.echo("Use --force to overwrite.")
        sys.exit(1)

    path = save_template()
    click.echo(f"Created config file: {path}")
    click.echo("Edit this file to configure your API keys and settings.")
    click.echo()
    click.echo("Quick start:")
    click.echo("  1. Add your API key to ~/.bdb/config.yaml")
    click.echo("  2. Run: bdb install claude-code")
    click.echo("  3. Start using Claude Code as normal")
```

**Step 2: Update check command references**

Update `check` command output:
```python
click.echo("  Run 'bdb init' to create one.")
# and
click.echo("  Add api_key or api_key_env to ~/.bdb/config.yaml")
```

**Step 3: Run all tests**

Run: `pytest -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/drinkingbird/cli.py
git commit -m "$(cat <<'EOF'
feat: update CLI for new config location

Init command now creates ~/.bdb/config.yaml and offers to migrate
legacy ~/.bdbrc configs.
EOF
)"
```

---

## Task 6: Run full test suite and verify

**Step 1: Run all tests**

Run: `pytest -v`
Expected: All tests pass

**Step 2: Manual verification**

```bash
# Test pause in git repo
cd /path/to/git/repo
bdb pause --reason "Testing"
cat .bdb-paused
bdb resume

# Test global pause
cd /tmp
bdb pause --global
cat ~/.bdb/.bdb-paused
bdb resume --global

# Test config init
rm -f ~/.bdb/config.yaml ~/.bdbrc
bdb init
cat ~/.bdb/config.yaml
```

**Step 3: Final commit if needed**

```bash
git status
# If clean, done. Otherwise commit any remaining changes.
```

---

## Verification Checklist

- [ ] `bdb pause` in git repo creates `.bdb-paused` in repo root
- [ ] `bdb pause --global` creates `~/.bdb/.bdb-paused`
- [ ] `bdb pause --reason "text"` stores reason in JSON
- [ ] `bdb resume` removes active sentinel
- [ ] Hooks return allow immediately when paused
- [ ] `bdb init` creates `~/.bdb/config.yaml`
- [ ] Legacy `~/.bdbrc` still works
- [ ] `bdb init` offers to migrate legacy config
- [ ] All existing tests pass
