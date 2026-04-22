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
    references: list[str] = field(default_factory=list)  # available for custom use; not auto-injected
    assets: pathlib.Path | None = None              # assets/ subdir path

    def render(self, user_input: str) -> str:
        for trigger in self.triggers:
            if user_input.startswith(trigger):
                args = user_input[len(trigger):].strip()
                return self.body.replace("$ARGUMENTS", args)
        return self.body.replace("$ARGUMENTS", user_input)


@dataclass
class AgentDef:
    name: str
    system_prompt: str
    tools: list[str]
    model: str | None = None


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

        # References: glob references/*.md sorted by name
        refs: list[str] = []
        refs_dir = entry / "references"
        if refs_dir.exists():
            for ref_file in sorted(refs_dir.glob("*.md")):
                try:
                    refs.append(ref_file.read_text())
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


def match_skill(user_input: str, skills: list[SkillDef]) -> SkillDef | None:
    for skill in skills:
        for trigger in skill.triggers:
            if user_input.startswith(trigger):
                return skill
    return None
