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

    Creates ~/.bdbrc with default settings and secure permissions.
    """
    if CONFIG_PATH.exists() and not force:
        click.echo(f"Config file already exists: {CONFIG_PATH}")
        click.echo("Use --force to overwrite.")
        sys.exit(1)

    path = save_template()
    click.echo(f"Created config file: {path}")
    click.echo("Edit this file to configure your API keys and settings.")
    click.echo()
    click.echo("Quick start:")
    click.echo("  1. Add your API key to ~/.bdbrc")
    click.echo("  2. Run: bdb install claude-code")
    click.echo("  3. Start using Claude Code as normal")


@main.command()
@click.argument("agent", type=click.Choice(["claude-code", "cursor", "copilot", "stdin"]))
@click.option(
    "--dry-run", "-n",
    is_flag=True,
    help="Show what would be done without making changes",
)
def install(agent: str, dry_run: bool) -> None:
    """Install hooks for an AI coding agent.

    Configures the specified agent to use Better Drinking Bird
    as its hook supervisor.
    """
    from drinkingbird.adapters import (
        ClaudeCodeAdapter,
        CopilotAdapter,
        CursorAdapter,
        StdinAdapter,
    )

    adapters = {
        "claude-code": ClaudeCodeAdapter,
        "cursor": CursorAdapter,
        "copilot": CopilotAdapter,
        "stdin": StdinAdapter,
    }

    adapter_class = adapters[agent]
    adapter = adapter_class()

    # Find bdb executable
    bdb_path = shutil.which("bdb")
    if not bdb_path:
        # Fallback to python -m bdb
        bdb_path = f"{sys.executable} -m bdb"

    if dry_run:
        click.echo(f"Would install hooks for {agent}")
        click.echo(f"Config path: {adapter.get_config_path()}")
        click.echo(f"Install config:")
        click.echo(json.dumps(adapter.get_install_config(), indent=2))
        return

    try:
        success = adapter.install(Path(bdb_path))
        if success:
            click.echo(f"Installed hooks for {agent}")
            click.echo(f"Config updated: {adapter.get_config_path()}")
        else:
            click.echo(f"Failed to install hooks for {agent}", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"Error installing hooks: {e}", err=True)
        sys.exit(1)


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
        click.echo("  Add api_key or api_key_env to ~/.bdbrc")

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
    type=click.Choice(["claude-code", "cursor", "copilot", "stdin"]),
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
        CopilotAdapter,
        CursorAdapter,
        StdinAdapter,
    )
    from drinkingbird.supervisor import Supervisor

    if debug:
        os.environ["BDB_DEBUG"] = "1"

    adapters = {
        "claude-code": ClaudeCodeAdapter,
        "cursor": CursorAdapter,
        "copilot": CopilotAdapter,
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


if __name__ == "__main__":
    main()
