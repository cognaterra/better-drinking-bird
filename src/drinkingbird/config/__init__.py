"""Configuration loading and validation for Better Drinking Bird.

This package was split out of a single ``config.py`` module for cohesion:

* :mod:`drinkingbird.config.defaults` — constants + shared path helpers
* :mod:`drinkingbird.config.models`   — the typed dataclass schema
* :mod:`drinkingbird.config.loader`   — load/merge/template/persist

Every public (and previously module-level private) name is re-exported here so
``from drinkingbird.config import X`` keeps working unchanged.
"""

from __future__ import annotations

from drinkingbird.config.defaults import (
    CONFIG_PATH,
    DEFAULT_CONFIG,
    LEGACY_CONFIG_PATH,
    _get_git_root,
)
from drinkingbird.config.loader import (
    _deep_merge,
    _update_gitignore,
    check_permissions,
    ensure_config,
    generate_template,
    load_config,
    save_template,
)
from drinkingbird.config.models import (
    AgentConfig,
    BlocklistEntry,
    Config,
    ConfigError,
    HooksConfig,
    LLMConfig,
    LoggingConfig,
    PreCompactHookConfig,
    PreToolHookConfig,
    StopHookConfig,
    ToolFailureHookConfig,
    TracingConfig,
)

__all__ = [
    "CONFIG_PATH",
    "LEGACY_CONFIG_PATH",
    "DEFAULT_CONFIG",
    "LLMConfig",
    "BlocklistEntry",
    "AgentConfig",
    "StopHookConfig",
    "PreToolHookConfig",
    "ToolFailureHookConfig",
    "PreCompactHookConfig",
    "HooksConfig",
    "LoggingConfig",
    "TracingConfig",
    "Config",
    "ConfigError",
    "check_permissions",
    "load_config",
    "generate_template",
    "save_template",
    "ensure_config",
    "_get_git_root",
    "_deep_merge",
    "_update_gitignore",
]
