from __future__ import annotations

import dataclasses
import pathlib

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
            import re
            console.print(f"\n[bold cyan]/{query}[/bold cyan]")
            # Highlight inline /command and --flag references so the body's
            # structure pops without rewriting all 16 help strings. The
            # lookbehind avoids URL paths (https://…) and filesystem paths
            # (skills/agents/modes) — only treat ``/word`` as a command when
            # it's not preceded by another path segment.
            body = COMMAND_HELP[query]
            body = re.sub(r"(?<![/\w])(/[a-z][\w-]*)", r"[cyan]\1[/cyan]", body)
            body = re.sub(r"(?<![\w])(--[a-z][\w-]*)", r"[cyan]\1[/cyan]", body)
            # Dim the leading "Usage:" label on lines starting with it.
            body = re.sub(r"(?m)^(\s*)(Usage:)", r"\1[dim]\2[/dim]", body)
            console.print(body)
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
            # Only show "— name" when it adds info; for single-trigger skills
            # whose trigger matches the name, the dash + name is pure noise.
            single = s.triggers[0].lstrip("/") if len(s.triggers) == 1 else None
            if single == s.name:
                console.print(f"  [yellow]{triggers}[/yellow]{suffix}")
            else:
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

    n = len(ctx.messages)
    if n == 0:
        console.print("[dim](history was already empty)[/dim]")
        return
    reclaimed = estimate_tokens(ctx.messages)
    ctx.messages.clear()
    console.print(
        f"[dim]✓ Cleared[/dim] [bold]{n}[/bold] "
        f"[dim]message{'s' if n != 1 else ''}[/dim] "
        f"[dim]·[/dim] [bold]~{reclaimed:,}[/bold] [dim]tokens reclaimed[/dim]"
    )


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
    # Compaction threshold matches the 85% in compaction.maybe_compact.
    compact_at = int(limit * 0.85) if limit else 0
    headroom = max(0, compact_at - used)
    # 30-cell bar split into filled / unfilled halves for an at-a-glance ratio.
    bar_width = 30
    if limit:
        filled = min(bar_width, max(0, int(used / limit * bar_width)))
    else:
        filled = 0
    bar = (
        f"[{colour}]{'█' * filled}[/{colour}]"
        f"[dim]{'░' * (bar_width - filled)}[/dim]"
    )
    console.print(
        f"[bold]Context:[/bold] {used:,} / {limit:,} tokens "
        f"([{colour}]{pct}% used[/{colour}])"
    )
    console.print(f"  {bar}")
    if compact_at and headroom > 0:
        console.print(
            f"  [dim]{headroom:,} tokens until /compact triggers "
            f"(at {compact_at:,})[/dim]"
        )
    elif compact_at:
        console.print(
            "  [yellow]past compaction threshold — next turn may auto-compact[/yellow]"
        )


