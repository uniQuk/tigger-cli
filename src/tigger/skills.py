from __future__ import annotations
import pathlib
import sys
from dataclasses import dataclass, field

from tigger.parsing import parse_blocks, parse_single

__all__ = [
    "AgentDef",
    "ModeRef",
    "SkillDef",
    "load_agents",
    "load_agents_dir",
    "load_modes_dir",
    "load_skills",
    "load_skills_dir",
    "match_skill",
    "warn_on_command_collisions",
]


@dataclass
class SkillDef:
    name: str
    triggers: list[str]
    tools: list[str]
    context: str                                    # "inline" | "fork"
    body: str                                       # prompt template
    folder: pathlib.Path | None = None              # source folder
    references: list[tuple[str, str]] = field(default_factory=list)  # (filename, content) pairs
    assets: pathlib.Path | None = None              # assets/ subdir path
    inject_references: bool = True                  # auto-inject references into rendered prompt

    def render(self, user_input: str) -> str:
        args = user_input
        for trigger in self.triggers:
            if user_input.startswith(trigger):
                args = user_input[len(trigger):].strip()
                break

        # Build the rendered body from the skill template
        if "$ARGUMENTS" in self.body:
            rendered = self.body.replace("$ARGUMENTS", args)
        else:
            rendered = (self.body + f"\n\n---\n{args}") if args else self.body

        # Prepend references if injection is enabled
        if self.inject_references and self.references:
            ref_sections = []
            for filename, content in self.references:
                ref_sections.append(f"## Reference: {filename}\n\n{content}")
            return "\n\n".join(ref_sections) + "\n\n" + rendered

        return rendered


@dataclass
class AgentDef:
    name: str
    system_prompt: str
    tools: list[str]
    model: str | None = None
    description: str = ""                           # when to spawn this agent


from tigger.types import ModeRef as ModeRef  # re-export for backward compat




def load_skills(path: pathlib.Path) -> list[SkillDef]:
    """Load skills from a flat skills.md file (legacy/fallback)."""
    if not path.exists():
        return []
    blocks = parse_blocks(path.read_text(), source=str(path))
    skills = []
    for b in blocks:
        fm = b["fm"]
        if "name" not in fm:
            continue
        triggers = fm.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [triggers]
        tools = fm.get("tools", [])
        skills.append(SkillDef(
            name=fm["name"],
            triggers=triggers,
            tools=tools,
            context=fm.get("context", "inline"),
            body=b["body"],
        ))
    return skills


def load_skills_dir(skills_dir: pathlib.Path) -> list[SkillDef]:
    """Load skills from a directory. Each subdirectory with SKILL.md is one skill."""
    if not skills_dir.exists() or not skills_dir.is_dir():
        return []
    skills = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            continue
        b = parse_single(skill_md.read_text(), source=str(skill_md))
        if not b:
            continue
        fm = b["fm"]
        if "name" not in fm:
            continue

        # Triggers: explicit frontmatter wins; default is /<folder-name>
        triggers = fm.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [triggers]
        if not triggers:
            triggers = [f"/{entry.name}"]

        # References: glob references/*.md sorted by name, store (filename, content) tuples
        refs: list[tuple[str, str]] = []
        refs_dir = entry / "references"
        if refs_dir.exists():
            for ref_file in sorted(refs_dir.glob("*.md")):
                try:
                    refs.append((ref_file.name, ref_file.read_text()))
                except OSError as exc:
                    print(f"Warning: could not read {ref_file}: {exc}", file=sys.stderr)

        # Assets: store path if directory exists
        assets_dir = entry / "assets"
        assets = assets_dir if assets_dir.exists() else None

        tools = fm.get("tools", [])
        skills.append(SkillDef(
            name=fm["name"],
            triggers=triggers,
            tools=tools,
            context=fm.get("context", "inline"),
            body=b["body"],
            folder=entry,
            references=refs,
            assets=assets,
            inject_references=fm.get("inject_references", True),
        ))
    return skills


def load_agents(path: pathlib.Path) -> list[AgentDef]:
    if not path.exists():
        return []
    blocks = parse_blocks(path.read_text(), source=str(path))
    agents = []
    for b in blocks:
        fm = b["fm"]
        if "name" not in fm:
            continue
        tools = fm.get("tools", [])
        agents.append(AgentDef(
            name=fm["name"],
            system_prompt=fm.get("system_prompt", ""),
            tools=tools,
            model=fm.get("model"),
        ))
    return agents


def load_agents_dir(agents_dir: pathlib.Path) -> list[AgentDef]:
    """Load agents from a directory. Each .md file is one agent."""
    if not agents_dir.exists() or not agents_dir.is_dir():
        return []
    agents = []
    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        b = parse_single(entry.read_text(), source=str(entry))
        if not b:
            continue
        fm = b["fm"]
        name = fm.get("name", entry.stem)
        if not name:
            continue
        agents.append(AgentDef(
            name=name,
            system_prompt=b["body"],
            tools=fm.get("tools", []),
            model=fm.get("model"),
            description=fm.get("description", ""),
        ))
    return agents


def load_modes_dir(modes_dir: pathlib.Path) -> list[ModeRef]:
    """Load modes from a directory. Each .md file is one mode."""
    if not modes_dir.exists() or not modes_dir.is_dir():
        return []
    modes = []
    for entry in sorted(modes_dir.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        b = parse_single(entry.read_text(), source=str(entry))
        if not b:
            continue
        fm = b["fm"]
        name = fm.get("name", entry.stem)
        if not name:
            continue
        modes.append(ModeRef(
            name=name,
            body=b["body"],
            source_path=entry,
        ))
    return modes


def match_skill(user_input: str, skills: list[SkillDef]) -> SkillDef | None:
    """Match input to a skill by trigger.

    A trigger matches when the input is exactly the trigger or starts
    with `trigger + " "`. This prevents a trigger like `/m` from
    shadowing a longer command like `/memory`.
    """
    stripped = user_input.rstrip()
    for skill in skills:
        for trigger in skill.triggers:
            if stripped == trigger or user_input.startswith(trigger + " "):
                return skill
    return None


def warn_on_command_collisions(
    skills: list[SkillDef],
    command_names: list[str],
) -> list[str]:
    """Warn when a skill trigger collides with a built-in /-command.

    Emits a stderr warning for each collision and returns the list of
    warning messages (useful for testing). `command_names` is the list
    of built-in command names without the leading `/`.
    """
    import sys

    command_triggers = {f"/{name}" for name in command_names}
    warnings: list[str] = []
    for skill in skills:
        for trigger in skill.triggers:
            if trigger in command_triggers:
                location = skill.folder if skill.folder is not None else skill.name
                msg = (
                    f"[skill] trigger {trigger!r} in {location} "
                    f"collides with built-in command {trigger}; "
                    f"the built-in will take precedence"
                )
                warnings.append(msg)
                print(msg, file=sys.stderr)
    return warnings
