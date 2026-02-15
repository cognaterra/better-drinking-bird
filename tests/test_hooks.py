"""Tests for hook implementations."""

import json
import os
import tempfile

import pytest

from drinkingbird.config import PreCompactHookConfig, PreToolHookConfig
from drinkingbird.hooks.base import Decision, HookResult
from drinkingbird.hooks.pre_compact import PreCompactHook
from drinkingbird.hooks.pre_tool import PreToolHook
from drinkingbird.hooks.stop import StopHook


class TestHookResult:
    """Tests for HookResult class."""

    def test_allow(self):
        """Test creating allow result."""
        result = HookResult.allow("Task complete")

        assert result.decision == Decision.ALLOW
        assert result.reason == "Task complete"

    def test_block(self):
        """Test creating block result."""
        result = HookResult.block("Get back to work", "Premature stop")

        assert result.decision == Decision.BLOCK
        assert result.message == "Get back to work"
        assert result.reason == "Premature stop"

    def test_kill(self):
        """Test creating kill result."""
        result = HookResult.kill("Agent is looping")

        assert result.decision == Decision.KILL
        assert result.reason == "Agent is looping"

    def test_with_context(self):
        """Test creating result with additional context."""
        result = HookResult.with_context("Remember to check docs/plan.md")

        assert result.decision == Decision.ALLOW
        assert result.additional_context == "Remember to check docs/plan.md"

    def test_to_dict_block(self):
        """Test converting block result to dict."""
        result = HookResult.block("Stop that", "Bad command")
        d = result.to_dict()

        assert d["decision"] == "block"
        assert d["reason"] == "Stop that"

    def test_to_dict_context(self):
        """Test converting context result to dict."""
        result = HookResult.with_context("Extra info")
        d = result.to_dict()

        assert "hookSpecificOutput" in d
        assert d["hookSpecificOutput"]["additionalContext"] == "Extra info"

    def test_to_dict_allow_empty(self):
        """Test that simple allow returns empty dict."""
        result = HookResult.allow()
        d = result.to_dict()

        assert d == {}


