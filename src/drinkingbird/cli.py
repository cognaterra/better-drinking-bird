"""CLI for Better Drinking Bird."""

from __future__ import annotations

import json
import re
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
from drinkingbird.mode import (
    GLOBAL_MODE_PATH,
    Mode,
    clear_mode,
    get_local_mode_path,
    get_mode_info,
    set_mode,
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
@click.argument("agent", type=click.Choice(["claude-code", "cline", "cursor", "copilot", "kilo-code", "stdin", "windsurf"]))
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
    from drinkingbird.adapters import ADAPTER_MAP
    from drinkingbird.manifest import Manifest

    adapter_class = ADAPTER_MAP[agent]
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
        return

    try:
        success = adapter.install(Path(bdb_path), scope=scope, workspace=workspace)
        if success:
            click.echo(f"Installed hooks for {agent} ({scope})")

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
@click.argument("agent", type=click.Choice(["claude-code", "cline", "cursor", "copilot", "kilo-code", "stdin", "windsurf"]), required=False)
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
    from drinkingbird.adapters import ADAPTER_MAP
    from drinkingbird.manifest import Manifest

    if uninstall_all and agent:
        click.echo("Cannot specify both --all and an agent", err=True)
        sys.exit(1)

    if not uninstall_all and not agent:
        click.echo("Either specify an agent or use --all", err=True)
        sys.exit(1)

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
                click.echo(f"  - {inst.agent} ({inst.scope})")
            return

        for inst in installations:
            if inst.agent not in ADAPTER_MAP:
                click.echo(f"Unknown agent {inst.agent}, skipping", err=True)
                continue

            adapter = ADAPTER_MAP[inst.agent]()
            workspace = Path(inst.path).parent.parent if inst.scope == "local" else None

            try:
                success = adapter.uninstall(scope=inst.scope, workspace=workspace)
                if success:
                    click.echo(f"Uninstalled {inst.agent} ({inst.scope})")
                    manifest.remove(agent=inst.agent, scope=inst.scope, path=inst.path)
                else:
                    click.echo(f"No hooks found for {inst.agent} ({inst.scope})")
                    # Still remove from manifest if file doesn't exist
                    manifest.remove(agent=inst.agent, scope=inst.scope, path=inst.path)
            except Exception as e:
                click.echo(f"Error uninstalling {inst.agent}: {e}", err=True)

        manifest.save()
        return

    # Single agent uninstall
    adapter_class = ADAPTER_MAP[agent]
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
        return

    try:
        success = adapter.uninstall(scope=scope, workspace=workspace)
        if success:
            click.echo(f"Uninstalled hooks for {agent} ({scope})")

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
    from drinkingbird.adapters import ADAPTER_MAP

    agents_info = [
        ("claude-code", ADAPTER_MAP["claude-code"](), "Claude Code editor", "Native hooks"),
        ("cursor", ADAPTER_MAP["cursor"](), "Cursor editor", "Script-based hooks"),
        ("copilot", ADAPTER_MAP["copilot"](), "GitHub Copilot", "Shell command hooks"),
        ("cline", ADAPTER_MAP["cline"](), "Cline VS Code extension", "Script hooks"),
        ("kilo-code", ADAPTER_MAP["kilo-code"](), "Kilo Code extension", "Native hooks"),
        ("stdin", ADAPTER_MAP["stdin"](), "Generic stdin/stdout", "Piped JSON"),
        ("windsurf", ADAPTER_MAP["windsurf"](), "Windsurf (Codeium) editor", "Cascade hooks"),
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

    Displays a concise summary of configuration, installations, and issues.
    Use --global to see all installations, --fix to repair issues,
    or --test-connection to verify LLM API connectivity.
    """
    from drinkingbird.doctor import diagnose_global, diagnose_local, fix_issues
    from drinkingbird.manifest import Manifest

    ensure_config()

    # Build summary line: version | mode | config | LLM | pause
    parts = [f"bdb v{__version__}"]

    current_mode, _mode_source = get_mode_info()
    parts.append(current_mode.value)

    config = None
    try:
        config = load_config()
        config_ok = True
    except ConfigError:
        config_ok = False

    if not config_ok:
        parts.append(click.style("config: FAIL", fg="red"))
    elif (CONFIG_PATH.stat().st_mode & 0o077) != 0:
        parts.append(click.style("config: perms!", fg="yellow"))

    if config:
        api_key = config.llm.get_api_key()
        if api_key:
            parts.append(click.style("llm: ok", fg="green"))
        else:
            parts.append(click.style("llm: none", fg="yellow"))

    paused, _sentinel_path = is_paused()
    if paused:
        parts.append(click.style("PAUSED", fg="yellow", bold=True))

    click.echo(" | ".join(parts))

    # Test LLM connectivity if requested
    if test_connection:
        if config and config.llm.get_api_key():
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
                        click.secho("  connection: ok", fg="green")
                    else:
                        click.secho("  connection: FAIL", fg="red")
                except Exception:
                    click.secho("  connection: FAIL", fg="red")
        else:
            click.secho("  connection: no api key", fg="yellow")

    # Installations
    manifest = Manifest.load()
    workspace = get_workspace_root()

    if workspace:
        active_scope = "local"
        active_path = str(workspace)
    else:
        active_scope = "global"
        active_path = None

    if use_global:
        installations = manifest.get()
    else:
        installations = manifest.get(scope=active_scope)
        if active_scope == "local" and active_path:
            installations = [i for i in installations if active_path in i.path]

    # Clean stale entries silently
    live = []
    dirty = False
    for inst in installations:
        if not Path(inst.path).exists():
            manifest.remove(path=inst.path)
            dirty = True
        else:
            live.append(inst)
    if dirty:
        manifest.save()

    if not live:
        click.echo("No agents installed. Run: bdb install <agent>")
    else:
        agents_str = ", ".join(
            f"{inst.agent} ({inst.scope})" for inst in live
        )
        click.echo(f"Agents: {agents_str}")

    # Health
    if use_global:
        issues = diagnose_global()
    else:
        issues = diagnose_local(workspace) if workspace else diagnose_global()

    if issues:
        for issue in issues:
            click.secho(f"  ! {issue}", fg="red")
        if do_fix:
            fixes = fix_issues(issues)
            for fix in fixes:
                click.secho(f"  ✓ {fix}", fg="green")
        else:
            click.echo("  Run 'bdb status --fix' to repair.")






@main.command()
@click.option(
    "--adapter", "-a",
    type=click.Choice(["claude-code", "cline", "cursor", "copilot", "kilo-code", "stdin", "windsurf"]),
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

    from drinkingbird.adapters import ADAPTER_MAP
    from drinkingbird.supervisor import Supervisor

    if debug:
        os.environ["BDB_DEBUG"] = "1"

    adapter_instance = ADAPTER_MAP[adapter]()

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

    # Handle exit codes for adapters that use them (e.g., Windsurf)
    exit_code = output.pop("_windsurf_exit_code", None) if output else None
    windsurf_message = output.pop("_windsurf_message", None) if output else None

    # For Windsurf, print human-readable message instead of JSON
    if windsurf_message:
        print(windsurf_message)
    elif output:
        print(json.dumps(output))

    # Exit with appropriate code for adapters that use exit codes for blocking
    if exit_code is not None:
        sys.exit(exit_code)


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
    """Show current configuration (secrets redacted)."""
    content = ensure_config().read_text()
    click.echo(re.sub(r"((?:api_key|secret_key|secret|password|token)\s*:\s*)\S+", r"\1***", content))


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
        click.echo(f"No {log_type} log found. Logs are created when hooks are triggered.")
        return

    if tail:
        # Use tail -f for following
        click.echo("Following log (Ctrl+C to stop)")
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
    click.echo(f"BDB paused ({location})")
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
        click.echo("BDB resumed.")
    else:
        click.echo("BDB is not paused.")


@main.command("mode")
@click.argument("new_mode", type=click.Choice(["default", "auto", "interactive"]), required=False)
@click.option("--global", "use_global", is_flag=True, help="Set/clear global mode instead of local")
@click.option("--clear", "do_clear", is_flag=True, help="Clear mode file (revert to default)")
def mode_cmd(new_mode: str | None, use_global: bool, do_clear: bool) -> None:
    """Get or set BDB supervision mode.

    \b
    Modes:
      default      LLM infers session type and decision
      auto         Same as default
      interactive  Stop hook returns ALLOW (safety hooks still run)

    \b
    Examples:
      bdb mode                  # Show current mode
      bdb mode interactive      # Set local mode to interactive
      bdb mode --global auto    # Set global mode to auto
      bdb mode --clear          # Clear local mode file
    """
    if do_clear:
        scope = "global" if use_global else "local"
        path = clear_mode(use_global=use_global)
        if path:
            click.echo(f"Mode cleared ({scope})")
        else:
            click.echo(f"No {scope} mode to clear.")
        return

    if new_mode is None:
        # Show current mode
        current_mode, source = get_mode_info()
        click.echo(f"Mode: {current_mode.value}")
        if source:
            scope = "global" if "/.bdb/" in str(source) else "local"
            click.echo(f"Source: {scope}")
        else:
            click.echo("Source: default")
        return

    # Set mode
    try:
        mode_enum = Mode(new_mode)
        set_mode(mode_enum, use_global=use_global)
        scope = "global" if use_global else "local"
        click.echo(f"Mode set to {new_mode} ({scope})")
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
