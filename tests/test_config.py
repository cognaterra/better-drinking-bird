"""Tests for configuration loading and validation."""

import os
import stat
import tempfile
from pathlib import Path

import pytest
import yaml

from drinkingbird.config import (
    Config,
    ConfigError,
    check_permissions,
    generate_template,
    load_config,
    save_template,
)


class TestConfig:
    """Tests for Config dataclass."""

    def test_default_config(self):
        """Test that default config has expected values."""
        config = Config()

        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4o-mini"
        assert config.agent.type == "claude-code"
        assert config.agent.conversation_depth == 1
        assert config.hooks.stop.enabled is True
        assert config.hooks.pre_tool.enabled is True

    def test_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "llm": {
                "provider": "anthropic",
                "model": "claude-3-5-haiku",
            },
            "agent": {
                "conversation_depth": 2,
            },
        }

        config = Config.from_dict(data)

        assert config.llm.provider == "anthropic"
        assert config.llm.model == "claude-3-5-haiku"
        assert config.agent.conversation_depth == 2


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_nonexistent_returns_defaults(self):
        """Test that missing config file returns defaults."""
        config = load_config(Path("/nonexistent/path/.bdbrc"))

        assert config.llm.provider == "openai"
        assert config.hooks.stop.enabled is True

    def test_load_valid_yaml(self, tmp_path):
        """Test loading a valid YAML config file."""
        config_file = tmp_path / ".bdbrc"
        config_file.write_text("""
llm:
  provider: anthropic
  model: claude-3-haiku
hooks:
  stop:
    enabled: false
""")
        # Set secure permissions
        config_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

        config = load_config(config_file)

        assert config.llm.provider == "anthropic"
        assert config.hooks.stop.enabled is False

    def test_load_insecure_permissions_raises(self, tmp_path):
        """Test that insecure file permissions raise error."""
        config_file = tmp_path / ".bdbrc"
        config_file.write_text("llm:\n  provider: openai")
        # Set insecure permissions (world readable)
        config_file.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IROTH)

        with pytest.raises(ConfigError, match="insecure permissions"):
            load_config(config_file)

    def test_load_invalid_yaml_raises(self, tmp_path):
        """Test that invalid YAML raises error."""
        config_file = tmp_path / ".bdbrc"
        config_file.write_text("invalid: yaml: content: [")
        config_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_config(config_file)


class TestCheckPermissions:
    """Tests for check_permissions function."""

    def test_nonexistent_file_ok(self):
        """Test that nonexistent file passes (will be created correctly)."""
        assert check_permissions(Path("/nonexistent/.bdbrc")) is True

    def test_secure_permissions_ok(self, tmp_path):
        """Test that 600 permissions pass."""
        config_file = tmp_path / ".bdbrc"
        config_file.write_text("test")
        config_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

        assert check_permissions(config_file) is True

    def test_group_readable_fails(self, tmp_path):
        """Test that group readable fails."""
        config_file = tmp_path / ".bdbrc"
        config_file.write_text("test")
        config_file.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)

        assert check_permissions(config_file) is False


class TestConfigPaths:
    """Tests for config path resolution."""

    def test_new_config_path(self):
        """Test that CONFIG_PATH points to ~/.bdb/config.yaml."""
        from drinkingbird.config import CONFIG_PATH
        assert CONFIG_PATH == Path.home() / ".bdb" / "config.yaml"

    def test_legacy_config_path(self):
        """Test that LEGACY_CONFIG_PATH points to ~/.bdbrc."""
        from drinkingbird.config import LEGACY_CONFIG_PATH
        assert LEGACY_CONFIG_PATH == Path.home() / ".bdbrc"


class TestLegacyConfigFallback:
    """Tests for backwards-compatible config loading."""

    def test_loads_from_new_path(self, tmp_path):
        """Test loading from new config path."""
        new_config = tmp_path / ".bdb" / "config.yaml"
        new_config.parent.mkdir()
        new_config.write_text("llm:\n  provider: anthropic")
        new_config.chmod(0o600)

        config = load_config(new_config)
        assert config.llm.provider == "anthropic"

    def test_falls_back_to_legacy(self, tmp_path, monkeypatch):
        """Test fallback to legacy path when new doesn't exist."""
        new_path = tmp_path / ".bdb" / "config.yaml"
        legacy_path = tmp_path / ".bdbrc"
        legacy_path.write_text("llm:\n  provider: ollama")
        legacy_path.chmod(0o600)

        monkeypatch.setattr("drinkingbird.config.CONFIG_PATH", new_path)
        monkeypatch.setattr("drinkingbird.config.LEGACY_CONFIG_PATH", legacy_path)

        config = load_config()
        assert config.llm.provider == "ollama"

    def test_new_path_takes_precedence(self, tmp_path, monkeypatch):
        """Test that new path takes precedence over legacy."""
        new_path = tmp_path / ".bdb" / "config.yaml"
        new_path.parent.mkdir()
        new_path.write_text("llm:\n  provider: anthropic")
        new_path.chmod(0o600)

        legacy_path = tmp_path / ".bdbrc"
        legacy_path.write_text("llm:\n  provider: ollama")
        legacy_path.chmod(0o600)

        monkeypatch.setattr("drinkingbird.config.CONFIG_PATH", new_path)
        monkeypatch.setattr("drinkingbird.config.LEGACY_CONFIG_PATH", legacy_path)

        config = load_config()
        assert config.llm.provider == "anthropic"


class TestTemplate:
    """Tests for template generation."""

    def test_generate_template(self):
        """Test that template contains expected sections."""
        template = generate_template()

        assert "llm:" in template
        assert "provider:" in template
        assert "hooks:" in template
        assert "stop:" in template
        assert "pre_tool:" in template

    def test_save_template_creates_file(self, tmp_path):
        """Test that save_template creates file with correct permissions."""
        config_file = tmp_path / ".bdbrc"

        result = save_template(config_file)

        assert result == config_file
        assert config_file.exists()

        # Check permissions (600)
        mode = config_file.stat().st_mode
        assert (mode & stat.S_IRWXU) == (stat.S_IRUSR | stat.S_IWUSR)
        assert (mode & stat.S_IRWXG) == 0
        assert (mode & stat.S_IRWXO) == 0

    def test_template_is_valid_yaml(self):
        """Test that generated template is valid YAML."""
        template = generate_template()
        data = yaml.safe_load(template)

        assert isinstance(data, dict)
        assert "llm" in data
        assert "hooks" in data
