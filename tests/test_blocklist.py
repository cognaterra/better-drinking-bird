"""Tests for user-configured blocklists."""

import os
from pathlib import Path

import pytest

from drinkingbird.config import BlocklistEntry, Config, load_config


class TestBlocklistEntry:
    """Tests for BlocklistEntry dataclass."""

    def test_create_basic_entry(self):
        """Test creating a blocklist entry."""
        entry = BlocklistEntry(
            pattern=r"secret",
            reason="Blocked secret access",
        )
        assert entry.pattern == r"secret"
        assert entry.reason == "Blocked secret access"
        assert entry.tools == ["*"]

    def test_create_entry_with_tools(self):
        """Test creating entry with specific tools."""
        entry = BlocklistEntry(
            pattern=r"\.env",
            reason="No env files",
            tools=["Read", "Bash"],
        )
        assert entry.tools == ["Read", "Bash"]


class TestBlocklistConfig:
    """Tests for blocklist in config loading."""

    def test_empty_blocklist_default(self):
        """Test that default config has empty blocklist."""
        config = Config()
        assert config.blocklist == []

    def test_load_blocklist_from_yaml(self, tmp_path):
        """Test loading blocklist from config file."""
        config_content = """
blocklist:
  - pattern: "secret"
    reason: "No secrets"
  - pattern: '\\.env'
    reason: "No env files"
    tools: ["Read"]
"""
        config_file = tmp_path / ".bdbrc"
        config_file.write_text(config_content)
        os.chmod(config_file, 0o600)

        config = load_config(config_file)

        assert len(config.blocklist) == 2
        assert config.blocklist[0].pattern == "secret"
        assert config.blocklist[0].tools == ["*"]
        assert config.blocklist[1].tools == ["Read"]


class TestCheckUserBlocklist:
    """Tests for check_user_blocklist function."""

    def test_empty_blocklist_allows(self):
        """Test that empty blocklist allows everything."""
        from drinkingbird.safety.blocklist import check_user_blocklist

        is_blocked, reason = check_user_blocklist(
            tool_name="Bash",
            tool_input={"command": "rm -rf /"},
            blocklist=[],
        )
        assert is_blocked is False
        assert reason == ""

    def test_pattern_match_blocks(self):
        """Test that matching pattern blocks."""
        from drinkingbird.safety.blocklist import check_user_blocklist

        blocklist = [
            BlocklistEntry(pattern=r"secret", reason="No secrets"),
        ]
        is_blocked, reason = check_user_blocklist(
            tool_name="Read",
            tool_input={"file_path": "/path/to/secret.txt"},
            blocklist=blocklist,
        )
        assert is_blocked is True
        assert reason == "No secrets"

    def test_pattern_no_match_allows(self):
        """Test that non-matching pattern allows."""
        from drinkingbird.safety.blocklist import check_user_blocklist

        blocklist = [
            BlocklistEntry(pattern=r"secret", reason="No secrets"),
        ]
        is_blocked, reason = check_user_blocklist(
            tool_name="Read",
            tool_input={"file_path": "/path/to/readme.txt"},
            blocklist=blocklist,
        )
        assert is_blocked is False

    def test_tool_filter_specific(self):
        """Test that tool filter works."""
        from drinkingbird.safety.blocklist import check_user_blocklist

        blocklist = [
            BlocklistEntry(pattern=r"secret", reason="No secrets", tools=["Read"]),
        ]
        # Should block Read
        is_blocked, _ = check_user_blocklist(
            tool_name="Read",
            tool_input={"file_path": "secret.txt"},
            blocklist=blocklist,
        )
        assert is_blocked is True

        # Should allow Bash (not in tools list)
        is_blocked, _ = check_user_blocklist(
            tool_name="Bash",
            tool_input={"command": "cat secret.txt"},
            blocklist=blocklist,
        )
        assert is_blocked is False

    def test_wildcard_tool_matches_all(self):
        """Test that wildcard tool matches all tools."""
        from drinkingbird.safety.blocklist import check_user_blocklist

        blocklist = [
            BlocklistEntry(pattern=r"secret", reason="No secrets", tools=["*"]),
        ]
        for tool in ["Read", "Bash", "Write", "Edit"]:
            is_blocked, _ = check_user_blocklist(
                tool_name=tool,
                tool_input={"content": "secret"},
                blocklist=blocklist,
            )
            assert is_blocked is True

    def test_case_insensitive(self):
        """Test that pattern matching is case insensitive."""
        from drinkingbird.safety.blocklist import check_user_blocklist

        blocklist = [
            BlocklistEntry(pattern=r"SECRET", reason="No secrets"),
        ]
        is_blocked, _ = check_user_blocklist(
            tool_name="Read",
            tool_input={"file_path": "secret.txt"},
            blocklist=blocklist,
        )
        assert is_blocked is True

    def test_first_match_wins(self):
        """Test that first matching pattern's reason is returned."""
        from drinkingbird.safety.blocklist import check_user_blocklist

        blocklist = [
            BlocklistEntry(pattern=r"secret", reason="First reason"),
            BlocklistEntry(pattern=r"secret", reason="Second reason"),
        ]
        is_blocked, reason = check_user_blocklist(
            tool_name="Read",
            tool_input={"file_path": "secret.txt"},
            blocklist=blocklist,
        )
        assert is_blocked is True
        assert reason == "First reason"
