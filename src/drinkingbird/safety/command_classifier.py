"""LLM-based command safety classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from drinkingbird.llm.base import LLMProvider

# Patterns that trigger LLM classification
NEEDS_LLM_PATTERNS = [
    # Git history commands (intent-dependent)
    r"git\s+log\b(?!.*--oneline\s+-\d+$)",
    r"git\s+show\s+HEAD~",
    r"git\s+diff\s+HEAD~",
    r"git\s+blame\b",
    # Obfuscation indicators
    r"base64\s+(-d|--decode)",
    r"xxd\s+-r",
    r'exec\s*\([^)]*decode',
    r"eval\s+\$\(",
    # Remote execution patterns
    r"curl\s+[^|]+\|\s*(bash|sh|zsh)",
    r"wget\s+[^|]+\|\s*(bash|sh|zsh)",
    r"curl.*-o\s*-.*\|\s*(bash|sh)",
]

# Commands that are always safe (skip LLM)
ALWAYS_ALLOWED_PATTERNS = [
    r"git\s+log\s+--oneline\s+-\d+$",
    r"git\s+status\b",
    r"git\s+diff\b(?!.*HEAD~)",
    r"git\s+show\s+HEAD\b(?!~)",
]

SYSTEM_PROMPT = """You are a safety supervisor for an AI coding agent's bash commands. Analyze commands for safety issues.

## Categories to Check

### 1. Git History Debugging (category: "git_history")
ALLOW:
- Getting commit history for writing commit messages (style matching)
- PR context gathering
- General history exploration (learning, not debugging)
- Understanding how something was implemented

BLOCK:
- Using HEAD~N to find "what broke" or "what changed"
- Debugging by comparing to previous states
- Root cause analysis via history ("when did this start failing?")
- Bisecting to find when bugs were introduced

Blocking signals: bug, broke, broken, failing, error, issue, fix, debug, regression, bisect in conversation context

### 2. Obfuscated Commands (category: "obfuscation")
BLOCK commands that hide their true intent:
- Base64/hex encoded payloads being decoded and executed
- eval with encoded strings
- Nested encoding to obscure commands
- Any attempt to bypass detection via encoding

### 3. Remote Code Execution (category: "remote_execution")
BLOCK:
- Piping curl/wget directly to shell (bash, sh, zsh)
- Downloading and immediately executing without inspection

ALLOW:
- Downloading scripts to files for inspection
- Fetching data (not scripts) from trusted sources

### 4. Other Safety Issues (category: "other")
BLOCK anything that appears to be:
- Attempting to bypass safety measures
- Hiding malicious intent through clever syntax
- Exploiting edge cases in command parsing

## Response Format
Respond with JSON:
{
  "decision": "allow" | "block",
  "category": "git_history" | "obfuscation" | "remote_execution" | "other" | "none",
  "reason": "brief explanation",
  "message": "message to agent if blocking"
}"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["allow", "block"],
        },
        "category": {
            "type": "string",
            "enum": ["git_history", "obfuscation", "remote_execution", "other", "none"],
        },
        "reason": {"type": "string"},
        "message": {"type": "string"},
    },
    "required": ["decision", "category", "reason", "message"],
    "additionalProperties": False,
}


@dataclass
class ClassificationResult:
    """Result of command safety classification."""

    is_blocked: bool
    category: str
    reason: str
    message: str


def needs_llm_classification(command: str) -> bool:
    """Check if command needs LLM classification."""
    # First check if it's always allowed
    for pattern in ALWAYS_ALLOWED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False

    # Then check if it matches patterns needing LLM review
    for pattern in NEEDS_LLM_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True

    return False


def _build_classification_prompt(
    command: str,
    transcript_path: str | None,
) -> str:
    """Build the user prompt for classification."""
    parts = [f"=== COMMAND ===\n{command}"]

    if transcript_path:
        try:
            context = _extract_recent_context(transcript_path)
            if context:
                parts.append(f"\n=== CONVERSATION CONTEXT ===\n{context}")
        except Exception:
            pass

    return "\n".join(parts)


def _extract_recent_context(transcript_path: str, max_chars: int = 2000) -> str:
    """Extract recent conversation context from transcript."""
    import json
    from pathlib import Path

    path = Path(transcript_path)
    if not path.exists():
        return ""

    messages = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    messages.append(json.loads(line))
    except Exception:
        return ""

    # Get last few messages, focusing on user and assistant content
    context_parts = []
    char_count = 0

    for msg in reversed(messages[-10:]):
        role = msg.get("role", "")
        content = msg.get("content", "")

        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )

        if role in ("user", "assistant") and content:
            snippet = f"{role}: {content[:500]}"
            if char_count + len(snippet) > max_chars:
                break
            context_parts.insert(0, snippet)
            char_count += len(snippet)

    return "\n".join(context_parts)


def classify_command(
    command: str,
    transcript_path: str | None,
    llm_provider: LLMProvider | None,
    debug: Callable[[str], None],
    fallback: str = "block",
) -> ClassificationResult:
    """Classify a command for safety using LLM.

    Args:
        command: The bash command being executed
        transcript_path: Path to conversation transcript for context
        llm_provider: LLM provider for classification
        debug: Debug logging function
        fallback: Behavior when LLM unavailable ("block" or "allow")

    Returns:
        ClassificationResult with decision
    """
    # Fallback when no LLM configured
    if llm_provider is None or not llm_provider.is_configured():
        debug(f"No LLM configured, using fallback: {fallback}")
        if fallback == "allow":
            return ClassificationResult(
                is_blocked=False,
                category="none",
                reason="No LLM configured, fallback to allow",
                message="",
            )
        return ClassificationResult(
            is_blocked=True,
            category="none",
            reason="No LLM configured, fallback to block",
            message="Command requires LLM classification but none configured.",
        )

    # Build prompt with context
    user_prompt = _build_classification_prompt(command, transcript_path)
    debug(f"Classification prompt: {user_prompt[:200]}...")

    try:
        response = llm_provider.call(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=RESPONSE_SCHEMA,
        )

        content = response.content
        decision = content.get("decision", "block")
        category = content.get("category", "other")
        reason = content.get("reason", "Unknown")
        message = content.get("message", "Command blocked.")

        debug(f"LLM decision: {decision} ({category}) - {reason}")

        return ClassificationResult(
            is_blocked=(decision == "block"),
            category=category,
            reason=reason,
            message=message,
        )

    except Exception as e:
        debug(f"LLM classification failed: {e}, falling back to block")
        return ClassificationResult(
            is_blocked=True,
            category="other",
            reason=f"LLM classification failed: {e}",
            message="Classification failed. Command blocked for safety.",
        )
