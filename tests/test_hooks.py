"""Tests for hook implementations."""

import pytest

from drinkingbird.config import PreToolHookConfig
from drinkingbird.hooks.base import Decision, HookResult
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

    def test_extract_all_user_messages_human_format(self):
        """Test extracting all user messages from human/type format."""
        messages = [
            {"type": "human", "message": "First message"},
            {"type": "assistant", "message": "Response"},
            {"type": "human", "message": "Second message"},
        ]

        result = self.hook._extract_all_user_messages(messages)

        assert result == ["First message", "Second message"]

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

