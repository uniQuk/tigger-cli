from __future__ import annotations

import pathlib

from tigger._constants import home_config_dir
from tigger.hooks import HookDef
from tigger.resolve import INTERNAL_DIR
from tigger.skills import AgentDef, SkillDef
from tigger.types import RunContext


def _tier_label(source: pathlib.Path | None) -> str:
    """Return a human-readable tier label based on the source path."""
    if source is None:
        return "unknown"
    resolved = source.resolve()
    try:
        resolved.relative_to(INTERNAL_DIR.resolve())
        return "internal"
    except ValueError:
        pass
    try:
        resolved.relative_to(home_config_dir().resolve())
        return "user"
    except ValueError:
        pass
    return "project"


def cmd_status(
    args: str,
    ctx: RunContext,
    *,
    config_path: pathlib.Path,
    skills: list[SkillDef],
    agents: list[AgentDef],
    hook_defs: list[HookDef],
    memory_path: pathlib.Path,
) -> None:
    """Print the resolved runtime configuration."""
    from tigger.ui import console

    cfg = ctx.config
    provider = cfg.active_provider
    if not provider:
        from tigger.config import derive_provider_name
        provider = derive_provider_name(cfg.base_url)

    # -- Config --
    console.print()
    console.print("[bold]Config[/bold]")
    console.print(f"  [dim]path:[/dim]       {config_path}", soft_wrap=True)
    console.print(f"  [dim]provider:[/dim]   [magenta]{provider}[/magenta]")
    console.print(f"  [dim]model:[/dim]      [cyan]{cfg.model}[/cyan]")
    console.print(f"  [dim]mode:[/dim]       [cyan]{cfg.mode}[/cyan]")
    console.print(f"  [dim]permission:[/dim] [cyan]{cfg.permission_mode}[/cyan]")
    console.print(f"  [dim]memory:[/dim]     {memory_path}", soft_wrap=True)

    # -- Skills --
    console.print()
    console.print(f"[bold]Skills[/bold] [dim]({len(skills)})[/dim]")
    if skills:
        for s in sorted(skills, key=lambda s: s.name):
            tier = _tier_label(s.folder)
            triggers = ", ".join(s.triggers)
            console.print(
                f"  [magenta]{s.name:<20}[/magenta] "
                f"[dim][{tier}][/dim]  "
                f"[dim]triggers:[/dim] [yellow]{triggers}[/yellow]"
            )
    else:
        console.print("  [dim](none)[/dim]")

    # -- Agents --
    console.print()
    console.print(f"[bold]Agents[/bold] [dim]({len(agents)})[/dim]")
    if agents:
        for a in sorted(agents, key=lambda a: a.name):
            desc = f" [dim]— {a.description}[/dim]" if a.description else ""
            console.print(f"  [magenta]{a.name}[/magenta]{desc}")
    else:
        console.print("  [dim](none)[/dim]")

    # -- Hooks --
    console.print()
    console.print(f"[bold]Hooks[/bold] [dim]({len(hook_defs)})[/dim]")
    if hook_defs:
        for h in hook_defs:
            tier = _tier_label(h.source_path)
            enabled = "" if h.enabled else " [yellow](disabled)[/yellow]"
            console.print(
                f"  [magenta]{h.name:<20}[/magenta] "
                f"[dim][{tier}][/dim]  "
                f"[cyan]{h.event}[/cyan] "
                f"[dim]matcher=[/dim]{h.matcher} "
                f"[dim]action=[/dim]{h.action}{enabled}"
            )
    else:
        console.print("  [dim](none)[/dim]")

    console.print()
