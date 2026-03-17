# Claude Code Permissions Checking in PreToolUse Hook

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-approve Bash commands that are already permitted in Claude Code's settings files, skipping unnecessary LLM classification calls.

**Architecture:** New `safety/permissions.py` module splits compound commands into sub-commands, loads Claude Code's permissions files, and checks each sub-command against allow/deny patterns using fnmatch. Integrated into `pre_tool.py` between BDB pattern checks (which always take priority) and LLM classification.

**Tech Stack:** Python stdlib (`json`, `fnmatch`, `pathlib`), pytest

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/drinkingbird/safety/permissions.py` | Command splitting, permissions loading, permission matching |
| Create | `tests/test_permissions.py` | Unit tests for all permissions functions |
| Modify | `src/drinkingbird/hooks/pre_tool.py:68-106` | Insert permissions check between pattern check and LLM |
| Modify | `tests/test_hooks.py` | Integration tests for permissions in PreToolHook |

**Reuse:**
- `config._get_git_root()` pattern for finding project root (but use `cwd` param, don't call `Path.cwd()`)
- `blocklist.py` module pattern: single public function returning `tuple[bool, str]`
- `ClaudeCodeAdapter.get_config_path()` / `get_local_config_path()` for settings file paths (reference only — we read directly since adapter isn't available in safety module)

**Pipeline after change:**
1. Protected path check (unchanged)
2. Non-Bash early exit (unchanged)
3. BDB pattern check (unchanged) — **blocks pre-empt permissions**
4. **NEW: Permissions check** — if all sub-commands permitted, allow
5. LLM classification (unchanged) — only if permissions don't cover command
6. Default allow (unchanged)

---

## Chunk 1: Command Splitting

### Task 1: `split_compound_command` — tests

**Files:**
- Create: `tests/test_permissions.py`

- [ ] **Step 1: Write failing tests for command splitting**

```python
"""Tests for drinkingbird.safety.permissions module."""

from __future__ import annotations

import pytest

from drinkingbird.safety.permissions import split_compound_command


