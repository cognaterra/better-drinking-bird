"""Doctor diagnostics for BDB installation health."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drinkingbird.adapters import (
    ClaudeCodeAdapter,
    ClineAdapter,
    CopilotAdapter,
    CursorAdapter,
    KiloCodeAdapter,
)
from drinkingbird.manifest import Installation, Manifest


@dataclass
class Issue:
    """A detected installation issue."""

    severity: str  # "error" or "warning"
    issue_type: str  # "orphaned_manifest", "untracked_hooks", "missing_hooks"
    agent: str
    scope: str
    path: str
    description: str

    def __str__(self) -> str:
        icon = "✗" if self.severity == "error" else "⚠"
        return f"{icon} [{self.agent}/{self.scope}] {self.description}"


def get_adapters() -> dict[str, Any]:
    """Get all adapters that support installation."""
    return {
        "claude-code": ClaudeCodeAdapter(),
        "cline": ClineAdapter(),
        "cursor": CursorAdapter(),
        "copilot": CopilotAdapter(),
        "kilo-code": KiloCodeAdapter(),
    }


def config_has_bdb_hooks(config_path: Path, agent: str) -> bool:
    """Check if a config file contains bdb hooks."""
    if not config_path.exists():
        return False

    try:
        if config_path.suffix == ".yaml":
            import yaml
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = json.loads(config_path.read_text())
    except (json.JSONDecodeError, Exception):
        return False

    hooks = data.get("hooks", {})
    if not hooks:
        return False

    # Check for bdb in hook commands
    for hook_name, hook_config in hooks.items():
        if isinstance(hook_config, list):
            # Claude Code / Kilo Code style: list of hook entries
            for entry in hook_config:
                if isinstance(entry, dict):
                    # Nested hooks structure
                    for hook in entry.get("hooks", []):
                        if "bdb" in hook.get("command", ""):
                            return True
                    # Direct command
                    if "bdb" in entry.get("command", ""):
                        return True
        elif isinstance(hook_config, dict):
            # Cursor style: dict with command
            if "bdb" in hook_config.get("command", ""):
                return True
        elif isinstance(hook_config, str):
            # Copilot style: direct command string
            if "bdb" in hook_config:
                return True

    return False


def cline_has_bdb_hooks(hooks_dir: Path) -> bool:
    """Check if Cline hooks directory has bdb scripts."""
    if not hooks_dir.exists():
        return False

    for script in hooks_dir.iterdir():
        if script.is_file():
            try:
                if "bdb" in script.read_text():
                    return True
            except Exception:
                pass
    return False


def check_manifest_entry(
    inst: Installation,
    adapters: dict[str, Any],
) -> Issue | None:
    """Check if a manifest entry is valid."""
    if inst.agent not in adapters:
        return Issue(
            severity="warning",
            issue_type="unknown_agent",
            agent=inst.agent,
            scope=inst.scope,
            path=inst.path,
            description=f"Unknown agent '{inst.agent}' in manifest",
        )

    config_path = Path(inst.path)

    # Check if config file exists
    if not config_path.exists():
        return Issue(
            severity="error",
            issue_type="missing_config",
            agent=inst.agent,
            scope=inst.scope,
            path=inst.path,
            description=f"Config file missing: {inst.path}",
        )

    # Check if config has bdb hooks
    if inst.agent == "cline":
        has_hooks = cline_has_bdb_hooks(config_path)
    else:
        has_hooks = config_has_bdb_hooks(config_path, inst.agent)

    if not has_hooks:
        return Issue(
            severity="error",
            issue_type="missing_hooks",
            agent=inst.agent,
            scope=inst.scope,
            path=inst.path,
            description=f"Config exists but no bdb hooks found: {inst.path}",
        )

    return None


def check_untracked_installation(
    agent: str,
    scope: str,
    config_path: Path,
    manifest: Manifest,
) -> Issue | None:
    """Check if a config location has untracked bdb hooks."""
    # Check if already in manifest
    for inst in manifest.get(agent=agent, scope=scope):
        if inst.path == str(config_path):
            return None

    # Check if config has bdb hooks
    if agent == "cline":
        has_hooks = cline_has_bdb_hooks(config_path)
    else:
        has_hooks = config_has_bdb_hooks(config_path, agent)

    if has_hooks:
        return Issue(
            severity="warning",
            issue_type="untracked_hooks",
            agent=agent,
            scope=scope,
            path=str(config_path),
            description=f"Found bdb hooks not in manifest: {config_path}",
        )

    return None


def diagnose_local(workspace: Path) -> list[Issue]:
    """Diagnose installation health for a specific workspace."""
    issues: list[Issue] = []
    manifest = Manifest.load()
    adapters = get_adapters()

    # Check manifest entries for this workspace
    for inst in manifest.get(scope="local"):
        # Check if this installation is in the current workspace
        inst_workspace = Path(inst.path).parent.parent
        if inst_workspace == workspace:
            issue = check_manifest_entry(inst, adapters)
            if issue:
                issues.append(issue)

    # Check for untracked local installations
    for agent, adapter in adapters.items():
        if not adapter.supports_local:
            continue

        try:
            local_path = adapter.get_local_config_path(workspace)
            issue = check_untracked_installation(agent, "local", local_path, manifest)
            if issue:
                issues.append(issue)
        except NotImplementedError:
            pass

    return issues


def diagnose_global() -> list[Issue]:
    """Diagnose installation health for all installations."""
    issues: list[Issue] = []
    manifest = Manifest.load()
    adapters = get_adapters()

    # Check all manifest entries
    for inst in manifest.get():
        issue = check_manifest_entry(inst, adapters)
        if issue:
            issues.append(issue)

    # Check for untracked global installations
    for agent, adapter in adapters.items():
        global_path = adapter.get_config_path()
        issue = check_untracked_installation(agent, "global", global_path, manifest)
        if issue:
            issues.append(issue)

    return issues


def fix_issue(issue: Issue, manifest: Manifest) -> str:
    """Fix a single issue. Returns description of fix applied."""
    adapters = get_adapters()

    if issue.issue_type == "missing_config":
        # Config file is gone - remove from manifest
        manifest.remove(agent=issue.agent, scope=issue.scope, path=issue.path)
        return f"Removed stale manifest entry for {issue.agent} ({issue.scope})"

    elif issue.issue_type == "missing_hooks":
        # Config exists but no hooks - remove from manifest
        # (User can reinstall if they want hooks)
        manifest.remove(agent=issue.agent, scope=issue.scope, path=issue.path)
        return f"Removed manifest entry (hooks were removed from config)"

    elif issue.issue_type == "untracked_hooks":
        # Hooks exist but not tracked - add to manifest
        manifest.add(issue.agent, issue.scope, issue.path)
        return f"Added {issue.agent} ({issue.scope}) to manifest"

    elif issue.issue_type == "unknown_agent":
        # Unknown agent - remove from manifest
        manifest.remove(agent=issue.agent, scope=issue.scope, path=issue.path)
        return f"Removed unknown agent entry from manifest"

    return "No fix available"


def fix_issues(issues: list[Issue]) -> list[str]:
    """Fix all issues. Returns list of fixes applied."""
    fixes: list[str] = []
    manifest = Manifest.load()

    for issue in issues:
        fix_desc = fix_issue(issue, manifest)
        fixes.append(fix_desc)

    manifest.save()
    return fixes