def cmd_model(
    args: str,
    ctx: RunContext,
    config_path: pathlib.Path | None = None,
) -> None:
    from tigger.config import switch_model, write_config
    from tigger.ui import console

    def _persist() -> None:
        # Persist `default_model` (and `default_provider`) so the next
        # session resumes on the model the user actually picked. write_config
        # is non-destructive — unknown top-level / per-model keys survive.
        if config_path is not None:
            write_config(config_path, ctx.config)

    providers = ctx.config.providers

    # No providers configured — fall back to simple name-only switch
    if not providers:
        if not args.strip():
            label = ctx.config.model_name or ctx.config.model
            console.print(
                f"[bold]Current model:[/bold] [cyan]{label}[/cyan] "
                f"[dim]({ctx.config.model})[/dim]"
            )
            return
        ctx.config = dataclasses.replace(ctx.config, model=args.strip())
        console.print(f"[dim]✓ Model set to[/dim] [cyan]{args.strip()}[/cyan]")
        _persist()
        return

    # Direct switch: /model provider/model
    if "/" in args.strip():
        prov_name, model_name = args.strip().split("/", 1)
        if prov_name not in providers:
            console.print(
                f"[red]Unknown provider:[/red] {prov_name}. "
                f"[dim]Available:[/dim] {', '.join(providers)}"
            )
            return
        if model_name not in providers[prov_name].model_names:
            console.print(
                f"[red]Model[/red] {model_name!r} [red]not found in provider[/red] "
                f"{prov_name!r}. [dim]Available:[/dim] "
                f"{', '.join(providers[prov_name].model_names)}"
            )
            return
        ctx.config = switch_model(ctx.config, prov_name, model_name)
        console.print(
            f"[dim]✓ Switched to[/dim] [cyan]{prov_name}/{model_name}[/cyan]"
        )
        _persist()
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
            console.print(f"[dim]✓ Switched to[/dim] [cyan]{pname}/{mname}[/cyan]")
            _persist()
            return
        if len(matches) > 1:
            console.print(
                f"[yellow]Model[/yellow] {target!r} "
                "[yellow]found in multiple providers:[/yellow]"
            )
            for pname, _ in matches:
                console.print(f"  [cyan]{pname}/{target}[/cyan]")
            console.print(
                "[dim]Use provider/model syntax to disambiguate.[/dim]"
            )
            return
        console.print(
            f"[red]Model[/red] {target!r} [red]not found.[/red] "
            "[dim]Available models:[/dim]"
        )
        for pname, prov in providers.items():
            console.print(
                f"  [magenta]{pname}:[/magenta] "
                f"{', '.join(prov.model_names)}"
            )
        return

    # No args — interactive picker
    numbered: list[tuple[str, str]] = []  # (provider_name, model_name)
    for pname, prov in providers.items():
        console.print(f"\n  [bold magenta]{pname}[/bold magenta]")
        for mname in prov.model_names:
            numbered.append((pname, mname))
            idx = len(numbered)
            is_active = (
                pname == ctx.config.active_provider
                and mname == ctx.config.model_slug
            )
            label = mname
            if isinstance(prov.models, dict):
                mcfg = prov.models.get(mname)
                if mcfg and mcfg.name:
                    label = f"{mcfg.name} ({mname})"
            line = f"    [dim]{idx}.[/dim] [cyan]{label}[/cyan]"
            if is_active:
                line += " [green](active)[/green]"
            console.print(line)

    try:
        choice = input(f"\nPick [1-{len(numbered)}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(numbered):
        console.print("[dim]Cancelled.[/dim]")
        return
    pname, mname = numbered[int(choice) - 1]
    ctx.config = switch_model(ctx.config, pname, mname)
    console.print(f"[dim]✓ Switched to[/dim] [cyan]{pname}/{mname}[/cyan]")
    _persist()


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


def cmd_think(args: str, ctx: RunContext) -> None:
    """Toggle chat_template_kwargs.enable_thinking on the active config.

    Useful when the configured model has thinking enabled by default
    (Qwen 3.6 with `enable_thinking: true`): a 30-second simple question
    becomes 4 minutes of buffered reasoning before any output. Flipping
    it off mid-session swaps that for fast non-thinking responses.
    """
    from tigger.ui import console

    sub = args.strip().lower()
    kwargs = dict(ctx.config.chat_template_kwargs or {})
    current = bool(kwargs.get("enable_thinking", False))

    if not sub or sub == "status":
        state = "[green]on[/green]" if current else "[red]off[/red]"
        console.print(f"[bold]Thinking:[/bold] {state}")
        return

    if sub in ("on", "true", "1", "enable"):
        new_val = True
    elif sub in ("off", "false", "0", "disable"):
        new_val = False
    elif sub == "toggle":
        new_val = not current
    else:
        console.print(
            f"[red]Unknown[/red] /think [red]subcommand[/red] {sub!r}. "
            "[dim]Try[/dim] [cyan]on[/cyan] | [cyan]off[/cyan] | "
            "[cyan]toggle[/cyan] | [cyan]status[/cyan]."
        )
        return

    if new_val == current:
        word = "on" if new_val else "off"
        console.print(f"[dim]Thinking already {word}.[/dim]")
        return

    # No-op for non-Qwen models: their jinja templates don't know about
    # `enable_thinking` and reject the request with UndefinedValue. The
    # current state is False AND the kwarg isn't present in the active
    # config, so this model doesn't opt into Qwen-style thinking kwargs.
    if "enable_thinking" not in kwargs:
        console.print(
            "[dim]This model doesn't use[/dim] [cyan]chat_template_kwargs.enable_thinking[/cyan][dim]; "
            "/think is a no-op.[/dim]"
        )
        return

    kwargs["enable_thinking"] = new_val
    ctx.config = dataclasses.replace(ctx.config, chat_template_kwargs=kwargs)
    word = "[green]on[/green]" if new_val else "[red]off[/red]"
    console.print(f"[dim]✓ Thinking[/dim] {word}")


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
