from __future__ import annotations
import dataclasses
from tigger.types import RunContext
from tigger.compaction import estimate_tokens


def cmd_help(args: str, ctx: RunContext, commands: dict, skills: list) -> None:
    from tigger.commands import COMMAND_DESCRIPTIONS, COMMAND_HELP

    query = args.strip()
    if query:
        if query in COMMAND_HELP:
            print(f"\n/{query}\n{COMMAND_HELP[query]}\n")
        else:
            print(f"\nUnknown command: {query}\n")
        return

    width = max(len(name) for name in commands)
    print("\nBuilt-in commands:")
    for name in sorted(commands):
        desc = COMMAND_DESCRIPTIONS.get(name, "")
        print(f"  /{name:<{width}}  {desc}")
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
    from tigger.config import switch_model

    providers = ctx.config.providers

    # No providers configured — fall back to simple name-only switch
    if not providers:
        if not args.strip():
            print(f"Current model: {ctx.config.model}")
            return
        ctx.config = dataclasses.replace(ctx.config, model=args.strip())
        print(f"Model set to: {args.strip()}")
        return

    # Direct switch: /model provider/model
    if "/" in args.strip():
        prov_name, model_name = args.strip().split("/", 1)
        if prov_name not in providers:
            print(f"Unknown provider: {prov_name}. Available: {', '.join(providers)}")
            return
        if model_name not in providers[prov_name].models:
            print(f"Model {model_name!r} not found in provider {prov_name!r}. "
                  f"Available: {', '.join(providers[prov_name].models)}")
            return
        ctx.config = switch_model(ctx.config, prov_name, model_name)
        print(f"Switched to {prov_name}/{model_name}")
        return

    # Direct switch: /model <name> — search all providers
    if args.strip():
        target = args.strip()
        matches = []
        for pname, prov in providers.items():
            if target in prov.models:
                matches.append((pname, target))
        if len(matches) == 1:
            pname, mname = matches[0]
            ctx.config = switch_model(ctx.config, pname, mname)
            print(f"Switched to {pname}/{mname}")
            return
        if len(matches) > 1:
            print(f"Model {target!r} found in multiple providers:")
            for pname, _ in matches:
                print(f"  {pname}/{target}")
            print("Use provider/model syntax to disambiguate.")
            return
        print(f"Model {target!r} not found. Available models:")
        for pname, prov in providers.items():
            print(f"  {pname}: {', '.join(prov.models)}")
        return

    # No args — interactive picker
    numbered: list[tuple[str, str]] = []  # (provider_name, model_name)
    for pname, prov in providers.items():
        print(f"\n  {pname}:")
        for mname in prov.models:
            numbered.append((pname, mname))
            idx = len(numbered)
            active = " (active)" if (pname == ctx.config.active_provider
                                     and mname == ctx.config.model) else ""
            print(f"    {idx}. {mname}{active}")

    try:
        choice = input(f"\nPick [1-{len(numbered)}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(numbered):
        print("Cancelled.")
        return
    pname, mname = numbered[int(choice) - 1]
    ctx.config = switch_model(ctx.config, pname, mname)
    print(f"Switched to {pname}/{mname}")


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
