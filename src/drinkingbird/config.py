"""Configuration loading and validation for Better Drinking Bird."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH = Path.home() / ".bdb" / "config.yaml"
LEGACY_CONFIG_PATH = Path.home() / ".bdbrc"

# Default configuration
DEFAULT_CONFIG = {
    "llm": {
        "provider": "openai",
        "model": "gpt-5-nano",
        "api_key": None,
        "api_key_env": None,
        "base_url": None,
        "timeout": 30,
        "deployment": None,
        "api_version": "2024-08-01-preview",
    },
    "agent": {
        "type": "claude-code",
        "conversation_depth": 1,
    },
    "hooks": {
        "stop": {
            "enabled": True,
            "block_permission_seeking": True,
            "block_plan_deviation": True,
            "block_quality_shortcuts": True,
        },
        "pre_tool": {
            "enabled": True,
            "categories": {
                "ci_bypass": True,
                "destructive_git": True,
                "branch_switching": True,
                "interactive_git": True,
                "dangerous_files": True,
                "git_history": True,
                "credential_access": True,
            },
        },
        "tool_failure": {
            "enabled": True,
            "confidence_threshold": "medium",
        },
        "pre_compact": {
            "enabled": True,
            "context_patterns": [
                "docs/plans/*.md",
                "docs/*.md",
                ".claude/plans/*.md",
                "CLAUDE.md",
                "README.md",
            ],
        },
    },
    "logging": {
        "level": "info",
        "file": "~/.bdb/supervisor.log",
        "error_file": "~/.bdb/errors.log",
    },
    "tracing": {
        "enabled": False,
        "public_key": None,
        "secret_key": None,
        "public_key_env": None,
        "secret_key_env": None,
        "host": "https://cloud.langfuse.com",
    },
    "blocklist": [],
}


@dataclass
class LLMConfig:
    """LLM provider configuration."""

    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    timeout: int = 30
    # Azure OpenAI specific
    deployment: str | None = None  # Azure deployment name
    api_version: str = "2024-08-01-preview"  # Azure API version

    def get_api_key(self) -> str | None:
        """Get API key from config or environment variable."""
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env)
        # Fallback to common env vars by provider
        env_vars = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "azure": "AZURE_OPENAI_API_KEY",
        }
        if self.provider in env_vars:
            return os.environ.get(env_vars[self.provider])
        return None


@dataclass
class BlocklistEntry:
    """A user-configured blocklist pattern."""

    pattern: str
    reason: str
    tools: list[str] = field(default_factory=lambda: ["*"])
    _compiled: re.Pattern | None = field(default=None, repr=False)

    def get_compiled_pattern(self) -> re.Pattern:
        """Get compiled regex, caching for performance."""
        if self._compiled is None:
            self._compiled = re.compile(self.pattern, re.IGNORECASE)
        return self._compiled

    def matches_tool(self, tool_name: str) -> bool:
        """Check if this entry applies to the given tool."""
        return "*" in self.tools or tool_name in self.tools


@dataclass
class AgentConfig:
    """Agent configuration."""

    type: str = "claude-code"
    conversation_depth: int = 1


@dataclass
class StopHookConfig:
    """Stop hook configuration."""

    enabled: bool = True
    block_permission_seeking: bool = True
    block_plan_deviation: bool = True
    block_quality_shortcuts: bool = True


@dataclass
class PreToolHookConfig:
    """Pre-tool hook configuration."""

    enabled: bool = True
    categories: dict[str, bool] = field(default_factory=lambda: {
        "ci_bypass": True,
        "destructive_git": True,
        "branch_switching": True,
        "interactive_git": True,
        "dangerous_files": True,
        "git_history": True,
        "credential_access": True,
    })


@dataclass
class ToolFailureHookConfig:
    """Tool failure hook configuration."""

    enabled: bool = True
    confidence_threshold: str = "medium"


@dataclass
class PreCompactHookConfig:
    """Pre-compact hook configuration."""

    enabled: bool = True
    context_patterns: list[str] = field(default_factory=lambda: [
        "docs/plans/*.md",
        "docs/*.md",
        ".claude/plans/*.md",
        "CLAUDE.md",
        "README.md",
    ])


@dataclass
class HooksConfig:
    """Hooks configuration."""

    stop: StopHookConfig = field(default_factory=StopHookConfig)
    pre_tool: PreToolHookConfig = field(default_factory=PreToolHookConfig)
    tool_failure: ToolFailureHookConfig = field(default_factory=ToolFailureHookConfig)
    pre_compact: PreCompactHookConfig = field(default_factory=PreCompactHookConfig)


@dataclass
class LoggingConfig:
    """Logging configuration."""

    level: str = "info"
    file: str = "~/.bdb/supervisor.log"
    error_file: str = "~/.bdb/errors.log"

    def get_log_path(self) -> Path:
        """Get expanded log file path."""
        return Path(self.file).expanduser()

    def get_error_log_path(self) -> Path:
        """Get expanded error log file path."""
        return Path(self.error_file).expanduser()


@dataclass
class TracingConfig:
    """Langfuse tracing configuration."""

    enabled: bool = False
    public_key: str | None = None
    secret_key: str | None = None
    public_key_env: str | None = None
    secret_key_env: str | None = None
    host: str = "https://cloud.langfuse.com"

    def get_public_key(self) -> str | None:
        """Get public key from config or environment variable."""
        if self.public_key:
            return self.public_key
        if self.public_key_env:
            return os.environ.get(self.public_key_env)
        return os.environ.get("LANGFUSE_PUBLIC_KEY")

    def get_secret_key(self) -> str | None:
        """Get secret key from config or environment variable."""
        if self.secret_key:
            return self.secret_key
        if self.secret_key_env:
            return os.environ.get(self.secret_key_env)
        return os.environ.get("LANGFUSE_SECRET_KEY")

    def is_configured(self) -> bool:
        """Check if tracing is properly configured."""
        return self.enabled and bool(self.get_public_key()) and bool(self.get_secret_key())


@dataclass
class Config:
    """Main configuration object."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    hooks: HooksConfig = field(default_factory=HooksConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    tracing: TracingConfig = field(default_factory=TracingConfig)
    blocklist: list[BlocklistEntry] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        """Create Config from dictionary."""
        llm_data = data.get("llm", {})
        agent_data = data.get("agent", {})
        hooks_data = data.get("hooks", {})
        logging_data = data.get("logging", {})
        tracing_data = data.get("tracing", {})
        blocklist_data = data.get("blocklist", [])

        # Build hooks config
        stop_data = hooks_data.get("stop", {})
        pre_tool_data = hooks_data.get("pre_tool", {})
        tool_failure_data = hooks_data.get("tool_failure", {})
        pre_compact_data = hooks_data.get("pre_compact", {})

        hooks_config = HooksConfig(
            stop=StopHookConfig(**stop_data) if stop_data else StopHookConfig(),
            pre_tool=PreToolHookConfig(**pre_tool_data) if pre_tool_data else PreToolHookConfig(),
            tool_failure=ToolFailureHookConfig(**tool_failure_data) if tool_failure_data else ToolFailureHookConfig(),
            pre_compact=PreCompactHookConfig(**pre_compact_data) if pre_compact_data else PreCompactHookConfig(),
        )

        # Parse blocklist entries
        blocklist = []
        for entry in blocklist_data:
            blocklist.append(BlocklistEntry(
                pattern=entry.get("pattern", ""),
                reason=entry.get("reason", "Blocked by user blocklist"),
                tools=entry.get("tools", ["*"]),
            ))

        return cls(
            llm=LLMConfig(**llm_data) if llm_data else LLMConfig(),
            agent=AgentConfig(**agent_data) if agent_data else AgentConfig(),
            hooks=hooks_config,
            logging=LoggingConfig(**logging_data) if logging_data else LoggingConfig(),
            tracing=TracingConfig(**tracing_data) if tracing_data else TracingConfig(),
            blocklist=blocklist,
        )


