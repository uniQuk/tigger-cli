"""3-tier resource resolution: project .tigger/ > user ~/.tigger/ > package internal/."""
from __future__ import annotations

import pathlib

from tigger._constants import home_config_dir
from tigger.skills import AgentDef, SkillDef, load_agents, load_agents_dir, load_skills_dir

INTERNAL_DIR = pathlib.Path(__file__).parent / "internal"


def is_global_config(config_path: pathlib.Path) -> bool:
    """Return True if *config_path* is under ~/.tigger/."""
    try:
        config_path.resolve().relative_to(home_config_dir().resolve())
        return True
    except ValueError:
        return False


def resolve_file(
    name: str,
    project_dir: pathlib.Path | None,
    global_dir: pathlib.Path | None,
    bundled_dir: pathlib.Path | None = None,
) -> pathlib.Path | None:
    """Return the first existing path for *name* in tier order, or None."""
    for d in (project_dir, global_dir, bundled_dir):
        if d is not None:
            candidate = d / name
            if candidate.exists():
                return candidate
    return None


def resolve_skills(
    project_dir: pathlib.Path | None,
    global_dir: pathlib.Path | None,
    internal_dir: pathlib.Path | None = None,
) -> list[SkillDef]:
    """Merge skills across tiers. Project shadows global shadows internal by name."""
    if internal_dir is None:
        internal_dir = INTERNAL_DIR
    seen: dict[str, SkillDef] = {}
    # Load in reverse priority: internal first, then global, then project.
    # Later entries shadow earlier ones by name.
    for tier_dir, is_internal in [
        (internal_dir / "skills" if internal_dir else None, True),
        (global_dir / "skills" if global_dir else None, False),
        (project_dir / "skills" if project_dir else None, False),
    ]:
        if tier_dir is None:
            continue
        for skill in load_skills_dir(tier_dir):
            if is_internal:
                skill.internal = True
            seen[skill.name] = skill
    return list(seen.values())


def resolve_agents(
    project_dir: pathlib.Path | None,
    global_dir: pathlib.Path | None,
    internal_dir: pathlib.Path | None = None,
) -> list[AgentDef]:
    """Merge agents across tiers. Project shadows global shadows internal by name.

    Within each tier, directory agents are loaded first, then flat agents.md
    entries are merged (directory wins on name collision).
    """
    if internal_dir is None:
        internal_dir = INTERNAL_DIR
    seen: dict[str, AgentDef] = {}
    # Load in reverse priority order so higher-priority tiers overwrite.
    tiers = [
        (internal_dir / "agents" if internal_dir else None,
         internal_dir / "agents.md" if internal_dir else None,
         True),
        (global_dir / "agents" if global_dir else None,
         global_dir / "agents.md" if global_dir else None,
         False),
        (project_dir / "agents" if project_dir else None,
         project_dir / "agents.md" if project_dir else None,
         False),
    ]
    for agents_dir, agents_md, is_internal in tiers:
        if agents_dir is None:
            continue
        # Within each tier: flat file first, directory second (directory wins).
        tier_agents: dict[str, AgentDef] = {}
        if agents_md is not None:
            for agent in load_agents(agents_md):
                if is_internal:
                    agent.internal = True
                tier_agents[agent.name] = agent
        for agent in load_agents_dir(agents_dir):
            if is_internal:
                agent.internal = True
            tier_agents[agent.name] = agent
        seen.update(tier_agents)
    return list(seen.values())
