"""Configuration loading, merging, templating, and on-disk persistence."""

from __future__ import annotations

import stat
from pathlib import Path

import yaml

from drinkingbird.config.defaults import DEFAULT_CONFIG, _get_git_root
from drinkingbird.config.models import Config, ConfigError


def _active_config_paths() -> tuple[Path, Path]:
    """Return ``(primary, legacy)`` config paths read from the package namespace.

    These were patchable as ``drinkingbird.config.CONFIG_PATH`` /
    ``LEGACY_CONFIG_PATH`` when this lived in a single module; reading them off the
    package at call time keeps that monkeypatch contract intact after the split.
    """
    import drinkingbird.config as cfg

    return cfg.CONFIG_PATH, cfg.LEGACY_CONFIG_PATH


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
    primary_path, legacy_path = _active_config_paths()
    if path is not None:
        config_path = path
    elif primary_path.exists():
        config_path = primary_path
    elif legacy_path.exists():
        config_path = legacy_path
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
    inject_git_context: true  # Inject branch name and worktree path before compaction
    inject_file_references: true  # Inject context file names and @refs before compaction
    inject_original_prompt: false  # Inject the first user message before compaction
    quote_context_files: true  # Include full content of CLAUDE.md/AGENTS.md (not just filenames)
    context_patterns:
      - "docs/plans/*.md"
      - "docs/*.md"
      - ".claude/plans/*.md"
      - "CLAUDE.md"
      - "README.md"

# Logging (relative paths resolve under git root, e.g. <repo>/.bdb/)
logging:
  level: info  # debug | info | warn | error
  file: .bdb/supervisor.log
  error_file: .bdb/errors.log

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
    config_path = path or _active_config_paths()[0]

    # Write file
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(generate_template())

    # Set secure permissions (owner read/write only)
    config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    return config_path


def _update_gitignore(git_root: Path) -> None:
    """Add .bdb/ to .gitignore if not already present."""
    gitignore_path = git_root / ".gitignore"
    comment = "# better-drinking-bird 🐦⛲"
    entries_to_add = [".bdb/"]

    # Read existing content
    existing_lines: set[str] = set()
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        existing_lines = {line.strip() for line in content.splitlines()}
    else:
        content = ""

    # Find entries that need to be added
    missing = [entry for entry in entries_to_add if entry not in existing_lines]
    if not missing:
        return

    # Append missing entries with comment (only if adding new entries)
    if comment not in existing_lines:
        lines_to_add = comment + "\n" + "\n".join(missing)
    else:
        lines_to_add = "\n".join(missing)
    if content and not content.endswith("\n"):
        lines_to_add = "\n" + lines_to_add
    if not content:
        lines_to_add = lines_to_add + "\n"
    else:
        lines_to_add = lines_to_add + "\n"

    gitignore_path.write_text(content + lines_to_add)


def ensure_config() -> Path:
    """Ensure config file exists, creating it if necessary.

    Handles legacy config migration from ~/.bdbrc to ~/.bdb/config.yaml.
    Also updates .gitignore in the current git repository to ignore BDB files.

    Returns:
        Path to the config file
    """
    import shutil

    primary_path, legacy_path = _active_config_paths()

    # Check for legacy config that needs migration
    if legacy_path.exists() and not primary_path.exists():
        primary_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_path), str(primary_path))

    # Create config if it doesn't exist
    if not primary_path.exists():
        save_template()

    # Update .gitignore if in a git repository
    git_root = _get_git_root()
    if git_root:
        _update_gitignore(git_root)

    return primary_path
