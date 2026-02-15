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
    "AGENTS.md",
    "README.md",
]

# Max characters to include per quoted file
MAX_QUOTE_LENGTH = 10000


class PreCompactHook(Hook):
    """Hook that preserves critical context during compaction."""

    event_name = "PreCompact"

    def handle(self, hook_input: dict[str, Any], debug: DebugFn) -> HookResult:
        """Handle pre-compact hook event."""
        cwd = hook_input.get("cwd", os.getcwd())
        trigger = hook_input.get("matcher", "auto")
        transcript_path = hook_input.get("transcript_path", "")

        debug(f"PreCompact triggered by: {trigger}")

        # Gather git context if enabled
        inject_git = getattr(self.config, "inject_git_context", True)
        git_context: dict[str, str] = {}
        if inject_git:
            git_context = self._get_git_context(cwd, transcript_path, debug)
            debug(f"Git context: branch={'branch' in git_context}, worktree={'worktree_path' in git_context}")

        # Find default context files (CLAUDE.md, AGENTS.md, README.md)
        context_files = self._find_default_files(cwd)
        debug(f"Found {len(context_files)} context files")

        # Read file contents if quoting is enabled
        quote_files = getattr(self.config, "quote_context_files", True)
        file_contents: dict[str, str] = {}
        if quote_files and context_files:
            file_contents = self._read_context_files(cwd, context_files, debug)
            debug(f"Quoted {len(file_contents)} context files")

        # Extract @refs from user messages in transcript
        user_refs = self._extract_user_refs(transcript_path, cwd, debug)
        debug(f"Found {len(user_refs)} user @refs")

        if not context_files and not user_refs and not git_context:
            debug("No context files, user refs, or git context found")
            return HookResult.allow("No context to preserve")

        # Build reminder
        reminder = self._build_context_reminder(
            context_files, user_refs, git_context, file_contents
        )
        debug(f"Reminder length: {len(reminder)}")

        return HookResult.with_context(reminder)

    def _get_git_context(
        self, cwd: str, transcript_path: str, debug: DebugFn
    ) -> dict[str, str]:
        """Detect git branch name and worktree path from the filesystem.

        Returns a dict with optional keys 'branch' and 'worktree_path'.
        Reads .git/HEAD directly to avoid subprocess overhead.

        When cwd is a normal repo (not itself a worktree), checks
        .git/worktrees/ for linked worktrees and matches against the
        transcript to identify which worktree this agent is working in.
        """
        context: dict[str, str] = {}

        # Walk up to find the git root
        git_root = self._find_git_root(cwd)
        if not git_root:
            debug("Not in a git repository")
            return context

        git_path = git_root / ".git"

        if git_path.is_file():
            # Linked worktree: .git is a file with "gitdir: <path>"
            context["worktree_path"] = str(git_root)
            try:
                gitdir_line = git_path.read_text().strip()
                if gitdir_line.startswith("gitdir:"):
                    gitdir = Path(gitdir_line.split(":", 1)[1].strip())
                    if not gitdir.is_absolute():
                        gitdir = (git_root / gitdir).resolve()
                    head_file = gitdir / "HEAD"
                else:
                    debug(f"Unexpected .git file content: {gitdir_line[:80]}")
                    return context
            except OSError as e:
                debug(f"Cannot read .git file: {e}")
                return context
        elif git_path.is_dir():
            # Normal repo — but the agent may be working in a linked worktree
            # while cwd is still the main repo.  Check .git/worktrees/ and
            # match against the transcript to find the right one.
            worktree_ctx = self._match_worktree_from_transcript(
                git_path, transcript_path, debug
            )
            if worktree_ctx is not None:
                # {} = ambiguous (omit branch), populated = matched worktree
                return worktree_ctx

            # No worktrees or no match — use main repo HEAD
            head_file = git_path / "HEAD"
        else:
            debug(f".git is neither file nor directory at {git_path}")
            return context

        # Read HEAD to get branch name
        context.update(self._read_branch_from_head(head_file, debug))

        return context

    def _read_branch_from_head(
        self, head_file: Path, debug: DebugFn
    ) -> dict[str, str]:
        """Read a HEAD file and return {'branch': ...} or {}."""
        try:
            head_content = head_file.read_text().strip()
            if head_content.startswith("ref: refs/heads/"):
                return {"branch": head_content[len("ref: refs/heads/"):]}
            elif head_content.startswith("ref:"):
                return {"branch": head_content[len("ref:"):].strip()}
            else:
                return {"branch": f"(detached at {head_content[:8]})"}
        except OSError as e:
            debug(f"Cannot read HEAD: {e}")
            return {}

    def _match_worktree_from_transcript(
        self,
        git_dir: Path,
        transcript_path: str,
        debug: DebugFn,
    ) -> dict[str, str] | None:
        """Match a linked worktree to this agent via the transcript.

        Lists entries in .git/worktrees/, then searches the transcript
        for each worktree name.

        Returns:
            dict with branch/worktree_path — single worktree matched
            {} (empty dict) — ambiguous match, omit branch info
            None — no worktrees exist or no match, caller should use main repo
        """
        worktrees_dir = git_dir / "worktrees"
        if not worktrees_dir.is_dir():
            return None

        # Enumerate worktrees: name -> (HEAD path, worktree path)
        candidates: dict[str, tuple[Path, str | None]] = {}
        try:
            for entry in worktrees_dir.iterdir():
                if not entry.is_dir():
                    continue
                head_file = entry / "HEAD"
                if not head_file.exists():
                    continue
                # Derive worktree directory from the gitdir file
                wt_path = self._resolve_worktree_path(entry, debug)
                candidates[entry.name] = (head_file, wt_path)
        except OSError as e:
            debug(f"Cannot read worktrees dir: {e}")
            return None

        if not candidates:
            return None

        debug(f"Found {len(candidates)} worktree candidate(s): {list(candidates.keys())}")

        if not transcript_path:
            return None

        # Read transcript and search for worktree names
        try:
            transcript_text = Path(transcript_path).read_text()
        except OSError as e:
            debug(f"Cannot read transcript for worktree matching: {e}")
            return None

        # Find which worktree name appears in the transcript
        matched_name: str | None = None
        for name in candidates:
            if name in transcript_text:
                if matched_name is not None:
                    # Multiple matches — ambiguous, omit branch entirely
                    debug(f"Ambiguous worktree match: both {matched_name} and {name} found in transcript")
                    return {}
                matched_name = name

        if not matched_name:
            debug("No worktree name found in transcript")
            return None

        head_file, wt_path = candidates[matched_name]
        debug(f"Matched worktree: {matched_name}")

        context: dict[str, str] = {}
        context.update(self._read_branch_from_head(head_file, debug))
        if wt_path:
            context["worktree_path"] = wt_path

        return context

    def _resolve_worktree_path(
        self, wt_gitdir: Path, debug: DebugFn
    ) -> str | None:
        """Resolve the worktree directory from its .git/worktrees/<name>/ entry.

        Reads the 'gitdir' file which points back to the worktree's .git file.
        The worktree directory is the parent of that .git file path.
        """
        gitdir_file = wt_gitdir / "gitdir"
        if not gitdir_file.exists():
            return None
        try:
            gitdir_target = gitdir_file.read_text().strip()
            # gitdir points to <worktree>/.git
            wt_git = Path(gitdir_target)
            if not wt_git.is_absolute():
                wt_git = (wt_gitdir / wt_git).resolve()
            # The worktree root is the parent of the .git file
            return str(wt_git.parent)
        except OSError as e:
            debug(f"Cannot read gitdir for {wt_gitdir.name}: {e}")
            return None

    def _find_git_root(self, cwd: str) -> Path | None:
        """Walk up from cwd to find the directory containing .git."""
        current = Path(cwd).resolve()
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        return None

    def _find_default_files(self, cwd: str) -> list[str]:
        """Find default context files (CLAUDE.md, README.md)."""
        found = []
        cwd_path = Path(cwd)

        for filename in DEFAULT_CONTEXT_FILES:
            file_path = cwd_path / filename
            if file_path.exists() and file_path.is_file():
                found.append(filename)

        return found

    def _read_context_files(
        self, cwd: str, filenames: list[str], debug: DebugFn
    ) -> dict[str, str]:
        """Read the contents of context files for quoting.

        Returns a mapping of filename to content for files that were
        successfully read. Content is truncated to MAX_QUOTE_LENGTH.
        """
        contents: dict[str, str] = {}
        cwd_path = Path(cwd)

        for filename in filenames:
            file_path = cwd_path / filename
            try:
                text = file_path.read_text()
                if len(text) > MAX_QUOTE_LENGTH:
                    text = text[:MAX_QUOTE_LENGTH] + "\n... [truncated]"
                contents[filename] = text
            except (OSError, UnicodeDecodeError) as e:
                debug(f"Cannot read {filename} for quoting: {e}")

        return contents

    def _extract_user_refs(
        self, transcript_path: str, cwd: str, debug: DebugFn
    ) -> list[str]:
        """Extract @references from all user messages in transcript.

        Preserves all @references regardless of whether the file exists on disk.
        The user's intent matters — files may have been renamed, deleted, or
        be on a different branch.
        """
        if not transcript_path:
            debug("No transcript path provided")
            return []

        refs: list[str] = []
        seen: set[str] = set()
        messages_parsed = 0

        try:
            with open(transcript_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError as e:
                        debug(f"Failed to parse transcript line: {e}")
                        continue

                    messages_parsed += 1
                    content = self._get_user_content(msg)
                    if content:
                        for ref in self._extract_mentions(content):
                            if ref not in seen:
                                refs.append(ref)
                                seen.add(ref)
        except FileNotFoundError:
            debug(f"Transcript file not found: {transcript_path}")
        except PermissionError:
            debug(f"Permission denied reading transcript: {transcript_path}")

        debug(f"Parsed {messages_parsed} messages, found {len(refs)} refs")
        return refs

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
        self,
        files: list[str],
        user_refs: list[str],
        git_context: dict[str, str] | None = None,
        file_contents: dict[str, str] | None = None,
    ) -> str:
        """Build a context reminder string.

        When file_contents is provided, files that have content are quoted
        inline instead of just listed by name.
        """
        parts = []

        if git_context:
            ctx = []
            if "branch" in git_context:
                ctx.append(f"Branch: {git_context['branch']}")
            if "worktree_path" in git_context:
                ctx.append(f"Worktree: {git_context['worktree_path']}")
            if ctx:
                parts.append(" | ".join(ctx))

        if files:
            file_contents = file_contents or {}
            quoted = [f for f in files if f in file_contents]
            unquoted = [f for f in files if f not in file_contents]

            if unquoted:
                parts.append("Context: " + ", ".join(unquoted))

            for filename in quoted:
                parts.append(f"\n--- {filename} ---\n{file_contents[filename]}")

        if user_refs:
            refs = ["@" + r for r in user_refs[:20]]
            parts.append("Refs: " + ", ".join(refs))

        return "\n".join(parts) if parts else ""
