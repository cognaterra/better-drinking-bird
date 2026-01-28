"""Langfuse tracing integration for Better Drinking Bird."""

from __future__ import annotations

import atexit
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langfuse import Langfuse
    from langfuse.client import StatefulSpanClient, StatefulTraceClient

    from drinkingbird.config import TracingConfig

# Global Langfuse client (lazily initialized)
_langfuse_client: Langfuse | None = None


def init_langfuse(config: TracingConfig) -> Langfuse | None:
    """Initialize the Langfuse client if tracing is enabled and configured.

    Args:
        config: Tracing configuration

    Returns:
        Langfuse client if configured, None otherwise
    """
    global _langfuse_client

    if _langfuse_client is not None:
        return _langfuse_client

    if not config.is_configured():
        return None

    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=config.get_public_key(),
            secret_key=config.get_secret_key(),
            host=config.host,
        )

        # Ensure traces are flushed on exit
        atexit.register(_flush_langfuse)

        return _langfuse_client
    except ImportError:
        return None
    except Exception:
        return None


def _flush_langfuse() -> None:
    """Flush pending traces on exit."""
    global _langfuse_client
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
        except Exception:
            pass


def get_langfuse() -> Langfuse | None:
    """Get the current Langfuse client."""
    return _langfuse_client


class Tracer:
    """Wrapper for Langfuse tracing operations."""

    def __init__(self, config: TracingConfig):
        """Initialize tracer.

        Args:
            config: Tracing configuration
        """
        self.config = config
        self.client = init_langfuse(config)
        self._current_trace: StatefulTraceClient | None = None
        self._current_span: StatefulSpanClient | None = None

    @property
    def enabled(self) -> bool:
        """Check if tracing is enabled and configured."""
        return self.client is not None

    @contextmanager
    def trace(self, name: str, metadata: dict[str, Any] | None = None):
        """Create a trace context for a hook invocation.

        Args:
            name: Trace name (e.g., "stop_hook", "tool_failure_hook")
            metadata: Optional metadata to attach to the trace

        Yields:
            The trace object (or None if tracing is disabled)
        """
        if not self.enabled:
            yield None
            return

        trace = self.client.trace(
            name=name,
            metadata=metadata or {},
        )
        self._current_trace = trace

        try:
            yield trace
        finally:
            self._current_trace = None
            # Flush to ensure trace is sent
            if self.client:
                self.client.flush()

    def generation(
        self,
        name: str,
        model: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any] | None = None,
        usage: dict[str, int] | None = None,
        metadata: dict[str, Any] | None = None,
        level: str = "DEFAULT",
    ) -> None:
        """Log an LLM generation within the current trace.

        Args:
            name: Generation name (e.g., "evaluate_stop_decision")
            model: Model identifier (e.g., "gpt-4o-mini", "claude-3-5-haiku-20241022")
            input_data: Input prompts/messages
            output_data: Model output
            usage: Token usage dict with keys: input, output, total
            metadata: Optional metadata
            level: Log level (DEFAULT, DEBUG, WARNING, ERROR)
        """
        if not self.enabled or not self._current_trace:
            return

        generation_params = {
            "name": name,
            "model": model,
            "input": input_data,
            "metadata": metadata or {},
            "level": level,
        }

        if output_data is not None:
            generation_params["output"] = output_data

        if usage:
            generation_params["usage"] = {
                "input": usage.get("input", 0),
                "output": usage.get("output", 0),
                "total": usage.get("total", usage.get("input", 0) + usage.get("output", 0)),
            }

        self._current_trace.generation(**generation_params)

    def event(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
        level: str = "DEFAULT",
    ) -> None:
        """Log an event within the current trace.

        Args:
            name: Event name
            metadata: Optional metadata
            level: Log level
        """
        if not self.enabled or not self._current_trace:
            return

        self._current_trace.event(
            name=name,
            metadata=metadata or {},
            level=level,
        )

    def score(
        self,
        name: str,
        value: float | int | str,
        comment: str | None = None,
    ) -> None:
        """Add a score to the current trace.

        Args:
            name: Score name (e.g., "decision", "confidence")
            value: Score value
            comment: Optional comment
        """
        if not self.enabled or not self._current_trace:
            return

        score_params = {
            "name": name,
            "value": value,
        }
        if comment:
            score_params["comment"] = comment

        self._current_trace.score(**score_params)
