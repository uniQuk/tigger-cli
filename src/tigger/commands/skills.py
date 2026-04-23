from __future__ import annotations
from tigger.types import RunContext


def cmd_skills(args: str, ctx: RunContext, skills: list) -> None:
    if not skills:
        print("No skills loaded.")
        return
    for s in skills:
        print(f"  {s.name}  triggers={s.triggers}  context={s.context}  tools={s.tools}")