class TestPreToolHook:
    """Tests for PreToolHook."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = PreToolHookConfig(
            enabled=True,
            categories={
                "ci_bypass": True,
                "destructive_git": True,
                "branch_switching": True,
                "interactive_git": True,
                "dangerous_files": True,
                "git_history": True,
                "credential_access": True,
            },
        )
        self.hook = PreToolHook(config=self.config)
        self.debug_messages = []

    def debug(self, msg):
        """Capture debug messages."""
        self.debug_messages.append(msg)

    def test_non_bash_allowed(self):
        """Test that non-Bash tools are allowed."""
        result = self.hook.handle(
            {"tool_name": "Read", "tool_input": {"path": "/etc/passwd"}},
            self.debug,
        )

        assert result.decision == Decision.ALLOW

    def test_safe_command_allowed(self):
        """Test that safe commands are allowed."""
        result = self.hook.handle(
            {"tool_name": "Bash", "tool_input": {"command": "git status"}},
            self.debug,
        )

        assert result.decision == Decision.ALLOW

    def test_dangerous_command_blocked(self):
        """Test that dangerous commands are blocked."""
        result = self.hook.handle(
            {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}},
            self.debug,
        )

        assert result.decision == Decision.BLOCK
        assert "destroys work" in result.message.lower()

    def test_ci_bypass_blocked(self):
        """Test that CI bypass is blocked."""
        result = self.hook.handle(
            {"tool_name": "Bash", "tool_input": {"command": "git commit --no-verify -m 'test'"}},
            self.debug,
        )

        assert result.decision == Decision.BLOCK
        assert "pre-commit" in result.message.lower() or "bypass" in result.message.lower()

    def test_branch_switch_blocked(self):
        """Test that branch switching is blocked."""
        result = self.hook.handle(
            {"tool_name": "Bash", "tool_input": {"command": "git checkout main"}},
            self.debug,
        )

        assert result.decision == Decision.BLOCK
        assert "worktree" in result.message.lower() or "branch" in result.message.lower()

    def test_disabled_category_allowed(self):
        """Test that disabled categories allow commands."""
        self.config.categories["destructive_git"] = False
        hook = PreToolHook(config=self.config)

        result = hook.handle(
            {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}},
            self.debug,
        )

        assert result.decision == Decision.ALLOW

    def test_allowed_git_log_oneline(self):
        """Test that brief git log is allowed."""
        result = self.hook.handle(
            {"tool_name": "Bash", "tool_input": {"command": "git log --oneline -5"}},
            self.debug,
        )

        assert result.decision == Decision.ALLOW

    @pytest.mark.parametrize("tool_name,tool_input", [
        ("Read", {"file_path": ".git/hooks/pre-commit"}),
        ("Read", {"file_path": "/Users/me/project/.git/hooks/pre-commit"}),
        ("Write", {"file_path": "scripts/pre-commit", "content": "#!/bin/bash"}),
        ("Edit", {"file_path": ".pre-commit-config.yaml", "old_string": "x", "new_string": "y"}),
        ("Glob", {"pattern": "**/*", "path": ".git/hooks/pre-commit"}),
        ("Grep", {"pattern": "threshold", "path": "scripts/pre-commit"}),
        ("Bash", {"command": "cat .git/hooks/pre-commit"}),
        ("Bash", {"command": "grep THRESHOLD scripts/pre-commit"}),
        ("Bash", {"command": "sed -i '' 's/90/80/' .git/hooks/pre-commit"}),
        ("Bash", {"command": "cp scripts/pre-commit .git/hooks/pre-commit"}),
        ("Bash", {"command": "head -10 /Users/me/Work/act/.git/hooks/pre-commit"}),
        ("Bash", {"command": "git add scripts/pre-commit"}),
        ("Bash", {"command": "chmod +x .git/hooks/pre-commit"}),
        ("Bash", {"command": "tail -50 .pre-commit-config.yaml"}),
        ("MultiEdit", {"file_path": "pre-commit", "edits": []}),
    ])
    def test_precommit_blocked_all_tools(self, tool_name, tool_input):
        """Test that ANY tool touching pre-commit files is blocked."""
        result = self.hook.handle(
            {"tool_name": tool_name, "tool_input": tool_input},
            self.debug,
        )

        assert result.decision == Decision.BLOCK, (
            f"{tool_name} with {tool_input} was not blocked"
        )

    def test_non_precommit_read_allowed(self):
        """Test that reading non-protected files is still allowed."""
        result = self.hook.handle(
            {"tool_name": "Read", "tool_input": {"file_path": "src/main.py"}},
            self.debug,
        )

        assert result.decision == Decision.ALLOW


class TestStopHook:
    """Tests for StopHook mention extraction."""

    def setup_method(self):
        """Set up test fixtures."""
        self.hook = StopHook(config=None)

    def test_extract_mentions_single(self):
        """Test extracting a single @ mention."""
        mentions = self.hook._extract_mentions("Check @src/main.py for issues")

        assert mentions == ["src/main.py"]

    def test_extract_mentions_multiple(self):
        """Test extracting multiple @ mentions."""
        mentions = self.hook._extract_mentions(
            "See @src/main.py and @tests/test_main.py"
        )

        assert mentions == ["src/main.py", "tests/test_main.py"]

    def test_extract_mentions_empty(self):
        """Test extracting from text with no mentions."""
        mentions = self.hook._extract_mentions("No mentions here")

        assert mentions == []

    def test_extract_mentions_none(self):
        """Test extracting from None returns empty list."""
        mentions = self.hook._extract_mentions(None)

        assert mentions == []

    def test_extract_all_user_messages_role_format(self):
        """Test extracting all user messages from role-based format."""
        messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Response"},
            {"role": "user", "content": "Second message"},
            {"role": "assistant", "content": "Another response"},
            {"role": "user", "content": "Third message"},
        ]

        result = self.hook._extract_all_user_messages(messages)

        assert result == ["First message", "Second message", "Third message"]

    def test_extract_all_user_messages_list_content(self):
        """Test extracting user messages with list content blocks."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Part 1"},
                    {"type": "text", "text": "Part 2"},
                ],
            },
            {"role": "user", "content": "Simple message"},
        ]

        result = self.hook._extract_all_user_messages(messages)

        assert result == ["Part 1\nPart 2", "Simple message"]

    def test_mentions_from_all_messages_deduplicated(self):
        """Test that mentions from multiple messages are deduplicated."""
        messages = [
            {"role": "user", "content": "Check @src/main.py"},
            {"role": "assistant", "content": "Done"},
            {"role": "user", "content": "Also @src/main.py and @src/utils.py"},
        ]

        all_user_messages = self.hook._extract_all_user_messages(messages)
        all_mentions = []
        seen = set()
        for user_msg in all_user_messages:
            for mention in self.hook._extract_mentions(user_msg):
                if mention not in seen:
                    all_mentions.append(mention)
                    seen.add(mention)

        # src/main.py appears twice but should only be collected once
        assert all_mentions == ["src/main.py", "src/utils.py"]

    def test_build_user_prompt_renders_at_prefix(self):
        """Test that file paths are rendered with @ prefix."""
        files = {"src/main.py": "print('hello')"}

        prompt = self.hook._build_user_prompt(
            first_user="Check the file",
            last_user=None,
            last_assistant=None,
            files=files,
        )

        assert "--- @src/main.py ---" in prompt

    def test_build_user_prompt_multiple_files(self):
        """Test rendering multiple files with @ prefix."""
        files = {
            "src/main.py": "main code",
            "src/utils.py": "utils code",
        }

        prompt = self.hook._build_user_prompt(
            first_user="Check files",
            last_user=None,
            last_assistant=None,
            files=files,
        )

        assert "--- @src/main.py ---" in prompt
        assert "--- @src/utils.py ---" in prompt

    def test_extract_all_user_messages_claude_code_format(self):
        """Test extracting user messages from Claude Code transcript format.

        Claude Code uses: type="user", message={role: "user", content: "..."}
        This is the format that was failing before the fix.
        """
        messages = [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "complete execution of @docs/plan.md",
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Working on it"}],
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "Check @src/main.py too",
                },
            },
        ]

        result = self.hook._extract_all_user_messages(messages)

        assert len(result) == 2
        assert result[0] == "complete execution of @docs/plan.md"
        assert result[1] == "Check @src/main.py too"

        # Verify @-mentions are extractable from these messages
        all_mentions = []
        seen = set()
        for user_msg in result:
            for mention in self.hook._extract_mentions(user_msg):
                if mention not in seen:
                    all_mentions.append(mention)
                    seen.add(mention)

        assert all_mentions == ["docs/plan.md", "src/main.py"]

    def test_extract_all_user_messages_claude_code_list_content(self):
        """Test Claude Code format with list content blocks."""
        messages = [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Check @file1.py"},
                        {"type": "text", "text": "and @file2.py"},
                    ],
                },
            },
        ]

        result = self.hook._extract_all_user_messages(messages)

        assert len(result) == 1
        assert "Check @file1.py" in result[0]
        assert "and @file2.py" in result[0]

    def test_no_assistant_text_blocks(self):
        """Test that stop is blocked when no assistant text can be extracted.

        When the last assistant message is all tool_use blocks with no text,
        extracted text is empty. No text = no evidence of completion = BLOCK.
        """
        from unittest.mock import Mock
        from drinkingbird.config import StopHookConfig

        mock_llm = Mock()
        mock_llm.is_configured.return_value = True

        config = StopHookConfig()
        hook = StopHook(config=config, llm_provider=mock_llm)

        # Write a transcript where the last assistant message has no text content
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            # User message
            f.write(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": "execute the plan @docs/plan.md"},
            }) + "\n")
            # Assistant message with only tool_use blocks (no text)
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "1", "name": "Bash",
                         "input": {"command": "cargo test"}},
                    ],
                },
            }) + "\n")
            transcript_path = f.name

        try:
            hook_input = {
                "transcript_path": transcript_path,
                "cwd": "/tmp",
            }

            debug_messages = []
            result = hook.handle(hook_input, lambda msg: debug_messages.append(msg))

            assert result.decision == Decision.BLOCK
            # LLM should NOT have been called — blocked before reaching it
            mock_llm.call.assert_not_called()
            debug_text = " ".join(debug_messages)
            assert "no completion evidence" in debug_text.lower()
        finally:
            os.unlink(transcript_path)

    def test_stop_hook_active_flag_ignored(self):
        """Test that stop_hook_active flag is ignored.

        Every stop request should be evaluated independently. The flag should
        not cause the hook to bypass evaluation and auto-allow.
        """
        from unittest.mock import Mock
        from drinkingbird.config import StopHookConfig

        # Create a hook with a mock LLM that would normally evaluate
        mock_llm = Mock()
        mock_llm.is_configured.return_value = False

        config = StopHookConfig()
        hook = StopHook(config=config, llm_provider=mock_llm)

        # Create hook input with the flag set
        hook_input = {
            "stop_hook_active": True,
            "transcript_path": "",
            "cwd": "/tmp",
        }

        debug_messages = []
        def debug(msg):
            debug_messages.append(msg)

        # Call the hook
        result = hook.handle(hook_input, debug)

        # The hook should NOT bypass evaluation due to the flag
        # Default behavior is BLOCK - keep the agent working
        assert result.decision == Decision.BLOCK
        assert "Great work! Keep going." in result.reason

        # Verify the flag was NOT checked (no "stop_hook_active=true" in debug)
        debug_text = " ".join(debug_messages)
        assert "stop_hook_active" not in debug_text.lower()


