"""Stop Hook - Decides whether to allow agent to stop or nudge it back to work."""

from __future__ import annotations

import json
import os
import re
import signal
from typing import Any

from drinkingbird.hooks.base import DebugFn, Decision, Hook, HookResult

# Standard project files that don't count as implementation specs
IGNORED_DOC_FILES = {"CLAUDE.md", "AGENTS.md", "README.md"}


SYSTEM_PROMPT = """You supervise an AI coding agent. When the agent wants to \
stop, you decide whether to allow it.

You receive: the user's original intent, any referenced documents (the \
spec/plan the agent is executing), and the agent's most recent response.

## Step 1: Does the user want the agent to stop?

Read the most recent user message. ALLOW immediately if either:

- The user explicitly said to stop, approved stopping, or indicated the work \
is done ("stop", "that's fine", "don't block", "done", "ship it", etc.)
- The user asked a question — not assigned a task — and the agent answered it

If neither applies, proceed to Step 2.

## Step 2: Evaluate against the user's goal

The user's original intent + referenced documents define the goal. The agent's \
claims about completion are not authoritative — measure against the documented \
goal.

Only flag signals that relate to work the user asked for. Ignore pre-existing \
failures or codebase issues outside the plan scope.

Detect any of the following:

### False completion
The agent is stopping before the documented goal is fully met. The act of \
stopping IS the completion claim — the agent does not need to say "I'm done" \
or "work is complete." If it is stopping and any of the following are present, \
it is false completion:
- Progress metrics below 100% — "3/19 passing", "16%", "51.6% complete"
- Remaining work — open tasks, failing tests, unimplemented items, \
placeholder implementations, stubs, TODO markers
- Deferral — "next steps would be", "future session", "resume later", \
describing what would need to happen to finish
- Rationalizing partial completion — "significant progress", \
"solid foundation", "main blocker", "blocked by", "due to complexity"
- Phased framing — calling work a "phase" or "stage" while more phases remain
- Task lists with unchecked items, failure markers
- Session summaries — wrapping up, recapping work done, listing commits so far \
(NOTE: reporting a final deliverable — PR URL, commit hash — with no remaining \
work is completion, not a session summary)

### Work evasion
The agent has been assigned work and is not doing it:
- Offering or proposing to do the work instead of doing it — "I can implement \
this", "I could fix", "offered to implement", "I would add"
- Permission-seeking — "would you like me to", "shall I proceed", \
"ready to proceed", "let me know", "how would you like", "which direction", \
"which path should I take"
- Presenting a menu of options — numbered lists of choices ("1. Merge locally \
2. Create a PR 3. Keep the branch"), asking the user to pick a direction. \
The agent always has instructions — a skill, a plan, a user instruction. \
There is no valid scenario where a menu is the correct response. BLOCK with: \
"Follow the instructions you were given."
- Escalation theater — framing a solvable technical decision as requiring \
user or team input. The agent's job is to make technical decisions, not \
escalate them.

### Plan deviation
The agent is working on something materially different from what was asked.

## Step 3: Decide

**If anything is detected → BLOCK.**

Exception — verified completion overrides false-completion signals ONLY if \
ALL of the following are true:
- 100% completion metrics where both numbers match (e.g., "146/146 PASS") — \
sub-metrics do not count if the overall task has more work remaining
- Concrete verification output (test results with counts, build passing, \
commit hashes)
- Zero failures, zero remaining items, zero placeholders, zero stubs
- No language implying work is left

If ALL conditions are met, the signals are false positives — ALLOW.

**If nothing is detected → ALLOW.**

INTERACTIVE (user present, short back-and-forth): ALLOW if the agent answered \
and no work is being abandoned. Presenting a plan or analysis and asking \
for permission is NOT answering — if the user assigned work, the agent \
must DO the work, not describe it.

AUTONOMOUS (user assigned a task with a spec/plan): ALLOW only if the task is \
complete with concrete evidence OR the agent hit a genuine external blocker \
(needs credentials or a policy decision only the user can make — NOT choosing \
between technical approaches).

## Step 4: Check for KILL

KILL only if:
- The agent is looping on the same failure 3+ times with no new approach
- The agent is hallucinating files, APIs, or tools that do not exist
- The agent is completely off-task and not working on anything the user requested

## What counts as "work"

Work is the TECHNICAL DELIVERABLE: code written, tests passing, features \
functioning, bugs fixed. Work is NOT process artifacts — task tracking, \
tool invocations, documentation updates, progress reporting, or any \
meta-activity about the work.

If a plan says "use TodoWrite to track tasks" or "update the task list" or \
"mark items complete," those are process instructions for how to organize \
work, not the work itself. A plan that says "implement parser, register \
operations, add tests, use TodoWrite to track progress" has THREE work \
items and ZERO process requirements you should enforce.

Completion means the deliverable EXISTS and FUNCTIONS — code is written, \
tests pass, the feature works. Completion does NOT mean the code has been \
merged, pushed, deployed, or integrated into main. Merging and pushing are \
INTEGRATION decisions that belong to the user, not work items. An agent \
that has written the code, passed the tests, and committed to its branch \
has COMPLETED its work. Never block because code is "only on a branch."

Never block for: tool usage, task tracking, progress documentation, \
showing work, proving completion, merging, pushing, deploying, or any \
non-technical-deliverable activity.

## Block messages

Write ONE sentence. The sentence must be grounded in BOTH the detection \
that caused the block AND what the agent actually said. A message that \
ignores either one is wrong.

If you blocked for **work evasion** (permission-seeking, offering to do \
work, presenting options): address the evasion behavior directly — tell \
the agent to act. Do not summarize the original task. The agent knows \
the task; they are avoiding it.

If you blocked for **false completion** (partial metrics, remaining items, \
deferred work): name the specific incomplete deliverable. One item. Not \
a recap of the full task.

If you cannot write a sentence grounded in what the agent actually said \
AND why you blocked, reconsider — you may be misreading the situation. \
ALLOW instead.

Block messages name WHAT is undone or WHAT evasion behavior to stop. \
Never HOW to fix it. Never restate the original task requirements as the \
block message. Never invent work items not in the user's instruction.

Good: "Stop asking and proceed with the verification."
Good: "The parser operations are not yet implemented."
Bad: "Fix all failures from the quality gate." (restates original task, ignores what agent said)
Bad: "Invoke TodoWrite and create tasks." (HOW, not WHAT)
Bad: "Finish X, then run Y, and update Z." (multiple items)

## Response format

Respond with JSON: {"decision": "allow"|"block"|"kill", "reason": "<your reasoning>", \
"message": "<message to agent if blocking>"}
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["allow", "block", "kill"],
        },
        "reason": {"type": "string"},
        "message": {"type": "string"},
    },
    "required": ["decision", "reason", "message"],
    "additionalProperties": False,
}


class StopHook(Hook):
    """Hook that decides whether to allow agent to stop."""

    event_name = "Stop"

    # Regex patterns in ASSISTANT message that indicate hard external blockers.
    # The agent literally cannot continue due to external factors.
    # These trigger ALLOW because the agent is stuck, not avoiding work.
    ASSISTANT_HARD_BLOCKER_PATTERNS = [
        r"hit your limit.*resets",
        r"rate limit",
        r"quota exceeded",
        r"too many requests",
        r"service unavailable",
        r"authentication failed",
        r"access denied",
        r"internal server error",
        r"temporarily unavailable",
    ]

    # Regex patterns in USER message that explicitly confirm completion.
    # Only the USER can declare work done - agent self-declarations don't count.
    USER_COMPLETION_PATTERNS = [
        # Explicit completion with strong modifiers
        r"This (?:is|was) (?:OBVIOUSLY|CLEARLY|DEFINITELY|VALID) (?:(?:VALID )?COMPLETION|DONE|FINISHED)",
        # Direct "don't block" instructions
        r"(?:DO NOT|DON'T) (?:BLOCK|STOP)",
        # User confirming after reviewing
        r"(?:Looks?|Seems?) (?:good|complete|done|finished)",
    ]

    # Hard-block patterns: unambiguous evidence of incomplete work.
    # These are facts, not interpretations — no context changes their meaning.
    # The LLM handles everything semantic; these catch what the LLM misses
    # when dazzled by ✅ markers and passing test counts.
    HARD_BLOCK_PATTERNS = [
        # Zero progress on non-zero total (0/27, 0/81, etc.)
        r"\b0/[1-9]\d*\b",
        # Explicit "not started" declarations
        r"\bNOT\s+STARTED\b",
        # Explicit partial/incomplete status
        r"\bPARTIAL\s+IMPLEMENTATION\b",
        # Agent estimating future work hours — work is not done
        r"\bEstimated\s+(?:effort|time)\s+to\s+complete\b",
        # Permission-seeking — agent asking to do work instead of doing it
        r"(?:Ready|Want\s+me)\s+to\s+proceed\??",
    ]
    def _precheck_hard_block(self, text: str, debug: DebugFn) -> bool:
        """Check for unambiguous incomplete-work signals that warrant immediate block.

        Returns True if a hard-block pattern is matched.
        """
        if not text:
            return False
        for pattern in self.HARD_BLOCK_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                debug(f"Hard block pattern matched: {pattern}")
                return True
        return False

    def _precheck_assistant_hard_blocker(self, text: str, debug: DebugFn) -> bool:
        """Check if assistant hit a hard external blocker (rate limit, auth, etc).

        Returns True if a hard blocker is detected, meaning we should ALLOW the stop.
        The agent cannot continue due to external factors, not work avoidance.
        """
        if not text:
            return False
        for pattern in self.ASSISTANT_HARD_BLOCKER_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                debug(f"Hard blocker detected: {pattern}")
                return True
        return False

    def _precheck_user_completion(self, text: str, debug: DebugFn) -> bool:
        """Check if user has explicitly confirmed work is complete.

        Returns True if user confirmation is detected, meaning we should ALLOW.
        Only USER declarations count - agent self-declarations are work avoidance.
        """
        if not text:
            return False
        for pattern in self.USER_COMPLETION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                debug(f"User completion confirmed: {pattern}")
                return True
        return False

    def handle(self, hook_input: dict[str, Any], debug: DebugFn) -> HookResult:
        """Handle stop hook event."""
        llm_ready = self.llm_provider is not None and self.llm_provider.is_configured()
        debug(f"Stop hook: LLM configured: {llm_ready}")

        transcript_path = hook_input.get("transcript_path", "")
        cwd = hook_input.get("cwd", os.getcwd())
        conversation_depth = getattr(self.config, "conversation_depth", 1)

        # Claude Code provides last_assistant_message directly in hook input.
        # Use it as the primary source — transcript parsing is the fallback.
        direct_assistant_msg = hook_input.get("last_assistant_message", "")

        # Parse transcript to get user messages
        messages = self._parse_transcript(transcript_path, debug)
        debug(f"Parsed {len(messages)} messages")

        # Extract relevant messages
        first_user, last_user = self._extract_user_messages(messages)
        last_assistant = self._extract_last_assistant(messages)

        # Prefer direct hook input over transcript extraction for assistant
        if direct_assistant_msg and (
            not last_assistant or len(direct_assistant_msg) > len(last_assistant)
        ):
            debug(f"Using last_assistant_message from hook input ({len(direct_assistant_msg)} chars)")
            last_assistant = direct_assistant_msg

        # === ALLOW CHECKS (check these BEFORE block patterns) ===

        # 1. Check for hard external blockers in assistant message
        # (rate limits, auth errors) - agent literally cannot continue
        if last_assistant and self._precheck_assistant_hard_blocker(last_assistant, debug):
            debug("Hard blocker detected - allowing stop")
            return HookResult.allow("External blocker detected (rate limit, auth, etc.)")

        # 2. Check if user explicitly confirmed completion
        # Only USER declarations count - agent self-declarations are work avoidance
        if last_user and self._precheck_user_completion(last_user, debug):
            debug("User confirmed completion - allowing stop")
            return HookResult.allow("User confirmed work is complete")

        # === BLOCK CHECKS ===

        # No messages = nothing to evaluate, proceed to allow
        if not messages and not direct_assistant_msg:
            debug("No messages and no direct assistant message - allowing (no signals to block)")
            return HookResult.allow("No messages to evaluate")

        # No assistant text = no evidence of incomplete work signals, proceed
        if not last_assistant:
            debug("No assistant text found - allowing (no incomplete work signals)")
            return HookResult.allow("No assistant text to evaluate")

        # Hard block: unambiguous incomplete-work signals the LLM can miss
        # when distracted by passing test counts and ✅ phase markers.
        if self._precheck_hard_block(last_assistant, debug):
            return HookResult.block("Keep going.")

        # No user instruction = no way to judge completion. We can't block
        # without a baseline to evaluate against — same principle as LLM
        # errors (line 422): "it's wrong to block an agent that may have
        # finished its work."
        if not first_user:
            debug("No user instruction found - allowing (cannot evaluate without baseline)")
            return HookResult.allow("No user instruction to evaluate against")

        debug(f"First user: {first_user[:100] if first_user else None}...")
        debug(f"Last user: {last_user[:100] if last_user else None}...")
        debug(f"First == Last user: {first_user == last_user}")
        debug(f"Last assistant: {last_assistant[:100] if last_assistant else None}...")

        # Extract @mentions from ALL user messages (deduplicated)
        all_user_messages = self._extract_all_user_messages(messages)
        all_mentions: list[str] = []
        seen: set[str] = set()
        for user_msg in all_user_messages:
            for mention in self._extract_mentions(user_msg):
                if mention not in seen:
                    all_mentions.append(mention)
                    seen.add(mention)

        files = self._read_mentioned_files(all_mentions, cwd, debug)

        # Build prompt
        user_prompt = self._build_user_prompt(
            first_user, last_user, last_assistant, files
        )
        debug(f"User prompt length: {len(user_prompt)}")

        # Call LLM - if not configured, default to BLOCK.
        # With precheck patterns removed, the LLM is the only thing evaluating
        # whether work is complete. Without it, we must assume it isn't.
        if not self.llm_provider or not self.llm_provider.is_configured():
            debug("No LLM configured - blocking (no precheck patterns to evaluate signals)")
            return HookResult.block("Keep going.")

        debug("Calling LLM...")
        response = self.llm_provider.call(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=RESPONSE_SCHEMA,
        )
        debug(f"LLM response: {response.content}")

        # Log generation to tracer
        if self.tracer:
            self.tracer.generation(
                name="evaluate_stop_decision",
                model=response.model or self.llm_provider.model or "unknown",
                input_data={
                    "system_prompt": SYSTEM_PROMPT,
                    "user_prompt": user_prompt,
                },
                output_data=response.content,
                usage=response.usage.to_dict() if response.usage else None,
                metadata={"response_schema": RESPONSE_SCHEMA},
            )

        # If the LLM errored or timed out, allow the stop — we can't evaluate signals
        # and it's wrong to block an agent that may have finished its work.
        if "error" in response.content:
            debug(f"LLM error/timeout - allowing stop: {response.content.get('error')}")
            return HookResult.allow(f"LLM unavailable: {response.content.get('error')}")

        decision = response.content.get("decision", "block")
        reason = response.content.get("reason", "")
        message = response.content.get("message", "")

        debug(f"Decision: {decision}")

        if decision == "kill":
            debug("Killing parent process")
            os.kill(os.getppid(), signal.SIGKILL)
            return HookResult.kill(reason or "Agent terminated")

        if decision == "allow":
            debug(f"ALLOW: {reason}")
            return HookResult.allow(reason)

        # decision == "block"
        if not message:
            message = "Keep going."
        # Only include real spec documents, not standard project files
        real_docs = [m for m in files.keys() if os.path.basename(m) not in IGNORED_DOC_FILES]
        if real_docs:
            refs = ", ".join(f"@{m}" for m in real_docs)
            message = f"{message}\n\nReferenced documents: {refs}"
        return HookResult.block(message)

    def _parse_transcript(
        self, transcript_path: str, debug: DebugFn
    ) -> list[dict]:
        """Parse JSONL transcript file into list of messages."""
        messages = []
        if not transcript_path:
            debug("No transcript path provided")
            return messages

        try:
            with open(transcript_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            msg = json.loads(line)
                            messages.append(msg)
                        except json.JSONDecodeError as e:
                            debug(f"Failed to parse transcript line: {e}")
                            continue
        except FileNotFoundError:
            debug(f"Transcript file not found: {transcript_path}")
        except PermissionError:
            debug(f"Permission denied reading transcript: {transcript_path}")

        return messages

    def _extract_all_user_messages(self, messages: list[dict]) -> list[str]:
        """Extract all user messages from transcript."""
        user_messages = []
        for msg in messages:
            # Claude Code format: type="user", message={role, content, ...}
            if msg.get("type") == "user":
                inner_msg = msg.get("message", {})
                if isinstance(inner_msg, dict):
                    content = inner_msg.get("content", "")
                    if isinstance(content, str):
                        user_messages.append(content)
                    elif isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif isinstance(block, str):
                                text_parts.append(block)
                        # Skip entries with no text (e.g. tool_result-only messages)
                        joined = "\n".join(text_parts).strip()
                        if joined:
                            user_messages.append(joined)
                elif isinstance(inner_msg, str):
                    user_messages.append(inner_msg)
            # API format: role="user" at top level
            elif msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_parts.append(block)
                    content = "\n".join(text_parts).strip()
                if content:
                    user_messages.append(content)
        return user_messages

    def _extract_user_messages(
        self, messages: list[dict]
    ) -> tuple[str | None, str | None]:
        """Extract first and last user messages from transcript."""
        user_messages = self._extract_all_user_messages(messages)
        first_user = user_messages[0] if user_messages else None
        last_user = user_messages[-1] if user_messages else None
        return first_user, last_user

    def _extract_last_assistant(self, messages: list[dict]) -> str | None:
        """Extract the last assistant message from transcript."""
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_parts.append(block)
                    return "\n".join(text_parts)
                elif isinstance(content, dict):
                    if content.get("type") == "text":
                        return content.get("text", "")
                    return str(content)
                return str(content)
            elif msg.get("type") == "assistant":
                # Claude Code format: type="assistant", message={role, content, ...}
                message = msg.get("message", {})
                if isinstance(message, dict):
                    content = message.get("content", "")
                    if isinstance(content, str):
                        return content
                    elif isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif isinstance(block, str):
                                text_parts.append(block)
                        return "\n".join(text_parts)
                    elif isinstance(content, dict):
                        if content.get("type") == "text":
                            return content.get("text", "")
                        return str(content)
                return message if isinstance(message, str) else str(message)
        return None

    def _extract_mentions(self, text: str) -> list[str]:
        """Extract @path/to/file mentions from text."""
        if not text:
            return []
        pattern = r"@([\w./-]+)"
        return re.findall(pattern, text)

    def _read_mentioned_files(
        self, mentions: list[str], cwd: str, debug: DebugFn
    ) -> dict[str, str]:
        """Read contents of mentioned files, resolving relative paths.

        Logs when files can't be found or read.
        """
        files = {}
        for mention in mentions:
            if not os.path.isabs(mention):
                path = os.path.join(cwd, mention)
            else:
                path = mention

            if not os.path.isfile(path):
                debug(f"Referenced file not found: {mention} (resolved: {path})")
                continue

            try:
                with open(path, "r") as f:
                    files[mention] = f.read()
            except (PermissionError, IsADirectoryError) as e:
                debug(f"Cannot read referenced file {mention}: {e}")
                continue
        return files

    def _build_user_prompt(
        self,
        first_user: str | None,
        last_user: str | None,
        last_assistant: str | None,
        files: dict[str, str],
    ) -> str:
        """Build the user prompt for the LLM."""
        parts = []

        first_user = (first_user or "").strip() or "[No user message found]"
        parts.append("=== ORIGINAL INTENT ===")
        parts.append(first_user)

        if files:
            parts.append("\n=== REFERENCED FILES ===")
            for path, content in files.items():
                parts.append(f"\n--- @{path} ---")
                if len(content) > 10000:
                    content = content[:10000] + "\n... [truncated]"
                parts.append(content)

        last_user = (last_user or "").strip()
        last_assistant = (last_assistant or "").strip()

        if last_user and last_user != first_user:
            parts.append("\n=== MOST RECENT USER INSTRUCTION (supersedes original intent) ===")
            parts.append(last_user)

        if last_assistant:
            parts.append("\n=== AGENT'S RESPONSE ===")
            parts.append(last_assistant)

        result = "\n".join(parts)
        return result if result.strip() else "[No context available]"
