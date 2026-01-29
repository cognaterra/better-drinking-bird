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
    ensure_config,
    generate_template,
    load_config,
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

    # Ensure BDB config exists (auto-create if needed)
    bdb_config_path = ensure_config()

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
            click.echo()
            click.echo(f"BDB config: {bdb_config_path}")
            click.echo("Edit this file to add your API key if not already configured.")

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
def agents() -> None:
    """List supported AI coding agents.

    Shows all agents that BDB can integrate with, along with their
    integration method and local installation support.
    """
    from drinkingbird.adapters import (
        ClaudeCodeAdapter,
        ClineAdapter,
        CopilotAdapter,
        CursorAdapter,
        KiloCodeAdapter,
        StdinAdapter,
    )

    agents_info = [
        ("claude-code", ClaudeCodeAdapter(), "Claude Code editor", "Native hooks"),
        ("cursor", CursorAdapter(), "Cursor editor", "Script-based hooks"),
        ("copilot", CopilotAdapter(), "GitHub Copilot", "Shell command hooks"),
        ("cline", ClineAdapter(), "Cline VS Code extension", "Script hooks"),
        ("kilo-code", KiloCodeAdapter(), "Kilo Code extension", "Native hooks"),
        ("stdin", StdinAdapter(), "Generic stdin/stdout", "Piped JSON"),
    ]

    click.echo("Supported Agents")
    click.echo("=" * 50)
    click.echo()

    for name, adapter, description, method in agents_info:
        local_support = "✓" if adapter.supports_local else "-"
        click.echo(f"  {name:<12} {description}")
        click.echo(f"               Method: {method}")
        click.echo(f"               Local install: {local_support}")
        click.echo()

    click.echo("Usage:")
    click.echo("  bdb install <agent>    Install hooks for an agent")
    click.echo("  bdb uninstall <agent>  Remove hooks from an agent")


@main.command()
@click.option(
    "--global",
    "use_global",
    is_flag=True,
    help="Show all installations (not just current workspace)",
)
@click.option(
    "--fix",
    "do_fix",
    is_flag=True,
    help="Automatically fix detected issues",
)
@click.option(
    "--test-connection",
    is_flag=True,
    help="Test LLM API connectivity",
)
def status(use_global: bool, do_fix: bool, test_connection: bool) -> None:
    """Show BDB status and health.

    Displays configuration, installations, and any detected issues.

    \b
    By default, shows only the current workspace:
    - Local installations if in a git repository
    - Global installations otherwise

    Use --global to see all installations.
    Use --fix to automatically repair detected issues.
    Use --test-connection to verify LLM API connectivity.
    """
    from drinkingbird.doctor import diagnose_global, diagnose_local, fix_issues
    from drinkingbird.manifest import Installation, Manifest

    click.echo("BDB Status")
    click.echo("=" * 40)

    # Show pause status first
    paused, sentinel_path = is_paused()
    if paused:
        click.secho("⏸  PAUSED", fg="yellow", bold=True)
        if sentinel_path:
            click.echo(f"   {sentinel_path}")
        click.echo()

    # Config section
    click.echo("Config")
    click.echo("-" * 40)
    config_path = ensure_config()
    click.echo(f"  File: {config_path}")

    try:
        config = load_config()
        click.secho("  Syntax: OK", fg="green")
    except ConfigError as e:
        click.secho(f"  Syntax: FAILED - {e}", fg="red")
        config = None

    if config:
        # Check permissions
        mode = CONFIG_PATH.stat().st_mode
        if (mode & 0o077) != 0:
            click.secho("  Permissions: WARNING - readable by others", fg="yellow")
        else:
            click.echo("  Permissions: OK (600)")

        # Show API key status
        api_key = config.llm.get_api_key()
        if api_key:
            masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
            click.echo(f"  API key: {masked}")
            click.echo(f"  Provider: {config.llm.provider}")
            click.echo(f"  Model: {config.llm.model}")
        else:
            click.secho("  API key: NOT CONFIGURED", fg="yellow")
            click.echo("  (Hooks will allow all actions without supervision)")

        # Test LLM connectivity if requested
        if test_connection and api_key:
            click.echo()
            click.echo("Testing LLM connection...")
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
                        click.secho("  Connection: OK", fg="green")
                    else:
                        click.secho(f"  Connection: FAILED - {response.content}", fg="red")
                except Exception as e:
                    click.secho(f"  Connection: FAILED - {e}", fg="red")
        elif test_connection and not api_key:
            click.secho("  Cannot test connection: no API key configured", fg="yellow")

    # Installations section
    click.echo()
    click.echo("Installations")
    click.echo("-" * 40)

    manifest = Manifest.load()
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
        if active_scope == "local" and active_path:
            installations = [i for i in installations if active_path in i.path]

    # Clean up missing installations and group by agent
    by_agent: dict[str, list] = {}
    removed_count = 0
    for inst in installations:
        if not Path(inst.path).exists():
            manifest.remove(path=inst.path)
            removed_count += 1
            continue
        if inst.agent not in by_agent:
            by_agent[inst.agent] = []
        by_agent[inst.agent].append(inst)

    if removed_count > 0:
        manifest.save()
        click.secho(f"  Cleaned up {removed_count} stale installation(s)", fg="yellow")

    if not by_agent:
        click.echo("  No installations found.")
        click.echo()
        click.echo("  To install hooks, run:")
        click.echo("    bdb install claude-code")
    else:
        for agent in sorted(by_agent.keys()):
            for inst in by_agent[agent]:
                date_str = inst.installed_at[:10] if inst.installed_at else "unknown"
                line = f"  ✓ {agent} ({inst.scope}): {inst.path}"

                if use_global and is_active(inst):
                    click.secho(line, fg="cyan")
                else:
                    click.echo(line)
                click.echo(f"      installed: {date_str}")

        total = sum(len(insts) for insts in by_agent.values())
        click.echo()
        click.echo(f"  Total: {total} installation(s)")

    # Health check section
    click.echo()
    click.echo("Health")
    click.echo("-" * 40)

    if use_global:
        issues = diagnose_global()
    else:
        if workspace:
            issues = diagnose_local(workspace)
        else:
            issues = diagnose_global()

    if not issues:
        click.secho("  No issues found.", fg="green")
    else:
        click.echo(f"  Found {len(issues)} issue(s):")
        for issue in issues:
            click.echo(f"    {issue}")

        if do_fix:
            click.echo()
            click.echo("  Applying fixes...")
            fixes = fix_issues(issues)
            for fix in fixes:
                click.secho(f"    ✓ {fix}", fg="green")
        else:
            click.echo()
            click.echo("  Run 'bdb status --fix' to repair these issues.")






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

    \b
    Examples:
      bdb test stop --transcript ./conversation.jsonl
      bdb test pre-tool --command "git reset --hard"
      bdb test tool-failure --error "command not found"
      bdb test pre-compact

    \b
    Transcript format (JSONL, one message per line):
      {"role": "user", "content": "..."}
      {"role": "assistant", "content": "..."}
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
    config_path = ensure_config()
    click.echo(config_path.read_text())


