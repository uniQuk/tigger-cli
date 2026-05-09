from __future__ import annotations

import dataclasses

from tigger.compaction import estimate_tokens
from tigger.types import RunContext


def cmd_help(
    args: str, ctx: RunContext, commands: dict, skills: list, agents: list | None = None,
) -> None:
    from tigger.commands import COMMAND_DESCRIPTIONS, COMMAND_HELP
    from tigger.ui import console

    if agents is None:
        agents = []

    query = args.strip()
    show_all = "--all" in query
    if show_all:
        query = query.replace("--all", "").strip()

    if query:
        if query in COMMAND_HELP:
            console.print(f"\n[bold cyan]/{query}[/bold cyan]")
            console.print(COMMAND_HELP[query])
            console.print()
        else:
            console.print(f"\n[red]Unknown command:[/red] /{query}\n")
        return

    width = max(len(name) for name in commands)
    console.print()
    console.print("[bold]Built-in commands[/bold]")
    for name in sorted(commands):
        desc = COMMAND_DESCRIPTIONS.get(name, "")
        console.print(f"  [cyan]/{name:<{width}}[/cyan]  [dim]{desc}[/dim]")

    visible_skills = skills if show_all else [s for s in skills if not s.name.startswith("_")]
    if visible_skills:
        console.print()
        console.print("[bold]Loaded skills[/bold]")
        for s in visible_skills:
            suffix = " [dim](internal)[/dim]" if s.name.startswith("_") else ""
            triggers = ", ".join(s.triggers)
            console.print(f"  [yellow]{triggers}[/yellow]  [dim]—[/dim] {s.name}{suffix}")

    visible_agents = agents if show_all else [a for a in agents if not a.name.startswith("_")]
    if visible_agents:
        console.print()
        console.print("[bold]Loaded agents[/bold]")
        for a in visible_agents:
            suffix = " [dim](internal)[/dim]" if a.name.startswith("_") else ""
            desc = f" [dim]— {a.description}[/dim]" if a.description else ""
            console.print(f"  [magenta]{a.name}[/magenta]{desc}{suffix}")
    console.print()


def cmd_clear(args: str, ctx: RunContext) -> None:
    from tigger.ui import console

    ctx.messages.clear()
    console.print("[dim]✓ Message history cleared.[/dim]")


def cmd_tokens(args: str, ctx: RunContext) -> None:
    from tigger.ui import console

    used = estimate_tokens(ctx.messages)
    limit = ctx.config.context_limit
    pct = int(used / limit * 100) if limit else 0
    # Colour the percentage by remaining headroom: green <50, yellow <80, red ≥80.
    if pct >= 80:
        colour = "red"
    elif pct >= 50:
        colour = "yellow"
    else:
        colour = "green"
    console.print(
        f"[bold]Context:[/bold] {used:,} / {limit:,} tokens "
        f"([{colour}]{pct}% used[/{colour}])"
    )


def cmd_model(args: str, ctx: RunContext) -> None:
    from tigger.config import switch_model

    providers = ctx.config.providers

    # No providers configured — fall back to simple name-only switch
    if not providers:
        if not args.strip():
            label = ctx.config.model_name or ctx.config.model
            print(f"Current model: {label} ({ctx.config.model})")
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
        if model_name not in providers[prov_name].model_names:
            print(f"Model {model_name!r} not found in provider {prov_name!r}. "
                  f"Available: {', '.join(providers[prov_name].model_names)}")
            return
        ctx.config = switch_model(ctx.config, prov_name, model_name)
        print(f"Switched to {prov_name}/{model_name}")
        return

    # Direct switch: /model <name> — search all providers
    if args.strip():
        target = args.strip()
        matches = []
        for pname, prov in providers.items():
            if target in prov.model_names:
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
            print(f"  {pname}: {', '.join(prov.model_names)}")
        return

    # No args — interactive picker
    numbered: list[tuple[str, str]] = []  # (provider_name, model_name)
    for pname, prov in providers.items():
        print(f"\n  {pname}:")
        for mname in prov.model_names:
            numbered.append((pname, mname))
            idx = len(numbered)
            active = " (active)" if (pname == ctx.config.active_provider
                                     and mname == ctx.config.model_slug) else ""
            label = mname
            if isinstance(prov.models, dict):
                mcfg = prov.models.get(mname)
                if mcfg and mcfg.name:
                    label = f"{mcfg.name} ({mname})"
            print(f"    {idx}. {label}{active}")

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


def cmd_mode(args: str, ctx: RunContext, modes: list | None = None) -> None:
    from tigger.ui import console

    if modes is None:
        modes = ctx.modes
    mode_names = sorted(m.name for m in modes)
    if not args.strip():
        console.print(f"[bold]Current mode:[/bold] [cyan]{ctx.config.mode}[/cyan]")
        if mode_names:
            console.print(f"[dim]Available:[/dim] {', '.join(mode_names)}")
        return
    new_mode = args.strip()
    if new_mode not in {m.name for m in modes}:
        console.print(
            f"[red]Invalid mode[/red] {new_mode!r}. "
            f"[dim]Available:[/dim] {', '.join(mode_names)}"
        )
        return
    ctx.config = dataclasses.replace(ctx.config, mode=new_mode)
    console.print(f"[dim]✓ Mode set to[/dim] [cyan]{new_mode}[/cyan]")


def cmd_permission(args: str, ctx: RunContext) -> None:
    from tigger.ui import console

    valid = {"ask", "allow", "bypass"}
    if not args.strip():
        console.print(
            f"[bold]Current permission:[/bold] [cyan]{ctx.config.permission_mode}[/cyan]"
        )
        return
    new_perm = args.strip()
    if new_perm not in valid:
        console.print(
            f"[red]Invalid permission[/red] {new_perm!r}. "
            f"[dim]Must be one of[/dim] {sorted(valid)}"
        )
        return
    ctx.config = dataclasses.replace(ctx.config, permission_mode=new_perm)
    console.print(f"[dim]✓ Permission set to[/dim] [cyan]{new_perm}[/cyan]")
