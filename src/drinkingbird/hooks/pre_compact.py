"""Pre-Compact Hook - Preserves critical context during memory compaction."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from drinkingbird.hooks.base import DebugFn, Hook, HookResult


# Default context files (no wildcards - only explicit files)
DEFAULT_CONTEXT_FILES = [
    "CLAUDE.md",
    "README.md",
]


class PreCompactHook(Hook):
    """Hook that preserves critical context during compaction."""

    event_name = "PreCompact"

    def handle(self, hook_input: dict[str, Any], debug: DebugFn) -> HookResult:
        """Handle pre-compact hook event."""
        cwd = hook_input.get("cwd", os.getcwd())
        trigger = hook_input.get("matcher", "auto")
        transcript_path = hook_input.get("transcript_path", "")

        debug(f"PreCompact triggered by: {trigger}")

        # Find default context files (CLAUDE.md, README.md)
        context_files = self._find_default_files(cwd)
        debug(f"Found {len(context_files)} context files")

        # Extract @refs from user messages in transcript (only valid files)
        user_refs = self._extract_user_refs(transcript_path, cwd)
        debug(f"Found {len(user_refs)} user @refs")

        if not context_files and not user_refs:
            debug("No context files or user refs found")
            return HookResult.allow("No context files")

        # Build reminder
        reminder = self._build_context_reminder(context_files, user_refs)
        debug(f"Reminder: {reminder[:200]}...")

        return HookResult.with_context(reminder)

    def _find_default_files(self, cwd: str) -> list[str]:
        """Find default context files (CLAUDE.md, README.md)."""
        found = []
        cwd_path = Path(cwd)

        for filename in DEFAULT_CONTEXT_FILES:
            file_path = cwd_path / filename
            if file_path.exists() and file_path.is_file():
                found.append(filename)

        return found

    def _extract_user_refs(self, transcript_path: str, cwd: str) -> list[str]:
        """Extract @references from all user messages in transcript.

        Only includes references that exist as actual files.
        """
        if not transcript_path:
            return []

        refs: list[str] = []
        seen: set[str] = set()

        try:
            with open(transcript_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Extract user message content
                    content = self._get_user_content(msg)
                    if content:
                        for ref in self._extract_mentions(content):
                            if ref not in seen:
                                # Validate file exists
                                if self._is_valid_file_ref(ref, cwd):
                                    refs.append(ref)
                                seen.add(ref)
        except (FileNotFoundError, PermissionError):
            pass

        return refs

    def _is_valid_file_ref(self, ref: str, cwd: str) -> bool:
        """Check if a reference points to an existing file."""
        if not os.path.isabs(ref):
            path = os.path.join(cwd, ref)
        else:
            path = ref
        return os.path.isfile(path)

    def _get_user_content(self, msg: dict) -> str | None:
        """Extract text content from a user message."""
        # Claude Code format: type="user", message={role, content, ...}
        if msg.get("type") == "user":
            inner_msg = msg.get("message", {})
            if isinstance(inner_msg, dict):
                content = inner_msg.get("content", "")
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            parts.append(block)
                    return "\n".join(parts)
            elif isinstance(inner_msg, str):
                return inner_msg
        # API format: role="user" at top level
        elif msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                return "\n".join(parts)
            return content if isinstance(content, str) else None
        return None

    def _extract_mentions(self, text: str) -> list[str]:
        """Extract @path/to/file mentions from text."""
        if not text:
            return []
        pattern = r"@([\w./-]+)"
        return re.findall(pattern, text)

    def _build_context_reminder(
        self, files: list[str], user_refs: list[str]
    ) -> str:
        """Build a context reminder string."""
        lines = []

        if files:
            lines.append("=== CRITICAL CONTEXT FILES ===")
            lines.append(
                "These files contain important project context. "
                "Reference them if you lose track:"
            )
            lines.append("")
            for f in files:
                lines.append(f"  - {f}")
            lines.append("")

        if user_refs:
            lines.append("=== USER-REFERENCED DOCUMENTS ===")
            lines.append(
                "The user referenced these documents. "
                "They are critical to the task:"
            )
            lines.append("")
            for ref in user_refs[:20]:  # Limit to 20 refs
                lines.append(f"  - @{ref}")
            lines.append("")

        return "\n".join(lines) if lines else ""
