from __future__ import annotations

from tigger.types import RunContext


def cmd_skills(args: str, ctx: RunContext, skills: list) -> None:
    parts = args.strip().split(None, 1)
    subcmd = parts[0] if parts else ""

    if subcmd == "preview":
        name = parts[1].strip() if len(parts) > 1 else ""
        _preview(name, skills)
        return

    if not skills:
        print("No skills loaded.")
        return
    for s in skills:
        print(f"  {s.name}  triggers={s.triggers}  context={s.context}  tools={s.tools}")


def _preview(name: str, skills: list) -> None:
    if not name:
        print("Usage: /skills preview <name>")
        return

    skill = None
    for s in skills:
        if s.name == name:
            skill = s
            break

    if skill is None:
        print(f"Skill not found: {name}")
        available = ", ".join(s.name for s in skills)
        if available:
            print(f"Available: {available}")
        return

    # Show frontmatter metadata
    print(f"── Skill: {skill.name} ──")
    print(f"  triggers:  {skill.triggers}")
    print(f"  context:   {skill.context}")
    print(f"  tools:     {skill.tools}")
    if skill.references:
        print(f"  references: {[r[0] for r in skill.references]}")
    if skill.assets:
        print(f"  assets:    {skill.assets}")
    print(f"  inject_references: {skill.inject_references}")
    print()

    # Render with placeholder arguments so the user sees the full prompt
    rendered = skill.render(f"{skill.triggers[0]} $ARGUMENTS" if skill.triggers else "$ARGUMENTS")
    print(rendered)
