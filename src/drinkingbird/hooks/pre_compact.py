"""Pre-Compact Hook - Preserves critical context during memory compaction."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from drinkingbird.hooks.base import DebugFn, Hook, HookResult


# Default context patterns
DEFAULT_CONTEXT_PATTERNS = [
    "*plan*.md",
    "*spec*.md",
    "*design*.md",
    "*architecture*.md",
    "*requirements*.md",
    "CLAUDE.md",
    "README.md",
]

# Priority directories to scan
CONTEXT_DIRS = [
    "docs/plans",
    "docs",
    ".claude/plans",
]


class PreCompactHook(Hook):
    """Hook that preserves critical context during compaction."""

    event_name = "PreCompact"

    def handle(self, hook_input: dict[str, Any], debug: DebugFn) -> HookResult:
        """Handle pre-compact hook event."""
        cwd = hook_input.get("cwd", os.getcwd())
        trigger = hook_input.get("matcher", "auto")

        debug(f"PreCompact triggered by: {trigger}")

        # Get patterns from config or use defaults
        patterns = getattr(self.config, "context_patterns", DEFAULT_CONTEXT_PATTERNS)

        # Find context files
        context_files = self._find_context_files(cwd, patterns)
        debug(f"Found {len(context_files)} context files")

        if not context_files:
            debug("No context files found")
            return HookResult.allow("No context files")

        # Build reminder
        reminder = self._build_context_reminder(context_files)
        debug(f"Reminder: {reminder[:200]}...")

        return HookResult.with_context(reminder)

    def _find_context_files(
        self, cwd: str, patterns: list[str]
    ) -> list[str]:
        """Find important context files in priority order."""
        found = []
        cwd_path = Path(cwd)

        # Check priority directories first
        for dir_pattern in CONTEXT_DIRS:
            dir_path = cwd_path / dir_pattern
            if dir_path.exists() and dir_path.is_dir():
                for pattern in patterns:
                    for match in dir_path.glob(pattern):
                        if match.is_file():
                            rel_path = str(match.relative_to(cwd_path))
                            if rel_path not in found:
                                found.append(rel_path)

        # Check root level for key files
        for pattern in ["CLAUDE.md", "README.md"]:
            root_file = cwd_path / pattern
            if root_file.exists():
                if pattern not in found:
                    found.append(pattern)

        return found

    def _build_context_reminder(self, files: list[str]) -> str:
        """Build a context reminder string."""
        if not files:
            return ""

        lines = [
            "=== CRITICAL CONTEXT FILES ===",
            "These files contain important project context. Reference them if you lose track:",
            "",
        ]

        for f in files[:10]:  # Limit to 10 files
            lines.append(f"  - {f}")

        lines.append("")
        lines.append("Re-read these files if you're unsure about the task or approach.")

        return "\n".join(lines)