class TestPreCompactHookGitContext:
    """Tests for PreCompactHook git context injection."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = PreCompactHookConfig(enabled=True, inject_git_context=True)
        self.hook = PreCompactHook(config=self.config)
        self.debug_messages = []

    def debug(self, msg):
        """Capture debug messages."""
        self.debug_messages.append(msg)

    def _make_git_repo(self, tmpdir, branch="feature/my-branch"):
        """Create a minimal git repo structure in tmpdir."""
        git_dir = os.path.join(tmpdir, ".git")
        os.makedirs(git_dir, exist_ok=True)
        with open(os.path.join(git_dir, "HEAD"), "w") as f:
            f.write(f"ref: refs/heads/{branch}\n")
        return tmpdir

    def _make_worktree(self, tmpdir, main_repo_git, branch="feature/wt-branch"):
        """Create a linked worktree structure in tmpdir.

        Args:
            tmpdir: Path for the worktree root.
            main_repo_git: Path to the main repo's .git directory.
            branch: Branch name for the worktree HEAD.
        """
        # Create the worktree's gitdir inside the main repo
        wt_name = os.path.basename(tmpdir)
        wt_gitdir = os.path.join(main_repo_git, "worktrees", wt_name)
        os.makedirs(wt_gitdir, exist_ok=True)

        # Write HEAD in the worktree gitdir
        with open(os.path.join(wt_gitdir, "HEAD"), "w") as f:
            f.write(f"ref: refs/heads/{branch}\n")

        # Write gitdir file pointing back to the worktree's .git file
        with open(os.path.join(wt_gitdir, "gitdir"), "w") as f:
            f.write(f"{os.path.join(tmpdir, '.git')}\n")

        # Write .git file in the worktree root pointing to the gitdir
        with open(os.path.join(tmpdir, ".git"), "w") as f:
            f.write(f"gitdir: {wt_gitdir}\n")

        return tmpdir

    def test_normal_repo_branch_detected(self):
        """Test branch detection in a normal git repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_git_repo(tmpdir, branch="main")

            result = self.hook._get_git_context(tmpdir, "", self.debug)

            assert result["branch"] == "main"
            assert "worktree_path" not in result

    def test_feature_branch_detected(self):
        """Test detection of a feature branch name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_git_repo(tmpdir, branch="feature/add-auth")

            result = self.hook._get_git_context(tmpdir, "", self.debug)

            assert result["branch"] == "feature/add-auth"

    def test_detached_head(self):
        """Test detached HEAD shows abbreviated hash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = os.path.join(tmpdir, ".git")
            os.makedirs(git_dir, exist_ok=True)
            with open(os.path.join(git_dir, "HEAD"), "w") as f:
                f.write("abc1234567890def\n")

            result = self.hook._get_git_context(tmpdir, "", self.debug)

            assert result["branch"] == "(detached at abc12345)"

    def test_worktree_detected(self):
        """Test worktree path and branch are detected for linked worktrees."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = os.path.realpath(tmpdir)
            # Create main repo
            main_repo = os.path.join(tmpdir, "main-repo")
            os.makedirs(main_repo)
            self._make_git_repo(main_repo, branch="main")

            # Create worktree
            wt_dir = os.path.join(tmpdir, "my-worktree")
            os.makedirs(wt_dir)
            self._make_worktree(
                wt_dir,
                os.path.join(main_repo, ".git"),
                branch="feature/wt-work",
            )

            result = self.hook._get_git_context(wt_dir, "", self.debug)

            assert result["branch"] == "feature/wt-work"
            assert result["worktree_path"] == wt_dir

    def test_worktree_with_relative_gitdir(self):
        """Test worktree with a relative gitdir path in .git file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = os.path.realpath(tmpdir)
            # Create main repo
            main_repo = os.path.join(tmpdir, "main-repo")
            os.makedirs(main_repo)
            self._make_git_repo(main_repo, branch="main")

            # Create worktree with relative gitdir
            wt_dir = os.path.join(tmpdir, "my-worktree")
            os.makedirs(wt_dir)

            wt_name = "my-worktree"
            wt_gitdir = os.path.join(main_repo, ".git", "worktrees", wt_name)
            os.makedirs(wt_gitdir, exist_ok=True)
            with open(os.path.join(wt_gitdir, "HEAD"), "w") as f:
                f.write("ref: refs/heads/feature/relative\n")

            # Write .git file with relative path
            rel_gitdir = os.path.relpath(wt_gitdir, wt_dir)
            with open(os.path.join(wt_dir, ".git"), "w") as f:
                f.write(f"gitdir: {rel_gitdir}\n")

            result = self.hook._get_git_context(wt_dir, "", self.debug)

            assert result["branch"] == "feature/relative"
            assert result["worktree_path"] == wt_dir

    def test_not_in_git_repo(self):
        """Test graceful handling when not in a git repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.hook._get_git_context(tmpdir, "", self.debug)

            assert result == {}

    def test_disabled_inject_git_context(self):
        """Test that git context is skipped when inject_git_context is False."""
        config = PreCompactHookConfig(enabled=True, inject_git_context=False)
        hook = PreCompactHook(config=config)

        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_git_repo(tmpdir, branch="main")

            result = hook.handle(
                {"cwd": tmpdir, "transcript_path": ""},
                self.debug,
            )

            # Should still work but without git context in the output
            assert "Branch:" not in result.additional_context

    def test_git_context_in_reminder_output(self):
        """Test that git context appears in the context reminder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_git_repo(tmpdir, branch="feature/cool-stuff")
            with open(os.path.join(tmpdir, "CLAUDE.md"), "w") as f:
                f.write("# Project\n")

            result = self.hook.handle(
                {"cwd": tmpdir, "transcript_path": ""},
                self.debug,
            )

            assert result.decision == Decision.ALLOW
            assert "Branch: feature/cool-stuff" in result.additional_context

    def test_git_context_only_produces_output(self):
        """Test that git context alone (no files/refs) still produces output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_git_repo(tmpdir, branch="fix/something")

            result = self.hook.handle(
                {"cwd": tmpdir, "transcript_path": ""},
                self.debug,
            )

            assert result.decision == Decision.ALLOW
            assert "Branch: fix/something" in result.additional_context

    def test_worktree_context_in_reminder_output(self):
        """Test that worktree path appears in the context reminder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = os.path.realpath(tmpdir)
            main_repo = os.path.join(tmpdir, "main-repo")
            os.makedirs(main_repo)
            self._make_git_repo(main_repo, branch="main")

            wt_dir = os.path.join(tmpdir, "wt")
            os.makedirs(wt_dir)
            self._make_worktree(
                wt_dir,
                os.path.join(main_repo, ".git"),
                branch="feature/wt-test",
            )

            result = self.hook.handle(
                {"cwd": wt_dir, "transcript_path": ""},
                self.debug,
            )

            assert "Branch: feature/wt-test" in result.additional_context
            assert f"Worktree: {wt_dir}" in result.additional_context

    def test_git_context_appears_before_files(self):
        """Test that git context line appears before file context."""
        config = PreCompactHookConfig(
            enabled=True, inject_git_context=True, quote_context_files=False
        )
        hook = PreCompactHook(config=config)

        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_git_repo(tmpdir, branch="develop")
            with open(os.path.join(tmpdir, "CLAUDE.md"), "w") as f:
                f.write("# Project\n")

            result = hook.handle(
                {"cwd": tmpdir, "transcript_path": ""},
                self.debug,
            )

            ctx = result.additional_context
            git_pos = ctx.index("Branch:")
            files_pos = ctx.index("Context:")
            assert git_pos < files_pos

    def test_git_context_appears_before_quoted_files(self):
        """Test that git context line appears before quoted file content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_git_repo(tmpdir, branch="develop")
            with open(os.path.join(tmpdir, "CLAUDE.md"), "w") as f:
                f.write("# Project\n")

            result = self.hook.handle(
                {"cwd": tmpdir, "transcript_path": ""},
                self.debug,
            )

            ctx = result.additional_context
            git_pos = ctx.index("Branch:")
            files_pos = ctx.index("--- CLAUDE.md ---")
            assert git_pos < files_pos

    def test_quote_context_files_enabled_by_default(self):
        """Test that context file contents are quoted when option is enabled (default)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_git_repo(tmpdir, branch="main")
            with open(os.path.join(tmpdir, "CLAUDE.md"), "w") as f:
                f.write("# Project Rules\nAlways run tests.\n")

            result = self.hook.handle(
                {"cwd": tmpdir, "transcript_path": ""},
                self.debug,
            )

            assert result.decision == Decision.ALLOW
            assert "--- CLAUDE.md ---" in result.additional_context
            assert "# Project Rules" in result.additional_context
            assert "Always run tests." in result.additional_context

    def test_quote_context_files_disabled(self):
        """Test that files are listed by name only when quoting is disabled."""
        config = PreCompactHookConfig(
            enabled=True, inject_git_context=True, quote_context_files=False
        )
        hook = PreCompactHook(config=config)

        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_git_repo(tmpdir, branch="main")
            with open(os.path.join(tmpdir, "CLAUDE.md"), "w") as f:
                f.write("# Project Rules\nAlways run tests.\n")

            result = hook.handle(
                {"cwd": tmpdir, "transcript_path": ""},
                self.debug,
            )

            assert result.decision == Decision.ALLOW
            assert "Context: CLAUDE.md" in result.additional_context
            assert "--- CLAUDE.md ---" not in result.additional_context
            assert "# Project Rules" not in result.additional_context

    def test_quote_agents_md(self):
        """Test that AGENTS.md is quoted when present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_git_repo(tmpdir, branch="main")
            with open(os.path.join(tmpdir, "AGENTS.md"), "w") as f:
                f.write("# Agent Guidelines\nStay focused.\n")

            result = self.hook.handle(
                {"cwd": tmpdir, "transcript_path": ""},
                self.debug,
            )

            assert "--- AGENTS.md ---" in result.additional_context
            assert "# Agent Guidelines" in result.additional_context

    def test_quote_truncates_large_files(self):
        """Test that quoted files are truncated at MAX_QUOTE_LENGTH."""
        from drinkingbird.hooks.pre_compact import MAX_QUOTE_LENGTH

        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_git_repo(tmpdir, branch="main")
            with open(os.path.join(tmpdir, "CLAUDE.md"), "w") as f:
                f.write("x" * (MAX_QUOTE_LENGTH + 500))

            result = self.hook.handle(
                {"cwd": tmpdir, "transcript_path": ""},
                self.debug,
            )

            assert "... [truncated]" in result.additional_context

    def test_build_context_reminder_no_git_context(self):
        """Test _build_context_reminder with no git context."""
        result = self.hook._build_context_reminder(
            files=["CLAUDE.md"],
            user_refs=[],
            git_context={},
        )

        assert "Branch:" not in result
        assert "CLAUDE.md" in result

    def test_build_context_reminder_branch_only(self):
        """Test _build_context_reminder with only branch (no worktree)."""
        result = self.hook._build_context_reminder(
            files=[],
            user_refs=[],
            git_context={"branch": "main"},
        )

        assert "Branch: main" in result
        assert "Worktree:" not in result

    def test_build_context_reminder_branch_and_worktree(self):
        """Test _build_context_reminder with branch and worktree."""
        result = self.hook._build_context_reminder(
            files=[],
            user_refs=[],
            git_context={"branch": "feature/x", "worktree_path": "/tmp/wt"},
        )

        assert "Branch: feature/x" in result
        assert "Worktree: /tmp/wt" in result

    def test_subdirectory_finds_git_root(self):
        """Test that git root is found from a subdirectory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_git_repo(tmpdir, branch="feature/deep")
            subdir = os.path.join(tmpdir, "src", "deep", "path")
            os.makedirs(subdir)

            result = self.hook._get_git_context(subdir, "", self.debug)

            assert result["branch"] == "feature/deep"

    def _make_transcript(self, tmpdir, lines):
        """Write a JSONL transcript file and return its path."""
        path = os.path.join(tmpdir, "transcript.jsonl")
        with open(path, "w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
        return path

    def test_worktree_discovered_from_transcript_cd(self):
        """Test worktree detected when cwd is main repo but transcript has cd into worktree."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = os.path.realpath(tmpdir)
            main_repo = os.path.join(tmpdir, "main-repo")
            os.makedirs(main_repo)
            self._make_git_repo(main_repo, branch="main")

            wt_dir = os.path.join(tmpdir, "my-feature")
            os.makedirs(wt_dir)
            self._make_worktree(
                wt_dir,
                os.path.join(main_repo, ".git"),
                branch="feature/cool",
            )

            transcript = self._make_transcript(tmpdir, [
                {"role": "user", "content": "work in the my-feature worktree"},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "Bash",
                     "input": {"command": f"cd {wt_dir}"}},
                ]},
            ])

            result = self.hook._get_git_context(main_repo, transcript, self.debug)

            assert result["branch"] == "feature/cool"
            assert result["worktree_path"] == wt_dir

    def test_worktree_discovered_from_transcript_file_edit(self):
        """Test worktree detected from file edit paths in transcript."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = os.path.realpath(tmpdir)
            main_repo = os.path.join(tmpdir, "main-repo")
            os.makedirs(main_repo)
            self._make_git_repo(main_repo, branch="main")

            wt_dir = os.path.join(tmpdir, "bugfix-auth")
            os.makedirs(wt_dir)
            self._make_worktree(
                wt_dir,
                os.path.join(main_repo, ".git"),
                branch="fix/auth-flow",
            )

            transcript = self._make_transcript(tmpdir, [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "Edit",
                     "input": {"file_path": f"{wt_dir}/src/auth.py",
                               "old_string": "x", "new_string": "y"}},
                ]},
            ])

            result = self.hook._get_git_context(main_repo, transcript, self.debug)

            assert result["branch"] == "fix/auth-flow"
            assert result["worktree_path"] == wt_dir

    def test_worktree_discovered_from_transcript_worktree_add(self):
        """Test worktree detected when agent created it via git worktree add."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = os.path.realpath(tmpdir)
            main_repo = os.path.join(tmpdir, "main-repo")
            os.makedirs(main_repo)
            self._make_git_repo(main_repo, branch="main")

            wt_dir = os.path.join(tmpdir, "new-feature")
            os.makedirs(wt_dir)
            self._make_worktree(
                wt_dir,
                os.path.join(main_repo, ".git"),
                branch="feature/new-thing",
            )

            transcript = self._make_transcript(tmpdir, [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "Bash",
                     "input": {"command": "git worktree add ../new-feature feature/new-thing"}},
                ]},
            ])

            result = self.hook._get_git_context(main_repo, transcript, self.debug)

            assert result["branch"] == "feature/new-thing"
            assert result["worktree_path"] == wt_dir

    def test_worktree_no_match_falls_back_to_main(self):
        """Test that main repo context is used when no worktree matches transcript."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = os.path.realpath(tmpdir)
            main_repo = os.path.join(tmpdir, "main-repo")
            os.makedirs(main_repo)
            self._make_git_repo(main_repo, branch="main")

            wt_dir = os.path.join(tmpdir, "some-worktree")
            os.makedirs(wt_dir)
            self._make_worktree(
                wt_dir,
                os.path.join(main_repo, ".git"),
                branch="feature/other",
            )

            # Transcript mentions nothing about the worktree
            transcript = self._make_transcript(tmpdir, [
                {"role": "user", "content": "fix the bug in main"},
            ])

            result = self.hook._get_git_context(main_repo, transcript, self.debug)

            assert result["branch"] == "main"
            assert "worktree_path" not in result

    def test_worktree_ambiguous_match_omits_branch(self):
        """Test that ambiguous worktree matches omit branch info entirely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = os.path.realpath(tmpdir)
            main_repo = os.path.join(tmpdir, "main-repo")
            os.makedirs(main_repo)
            self._make_git_repo(main_repo, branch="main")

            # Create two worktrees
            wt1 = os.path.join(tmpdir, "wt-alpha")
            os.makedirs(wt1)
            self._make_worktree(wt1, os.path.join(main_repo, ".git"), branch="feature/a")

            wt2 = os.path.join(tmpdir, "wt-beta")
            os.makedirs(wt2)
            self._make_worktree(wt2, os.path.join(main_repo, ".git"), branch="feature/b")

            # Transcript mentions both worktrees
            transcript = self._make_transcript(tmpdir, [
                {"role": "user", "content": f"compare {wt1} and {wt2}"},
            ])

            result = self.hook._get_git_context(main_repo, transcript, self.debug)

            assert result == {}
            assert "branch" not in result
            assert "worktree_path" not in result

    def test_worktree_no_transcript_falls_back_to_main(self):
        """Test that missing transcript falls back to main repo context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = os.path.realpath(tmpdir)
            main_repo = os.path.join(tmpdir, "main-repo")
            os.makedirs(main_repo)
            self._make_git_repo(main_repo, branch="main")

            wt_dir = os.path.join(tmpdir, "my-wt")
            os.makedirs(wt_dir)
            self._make_worktree(wt_dir, os.path.join(main_repo, ".git"), branch="feature/x")

            result = self.hook._get_git_context(main_repo, "", self.debug)

            assert result["branch"] == "main"
            assert "worktree_path" not in result

    def test_worktree_from_main_repo_via_handle(self):
        """Test full handle() flow when cwd is main repo but agent works in worktree."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = os.path.realpath(tmpdir)
            main_repo = os.path.join(tmpdir, "main-repo")
            os.makedirs(main_repo)
            self._make_git_repo(main_repo, branch="main")

            wt_dir = os.path.join(tmpdir, "impl-feature")
            os.makedirs(wt_dir)
            self._make_worktree(
                wt_dir,
                os.path.join(main_repo, ".git"),
                branch="feature/impl",
            )

            # Put a CLAUDE.md in main repo (that's where cwd is)
            with open(os.path.join(main_repo, "CLAUDE.md"), "w") as f:
                f.write("# Rules\n")

            transcript = self._make_transcript(tmpdir, [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "Bash",
                     "input": {"command": f"cd {wt_dir} && cargo test"}},
                ]},
            ])

            result = self.hook.handle(
                {"cwd": main_repo, "transcript_path": transcript},
                self.debug,
            )

            assert "Branch: feature/impl" in result.additional_context
            assert f"Worktree: {wt_dir}" in result.additional_context

