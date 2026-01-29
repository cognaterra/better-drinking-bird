"""CLI for Better Drinking Bird."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import click

from drinkingbird import __version__
from drinkingbird.config import (
    CONFIG_PATH,
    ConfigError,
    generate_template,
    load_config,
    save_template,
)
from drinkingbird.pause import (
    GLOBAL_SENTINEL,
    create_sentinel,
    get_local_sentinel,
    get_pause_info,
    get_workspace_root,
    is_paused,
    remove_sentinel,
)


@click.group()
@click.version_option(version=__version__, prog_name="bdb")
def main() -> None:
    """Better Drinking Bird - Supervisor for AI coding agents.

    Keeps your coding agent on task like Homer's drinking bird
    pressing Enter on the keyboard.
    """
    pass


@main.command()
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Overwrite existing config file",
)
def init(force: bool) -> None:
    """Initialize configuration file.

    Creates ~/.bdb/config.yaml with default settings and secure permissions.
    """
    from drinkingbird.config import LEGACY_CONFIG_PATH

    # Check for legacy config
    if LEGACY_CONFIG_PATH.exists() and not CONFIG_PATH.exists():
        click.echo(f"Found legacy config at {LEGACY_CONFIG_PATH}")
        if click.confirm("Move to new location (~/.bdb/config.yaml)?"):
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.move(str(LEGACY_CONFIG_PATH), str(CONFIG_PATH))
            click.echo(f"Moved config to {CONFIG_PATH}")
            return

    if CONFIG_PATH.exists() and not force:
        click.echo(f"Config file already exists: {CONFIG_PATH}")
        click.echo("Use --force to overwrite.")
        sys.exit(1)

    path = save_template()
    click.echo(f"Created config file: {path}")
    click.echo("Edit this file to configure your API keys and settings.")
    click.echo()
    click.echo("Quick start:")
    click.echo("  1. Add your API key to ~/.bdb/config.yaml")
    click.echo("  2. Run: bdb install claude-code")
    click.echo("  3. Start using Claude Code as normal")


@main.command()
@click.argument("agent", type=click.Choice(["claude-code", "cline", "cursor", "copilot", "kilo-code", "stdin"]))
@click.option("--global", "use_global", is_flag=True, help="Install globally instead of locally")
@click.option(
    "--dry-run", "-n",
    is_flag=True,
    help="Show what would be done without making changes",
)
def install(agent: str, use_global: bool, dry_run: bool) -> None:
    """Install hooks for an AI coding agent.

    Configures the specified agent to use Better Drinking Bird
    as its hook supervisor.

    By default, installs locally if in a git repository, otherwise globally.
    Use --global to force global installation.
    """
    from drinkingbird.adapters import (
        ClaudeCodeAdapter,
        ClineAdapter,
        CopilotAdapter,
        CursorAdapter,
        KiloCodeAdapter,
        StdinAdapter,
    )
    from drinkingbird.manifest import Manifest

    adapters = {
        "claude-code": ClaudeCodeAdapter,
        "cline": ClineAdapter,
        "copilot": CopilotAdapter,
        "cursor": CursorAdapter,
        "kilo-code": KiloCodeAdapter,
        "stdin": StdinAdapter,
    }

    adapter_class = adapters[agent]
    adapter = adapter_class()

    # Determine scope: local if in git repo (and supported), otherwise global
    workspace = get_workspace_root()
    if use_global or not workspace or not adapter.supports_local:
        scope = "global"
        workspace = None
    else:
        scope = "local"

    # Find bdb executable
    bdb_path = shutil.which("bdb")
    if not bdb_path:
        # Fallback to python -m bdb
        bdb_path = f"{sys.executable} -m bdb"

    # Determine config path
    config_path = adapter.get_effective_config_path(scope, workspace)

    if dry_run:
        click.echo(f"Would install hooks for {agent} ({scope})")
        click.echo(f"Config path: {config_path}")
        click.echo(f"Install config:")
        click.echo(json.dumps(adapter.get_install_config(), indent=2))
        return

    try:
        success = adapter.install(Path(bdb_path), scope=scope, workspace=workspace)
        if success:
            click.echo(f"Installed hooks for {agent} ({scope})")
            click.echo(f"Config updated: {config_path}")

            # Update manifest
            manifest = Manifest.load()
            manifest.add(agent, scope, str(config_path))
            manifest.save()
        else:
            click.echo(f"Failed to install hooks for {agent}", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"Error installing hooks: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("agent", type=click.Choice(["claude-code", "cline", "cursor", "copilot", "kilo-code", "stdin"]), required=False)
@click.option("--global", "use_global", is_flag=True, help="Uninstall global hooks instead of local")
@click.option("--all", "uninstall_all", is_flag=True, help="Uninstall all bdb hooks everywhere")
@click.option(
    "--dry-run", "-n",
    is_flag=True,
    help="Show what would be done without making changes",
)
def uninstall(
    agent: str | None,
    use_global: bool,
    uninstall_all: bool,
    dry_run: bool,
) -> None:
    """Uninstall hooks for an AI coding agent.

    Removes Better Drinking Bird hooks from the specified agent's
    configuration while preserving other hooks and settings.

    By default, uninstalls locally if in a git repository.
    Use --global to uninstall global hooks, or --all for everything.
    """
    from drinkingbird.adapters import (
        ClaudeCodeAdapter,
        ClineAdapter,
        CopilotAdapter,
        CursorAdapter,
        KiloCodeAdapter,
        StdinAdapter,
    )
    from drinkingbird.manifest import Manifest

    if uninstall_all and agent:
        click.echo("Cannot specify both --all and an agent", err=True)
        sys.exit(1)

    if not uninstall_all and not agent:
        click.echo("Either specify an agent or use --all", err=True)
        sys.exit(1)

    adapters = {
        "claude-code": ClaudeCodeAdapter,
        "cline": ClineAdapter,
        "copilot": CopilotAdapter,
        "cursor": CursorAdapter,
        "kilo-code": KiloCodeAdapter,
        "stdin": StdinAdapter,
    }

    manifest = Manifest.load()

    if uninstall_all:
        # Uninstall everything in the manifest
        installations = manifest.get()

        if not installations:
            click.echo("No installations found in manifest.")
            return

        if dry_run:
            click.echo("Would uninstall:")
            for inst in installations:
                click.echo(f"  - {inst.agent} ({inst.scope}): {inst.path}")
            return

        for inst in installations:
            if inst.agent not in adapters:
                click.echo(f"Unknown agent {inst.agent}, skipping", err=True)
                continue

            adapter = adapters[inst.agent]()
            workspace = Path(inst.path).parent.parent if inst.scope == "local" else None

            try:
                success = adapter.uninstall(scope=inst.scope, workspace=workspace)
                if success:
                    click.echo(f"Uninstalled {inst.agent} ({inst.scope}): {inst.path}")
                    manifest.remove(agent=inst.agent, scope=inst.scope, path=inst.path)
                else:
                    click.echo(f"No hooks found for {inst.agent} at {inst.path}")
                    # Still remove from manifest if file doesn't exist
                    manifest.remove(agent=inst.agent, scope=inst.scope, path=inst.path)
            except Exception as e:
                click.echo(f"Error uninstalling {inst.agent}: {e}", err=True)

        manifest.save()
        return

    # Single agent uninstall
    adapter_class = adapters[agent]
    adapter = adapter_class()

    # Determine scope: local if in git repo (unless --global), otherwise global
    workspace = get_workspace_root()
    if use_global:
        scope = "global"
        workspace = None
    elif workspace and adapter.supports_local:
        scope = "local"
    else:
        scope = "global"
        workspace = None

    config_path = adapter.get_effective_config_path(scope, workspace)

    if dry_run:
        click.echo(f"Would uninstall hooks for {agent} ({scope})")
        click.echo(f"Config path: {config_path}")
        return

    try:
        success = adapter.uninstall(scope=scope, workspace=workspace)
        if success:
            click.echo(f"Uninstalled hooks for {agent} ({scope})")
            click.echo(f"Config updated: {config_path}")

            # Update manifest
            manifest.remove(agent=agent, scope=scope, path=str(config_path))
            manifest.save()
        else:
            click.echo(f"No bdb hooks found for {agent}")
    except Exception as e:
        click.echo(f"Error uninstalling hooks: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option(
    "--global",
    "use_global",
    is_flag=True,
    help="Show all installations (highlights active config in cyan)",
)
def status(use_global: bool) -> None:
    """Show BDB installation status.

    By default, shows only the config for the current location:
    - Local config if in a git repository with BDB installed
    - Global config otherwise

    Use --global to see all installations.
    """
    from drinkingbird.manifest import Installation, Manifest

    manifest = Manifest.load()

    # Determine active scope for current directory
    workspace = get_workspace_root()
    if workspace:
        active_scope = "local"
        active_path = str(workspace)
    else:
        active_scope = "global"
        active_path = None

    def is_active(inst: Installation) -> bool:
        """Check if installation is active for current directory."""
        if inst.scope != active_scope:
            return False
        if active_scope == "local" and active_path:
            return active_path in inst.path
        return active_scope == "global"

    if use_global:
        installations = manifest.get()
    else:
        installations = manifest.get(scope=active_scope)
        # Filter local installations to match current workspace
        if active_scope == "local" and active_path:
            installations = [i for i in installations if active_path in i.path]

    if not installations:
        click.echo("No BDB installations found.")
        click.echo()
        click.echo("To install hooks, run:")
        click.echo("  bdb install claude-code")
        return

    click.echo("BDB Installation Status")
    click.echo("=" * 40)

    # Show pause status
    paused, sentinel_path = is_paused()
    if paused:
        click.secho("⏸  PAUSED", fg="yellow", bold=True)
        if sentinel_path:
            click.echo(f"   {sentinel_path}")

    # Clean up missing installations and group by agent
    by_agent: dict[str, list] = {}
    removed_count = 0
    for inst in installations:
        if not Path(inst.path).exists():
            # Config file missing - remove from manifest
            manifest.remove(path=inst.path)
            removed_count += 1
            continue
        if inst.agent not in by_agent:
            by_agent[inst.agent] = []
        by_agent[inst.agent].append(inst)

    if removed_count > 0:
        manifest.save()
        click.secho(
            f"Cleaned up {removed_count} stale installation(s)", fg="yellow"
        )

    if not by_agent:
        click.echo("No BDB installations found.")
        click.echo()
        click.echo("To install hooks, run:")
        click.echo("  bdb install claude-code")
        return

    for agent in sorted(by_agent.keys()):
        click.echo()
        click.echo(f"{agent}:")
        for inst in by_agent[agent]:
            # Parse date from ISO format
            date_str = inst.installed_at[:10] if inst.installed_at else "unknown"
            line = f"  ✓ {inst.scope}: {inst.path}"

            # Highlight active config in cyan when showing all
            if use_global and is_active(inst):
                click.secho(line, fg="cyan")
            else:
                click.echo(line)
            click.echo(f"      installed: {date_str}")

    total = sum(len(insts) for insts in by_agent.values())
    click.echo()
    click.echo(f"Total: {total} installation(s)")


@main.command()
@click.option("--global", "use_global", is_flag=True, help="Check all installations (not just current workspace)")
@click.option("--fix", "do_fix", is_flag=True, help="Automatically fix detected issues")
def doctor(use_global: bool, do_fix: bool) -> None:
    """Diagnose and fix installation health.

    Compares the installation manifest against actual config files
    to find discrepancies:

    \b
    - Manifest entries where config/hooks are missing
    - Config files with bdb hooks not tracked in manifest
    - Unknown or stale manifest entries

    By default, only checks the current workspace (local scope).
    Use --global to check all installations.

    Use --fix to automatically repair issues:

    \b
    - Removes stale manifest entries
    - Adds untracked installations to manifest
    """
    from drinkingbird.doctor import diagnose_global, diagnose_local, fix_issues

    if use_global:
        click.echo("Checking all installations...")
        issues = diagnose_global()
    else:
        workspace = get_workspace_root()
        if workspace:
            click.echo(f"Checking workspace: {workspace}")
            issues = diagnose_local(workspace)
        else:
            click.echo("Not in a git repository. Use --global to check all installations.")
            sys.exit(1)

    if not issues:
        click.echo()
        click.echo("No issues found. Installation is healthy.")
        return

    click.echo()
    click.echo(f"Found {len(issues)} issue(s):")
    click.echo()

    for issue in issues:
        click.echo(f"  {issue}")

    if do_fix:
        click.echo()
        click.echo("Applying fixes...")
        fixes = fix_issues(issues)
        for fix in fixes:
            click.echo(f"  ✓ {fix}")
        click.echo()
        click.echo("Fixes applied. Run 'bdb doctor' again to verify.")
    else:
        click.echo()
        click.echo("Run 'bdb doctor --fix' to automatically fix these issues.")


@main.command()
def check() -> None:
    """Validate configuration and connectivity.

    Checks:
    - Config file exists and is valid YAML
    - File permissions are secure (600)
    - API key is configured
    - LLM provider is reachable
    """
    click.echo("Checking configuration...")

    # Check config file
    if not CONFIG_PATH.exists():
        click.echo(f"  Config file: MISSING ({CONFIG_PATH})")
        click.echo("  Run 'bdb init' to create one.")
        sys.exit(1)

    click.echo(f"  Config file: {CONFIG_PATH}")

    # Load and validate config
    try:
        config = load_config()
        click.echo("  Config syntax: OK")
    except ConfigError as e:
        click.echo(f"  Config syntax: FAILED - {e}", err=True)
        sys.exit(1)

    # Check permissions
    mode = CONFIG_PATH.stat().st_mode
    if (mode & 0o077) != 0:
        click.echo("  Permissions: WARNING - file is readable by others")
        click.echo(f"  Run: chmod 600 {CONFIG_PATH}")
    else:
        click.echo("  Permissions: OK (600)")

    # Check API key
    api_key = config.llm.get_api_key()
    if api_key:
        masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
        click.echo(f"  API key: {masked}")
    else:
        click.echo("  API key: NOT CONFIGURED")
        click.echo("  Add api_key or api_key_env to ~/.bdb/config.yaml")

    # Check LLM connectivity
    if api_key:
        click.echo(f"  LLM provider: {config.llm.provider}")
        click.echo(f"  Model: {config.llm.model}")

        # Try a simple API call
        from drinkingbird.supervisor import get_llm_provider

        provider = get_llm_provider(config)
        if provider:
            try:
                response = provider.call(
                    system_prompt="Reply with exactly: {\"status\": \"ok\"}",
                    user_prompt="Test connection",
                    response_schema={
                        "type": "object",
                        "properties": {"status": {"type": "string"}},
                        "required": ["status"],
                        "additionalProperties": False,
                    },
                )
                if response.success:
                    click.echo("  LLM connectivity: OK")
                else:
                    click.echo(f"  LLM connectivity: FAILED - {response.content}")
            except Exception as e:
                click.echo(f"  LLM connectivity: FAILED - {e}")

    # Summary
    click.echo()
    click.echo("Configuration check complete.")


@main.command()
@click.option(
    "--adapter", "-a",
    type=click.Choice(["claude-code", "cline", "cursor", "copilot", "kilo-code", "stdin"]),
    default="claude-code",
    help="Adapter to use for input/output format",
)
@click.option(
    "--debug", "-d",
    is_flag=True,
    help="Enable debug output to stderr",
)
def run(adapter: str, debug: bool) -> None:
    """Run supervisor in stdin/stdout mode.

    Reads hook input from stdin, processes it, and writes
    the result to stdout. This is the main entry point called
    by agent hook systems.
    """
    import os

    from drinkingbird.adapters import (
        ClaudeCodeAdapter,
        ClineAdapter,
        CopilotAdapter,
        CursorAdapter,
        KiloCodeAdapter,
        StdinAdapter,
    )
    from drinkingbird.supervisor import Supervisor

    if debug:
        os.environ["BDB_DEBUG"] = "1"

    adapters = {
        "claude-code": ClaudeCodeAdapter,
        "cline": ClineAdapter,
        "copilot": CopilotAdapter,
        "cursor": CursorAdapter,
        "kilo-code": KiloCodeAdapter,
        "stdin": StdinAdapter,
    }

    adapter_instance = adapters[adapter]()

    # Read input
    try:
        raw_input = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        if debug:
            click.echo(f"Failed to parse JSON: {e}", err=True)
        sys.exit(0)

    # Parse through adapter
    hook_input = adapter_instance.parse_input(raw_input)

    # Run supervisor
    try:
        config = load_config()
    except ConfigError as e:
        if debug:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(0)

    supervisor = Supervisor(config=config, debug_mode=debug)
    result = supervisor.handle(hook_input)

    # Format output through adapter
    output = adapter_instance.format_output(
        result.to_dict(),
        hook_input.get("hook_event_name", ""),
    )

    if output:
        print(json.dumps(output))


@main.command()
@click.argument("hook", type=click.Choice(["stop", "pre-tool", "tool-failure", "pre-compact"]))
@click.option(
    "--transcript", "-t",
    type=click.Path(exists=True),
    help="Path to transcript file (for stop hook)",
)
@click.option(
    "--command", "-c",
    type=str,
    help="Command to test (for pre-tool hook)",
)
@click.option(
    "--error", "-e",
    type=str,
    help="Error message to test (for tool-failure hook)",
)
def test(hook: str, transcript: str | None, command: str | None, error: str | None) -> None:
    """Test a specific hook with sample input.

    Useful for verifying hook behavior without a full agent session.
    """
    from drinkingbird.supervisor import Supervisor

    # Build test input
    hook_map = {
        "stop": "Stop",
        "pre-tool": "PreToolUse",
        "tool-failure": "PostToolUseFailure",
        "pre-compact": "PreCompact",
    }

    event_name = hook_map[hook]
    hook_input: dict = {"hook_event_name": event_name}

    if hook == "stop":
        if transcript:
            hook_input["transcript_path"] = transcript
        else:
            click.echo("Stop hook requires --transcript", err=True)
            sys.exit(1)

    elif hook == "pre-tool":
        if command:
            hook_input["tool_name"] = "Bash"
            hook_input["tool_input"] = {"command": command}
        else:
            click.echo("Pre-tool hook requires --command", err=True)
            sys.exit(1)

    elif hook == "tool-failure":
        if error:
            hook_input["tool_name"] = "Bash"
            hook_input["tool_input"] = {"command": "test"}
            hook_input["tool_response"] = error
        else:
            click.echo("Tool-failure hook requires --error", err=True)
            sys.exit(1)

    elif hook == "pre-compact":
        import os
        hook_input["cwd"] = os.getcwd()

    # Run test
    try:
        config = load_config()
    except ConfigError:
        click.echo("No config found. Using defaults.")
        config = None

    supervisor = Supervisor(config=config, debug_mode=True)
    result = supervisor.handle(hook_input)

    click.echo()
    click.echo(f"Result: {result.decision.value}")
    if result.reason:
        click.echo(f"Reason: {result.reason}")
    if result.message:
        click.echo(f"Message: {result.message}")
    if result.additional_context:
        click.echo(f"Context: {result.additional_context[:200]}...")


@main.group()
def config() -> None:
    """Configuration management commands."""
    pass


@config.command("show")
def config_show() -> None:
    """Show current configuration."""
    if not CONFIG_PATH.exists():
        click.echo(f"No config file found at {CONFIG_PATH}")
        click.echo("Run 'bdb init' to create one.")
        return

    click.echo(CONFIG_PATH.read_text())


@config.command("template")
def config_template() -> None:
    """Print configuration template to stdout."""
    click.echo(generate_template())


@main.command()
@click.option("--global", "use_global", is_flag=True, help="Use global sentinel (~/.bdb/) instead of local")
@click.option("--reason", "-r", type=str, help="Reason for pausing")
def pause(use_global: bool, reason: str | None) -> None:
    """Pause bdb hooks temporarily.

    Creates a sentinel file that causes bdb to bypass all hook checks.
    By default, creates local sentinel in git repos, global otherwise.
    Use --global to force global pause.
    """
    # Determine which sentinel to use
    if use_global:
        sentinel = GLOBAL_SENTINEL
        location = "global"
    else:
        # Default: local if in git repo, global otherwise
        local = get_local_sentinel()
        if local:
            sentinel = local
            location = "local"
        else:
            sentinel = GLOBAL_SENTINEL
            location = "global"

    create_sentinel(sentinel, reason)
    click.echo(f"BDB paused ({location}): {sentinel}")
    if reason:
        click.echo(f"Reason: {reason}")


@main.command()
@click.option("--global", "use_global", is_flag=True, help="Remove global sentinel instead of active one")
def resume(use_global: bool) -> None:
    """Resume bdb hooks.

    Removes the pause sentinel file. By default, removes whichever
    sentinel is currently active (local takes precedence).
    Use --global to specifically remove the global sentinel.
    """
    if use_global:
        sentinel = GLOBAL_SENTINEL
    else:
        # Find active sentinel
        paused, path = is_paused()
        if not paused:
            click.echo("BDB is not paused.")
            return
        sentinel = Path(path)

    if remove_sentinel(sentinel):
        click.echo(f"BDB resumed: removed {sentinel}")
    else:
        click.echo("BDB is not paused.")


if __name__ == "__main__":
    main()
