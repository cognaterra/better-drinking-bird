"""Tests for user-configured blocklists."""

import pytest

from drinkingbird.config import BlocklistEntry


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
