from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass, field

from tigger.parsing import parse_blocks, parse_single
from tigger.types import ModeRef as ModeRef  # re-export for backward compat

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
    "parse_output_budget",
    "warn_on_command_collisions",
]


def parse_output_budget(raw: object) -> int | None:
    """Parse the `output_budget` frontmatter field.

    - Missing / None → None (inherit default)
    - Integer (or numeric string) → that integer
    - "unbounded" (case-insensitive) → None (no gate)
    - Anything else → None (silently fall back rather than crashing skill load)
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None  # YAML true/false would coerce to 1/0 — reject.
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if s.lower() == "unbounded":
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _parse_chat_template_kwargs(raw: object) -> dict | None:
    """Coerce a frontmatter `chat_template_kwargs` value to a dict-or-None.

    Anything that isn't a dict is silently ignored — the loader's job is to
    survive bad skill files, not to fail the whole session.
    """
    if isinstance(raw, dict):
        return raw
    return None


def _parse_bool(raw: object) -> bool:
    """Liberal bool parser — accepts YAML true/false and the strings
    "true"/"false"/"1"/"0" (case-insensitive). Anything else returns False.
    """
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in {"true", "1", "yes", "on"}
    return False


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
    agent: str | None = None                         # delegate to named agent when context=fork
    # Per-call output budget (chars) for write.content / edit.new_string|old_string
    # when this skill is the active execution context. None means inherit from
    # config.output_budget_default. 0 means disable the gate explicitly.
    # YAML literal "unbounded" parses to None.
    output_budget: int | None = None
    # Per-skill chat_template_kwargs override (passed via OpenAI extra_body).
    # The skill-level dict is merged on top of the workspace config so a skill
    # can selectively flip flags like {"enable_thinking": False} without
    # losing the rest of the config. None = no override.
    chat_template_kwargs: dict | None = None
    # When True, the agent loop breaks immediately after a successful `write`
    # so the model can't enter a post-write recovery loop. Use for generative
    # skills whose output is a single big artifact (HTML, image, doc).
    stop_after_write: bool = False
    # Internal loader bookkeeping: false means the value came from Tigger's
    # defaults/inference rather than the skill frontmatter. Explicit skill
    # declarations always win over inferred artifact-generation defaults.
    context_explicit: bool = False
    tools_explicit: bool = False
    output_budget_explicit: bool = False
    chat_template_kwargs_explicit: bool = False
    stop_after_write_explicit: bool = False

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

        # Prepend a location header so the model can resolve relative paths
        # (e.g. `assets/template.html`) against the skill's actual folder,
        # whether it lives in the project's .tigger/ or the user's ~/.tigger/.
        location_lines: list[str] = []
        if self.folder is not None:
            location_lines.append(f"Skill folder: {self.folder.resolve()}")
        if self.assets is not None:
            location_lines.append(f"Assets folder: {self.assets.resolve()}")
        if location_lines:
            header = (
                "## Skill location\n\n"
                + "\n".join(location_lines)
                + "\n\nResolve any relative paths in the instructions below "
                "(e.g. `assets/template.html`) against the skill folder above. "
                "Read templates from there; do not recreate the skill or copy "
                "its files into the project source tree.\n"
            )
            rendered = header + "\n" + rendered

        # Prepend references if injection is enabled
        if self.inject_references and self.references:
            ref_sections = []
            for filename, content in self.references:
                ref_sections.append(f"## Reference: {filename}\n\n{content}")
            return "\n\n".join(ref_sections) + "\n\n" + rendered

        return rendered


_ARTIFACT_TOOLS = ["read", "glob", "write", "edit", "analyze"]
_ARTIFACT_OUTPUT_BUDGET = 32768


def _looks_like_single_file_artifact(body: str) -> bool:
    """Heuristic for portable skills that generate one large local artifact.

    Many shared skills intentionally contain only portable instructions, not
    Tigger-specific frontmatter. Running those inline in the full conversation
    makes local models pay repeated full-prefill costs while writing large
    HTML/SVG files. This narrow classifier lets the loader attach fast runtime
    defaults without changing the skill file itself.
    """
    lower = body.lower()
    has_artifact = (
        "single self-contained" in lower
        or "standalone html" in lower
        or "standalone .html" in lower
        or "standalone html files" in lower
    )
    has_format = ".html" in lower or "inline svg" in lower or "svg graphics" in lower
    has_file_intent = "produce" in lower or "create" in lower or "write" in lower
    return has_artifact and has_format and has_file_intent


def _apply_inferred_skill_defaults(skill: SkillDef) -> SkillDef:
    """Apply runtime-only defaults for portable single-artifact skills."""
    if not _looks_like_single_file_artifact(skill.body):
        return skill
    if not skill.context_explicit:
        skill.context = "fork"
    if not skill.tools_explicit:
        skill.tools = list(_ARTIFACT_TOOLS)
    if not skill.output_budget_explicit:
        skill.output_budget = _ARTIFACT_OUTPUT_BUDGET
    if not skill.chat_template_kwargs_explicit:
        skill.chat_template_kwargs = {
            "enable_thinking": False,
            "preserve_thinking": False,
        }
    return skill


@dataclass
class AgentDef:
    name: str
    system_prompt: str
    tools: list[str]
    model: str | None = None
    description: str = ""                           # when to spawn this agent


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
        skill = SkillDef(
            name=fm["name"],
            triggers=triggers,
            tools=tools,
            context=fm.get("context", "inline"),
            body=b["body"],
            agent=fm.get("agent"),
            output_budget=parse_output_budget(fm.get("output_budget")),
            chat_template_kwargs=_parse_chat_template_kwargs(
                fm.get("chat_template_kwargs")
            ),
            stop_after_write=_parse_bool(fm.get("stop_after_write")),
            context_explicit="context" in fm,
            tools_explicit="tools" in fm,
            output_budget_explicit="output_budget" in fm,
            chat_template_kwargs_explicit="chat_template_kwargs" in fm,
            stop_after_write_explicit="stop_after_write" in fm,
        )
        skills.append(_apply_inferred_skill_defaults(skill))
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
        skill = SkillDef(
            name=fm["name"],
            triggers=triggers,
            tools=tools,
            context=fm.get("context", "inline"),
            body=b["body"],
            folder=entry,
            references=refs,
            assets=assets,
            inject_references=fm.get("inject_references", True),
            agent=fm.get("agent"),
            output_budget=parse_output_budget(fm.get("output_budget")),
            chat_template_kwargs=_parse_chat_template_kwargs(
                fm.get("chat_template_kwargs")
            ),
            stop_after_write=_parse_bool(fm.get("stop_after_write")),
            context_explicit="context" in fm,
            tools_explicit="tools" in fm,
            output_budget_explicit="output_budget" in fm,
            chat_template_kwargs_explicit="chat_template_kwargs" in fm,
            stop_after_write_explicit="stop_after_write" in fm,
        )
        skills.append(_apply_inferred_skill_defaults(skill))
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
