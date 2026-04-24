from __future__ import annotations
import pathlib
import re
import sys
from dataclasses import dataclass, field


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
    internal: bool = False                          # set by resolver for bundled skills

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
    internal: bool = False                          # set by resolver for bundled agents


def _parse_blocks(text: str) -> list[dict]:
    import yaml
    blocks = []
    parts = re.split(r"^---\s*$", text, flags=re.MULTILINE)
    i = 1
    while i + 1 < len(parts):
        fm_text = parts[i].strip()
        body = parts[i + 1].strip()
        if fm_text:
            try:
                fm = yaml.safe_load(fm_text)
                if isinstance(fm, dict):
                    blocks.append({"fm": fm, "body": body})
            except Exception:
                pass
        i += 2
    return blocks


def load_skills(path: pathlib.Path) -> list[SkillDef]:
    """Load skills from a flat skills.md file (legacy/fallback)."""
    if not path.exists():
        return []
    blocks = _parse_blocks(path.read_text())
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
        blocks = _parse_blocks(skill_md.read_text())
        if not blocks:
            continue
        b = blocks[0]
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
    blocks = _parse_blocks(path.read_text())
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
        blocks = _parse_blocks(entry.read_text())
        if not blocks:
            continue
        b = blocks[0]
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


def match_skill(user_input: str, skills: list[SkillDef]) -> SkillDef | None:
    for skill in skills:
        for trigger in skill.triggers:
            if user_input.startswith(trigger):
                return skill
    return None
