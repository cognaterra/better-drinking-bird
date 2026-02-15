"""Tests for safety patterns."""

import pytest

from drinkingbird.safety.patterns import (
    SAFETY_CATEGORIES,
    check_command,
    get_enabled_patterns,
)


class TestCheckCommand:
    """Tests for check_command function."""

    @pytest.mark.parametrize("command,should_block", [
        # CI bypass - should block
        ("git commit --no-verify -m 'test'", True),
        ("HUSKY=0 git commit", True),
        ("git push --skip-hooks", True),

        # Destructive git - should block
        ("git reset --hard HEAD~1", True),
        ("git clean -f", True),
        ("git checkout .", True),
        ("git co .", True),
        ("git restore .", True),
        ("git push --force", True),
        ("git push -f origin main", True),
        ("git branch -D feature", True),

        # Branch switching - should block (ALL branch switches corrupt worktrees)
        ("git checkout main", True),
        ("git checkout master", True),
        ("git checkout develop", True),
        ("git checkout feature/other-branch", True),
        ("git checkout some-branch", True),
        ("git checkout origin/main", True),
        ("git checkout origin/feature/foo", True),
        ("git checkout -b new-branch", True),
        ("git checkout -B new-branch", True),
        ("git checkout -", True),
        ("git switch main", True),
        ("git switch feature/other-branch", True),
        ("git switch -", True),
        ("git switch --detach HEAD", True),

        # Git aliases - must also be blocked
        ("git co main", True),
        ("git co master", True),
        ("git co feature/other-branch", True),
        ("git co origin/main", True),
        ("git co -b new-branch", True),
        ("git co -", True),
        ("git sw main", True),
        ("git sw feature/other-branch", True),
        ("git sw -", True),

        # Checkout files from another ref with -- . (destroys worktree)
        ("git checkout main -- .", True),
        ("git co main -- .", True),
        ("git checkout origin/main -- .", True),
        ("git co origin/main -- .", True),

        # Branch creation via switch -c/-C is allowed (safe in worktrees)
        ("git switch -c new-branch", False),
        ("git switch -C new-branch", False),
        ("git switch --create new-branch", False),
        ("git sw -c new-branch", False),
        ("git sw -C new-branch", False),

        # Interactive git - should block
        ("git rebase -i HEAD~3", True),
        ("git add -i", True),
        ("git add -p", True),

        # Dangerous files - should block
        ("rm -rf /", True),
        ("rm -rf ~", True),
        ("rm -rf *", True),

        # Git history - should block
        ("git log", True),
        ("git log -p", True),
        ("git log HEAD~5..HEAD", True),
        ("git blame src/main.py", True),

        # Credential access - should block
        ("cat .env", True),
        ("cat ~/.ssh/id_rsa", True),
        ("cat credentials.json", True),

        # Allowed git commands
        ("git status", False),
        ("git diff", False),
        ("git log --oneline -5", False),
        ("git log --oneline HEAD..origin/main", False),
        ("git log --oneline main..HEAD", False),

        # File restore with -- is allowed (not a branch switch)
        ("git checkout -- file.py", False),
        ("git checkout --ours file.py", False),
        ("git checkout --theirs file.py", False),
        ("git co -- file.py", False),
        ("git co --ours file.py", False),
        ("git co --theirs file.py", False),
        # Single file restore from ref with -- is allowed
        ("git checkout HEAD -- file.py", False),
        ("git co HEAD -- file.py", False),
        ("git checkout origin/main -- crates/foo.rs", False),

        # Normal commands
        ("ls -la", False),
        ("npm install", False),
        ("python script.py", False),
        ("git add file.py", False),
        ("git commit -m 'message'", False),
        ("git push origin feature", False),
    ])
    def test_command_blocking(self, command, should_block):
        """Test that commands are blocked/allowed correctly."""
        is_blocked, reason = check_command(command)

        assert is_blocked == should_block, f"Command '{command}' block={is_blocked}, expected={should_block}"
        if should_block:
            assert reason != "", f"Blocked command should have a reason"

    def test_category_disable(self):
        """Test that disabled categories don't block."""
        # With all categories enabled
        is_blocked, _ = check_command("git reset --hard")
        assert is_blocked is True

        # With destructive_git disabled
        is_blocked, _ = check_command(
            "git reset --hard",
            enabled_categories={"destructive_git": False},
        )
        assert is_blocked is False

    def test_partial_categories(self):
        """Test with only some categories enabled."""
        categories = {
            "ci_bypass": True,
            "destructive_git": False,
            "branch_switching": False,
            "interactive_git": False,
            "dangerous_files": False,
            "git_history": False,
            "credential_access": False,
        }

        # CI bypass should still block
        is_blocked, _ = check_command("git commit --no-verify", categories)
        assert is_blocked is True

        # Destructive git should not block
        is_blocked, _ = check_command("git reset --hard", categories)
        assert is_blocked is False


class TestGetEnabledPatterns:
    """Tests for get_enabled_patterns function."""

    def test_all_enabled(self):
        """Test getting all patterns when all categories enabled."""
        all_enabled = {cat: True for cat in SAFETY_CATEGORIES}
        patterns = get_enabled_patterns(all_enabled)

        # Should have patterns from all categories
        total = sum(len(p) for p in SAFETY_CATEGORIES.values())
        assert len(patterns) == total

    def test_none_enabled(self):
        """Test getting no patterns when all categories disabled."""
        all_disabled = {cat: False for cat in SAFETY_CATEGORIES}
        patterns = get_enabled_patterns(all_disabled)

        assert len(patterns) == 0

    def test_single_category(self):
        """Test getting patterns from single category."""
        single = {
            "ci_bypass": True,
            "destructive_git": False,
        }
        patterns = get_enabled_patterns(single)

        assert len(patterns) == len(SAFETY_CATEGORIES["ci_bypass"])
        for p in patterns:
            assert p.category == "ci_bypass"


class TestSafetyCategories:
    """Tests for SAFETY_CATEGORIES structure."""

    def test_all_patterns_have_required_fields(self):
        """Test that all patterns have pattern, reason, and category."""
        for category, patterns in SAFETY_CATEGORIES.items():
            for pattern in patterns:
                assert pattern.pattern, f"Pattern in {category} missing pattern"
                assert pattern.reason, f"Pattern in {category} missing reason"
                assert pattern.category == category, f"Pattern category mismatch in {category}"

    def test_expected_categories_exist(self):
        """Test that expected categories are defined."""
        expected = [
            "ci_bypass",
            "destructive_git",
            "branch_switching",
            "interactive_git",
            "dangerous_files",
            "git_history",
            "credential_access",
        ]

        for cat in expected:
            assert cat in SAFETY_CATEGORIES, f"Missing category: {cat}"
