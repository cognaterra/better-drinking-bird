# src/drinkingbird/mode.py
"""Mode management for Better Drinking Bird.

Modes control how BDB supervises the agent:
- default: LLM infers session type and decision (current behavior)
- auto: Same as default
- interactive: Stop hook returns ALLOW (safety hooks still run)
"""

from __future__ import annotations

import getpass
import json
from datetime import datetime
from enum import Enum
from pathlib import Path


class Mode(Enum):
    """BDB supervision modes."""

    DEFAULT = "default"
    AUTO = "auto"
    INTERACTIVE = "interactive"


MODE_FILE = "mode"
GLOBAL_MODE_PATH = Path.home() / ".bdb" / MODE_FILE


def get_workspace_root() -> Path | None:
    """Get git repo root from cwd, or None if not in a repo."""
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def get_local_mode_path() -> Path | None:
    """Get local mode file path if in git repo."""
    root = get_workspace_root()
    if root:
        return root / ".bdb" / MODE_FILE
    return None


def _read_mode_file(path: Path) -> Mode | None:
    """Read mode from file, returning None if not found or invalid."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        mode_str = data.get("mode", "").lower()
        return Mode(mode_str)
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def get_mode() -> Mode:
    """Get current mode. Local takes precedence over global.

    Returns Mode.DEFAULT if no mode file exists.
    """
    # Check local first
    local_path = get_local_mode_path()
    if local_path:
        mode = _read_mode_file(local_path)
        if mode is not None:
            return mode

    # Check global
    mode = _read_mode_file(GLOBAL_MODE_PATH)
    if mode is not None:
        return mode

    return Mode.DEFAULT


def get_mode_info() -> tuple[Mode, str | None]:
    """Get current mode and its source path.

    Returns (mode, path) where path is None if using default.
    """
    # Check local first
    local_path = get_local_mode_path()
    if local_path and local_path.exists():
        mode = _read_mode_file(local_path)
        if mode is not None:
            return mode, str(local_path)

    # Check global
    if GLOBAL_MODE_PATH.exists():
        mode = _read_mode_file(GLOBAL_MODE_PATH)
        if mode is not None:
            return mode, str(GLOBAL_MODE_PATH)

    return Mode.DEFAULT, None


def set_mode(mode: Mode, use_global: bool = False) -> Path:
    """Set the supervision mode.

    Args:
        mode: The mode to set
        use_global: If True, set global mode. Otherwise set local (requires git repo).

    Returns:
        Path to the mode file that was written.

    Raises:
        ValueError: If use_global=False and not in a git repo.
    """
    if use_global:
        path = GLOBAL_MODE_PATH
    else:
        path = get_local_mode_path()
        if path is None:
            raise ValueError("Not in a git repository. Use --global to set global mode.")

    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "mode": mode.value,
        "timestamp": datetime.now().isoformat(),
        "user": getpass.getuser(),
    }
    path.write_text(json.dumps(data, indent=2))

    return path


def clear_mode(use_global: bool = False) -> Path | None:
    """Clear the mode file, reverting to default behavior.

    Args:
        use_global: If True, clear global mode. Otherwise clear local.

    Returns:
        Path that was removed, or None if no file existed.
    """
    if use_global:
        path = GLOBAL_MODE_PATH
    else:
        path = get_local_mode_path()
        if path is None:
            return None

    if path.exists():
        path.unlink()
        return path

    return None
