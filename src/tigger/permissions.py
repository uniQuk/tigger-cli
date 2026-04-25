from __future__ import annotations
import re
from tigger.types import ToolDef

# Shell metacharacters that allow command chaining/injection after a safe prefix.
_SHELL_METACHAR = re.compile(r"[;|&`$\n\\()\{\}<>]")


def _bash_command_is_safe(cmd: str, safe_prefixes: list[str]) -> bool:
    """Return True only if *cmd* starts with a safe prefix AND contains no shell metacharacters."""
    if not any(cmd.startswith(p) for p in safe_prefixes):
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
        if tool.name in ("edit", "write", "remember"):
            return True
        return False
    return False    # ask: caller must prompt the user
