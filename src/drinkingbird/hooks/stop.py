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


SYSTEM_PROMPT = """You supervise an AI coding agent. You decide whether the agent \
should be allowed to stop working.

You receive: the user's original task, any referenced documents (the plan/spec \
the agent is executing), and the most recent exchange between the user and the \
agent.

## Fundamental principle: User authority

The user is the ultimate authority. Your job is to catch the AGENT quitting \
prematurely — never to override the USER. If the agent is doing what the user \
asked (including stopping when told to stop, deleting when told to delete, \
skipping when told to skip), that is correct behavior. ALLOW it. \
Incomplete-work signals only matter when the AGENT is abandoning work on its \
own initiative, not when it is following the user's instructions.

## Step 1: Determine user intent (MANDATORY — do this FIRST)

Read the MOST RECENT USER INSTRUCTION. Summarize what the user is asking for \
in the user_intent field. Then determine: is the agent doing what the user \
asked? Set agent_followed_user accordingly. If true — ALLOW. Stop here. \
Do not proceed to signal scanning.

CRITICAL: Interpret the user's instruction LITERALLY, not expansively. \
The user's words define the scope of this evaluation. Do NOT expand the \
instruction to encompass the full plan, overall project goals, or remaining \
work beyond what was asked. If the user asked for a specific action and that \
action was completed, the agent followed the user — regardless of what other \
work remains in the plan or project.

Referenced documents (plans, specs) provide CONTEXT for understanding the \
work. They do NOT override or expand the user's latest instruction. If the \
plan defines a larger scope than the user's current instruction, evaluate \
against the instruction, not the plan. The plan is not a mandate — the user \
is the authority.

## Step 2: Scan for incomplete-work signals

Only reach this step if agent_followed_user is false.

Read the agent's last message line by line. List every signal you find in the \
signals_found array. Each entry must quote or paraphrase the specific evidence.

Signal categories to scan for:

1. Progress metrics below 100% — "3/19 passing", "16%", "51.6% complete", \
"16 of 31", "137/945"
2. Remaining work — open tasks, failing tests, unimplemented items, known bugs, \
placeholder implementations, items "ready to be wired in"
3. Deferral — "next steps would be", "future session", "resume later", \
"next up is", describing what WOULD need to happen to finish
4. Rationalizing partial completion — "significant progress", "solid foundation", \
"progressing well", "main blocker", "blocked by", "due to complexity"
5. Session summaries — "current status", wrapping up, recapping what was done, \
listing commits or work completed so far. NOTE: Reporting a final deliverable \
(PR URL, commit hash) with no remaining work mentioned is completion, not a \
session summary.
6. Permission-seeking — "would you like me to", "shall I proceed", "ready for \
feedback", "let me know", "how would you like", "which direction", \
"which path should I take". NOTE: Status declarations about completed actions \
are NOT permission-seeking. "PR created. Ready for merge." is a completion \
report, not asking permission.
7. Menus or options — numbered lists of choices ("Three paths forward: 1... \
2... 3..."), asking the user to choose a direction
8. Phased framing — calling work a "phase", "milestone", or "stage", or saying \
one phase is "complete" while more phases remain
9. Task lists with uncompleted items — checkboxes, open counts, pending labels
10. Failure markers — error symbols, "FAILED", "failing", "broken", "blocked"
11. Escalation theater — framing a technical decision as requiring user/team \
input when the agent should decide itself. Examples: "I cannot responsibly \
proceed without...", "this requires team lead input", presenting solvable \
technical problems as organizational blockers. The agent's job is to make \
technical decisions, not escalate them.
12. Stubs or skeletons — "Stub (ready for expansion)", placeholder functions, \
TODO markers, empty implementations described as "framework"

## Step 3: Decide based on signals_found

### If signals_found is NOT empty:

Default: BLOCK. The signal IS the decision.

**Exception — Verified completion overrides signals**: Signals are overridden \
ONLY if ALL of the following are true:
- 100% completion metrics FOR THE OVERALL TASK where both numbers match \
(e.g., "146/146 PASS", "32/32 operations", NOT "3/19" or "51%"). A sub-metric \
like "10/10 Phase 1 operations" does NOT count if the overall task has more \
phases, more operations, or more work remaining. Cherry-picked completion of a \
SUBSET is not completion of the TASK.
- Concrete verification output (test results with counts, build passing, \
commit hashes)
- Zero failures, zero remaining items, zero placeholders, zero stubs
- No "remaining work", "next session", "future development", "estimated \
completion", or any language implying work is left

If ALL conditions are met, the signals are false positives — ALLOW. \
Otherwise BLOCK.

### If signals_found IS empty:

Determine session type, then decide:

INTERACTIVE (user is present and conversing — short questions, commands, \
back-and-forth): ALLOW if the agent answered the question or completed the \
action and no work is being abandoned.

AUTONOMOUS (user assigned a task and left — references to a spec/plan, \
multi-step task): ALLOW only if the task is complete with concrete evidence \
OR the agent hit a genuine external blocker (needs a secret, credentials, \
or a policy decision only the user can make — NOT choosing between technical \
approaches).

## Step 4: Check for KILL

KILL only if:
- The agent is looping on the same failure 3+ times with no new approach
- The agent is hallucinating files, APIs, or tools that do not exist
- The agent is completely off-task and not working on anything the user requested

## Block messages

When you BLOCK, write exactly ONE sentence. Not two. Not a sentence with \
"and then" or "—" chaining more tasks onto it. ONE sentence with ONE verb \
pointing to the SINGLE most urgent incomplete thing. Stop after the period.

CRITICAL RULES:
- Only reference work that the USER explicitly asked for in their instruction. \
Do NOT reference work from the plan that the user did not ask for.
- Do NOT enforce plan-internal steps as user requirements. Plans document \
intended work; the user's instruction defines what to enforce now.
- Do NOT mention tools like TodoWrite unless the USER explicitly asked for \
them in their instruction — not because a plan document mentions them.
- Do NOT reference phase names, task counts, or steps you made up.
- If the original task has no remaining work, the task is DONE — ALLOW.
- NEVER echo escalation back as a command. If the agent asked the user to run \
a command manually or said it cannot proceed due to a safety block, do NOT tell \
the agent to "execute that command" or "find a secure way to do it." Instead, \
tell the agent to find a different technical approach that doesn't require user \
intervention.
- NEVER give validation instructions. Your job is to point at incomplete work, \
NOT to tell the agent how to prove completion. Do NOT say "provide verification", \
"attach logs", "show evidence", "confirm with tests", or anything requesting \
proof. The "Verified completion" criteria above are for YOUR internal judgment \
only — never surface them as commands to the agent.

Good: "Continue with the next incomplete item in the plan."
Good: "Replace the placeholder implementations with real ones."
Good: "Find an alternative approach that doesn't require user intervention."

Bad: "Finish X, then run Y, and update Z." (multiple steps — ONE only)
Bad: "Keep going." (too vague — name the specific incomplete thing)
Bad: Anything with "and", "then", or "—" connecting multiple tasks
Bad: "Provide verification that X passes." (validation instruction, not work)
Bad: "Attach build logs before requesting merge." (validation instruction)

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

        # No user instruction = no way to judge completion. Request a status
        # report so the next stop hook invocation has context to evaluate.
        if not first_user:
            debug("No user instruction found - requesting status report")
            return HookResult.block(
                "Report your current status: what was the original task, "
                "what have you completed, and what remains?"
            )

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
