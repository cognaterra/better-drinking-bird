"""Base adapter interface for Better Drinking Bird."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class Adapter(ABC):
    """Abstract base class for agent adapters.

    Adapters handle the translation between different agent hook formats
    and the common BDB hook interface.
    """

    # Name of the agent this adapter supports
    agent_name: str = ""

    # Whether this adapter supports local (per-workspace) installation
    supports_local: bool = True

    def __init__(self, config: Any = None):
        """Initialize adapter with optional configuration.

        Args:
            config: Agent-specific configuration
        """
        self.config = config

    @abstractmethod
    def parse_input(self, raw_input: dict[str, Any]) -> dict[str, Any]:
        """Parse raw input from the agent into common format.

        Args:
            raw_input: Raw input from the agent's hook system

        Returns:
            Normalized input dictionary with standard fields
        """
        pass

    @abstractmethod
    def format_output(self, result: dict[str, Any], hook_event: str) -> dict[str, Any]:
        """Format hook result for the agent.

        Args:
            result: Result dictionary from hook
            hook_event: The hook event name

        Returns:
            Formatted output dictionary for the agent
        """
        pass

    @abstractmethod
    def get_install_config(self) -> dict[str, Any]:
        """Get the configuration to install hooks for this agent.

        Returns:
            Configuration dictionary to write to agent's config file
        """
        pass

    @abstractmethod
    def get_config_path(self) -> Path:
        """Get path to the agent's global hook configuration file.

        Returns:
            Path to config file
        """
        pass

    def get_local_config_path(self, workspace: Path) -> Path:
        """Get path to the agent's local (per-workspace) config file.

        Args:
            workspace: Path to the workspace root

        Returns:
            Path to local config file

        Raises:
            NotImplementedError: If adapter doesn't support local installation
        """
        raise NotImplementedError(
            f"{self.agent_name} does not support local installation"
        )

    def get_effective_config_path(
        self, scope: str = "global", workspace: Path | None = None
    ) -> Path:
        """Get the config path for the given scope.

        Args:
            scope: "global" or "local"
            workspace: Workspace path (required for local scope)

        Returns:
            Path to config file
        """
        if scope == "local":
            if workspace is None:
                raise ValueError("workspace is required for local scope")
            return self.get_local_config_path(workspace)
        return self.get_config_path()

    def install(
        self,
        bdb_path: Path,
        scope: str = "global",
        workspace: Path | None = None,
    ) -> bool:
        """Install BDB hooks for this agent.

        Args:
            bdb_path: Path to the bdb executable
            scope: "global" or "local"
            workspace: Workspace path (required for local scope)

        Returns:
            True if installation succeeded
        """
        # Default implementation - subclasses can override
        import json

        config_path = self.get_effective_config_path(scope, workspace)
        install_config = self.get_install_config()

        # Read existing config if present
        existing = {}
        if config_path.exists():
            try:
                existing = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                pass

        # Merge configurations
        # This is agent-specific - subclasses should implement properly
        merged = self._merge_config(existing, install_config)

        # Write back
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(merged, indent=2))

        return True

    def _merge_config(
        self, existing: dict[str, Any], new: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge new config into existing.

        Default implementation replaces hooks section.
        Subclasses can override for agent-specific behavior.
        """
        result = existing.copy()
        for key, value in new.items():
            result[key] = value
        return result

    @abstractmethod
    def uninstall(self, scope: str = "global", workspace: Path | None = None) -> bool:
        """Uninstall BDB hooks for this agent.

        Args:
            scope: "global" or "local"
            workspace: Workspace path (required for local scope)

        Returns:
            True if uninstallation succeeded, False if nothing to uninstall
        """
        pass
