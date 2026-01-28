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
