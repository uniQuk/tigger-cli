from __future__ import annotations

import re

from tigger.types import ToolDef

# Shell metacharacters that allow command chaining/injection after a safe prefix.
_SHELL_METACHAR = re.compile(r"[;|&`$\n\\()\{\}<>]")


def _matches_safe_prefix(cmd: str, prefix: str) -> bool:
    """Return True only when cmd is exactly the prefix or starts with prefix + space.

    A bare startswith() lets `git logfoo` match a `git log` allowlist entry.
    Requiring a word boundary closes that escalation path. Trailing
    whitespace on the prefix is normalized so legacy configs that wrote
    ``git `` (with trailing space) keep working.
    """
    p = prefix.rstrip()
    return cmd == p or cmd.startswith(p + " ")


def _bash_command_is_safe(cmd: str, safe_prefixes: list[str]) -> bool:
    """Return True only if *cmd* starts with a safe prefix on a word boundary
    AND contains no shell metacharacters."""
    if not any(_matches_safe_prefix(cmd, p) for p in safe_prefixes):
        return False
    # Reject if any shell metacharacter appears anywhere in the command.
    return _SHELL_METACHAR.search(cmd) is None


def check(
    tool: ToolDef,
    mode: str,
    args: dict,
    bash_safe_prefixes: list[str],
) -> bool:
    """Return True if *tool* is auto-approved under *mode*; False means ask."""
    if tool.read_only:
        return True
    if mode == "bypass":
        return True
    if mode == "allow":
        if tool.name == "bash":
            cmd = args.get("command", "")
            return _bash_command_is_safe(cmd, bash_safe_prefixes)
        return tool.name in ("edit", "write", "remember")
    return False    # ask: caller must prompt the user
