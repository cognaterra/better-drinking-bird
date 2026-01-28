"""Installation manifest for Better Drinking Bird."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_PATH = Path.home() / ".bdb" / "manifest.json"


@dataclass
class Installation:
    """A single BDB installation record."""

    agent: str
    scope: str  # "global" or "local"
    path: str
    installed_at: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "agent": self.agent,
            "scope": self.scope,
            "path": self.path,
            "installed_at": self.installed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Installation:
        """Create from dictionary."""
        return cls(
            agent=data["agent"],
            scope=data["scope"],
            path=data["path"],
            installed_at=data["installed_at"],
        )


@dataclass
class Manifest:
    """Tracks all BDB installations."""

    version: int = 1
    installations: list[Installation] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> Manifest:
        """Load manifest from disk.

        Returns empty manifest if file doesn't exist.
        """
        manifest_path = path or MANIFEST_PATH

        if not manifest_path.exists():
            return cls()

        try:
            data = json.loads(manifest_path.read_text())
            installations = [
                Installation.from_dict(i) for i in data.get("installations", [])
            ]
            return cls(
                version=data.get("version", 1),
                installations=installations,
            )
        except (json.JSONDecodeError, KeyError):
            return cls()

    def save(self, path: Path | None = None) -> None:
        """Save manifest to disk."""
        manifest_path = path or MANIFEST_PATH

        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": self.version,
            "installations": [i.to_dict() for i in self.installations],
        }

        manifest_path.write_text(json.dumps(data, indent=2))

    def add(self, agent: str, scope: str, path: str) -> None:
        """Add an installation record.

        Replaces existing record for same agent+scope+path.
        """
        # Remove any existing record for same agent+scope+path
        self.installations = [
            i for i in self.installations
            if not (i.agent == agent and i.scope == scope and i.path == path)
        ]

        self.installations.append(
            Installation(
                agent=agent,
                scope=scope,
                path=path,
                installed_at=datetime.now(timezone.utc).isoformat(),
            )
        )

    def remove(
        self,
        agent: str | None = None,
        scope: str | None = None,
        path: str | None = None,
    ) -> list[Installation]:
        """Remove installation records matching criteria.

        Returns list of removed installations.
        """
        removed = []
        remaining = []

        for i in self.installations:
            matches = True
            if agent is not None and i.agent != agent:
                matches = False
            if scope is not None and i.scope != scope:
                matches = False
            if path is not None and i.path != path:
                matches = False

            if matches:
                removed.append(i)
            else:
                remaining.append(i)

        self.installations = remaining
        return removed

    def get(
        self,
        agent: str | None = None,
        scope: str | None = None,
    ) -> list[Installation]:
        """Get installation records matching criteria."""
        results = []

        for i in self.installations:
            matches = True
            if agent is not None and i.agent != agent:
                matches = False
            if scope is not None and i.scope != scope:
                matches = False

            if matches:
                results.append(i)

        return results

    def get_agents(self) -> list[str]:
        """Get list of unique agent names."""
        return sorted(set(i.agent for i in self.installations))
