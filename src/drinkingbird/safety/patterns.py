"""Safety patterns organized by category for Better Drinking Bird."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class SafetyPattern:
    """A safety pattern that blocks dangerous commands."""

    pattern: str
    reason: str
    category: str


# Common git aliases that must be caught.
# git checkout -> co, git switch -> sw
_CO = r"(?:checkout|co)"
_SW = r"(?:switch|sw)"

# Organized by category for easy enable/disable
SAFETY_CATEGORIES: dict[str, list[SafetyPattern]] = {
    "ci_bypass": [
        SafetyPattern(
            r"--no-verify",
            "NO. Do not bypass pre-commit hooks. Fix the issue.",
            "ci_bypass",
        ),
        SafetyPattern(
            r"--no-gpg-sign",
            "Do not skip GPG signing.",
            "ci_bypass",
        ),
        SafetyPattern(
            r"--skip-hooks",
            "Do not skip hooks.",
            "ci_bypass",
        ),
        SafetyPattern(
            r"HUSKY\s*=\s*0",
            "Do not disable Husky.",
            "ci_bypass",
        ),
        SafetyPattern(
            r"PRE_COMMIT_ALLOW_NO_CONFIG",
            "Do not bypass pre-commit.",
            "ci_bypass",
        ),
        SafetyPattern(
            r"(?:sed|awk|perl|ed|cat\s*>|echo\s.*>|tee)\s.*pre.commit",
            "Do not modify pre-commit hooks. Fix the code, not the safety net.",
            "ci_bypass",
        ),
        SafetyPattern(
            r"chmod\s.*pre.commit",
            "Do not modify pre-commit hook permissions. Fix the code, not the safety net.",
            "ci_bypass",
        ),
    ],
    "destructive_git": [
        SafetyPattern(
            r"git\s+reset\s+--hard",
            "NO. git reset --hard destroys work. Ask the user first.",
            "destructive_git",
        ),
        SafetyPattern(
            r"git\s+clean\s+-f",
            "NO. git clean -f deletes untracked files. Ask the user.",
            "destructive_git",
        ),
        SafetyPattern(
            rf"git\s+{_CO}\s+\.",
            "NO. git checkout . discards changes. Ask the user.",
            "destructive_git",
        ),
        SafetyPattern(
            r"git\s+restore\s+\.",
            "NO. git restore . discards changes. Ask the user.",
            "destructive_git",
        ),
        SafetyPattern(
            r"git\s+push\s+--force",
            "NO. Force push is destructive. Ask the user.",
            "destructive_git",
        ),
        SafetyPattern(
            r"git\s+push\s+-f\b",
            "NO. Force push is destructive. Ask the user.",
            "destructive_git",
        ),
        SafetyPattern(
            r"git\s+branch\s+-D",
            "NO. git branch -D force-deletes branches. Use -d instead.",
            "destructive_git",
        ),
    ],
    "branch_switching": [
        # Block git switch/sw to existing branches.
        # Allow -c / -C / --create (new branch creation is safe).
        SafetyPattern(
            rf"git\s+{_SW}\s+(?!-[cC]\b)(?!--create\b)\S",
            "ABSOLUTELY NOT. Switching branches corrupts worktrees. "
            "Stay on your assigned branch. Use `git switch -C <name>` to create a new branch.",
            "branch_switching",
        ),
        # Block ALL git checkout/co to a ref.
        # Safe cases (checkout <ref> -- <file>) are handled via ALLOWED_PATTERNS.
        SafetyPattern(
            rf"git\s+{_CO}\s+(?!--)[\w\-/]",
            "ABSOLUTELY NOT. Switching branches corrupts worktrees. "
            "Stay on your assigned branch. Use `git switch -C <name>` to create a new branch.",
            "branch_switching",
        ),
        # Block git checkout/co <ref> -- . (checks out ALL files from another ref)
        SafetyPattern(
            rf"git\s+{_CO}\s+\S+\s+--\s+\.",
            "ABSOLUTELY NOT. Checking out all files from another ref destroys the worktree. "
            "Stay on your assigned branch.",
            "branch_switching",
        ),
        SafetyPattern(
            r"git\s+push\s+\S+\s+(main|master)\b",
            "Do not push directly to main/master. Use a pull request.",
            "branch_switching",
        ),
        SafetyPattern(
            r"git\s+push\s+\S+\s+\S+:(main|master)\b",
            "Do not push directly to main/master. Use a pull request.",
            "branch_switching",
        ),
    ],
    "interactive_git": [
        SafetyPattern(
            r"git\s+rebase\s+-i",
            "Interactive rebase won't work in this environment.",
            "interactive_git",
        ),
        SafetyPattern(
            r"git\s+add\s+-i",
            "Interactive add won't work in this environment.",
            "interactive_git",
        ),
        SafetyPattern(
            r"git\s+add\s+-p",
            "Patch add won't work in this environment.",
            "interactive_git",
        ),
    ],
    "dangerous_files": [
        SafetyPattern(
            r"rm\s+-rf\s+/",
            "NO. Absolutely not.",
            "dangerous_files",
        ),
        SafetyPattern(
            r"rm\s+-rf\s+~",
            "NO. Do not delete home directory.",
            "dangerous_files",
        ),
        SafetyPattern(
            r"rm\s+-rf\s+\*",
            "NO. Do not delete everything.",
            "dangerous_files",
        ),
        SafetyPattern(
            r">\s*/dev/sd",
            "NO. Do not write to block devices.",
            "dangerous_files",
        ),
    ],
    "git_history": [
        SafetyPattern(
            r"git\s+log\b(?!.*--oneline\b)",
            "Don't dig through git history for bugs. Read the actual code.",
            "git_history",
        ),
        SafetyPattern(
            r"git\s+blame\b",
            "Don't use git blame. Claude wrote those commits. Read the actual code.",
            "git_history",
        ),
    ],
    "credential_access": [
        SafetyPattern(
            r"cat\s+.*\.env\b",
            "Do not cat .env files. They contain secrets.",
            "credential_access",
        ),
        SafetyPattern(
            r"cat\s+.*credentials",
            "Do not cat credential files.",
            "credential_access",
        ),
        SafetyPattern(
            r"cat\s+.*\.pem\b",
            "Do not cat private keys.",
            "credential_access",
        ),
        SafetyPattern(
            r"cat\s+.*_rsa\b",
            "Do not cat SSH keys.",
            "credential_access",
        ),
    ],
}

# Allowed patterns that override blocks above
ALLOWED_PATTERNS = [
    r"git\s+diff\b(?!.*HEAD~)",  # Diffing is fine, except HEAD~ comparisons
    r"git\s+status\b",  # Status is always fine
    r"git\s+log\s+--oneline\b",  # Brief history is fine (commit style, range checks, etc.)
    # File restore from a ref: git checkout <ref> -- <file> (but NOT -- . which is mass checkout)
    rf"git\s+(?:checkout|co)\s+\S+\s+--\s+(?!\.(?:\s|$))\S",
]


def get_enabled_patterns(enabled_categories: dict[str, bool]) -> list[SafetyPattern]:
    """Get all patterns from enabled categories.

    Args:
        enabled_categories: Dict mapping category name to enabled status

    Returns:
        List of SafetyPattern objects from enabled categories
    """
    patterns = []
    for category, is_enabled in enabled_categories.items():
        if is_enabled and category in SAFETY_CATEGORIES:
            patterns.extend(SAFETY_CATEGORIES[category])
    return patterns


def check_command(
    command: str,
    enabled_categories: dict[str, bool] | None = None,
) -> tuple[bool, str]:
    """Check if command matches any forbidden pattern.

    Args:
        command: The command to check
        enabled_categories: Which categories are enabled. If None, all enabled.

    Returns:
        Tuple of (is_forbidden, reason)
    """
    # First check if it matches an allowed pattern
    for pattern in ALLOWED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False, ""

    # Get patterns to check
    if enabled_categories is None:
        # All categories enabled
        enabled_categories = {cat: True for cat in SAFETY_CATEGORIES}

    patterns = get_enabled_patterns(enabled_categories)

    # Check each pattern
    for sp in patterns:
        if re.search(sp.pattern, command, re.IGNORECASE):
            return True, sp.reason

    return False, ""
