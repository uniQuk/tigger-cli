from __future__ import annotations
import dataclasses
from newcli.types import RunContext
from newcli.compaction import estimate_tokens


def cmd_help(args: str, ctx: RunContext, commands: dict, skills: list) -> None:
    print("\nBuilt-in commands:")
    for name in sorted(commands):
        print(f"  /{name}")
    if skills:
        print("\nLoaded skills:")
        for s in skills:
            print(f"  {', '.join(s.triggers)}  — {s.name}")
    print()


def cmd_clear(args: str, ctx: RunContext) -> None:
    ctx.messages.clear()
    print("Message history cleared.")


def cmd_tokens(args: str, ctx: RunContext) -> None:
    used = estimate_tokens(ctx.messages)
    limit = ctx.config.context_limit
    pct = int(used / limit * 100) if limit else 0
    print(f"Tokens: {used}/{limit} ({pct}% used)")


def cmd_model(args: str, ctx: RunContext) -> None:
    if not args.strip():
        print(f"Current model: {ctx.config.model}")
        return
    new_model = args.strip()
    ctx.config = dataclasses.replace(ctx.config, model=new_model)
    print(f"Model set to: {new_model}")


def cmd_mode(args: str, ctx: RunContext) -> None:
    valid = {"ask", "plan"}
    if not args.strip():
        print(f"Current mode: {ctx.config.mode}")
        return
    new_mode = args.strip()
    if new_mode not in valid:
        print(f"Invalid mode {new_mode!r}. Must be one of {sorted(valid)}")
        return
    ctx.config = dataclasses.replace(ctx.config, mode=new_mode)
    print(f"Mode set to: {new_mode}")


def cmd_permission(args: str, ctx: RunContext) -> None:
    valid = {"ask", "allow", "bypass"}
    if not args.strip():
        print(f"Current permission: {ctx.config.permission_mode}")
        return
    new_perm = args.strip()
    if new_perm not in valid:
        print(f"Invalid permission {new_perm!r}. Must be one of {sorted(valid)}")
        return
    ctx.config = dataclasses.replace(ctx.config, permission_mode=new_perm)
    print(f"Permission set to: {new_perm}")
