"""Default configuration values and shared path helpers."""

from __future__ import annotations

from pathlib import Path


CONFIG_PATH = Path.home() / ".bdb" / "config.yaml"
LEGACY_CONFIG_PATH = Path.home() / ".bdbrc"

# Default configuration
DEFAULT_CONFIG = {
    "llm": {
        "provider": "openai",
        "model": "gpt-4o-mini",
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
            "inject_git_context": True,
            "inject_file_references": True,
            "inject_original_prompt": False,
            "quote_context_files": True,
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
        "file": ".bdb/supervisor.log",
        "error_file": ".bdb/errors.log",
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


def _get_git_root() -> Path | None:
    """Get git repo root from cwd, or None if not in a repo."""
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None
