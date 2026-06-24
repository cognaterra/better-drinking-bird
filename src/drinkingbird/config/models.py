"""Configuration data model: typed dataclasses + ConfigError."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from drinkingbird.config.defaults import _get_git_root


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
        """Get API key from config or environment variable.

        Falls back to sourcing the user's shell profile if the env var
        isn't in the current process environment (common in hook subprocesses
        that don't source .zshrc/.bashrc).
        """
        if self.api_key:
            return self.api_key

        # Determine which env var to check
        env_var = self.api_key_env
        if not env_var:
            env_vars = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "azure": "AZURE_OPENAI_API_KEY",
            }
            env_var = env_vars.get(self.provider)

        if not env_var:
            return None

        # Try current environment first
        key = os.environ.get(env_var)
        if key:
            return key

        # Hook subprocesses often don't source shell profiles.
        # Try extracting from .zshrc/.bashrc as a last resort.
        return self._resolve_key_from_shell(env_var)

    @staticmethod
    def _resolve_key_from_shell(env_var: str) -> str | None:
        """Extract an env var value from shell profile files."""
        import pathlib
        import re as re_mod

        home = pathlib.Path.home()
        for profile in [home / ".zshrc", home / ".bashrc", home / ".zprofile", home / ".bash_profile"]:
            if not profile.exists():
                continue
            try:
                text = profile.read_text()
                # Match: export VAR=value or export VAR="value" or export VAR='value'
                pattern = rf'^export\s+{re.escape(env_var)}=["\']?([^"\'#\n]+)["\']?'
                match = re_mod.search(pattern, text, re_mod.MULTILINE)
                if match:
                    return match.group(1).strip()
            except (PermissionError, OSError):
                continue
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
    inject_git_context: bool = True
    inject_file_references: bool = True
    inject_original_prompt: bool = False
    quote_context_files: bool = True
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
    file: str = ".bdb/supervisor.log"
    error_file: str = ".bdb/errors.log"

    def get_log_path(self) -> Path:
        """Get log file path, resolved relative to git root or home."""
        return self._resolve(self.file)

    def get_error_log_path(self) -> Path:
        """Get error log file path, resolved relative to git root or home."""
        return self._resolve(self.error_file)

    @staticmethod
    def _resolve(path_str: str) -> Path:
        """Resolve a log path: absolute/~ paths as-is, relative paths under git root."""
        p = Path(path_str)
        if p.is_absolute() or path_str.startswith("~"):
            return p.expanduser()
        git_root = _get_git_root()
        if not git_root:
            raise RuntimeError("bdb must be run inside a git repository")
        return git_root / p


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