@config.command("template")
def config_template() -> None:
    """Print configuration template to stdout."""
    click.echo(generate_template())


@config.command("edit")
def config_edit() -> None:
    """Open configuration in your default editor.

    Uses the EDITOR or VISUAL environment variable to determine
    which editor to use. Falls back to system default if not set.
    """
    config_path = ensure_config()
    click.edit(filename=str(config_path))


@main.command()
@click.option("--tail", "-f", is_flag=True, help="Follow log output (like tail -f)")
@click.option("--errors", "-e", is_flag=True, help="Show error log instead of main log")
@click.option("--lines", "-n", default=50, help="Number of lines to show")
def logs(tail: bool, errors: bool, lines: int) -> None:
    """View BDB logs.

    Shows recent log entries from the BDB supervisor log.

    \b
    Examples:
      bdb logs              # Show last 50 lines
      bdb logs -n 100       # Show last 100 lines
      bdb logs --errors     # Show error log
      bdb logs --tail       # Follow log output
    """
    import subprocess

    try:
        config = load_config()
        if errors:
            log_path = config.logging.get_error_log_path()
        else:
            log_path = config.logging.get_log_path()
    except ConfigError:
        # Use defaults if config fails to load
        log_dir = Path.home() / ".bdb"
        log_path = log_dir / ("errors.log" if errors else "supervisor.log")

    if not log_path.exists():
        log_type = "error" if errors else "supervisor"
        click.echo(f"No {log_type} log found at {log_path}")
        click.echo("Logs are created when BDB hooks are triggered.")
        return

    if tail:
        # Use tail -f for following
        click.echo(f"Following {log_path} (Ctrl+C to stop)")
        try:
            subprocess.run(["tail", "-f", str(log_path)], check=True)
        except KeyboardInterrupt:
            pass
    else:
        # Show last N lines
        try:
            result = subprocess.run(
                ["tail", "-n", str(lines), str(log_path)],
                capture_output=True,
                text=True,
                check=True,
            )
            click.echo(result.stdout)
        except subprocess.CalledProcessError:
            # Fallback: read file directly
            with open(log_path) as f:
                all_lines = f.readlines()
                for line in all_lines[-lines:]:
                    click.echo(line, nl=False)


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
