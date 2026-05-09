from __future__ import annotations

from tigger.types import RunContext
from tigger.ui import console


def cmd_skills(args: str, ctx: RunContext, skills: list) -> None:
    parts = args.strip().split(None, 1)
    subcmd = parts[0] if parts else ""

    if subcmd == "preview":
        name = parts[1].strip() if len(parts) > 1 else ""
        _preview(name, skills)
        return

    if not skills:
        console.print("[dim]No skills loaded.[/dim]")
        return
    console.print()
    console.print("[bold]Loaded skills[/bold]")
    for s in skills:
        triggers = ", ".join(s.triggers)
        console.print(
            f"  [magenta]{s.name}[/magenta]  "
            f"[dim]triggers=[/dim][yellow]{triggers}[/yellow]  "
            f"[dim]context={s.context}  tools={s.tools}[/dim]"
        )
    console.print()


def _preview(name: str, skills: list) -> None:
    if not name:
        console.print("[dim]Usage:[/dim] /skills preview <name>")
        return

    skill = None
    for s in skills:
        if s.name == name:
            skill = s
            break

    if skill is None:
        console.print(f"[red]Skill not found:[/red] {name}")
        available = ", ".join(s.name for s in skills)
        if available:
            console.print(f"[dim]Available:[/dim] {available}")
        return

    triggers = ", ".join(skill.triggers) if skill.triggers else "[dim](none)[/dim]"
    console.print()
    console.print(f"[bold magenta]{skill.name}[/bold magenta]")
    console.print(f"  [dim]triggers:[/dim]           [yellow]{triggers}[/yellow]")
    console.print(f"  [dim]context:[/dim]            {skill.context}")
    console.print(f"  [dim]tools:[/dim]              {skill.tools}")
    if skill.references:
        refs = ", ".join(r[0] for r in skill.references)
        console.print(f"  [dim]references:[/dim]         {refs}")
    if skill.assets:
        console.print(f"  [dim]assets:[/dim]             {skill.assets}")
    console.print(f"  [dim]inject_references:[/dim]  {skill.inject_references}")
    console.print()

    # Render with placeholder arguments so the user sees the full prompt
    rendered = skill.render(f"{skill.triggers[0]} $ARGUMENTS" if skill.triggers else "$ARGUMENTS")
    console.print(rendered, highlight=False)
