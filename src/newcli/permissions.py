from __future__ import annotations
from newcli.types import ToolDef


def check(
    tool: ToolDef,
    mode: str,
    args: dict,
    bash_safe_prefixes: list[str],
) -> bool:
    """Return True if *tool* is auto-approved under *mode*; False means ask."""
    if tool.read_only:
        return True
    if mode == "accept-all":
        return True
    if mode == "auto":
        if tool.safe:
            return True
        if tool.name == "bash":
            cmd = args.get("command", "")
            return any(cmd.startswith(p) for p in bash_safe_prefixes)
        return False
    return False    # manual: caller must prompt the user
