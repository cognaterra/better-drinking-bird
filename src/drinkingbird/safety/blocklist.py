"""User-configured blocklist checking for Better Drinking Bird."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from drinkingbird.config import BlocklistEntry


def check_user_blocklist(
    tool_name: str,
    tool_input: dict,
    blocklist: list[BlocklistEntry],
) -> tuple[bool, str]:
    """Check if tool input matches any user blocklist pattern.

    Args:
        tool_name: Name of the tool being called
        tool_input: Input dict being passed to the tool
        blocklist: List of user-configured blocklist entries

    Returns:
        Tuple of (is_blocked, reason). If blocked, reason contains the message.
    """
    if not blocklist:
        return False, ""

    # Serialize tool input to string for matching
    try:
        input_str = json.dumps(tool_input)
    except (TypeError, ValueError):
        input_str = str(tool_input)

    for entry in blocklist:
        # Skip if tool doesn't match
        if not entry.matches_tool(tool_name):
            continue

        # Check pattern against serialized input
        pattern = entry.get_compiled_pattern()
        if pattern.search(input_str):
            return True, entry.reason

    return False, ""
