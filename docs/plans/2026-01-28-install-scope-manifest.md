# Install Scope & Manifest Tracking

## Overview

Add `--local`/`--global` flags to install/uninstall commands, track installations in a manifest, provide `--status` to show installations, and `uninstall --all` to remove everything.

## Tasks

### Task 1: Create manifest module

Create `src/drinkingbird/manifest.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json

MANIFEST_PATH = Path.home() / ".bdb" / "manifest.json"

@dataclass
class Installation:
    agent: str
    scope: str  # "global" or "local"
    path: str
    installed_at: str

@dataclass
class Manifest:
    version: int = 1
    installations: list[Installation] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Manifest": ...
    def save(self) -> None: ...
    def add(self, agent: str, scope: str, path: str) -> None: ...
    def remove(self, agent: str, scope: str | None = None, path: str | None = None) -> list[Installation]: ...
    def get(self, agent: str | None = None, scope: str | None = None) -> list[Installation]: ...
```

Verify: `python -c "from drinkingbird.manifest import Manifest; m = Manifest(); print('OK')"`

### Task 2: Update Adapter base class

Add to `src/drinkingbird/adapters/base.py`:

1. Add abstract method `get_local_config_path(self, workspace: Path) -> Path`
2. Update `install(self, bdb_path: Path, scope: str = "global", workspace: Path | None = None) -> bool`
3. Update `uninstall(self, scope: str = "global", workspace: Path | None = None) -> bool`

Verify: `python -m py_compile src/drinkingbird/adapters/base.py`

### Task 3: Update ClaudeCodeAdapter

Update `src/drinkingbird/adapters/claude_code.py`:

1. Implement `get_local_config_path()` returning `workspace / ".claude" / "settings.local.json"`
2. Update `install()` to handle scope parameter
3. Update `uninstall()` to handle scope parameter

Verify: `python -m py_compile src/drinkingbird/adapters/claude_code.py`

### Task 4: Update other adapters

Update remaining adapters to implement new interface:
- `cline.py` - local: `workspace / ".cline" / "hooks"`
- `cursor.py` - local: `workspace / ".cursor" / "hooks.json"`
- `copilot.py` - local: `workspace / ".github" / "copilot-hooks.json"`
- `kilo_code.py` - local: `workspace / ".kilo-code" / "hooks"`
- `stdin.py` - no local config (raises NotImplementedError)

Verify: `python -c "from drinkingbird.adapters import *; print('OK')"`

### Task 5: Update CLI install command

Update `src/drinkingbird/cli.py` install command:

1. Add `--local` flag
2. Add `--global` flag (explicit, default behavior)
3. Detect workspace root for local installs
4. Call adapter with scope parameter
5. Update manifest after successful install

Verify: `bdb install --help` shows new flags

### Task 6: Update CLI uninstall command

Update `src/drinkingbird/cli.py` uninstall command:

1. Add `--local` flag
2. Add `--global` flag
3. Add `--all` flag (no agent argument required)
4. Update manifest after successful uninstall

Verify: `bdb uninstall --help` shows new flags

### Task 7: Add status command

Add new `status` command to CLI:

```python
@main.command()
def status() -> None:
    """Show BDB installation status."""
    # Load manifest
    # Group by agent
    # Display each installation with scope and path
```

Verify: `bdb status` runs without error

### Task 8: Add tests

Create `tests/test_manifest.py`:
- Test Manifest load/save
- Test add/remove/get operations

Update `tests/test_cli.py`:
- Test install --local/--global
- Test uninstall --local/--global/--all
- Test status command

Verify: `pytest tests/test_manifest.py tests/test_cli.py -v`
