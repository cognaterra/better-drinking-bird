"""Tests for hook implementations."""

import pytest

from drinkingbird.config import PreToolHookConfig
from drinkingbird.hooks.base import Decision, HookResult
from drinkingbird.hooks.pre_tool import PreToolHook


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
