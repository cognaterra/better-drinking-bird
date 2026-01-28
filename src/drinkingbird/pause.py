# src/drinkingbird/pause.py
"""Pause/resume functionality for Better Drinking Bird."""

from __future__ import annotations

import getpass
import json
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