class TestSplitCompoundCommand:
    """Tests for splitting compound shell commands into sub-commands."""

    def test_simple_command(self):
        assert split_compound_command("git status") == ["git status"]

    def test_pipe(self):
        result = split_compound_command("cat file | grep foo")
        assert result == ["cat file", "grep foo"]

    def test_and_chain(self):
        result = split_compound_command("cmd1 && cmd2")
        assert result == ["cmd1", "cmd2"]

    def test_or_chain(self):
        result = split_compound_command("cmd1 || cmd2")
        assert result == ["cmd1", "cmd2"]

    def test_semicolon(self):
        result = split_compound_command("cmd1; cmd2")
        assert result == ["cmd1", "cmd2"]

    def test_mixed_operators(self):
        result = split_compound_command("cmd1 && cmd2 || cmd3; cmd4")
        assert result == ["cmd1", "cmd2", "cmd3", "cmd4"]

    def test_single_quoted_preserved(self):
        result = split_compound_command("echo 'a && b'")
        assert result == ["echo 'a && b'"]

    def test_double_quoted_preserved(self):
        result = split_compound_command('echo "a | b"')
        assert result == ['echo "a | b"']

    def test_subshell_extracted(self):
        result = split_compound_command("echo $(git status)")
        assert "git status" in result

    def test_backtick_subshell_extracted(self):
        result = split_compound_command("echo `git status`")
        assert "git status" in result

    def test_env_var_stripped(self):
        result = split_compound_command("FOO=bar git commit")
        assert result == ["git commit"]

    def test_multiple_env_vars_stripped(self):
        result = split_compound_command("FOO=bar BAZ=qux git commit")
        assert result == ["git commit"]

    def test_redirection_stripped(self):
        result = split_compound_command("ls > file.txt")
        assert result == ["ls"]

    def test_stderr_redirect_stripped(self):
        result = split_compound_command("cmd 2>&1")
        assert result == ["cmd"]

    def test_input_redirect_stripped(self):
        result = split_compound_command("cmd < input.txt")
        assert result == ["cmd"]

    def test_newline_as_separator(self):
        result = split_compound_command("cmd1\ncmd2")
        assert result == ["cmd1", "cmd2"]

    def test_empty_command(self):
        assert split_compound_command("") == []

    def test_whitespace_only(self):
        assert split_compound_command("   ") == []

    def test_compound_with_redirections(self):
        result = split_compound_command("ls > out.txt && grep foo < in.txt")
        assert result == ["ls", "grep foo"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_permissions.py -v`
Expected: ImportError — `permissions` module doesn't exist yet

### Task 2: `split_compound_command` — implementation

**Files:**
- Create: `src/drinkingbird/safety/permissions.py`

- [ ] **Step 3: Implement command splitting**

```python
"""Claude Code permissions checking for Better Drinking Bird."""

from __future__ import annotations

import re


def split_compound_command(command: str) -> list[str]:
    """Split a compound shell command into individual sub-commands.

    Splits on &&, ||, ;, |, and newlines while respecting quoted strings
    and $() subshells. Extracts commands from subshells recursively.
    Normalizes each sub-command by stripping env vars, redirections,
    and shell keywords.
    """
    if not command or not command.strip():
        return []

    segments = _split_on_operators(command)
    result = []

    for segment in segments:
        # Extract subshell commands
        subshell_cmds = _extract_subshells(segment)

        # Normalize the segment itself
        normalized = _normalize(segment)
        if normalized:
            result.append(normalized)

        # Add extracted subshell commands
        for sub in subshell_cmds:
            normalized_sub = _normalize(sub)
            if normalized_sub:
                result.append(normalized_sub)

    return result


def _split_on_operators(command: str) -> list[str]:
    """Split command on &&, ||, ;, |, and newlines respecting quotes and subshells."""
    segments: list[str] = []
    current: list[str] = []
    i = 0
    in_single_quote = False
    in_double_quote = False
    paren_depth = 0

    while i < len(command):
        ch = command[i]

        # Track quotes
        if ch == "'" and not in_double_quote and paren_depth == 0:
            in_single_quote = not in_single_quote
            current.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single_quote and paren_depth == 0:
            in_double_quote = not in_double_quote
            current.append(ch)
            i += 1
            continue

        # Inside quotes — pass through
        if in_single_quote or in_double_quote:
            current.append(ch)
            i += 1
            continue

        # Track subshell depth
        if ch == "(" or (ch == "$" and i + 1 < len(command) and command[i + 1] == "("):
            paren_depth += 1
            current.append(ch)
            if ch == "$":
                i += 1
                current.append("(")
            i += 1
            continue
        if ch == ")" and paren_depth > 0:
            paren_depth -= 1
            current.append(ch)
            i += 1
            continue

        # Inside subshell — pass through
        if paren_depth > 0:
            current.append(ch)
            i += 1
            continue

        # Split on operators
        if ch == "\n" or ch == ";":
            segments.append("".join(current))
            current = []
            i += 1
            continue
        if ch == "&" and i + 1 < len(command) and command[i + 1] == "&":
            segments.append("".join(current))
            current = []
            i += 2
            continue
        if ch == "|" and i + 1 < len(command) and command[i + 1] == "|":
            segments.append("".join(current))
            current = []
            i += 2
            continue
        if ch == "|":
            segments.append("".join(current))
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    if current:
        segments.append("".join(current))

    return [s.strip() for s in segments if s.strip()]


_SUBSHELL_RE = re.compile(r"\$\((.+?)\)|`(.+?)`")


def _extract_subshells(command: str) -> list[str]:
    """Extract commands from $() and backtick subshells."""
    results = []
    for match in _SUBSHELL_RE.finditer(command):
        inner = match.group(1) or match.group(2)
        if inner:
            results.append(inner.strip())
    return results


_ENV_PREFIX_RE = re.compile(r"^(\w+=\S+\s+)+")
_REDIRECT_RE = re.compile(r"\s*\d*[<>]+\s*\S+|\s*\d+>&\d+")
_SHELL_KEYWORDS = frozenset(
    {"if", "then", "else", "elif", "fi", "do", "done", "while", "for", "in", "case", "esac"}
)


def _normalize(command: str) -> str:
    """Normalize a sub-command by stripping env vars, redirections, and shell keywords."""
    cmd = command.strip()
    if not cmd:
        return ""

    # Strip env var assignments from the front
    cmd = _ENV_PREFIX_RE.sub("", cmd).strip()

    # Strip redirections
    cmd = _REDIRECT_RE.sub("", cmd).strip()

    # Strip leading shell keywords
    parts = cmd.split()
    while parts and parts[0] in _SHELL_KEYWORDS:
        parts.pop(0)

    return " ".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_permissions.py::TestSplitCompoundCommand -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/drinkingbird/safety/permissions.py tests/test_permissions.py
git commit -m "feat(permissions): add compound command splitting"
```

---

## Chunk 2: Permissions Loading

### Task 3: `load_claude_permissions` — tests

**Files:**
- Modify: `tests/test_permissions.py`

- [ ] **Step 6: Write failing tests for permissions loading**

Append to `tests/test_permissions.py`:

```python
import json
from pathlib import Path

from drinkingbird.safety.permissions import load_claude_permissions


class TestLoadClaudePermissions:
    """Tests for loading and merging Claude Code permissions files."""

    def test_no_files_exist(self, tmp_path):
        """No settings files → empty patterns."""
        allow, deny = load_claude_permissions(str(tmp_path))
        assert allow == []
        assert deny == []

    def test_global_settings_only(self, tmp_path, monkeypatch):
        """Only ~/.claude/settings.json exists."""
        fake_home = tmp_path / "home"
        fake_claude = fake_home / ".claude"
        fake_claude.mkdir(parents=True)
        (fake_claude / "settings.json").write_text(json.dumps({
            "permissions": {
                "allow": ["Bash(git status:*)"],
                "deny": ["Bash(rm:*)"],
            }
        }))
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        allow, deny = load_claude_permissions(str(tmp_path))
        assert allow == ["Bash(git status:*)"]
        assert deny == ["Bash(rm:*)"]

    def test_project_settings_merged(self, tmp_path, monkeypatch):
        """Project .claude/settings.json adds to global."""
        fake_home = tmp_path / "home"
        fake_claude = fake_home / ".claude"
        fake_claude.mkdir(parents=True)
        (fake_claude / "settings.json").write_text(json.dumps({
            "permissions": {"allow": ["Bash(git status:*)"]}
        }))
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        # Create project with .git
        project = tmp_path / "project"
        (project / ".git").mkdir(parents=True)
        (project / ".claude").mkdir()
        (project / ".claude" / "settings.json").write_text(json.dumps({
            "permissions": {"allow": ["Bash(npm test:*)"]}
        }))

        allow, deny = load_claude_permissions(str(project))
        assert "Bash(git status:*)" in allow
        assert "Bash(npm test:*)" in allow

    def test_local_settings_merged(self, tmp_path, monkeypatch):
        """settings.local.json adds to the union."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        project = tmp_path / "project"
        (project / ".git").mkdir(parents=True)
        (project / ".claude").mkdir()
        (project / ".claude" / "settings.local.json").write_text(json.dumps({
            "permissions": {"allow": ["Bash(echo:*)"]}
        }))

        allow, _ = load_claude_permissions(str(project))
        assert "Bash(echo:*)" in allow

    def test_malformed_json_skipped(self, tmp_path, monkeypatch):
        """Malformed JSON is silently skipped."""
        fake_home = tmp_path / "home"
        fake_claude = fake_home / ".claude"
        fake_claude.mkdir(parents=True)
        (fake_claude / "settings.json").write_text("not json{{{")
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        allow, deny = load_claude_permissions(str(tmp_path))
        assert allow == []
        assert deny == []

    def test_missing_permissions_key(self, tmp_path, monkeypatch):
        """Settings file with no 'permissions' key → empty."""
        fake_home = tmp_path / "home"
        fake_claude = fake_home / ".claude"
        fake_claude.mkdir(parents=True)
        (fake_claude / "settings.json").write_text(json.dumps({"hooks": {}}))
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        allow, deny = load_claude_permissions(str(tmp_path))
        assert allow == []
        assert deny == []
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `uv run pytest tests/test_permissions.py::TestLoadClaudePermissions -v`
Expected: ImportError — `load_claude_permissions` not yet exported

### Task 4: `load_claude_permissions` — implementation

**Files:**
- Modify: `src/drinkingbird/safety/permissions.py`

- [ ] **Step 8: Implement permissions loading**

Append to `permissions.py`:

```python
import json
from pathlib import Path


def _find_project_root(cwd: str) -> Path | None:
    """Find git repo root by walking up from cwd."""
    current = Path(cwd).resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def _load_settings_file(path: Path) -> tuple[list[str], list[str]]:
    """Read one Claude Code settings file, return (allow, deny) patterns."""
    if not path.exists():
        return [], []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return [], []
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        return [], []
    return (
        perms.get("allow", []),
        perms.get("deny", []),
    )


def load_claude_permissions(cwd: str) -> tuple[list[str], list[str]]:
    """Load and merge Claude Code permissions from all settings files.

    Reads (in order, union of all):
    1. ~/.claude/settings.json (global)
    2. <project>/.claude/settings.json (project)
    3. <project>/.claude/settings.local.json (local)
    """
    all_allow: list[str] = []
    all_deny: list[str] = []

    # Global settings
    global_path = Path.home() / ".claude" / "settings.json"
    allow, deny = _load_settings_file(global_path)
    all_allow.extend(allow)
    all_deny.extend(deny)

    # Project settings
    project_root = _find_project_root(cwd)
    if project_root:
        for name in ("settings.json", "settings.local.json"):
            path = project_root / ".claude" / name
            allow, deny = _load_settings_file(path)
            all_allow.extend(allow)
            all_deny.extend(deny)

    return all_allow, all_deny
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/test_permissions.py::TestLoadClaudePermissions -v`
Expected: All PASS

- [ ] **Step 10: Commit**

```bash
git add src/drinkingbird/safety/permissions.py tests/test_permissions.py
git commit -m "feat(permissions): add Claude Code permissions file loading"
```

---

## Chunk 3: Permission Matching & Integration

### Task 5: `check_permissions_allow` — tests

**Files:**
- Modify: `tests/test_permissions.py`

- [ ] **Step 11: Write failing tests for permission matching**

Append to `tests/test_permissions.py`:

```python
from unittest.mock import MagicMock

from drinkingbird.safety.permissions import check_permissions_allow


class TestCheckPermissionsAllow:
    """Tests for the top-level permissions check function."""

    def _setup_permissions(self, tmp_path, monkeypatch, allow=None, deny=None):
        """Helper to set up a project with permissions."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        project = tmp_path / "project"
        (project / ".git").mkdir(parents=True)
        (project / ".claude").mkdir()

        perms = {}
        if allow:
            perms["allow"] = allow
        if deny:
            perms["deny"] = deny
        (project / ".claude" / "settings.local.json").write_text(
            json.dumps({"permissions": perms})
        )
        return str(project)

    def test_simple_allowed(self, tmp_path, monkeypatch):
        cwd = self._setup_permissions(tmp_path, monkeypatch,
            allow=["Bash(git status:*)"])
        debug = MagicMock()
        is_allowed, _ = check_permissions_allow("git status", cwd, debug)
        assert is_allowed is True

    def test_not_in_allow(self, tmp_path, monkeypatch):
        cwd = self._setup_permissions(tmp_path, monkeypatch,
            allow=["Bash(git status:*)"])
        debug = MagicMock()
        is_allowed, _ = check_permissions_allow("rm -rf /", cwd, debug)
        assert is_allowed is False

    def test_denied_even_if_allowed(self, tmp_path, monkeypatch):
        cwd = self._setup_permissions(tmp_path, monkeypatch,
            allow=["Bash(rm:*)"], deny=["Bash(rm:*)"])
        debug = MagicMock()
        is_allowed, _ = check_permissions_allow("rm -rf /", cwd, debug)
        assert is_allowed is False

    def test_compound_all_allowed(self, tmp_path, monkeypatch):
        cwd = self._setup_permissions(tmp_path, monkeypatch,
            allow=["Bash(git status:*)", "Bash(git diff:*)"])
        debug = MagicMock()
        is_allowed, _ = check_permissions_allow("git status && git diff", cwd, debug)
        assert is_allowed is True

    def test_compound_one_not_allowed(self, tmp_path, monkeypatch):
        cwd = self._setup_permissions(tmp_path, monkeypatch,
            allow=["Bash(git status:*)"])
        debug = MagicMock()
        is_allowed, _ = check_permissions_allow("git status && rm -rf /", cwd, debug)
        assert is_allowed is False

    def test_no_permissions_files(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        debug = MagicMock()
        is_allowed, _ = check_permissions_allow("git status", str(tmp_path), debug)
        assert is_allowed is False

    def test_no_allow_patterns(self, tmp_path, monkeypatch):
        cwd = self._setup_permissions(tmp_path, monkeypatch,
            deny=["Bash(rm:*)"])
        debug = MagicMock()
        is_allowed, _ = check_permissions_allow("git status", cwd, debug)
        assert is_allowed is False

    def test_empty_command(self, tmp_path, monkeypatch):
        cwd = self._setup_permissions(tmp_path, monkeypatch,
            allow=["Bash(git:*)"])
        debug = MagicMock()
        is_allowed, _ = check_permissions_allow("", cwd, debug)
        assert is_allowed is False

    def test_piped_command_all_allowed(self, tmp_path, monkeypatch):
        cwd = self._setup_permissions(tmp_path, monkeypatch,
            allow=["Bash(cat:*)", "Bash(grep:*)"])
        debug = MagicMock()
        is_allowed, _ = check_permissions_allow("cat file.txt | grep pattern", cwd, debug)
        assert is_allowed is True
```

- [ ] **Step 12: Run tests to verify they fail**

Run: `uv run pytest tests/test_permissions.py::TestCheckPermissionsAllow -v`
Expected: ImportError — `check_permissions_allow` not yet exported

### Task 6: `check_permissions_allow` — implementation

**Files:**
- Modify: `src/drinkingbird/safety/permissions.py`

- [ ] **Step 13: Implement permission matching**

Append to `permissions.py`:

```python
from fnmatch import fnmatch
from typing import Any, Callable

DebugFn = Callable[..., Any]


def _normalize_pattern(pattern: str) -> str:
    """Normalize a Claude Code permission pattern for fnmatch.

    Claude Code uses ':*' as "with any arguments" separator, e.g.
    'Bash(git status:*)' means "git status with any args".
    Convert to fnmatch-compatible form: 'Bash(git status*)'.
    """
    return pattern.replace(":*", "*")


def _subcmd_permitted(subcmd: str, allow_patterns: list[str], deny_patterns: list[str]) -> bool:
    """Check if a single sub-command is permitted by the patterns.

    Returns True only if the sub-command matches an allow pattern
    and does NOT match any deny pattern.
    """
    wrapped = f"Bash({subcmd})"

    # Deny takes priority
    for pattern in deny_patterns:
        if fnmatch(wrapped, _normalize_pattern(pattern)):
            return False

    # Must match at least one allow pattern
    for pattern in allow_patterns:
        if fnmatch(wrapped, _normalize_pattern(pattern)):
            return True

    return False


def check_permissions_allow(
    command: str,
    cwd: str,
    debug: DebugFn,
) -> tuple[bool, str]:
    """Check if a command is permitted by Claude Code settings.

    Returns:
        (True, reason) if all sub-commands are permitted.
        (False, reason) if any sub-command is not permitted or no patterns exist.
    """
    allow_patterns, deny_patterns = load_claude_permissions(cwd)

    if not allow_patterns:
        return False, ""

    subcmds = split_compound_command(command)
    if not subcmds:
        return False, ""

    for subcmd in subcmds:
        if not _subcmd_permitted(subcmd, allow_patterns, deny_patterns):
            debug(f"Sub-command not permitted: {subcmd}")
            return False, f"sub-command not covered: {subcmd}"

    return True, "all sub-commands permitted by Claude Code settings"
```

- [ ] **Step 14: Run tests to verify they pass**

Run: `uv run pytest tests/test_permissions.py -v`
Expected: All PASS

- [ ] **Step 15: Commit**

```bash
git add src/drinkingbird/safety/permissions.py tests/test_permissions.py
git commit -m "feat(permissions): add permission matching and check_permissions_allow"
```

### Task 7: Integration into `pre_tool.py`

**Files:**
- Modify: `src/drinkingbird/hooks/pre_tool.py:68-106`
- Modify: `tests/test_hooks.py`

- [ ] **Step 16: Write failing integration tests**

Add to `tests/test_hooks.py` in the `TestPreToolHook` class (or new class):

Note: these tests require existing imports from `test_hooks.py`: `json`, `Decision`, `PreToolHook`, `PreToolHookConfig`.

```python
class TestPreToolHookPermissions:
    """Tests for permissions integration in PreToolHook."""

    def test_permitted_command_allowed(self, tmp_path, monkeypatch):
        """Command permitted by Claude Code settings is allowed without LLM."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        project = tmp_path / "project"
        (project / ".git").mkdir(parents=True)
        (project / ".claude").mkdir()
        (project / ".claude" / "settings.local.json").write_text(json.dumps({
            "permissions": {"allow": ["Bash(echo:*)"]}
        }))

        hook = PreToolHook(config=PreToolHookConfig(), llm_provider=None)
        result = hook.handle(
            {"tool_name": "Bash", "tool_input": {"command": "echo hello"}, "cwd": str(project)},
            debug=lambda *a, **k: None,
        )
        assert result.decision == Decision.ALLOW

    def test_bdb_block_overrides_permissions(self, tmp_path, monkeypatch):
        """BDB pattern block takes priority even if command is permitted."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        project = tmp_path / "project"
        (project / ".git").mkdir(parents=True)
        (project / ".claude").mkdir()
        (project / ".claude" / "settings.local.json").write_text(json.dumps({
            "permissions": {"allow": ["Bash(git reset:*)"]}
        }))

        hook = PreToolHook(config=PreToolHookConfig(), llm_provider=None)
        result = hook.handle(
            {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}, "cwd": str(project)},
            debug=lambda *a, **k: None,
        )
        assert result.decision == Decision.BLOCK

    def test_no_cwd_falls_through(self):
        """Missing cwd skips permissions check, falls through to default allow."""
        hook = PreToolHook(config=PreToolHookConfig(), llm_provider=None)
        result = hook.handle(
            {"tool_name": "Bash", "tool_input": {"command": "echo hi"}},
            debug=lambda *a, **k: None,
        )
        assert result.decision == Decision.ALLOW
```

- [ ] **Step 17: Run tests to verify they fail**

Run: `uv run pytest tests/test_hooks.py::TestPreToolHookPermissions -v`
Expected: FAIL — class doesn't exist yet / permissions check not integrated

- [ ] **Step 18: Integrate permissions check into pre_tool.py**

In `src/drinkingbird/hooks/pre_tool.py`, insert after the pattern check block (after line 78) and before the LLM classification (current line 80):

```python
        # Step 2: Check Claude Code permissions for fast allow
        cwd = hook_input.get("cwd", "")
        if cwd:
            from drinkingbird.safety.permissions import check_permissions_allow

            is_permitted, perm_reason = check_permissions_allow(command, cwd, debug)
            if is_permitted:
                debug(f"ALLOWED by permissions: {perm_reason}")
                return HookResult.allow(perm_reason)
```

Renumber the existing LLM step comment to "Step 3" and default allow to "Step 4".

- [ ] **Step 19: Run all tests**

Run: `uv run pytest tests/test_permissions.py tests/test_hooks.py -v`
Expected: All PASS

- [ ] **Step 20: Commit**

```bash
git add src/drinkingbird/hooks/pre_tool.py tests/test_hooks.py
git commit -m "feat(pre_tool): integrate Claude Code permissions check"
```

---

## Verification

1. `uv run pytest tests/test_permissions.py -v` — all unit tests pass
2. `uv run pytest tests/test_hooks.py -v` — all existing + new integration tests pass
3. `uv run pytest tests/ -v` — full suite green
