"""Main supervisor dispatcher for Better Drinking Bird.

This module handles the core dispatch logic - receiving hook events
and routing them to the appropriate hook handlers.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from drinkingbird.config import Config, load_config
from drinkingbird.mode import Mode, get_mode
from drinkingbird.pause import is_paused
from drinkingbird.hooks import (
    Hook,
    HookResult,
    PreCompactHook,
    PreToolHook,
    StopHook,
    ToolFailureHook,
)
from drinkingbird.llm import LLMProvider
from drinkingbird.llm.anthropic import AnthropicProvider
from drinkingbird.llm.azure import AzureOpenAIProvider
from drinkingbird.llm.ollama import OllamaProvider
from drinkingbird.llm.openai import OpenAIProvider
from drinkingbird.tracing import Tracer


def get_llm_provider(config: Config) -> LLMProvider | None:
    """Create LLM provider from config."""
    llm_config = config.llm
    api_key = llm_config.get_api_key()

    # Azure OpenAI needs special handling for deployment/api_version
    if llm_config.provider == "azure":
        return AzureOpenAIProvider(
            api_key=api_key,
            model=llm_config.model,
            base_url=llm_config.base_url,
            timeout=llm_config.timeout,
            deployment=llm_config.deployment,
            api_version=llm_config.api_version,
        )

    providers = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "ollama": OllamaProvider,
    }

    provider_class = providers.get(llm_config.provider)
    if not provider_class:
        return None

    return provider_class(
        api_key=api_key,
        model=llm_config.model,
        base_url=llm_config.base_url,
        timeout=llm_config.timeout,
    )


def get_hook(
    event_name: str,
    config: Config,
    llm_provider: LLMProvider | None,
    tracer: Tracer | None = None,
) -> Hook | None:
    """Get the appropriate hook for an event."""
    hooks_config = config.hooks

    hook_map: dict[str, tuple[type[Hook], Any]] = {
        "Stop": (StopHook, hooks_config.stop),
        "PreToolUse": (PreToolHook, hooks_config.pre_tool),
        "PostToolUseFailure": (ToolFailureHook, hooks_config.tool_failure),
        "PreCompact": (PreCompactHook, hooks_config.pre_compact),
    }

    if event_name not in hook_map:
        return None

    hook_class, hook_config = hook_map[event_name]

    # Check if hook is enabled
    if not getattr(hook_config, "enabled", True):
        return None

    return hook_class(config=hook_config, llm_provider=llm_provider, tracer=tracer)


class Supervisor:
    """Main supervisor that coordinates hooks."""

    def __init__(
        self,
        config: Config | None = None,
        log_dir: Path | None = None,
        debug_mode: bool = False,
    ):
        """Initialize supervisor.

        Args:
            config: Configuration object. If None, loads from default path.
            log_dir: Directory for log files. Defaults to ~/.bdb/
            debug_mode: If True, print debug messages to stderr.
        """
        self.config = config or load_config()
        self.log_dir = log_dir or Path.home() / ".bdb"
        self.debug_mode = debug_mode or os.environ.get("BDB_DEBUG", "") != ""

        self.log_file = self.log_dir / "supervisor.log"
        self.error_file = self.log_dir / "errors.log"

        # Create log directory
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Initialize LLM provider
        self.llm_provider = get_llm_provider(self.config)

        # Initialize tracer
        self.tracer = Tracer(self.config.tracing)

    def debug(self, msg: str, cwd: str | None = None) -> None:
        """Log debug message.

        Args:
            msg: The message to log
            cwd: Optional working directory to include in log
        """
        timestamp = datetime.now().isoformat()
        if cwd:
            log_line = f"[{timestamp}] [{cwd}] {msg}\n"
        else:
            log_line = f"[{timestamp}] {msg}\n"

        try:
            with open(self.log_file, "a") as f:
                f.write(log_line)
        except Exception:
            pass

        if self.debug_mode:
            print(f"[DEBUG] {msg}", file=sys.stderr)

    def log_error(self, msg: str, exc: Exception | None = None) -> None:
        """Log error with full context."""
        timestamp = datetime.now().isoformat()
        lines = [
            f"\n{'='*60}",
            f"[{timestamp}] ERROR: {msg}",
        ]
        if exc:
            lines.append(f"Exception: {type(exc).__name__}: {exc}")
            lines.append("Traceback:")
            lines.append(traceback.format_exc())
        lines.append(f"{'='*60}\n")

        error_msg = "\n".join(lines)
        try:
            with open(self.error_file, "a") as f:
                f.write(error_msg)
        except Exception:
            pass

        self.debug(f"ERROR logged: {msg}")

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Handle a hook event.

        Args:
            hook_input: Input data from the agent/adapter

        Returns:
            HookResult indicating what to do
        """
        event_name = hook_input.get("hook_event_name", "")
        cwd = hook_input.get("cwd") or os.getcwd()
        self.debug(f"Handling event: {event_name}", cwd=cwd)

        # Check if paused FIRST
        paused, sentinel_path = is_paused()
        if paused:
            self.debug(f"BDB paused via {sentinel_path}", cwd=cwd)
            return HookResult.allow("BDB is paused")

        # Check mode - interactive mode skips Stop hook (safety hooks still run)
        mode = get_mode()
        if event_name == "Stop" and mode == Mode.INTERACTIVE:
            self.debug("Interactive mode - allowing stop", cwd=cwd)
            return HookResult.allow("Interactive mode")

        # Get appropriate hook (pass tracer for LLM tracing)
        hook = get_hook(event_name, self.config, self.llm_provider, self.tracer)

        if hook is None:
            self.debug(f"No handler for event: {event_name}", cwd=cwd)
            return HookResult.allow(f"No handler for {event_name}")

        # Execute hook within trace context
        trace_metadata = {
            "hook": event_name,
            "llm_provider": self.config.llm.provider,
            "llm_model": self.config.llm.model,
        }

        with self.tracer.trace(f"bdb_{event_name.lower()}", metadata=trace_metadata):
            try:
                result = hook.handle(hook_input, self.debug)
                self.debug(f"Hook result: {result.decision.value}", cwd=cwd)

                # Log decision as score
                self.tracer.score(
                    name="decision",
                    value=result.decision.value,
                    comment=result.reason,
                )

                return result
            except Exception as e:
                self.log_error(f"Hook {event_name} failed", e)
                self.tracer.event(
                    name="hook_error",
                    metadata={"error": str(e), "hook": event_name},
                    level="ERROR",
                )
                return HookResult.allow(f"Hook failed: {e}")

    def run_stdin(self) -> None:
        """Run supervisor reading from stdin, writing to stdout.

        This is the main entry point for hook execution.
        """
        hook_input = {}
        event_name = "unknown"

        try:
            # Parse input
            try:
                hook_input = json.load(sys.stdin)
            except json.JSONDecodeError as e:
                self.log_error("Failed to parse JSON from stdin", e)
                sys.exit(0)

            event_name = hook_input.get("hook_event_name", "")
            self.debug(f"Supervisor started: {event_name}")

            # Handle the event
            result = self.handle(hook_input)

            # Output result if needed
            output = result.to_dict()
            if output:
                print(json.dumps(output))

            sys.exit(0)

        except SystemExit:
            raise

        except Exception as e:
            self.log_error(f"Unhandled exception in {event_name}", e)

            # Log the input that caused the problem
            try:
                with open(self.error_file, "a") as f:
                    f.write(f"Hook input was: {json.dumps(hook_input, indent=2)}\n")
            except Exception:
                pass

            # Always exit cleanly
            sys.exit(0)


def run() -> None:
    """Entry point for running supervisor from CLI."""
    try:
        supervisor = Supervisor()
        supervisor.run_stdin()
    except SystemExit:
        raise
    except Exception as e:
        # Last resort - never crash
        try:
            error_file = Path.home() / ".bdb" / "errors.log"
            error_file.parent.mkdir(parents=True, exist_ok=True)
            with open(error_file, "a") as f:
                f.write(f"\n[{datetime.now().isoformat()}] CRITICAL: {e}\n")
                f.write(traceback.format_exc())
        except Exception:
            pass
        sys.exit(0)