class ConfigError(Exception):
    """Configuration error."""

    pass


def check_permissions(path: Path) -> bool:
    """Check if config file has secure permissions (600 or stricter)."""
    if not path.exists():
        return True  # Will be created with correct permissions

    mode = path.stat().st_mode
    # Check that group and others have no access
    return (mode & (stat.S_IRWXG | stat.S_IRWXO)) == 0


def load_config(path: Path | None = None) -> Config:
    """Load configuration from YAML file.

    Args:
        path: Path to config file. Defaults to ~/.bdb/config.yaml,
              falls back to ~/.bdbrc for backwards compatibility.

    Returns:
        Loaded Config object

    Raises:
        ConfigError: If config file has insecure permissions or is invalid
    """
    if path is not None:
        config_path = path
    elif CONFIG_PATH.exists():
        config_path = CONFIG_PATH
    elif LEGACY_CONFIG_PATH.exists():
        config_path = LEGACY_CONFIG_PATH
    else:
        # Return default config if no file exists
        return Config()

    if not config_path.exists():
        return Config()

    # Check permissions
    if not check_permissions(config_path):
        raise ConfigError(
            f"Config file {config_path} has insecure permissions. "
            f"Run: chmod 600 {config_path}"
        )

    # Load YAML
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}")

    # Merge with defaults
    merged = _deep_merge(DEFAULT_CONFIG, data)

    return Config.from_dict(merged)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def generate_template() -> str:
    """Generate a template configuration file."""
    return """# Better Drinking Bird Configuration
# Location: ~/.bdb/config.yaml
# File permissions should be 600 (chmod 600 ~/.bdb/config.yaml)

# LLM Provider Configuration
llm:
  provider: openai  # openai | anthropic | ollama | azure
  model: gpt-4o-mini
  api_key: null  # Or set api_key_env to use an environment variable
  # api_key_env: OPENAI_API_KEY
  # base_url: null  # For custom endpoints
  timeout: 30
  # Azure OpenAI specific (required when provider: azure)
  # deployment: my-deployment-name  # Azure deployment name
  # api_version: 2024-08-01-preview

# Agent Configuration
agent:
  type: claude-code  # claude-code | cursor | copilot | stdin
  conversation_depth: 1  # 0=full history, 1=last exchange, N=last N exchanges

# Hook Configuration
hooks:
  # Stop hook - nudges agent to keep working
  stop:
    enabled: true
    block_permission_seeking: true  # "Should I proceed?"
    block_plan_deviation: true      # "Let me try a simpler approach"
    block_quality_shortcuts: true   # "Skip those tests"

  # Pre-tool hook - blocks dangerous commands
  pre_tool:
    enabled: true
    categories:
      ci_bypass: true        # --no-verify, HUSKY=0
      destructive_git: true  # reset --hard, clean -f, push --force
      branch_switching: true # checkout main (protects worktrees)
      interactive_git: true  # rebase -i, add -p
      dangerous_files: true  # rm -rf /
      git_history: true      # verbose git log, git blame
      credential_access: true # cat .env, .pem files

  # Tool failure hook - provides recovery hints
  tool_failure:
    enabled: true
    confidence_threshold: medium  # low | medium | high

  # Pre-compact hook - preserves context during compression
  pre_compact:
    enabled: true
    context_patterns:
      - "docs/plans/*.md"
      - "docs/*.md"
      - ".claude/plans/*.md"
      - "CLAUDE.md"
      - "README.md"

# Logging
logging:
  level: info  # debug | info | warn | error
  file: ~/.bdb/supervisor.log
  error_file: ~/.bdb/errors.log

# Tracing (Langfuse)
tracing:
  enabled: false
  # public_key: pk-lf-...  # Or use public_key_env
  # secret_key: sk-lf-...  # Or use secret_key_env
  # public_key_env: LANGFUSE_PUBLIC_KEY
  # secret_key_env: LANGFUSE_SECRET_KEY
  host: https://cloud.langfuse.com  # Or self-hosted URL
"""


def save_template(path: Path | None = None) -> Path:
    """Save template configuration to file with secure permissions.

    Returns:
        Path to the saved config file
    """
    config_path = path or CONFIG_PATH

    # Write file
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(generate_template())

    # Set secure permissions (owner read/write only)
    config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    return config_path
