"""3-tier resource resolution: project .tigger/ > user ~/.tigger/ > package internal/."""
from __future__ import annotations

import json
import pathlib
import shutil

from tigger._constants import home_config_dir
from tigger.hooks import HookDef, load_hooks_dir
from tigger.mcp import McpServerConfig, load_mcp_config
from tigger.skills import AgentDef, ModeRef, SkillDef, load_agents, load_agents_dir, load_modes_dir, load_skills_dir

INTERNAL_DIR = pathlib.Path(__file__).parent / "internal"


def is_global_config(config_path: pathlib.Path) -> bool:
    """Return True if *config_path* is under ~/.tigger/."""
    try:
        config_path.resolve().relative_to(home_config_dir().resolve())
        return True
    except ValueError:
        return False


def seed_global(global_dir: pathlib.Path, internal_dir: pathlib.Path | None = None) -> bool:
    """Copy internal skills/agents to ~/.tigger/ if they don't exist yet.

    Returns True if anything was seeded, False if global already populated.
    This runs once on first launch — after that, ~/.tigger/ is the living
    copy that the user and tigger can edit freely.
    """
    if internal_dir is None:
        internal_dir = INTERNAL_DIR
    seeded = False

    # Seed skills: copy each internal skill dir if not already present.
    # For underscore-prefixed internals (e.g. _debug/), also check if the
    # non-prefixed version (debug/) exists from a prior seed — skip if so.
    internal_skills = internal_dir / "skills"
    if internal_skills.exists():
        global_skills = global_dir / "skills"
        global_skills.mkdir(parents=True, exist_ok=True)
        for skill_dir in sorted(internal_skills.iterdir()):
            if not skill_dir.is_dir():
                continue
            target = global_skills / skill_dir.name
            if target.exists():
                continue
            # Check for non-prefixed version from prior seed
            if skill_dir.name.startswith("_"):
                non_prefixed = global_skills / skill_dir.name[1:]
                if non_prefixed.exists():
                    continue
            shutil.copytree(skill_dir, target)
            seeded = True

    # Seed agents: copy each internal agent .md if not already present.
    # Same underscore-prefix logic as skills above.
    internal_agents = internal_dir / "agents"
    if internal_agents.exists():
        global_agents = global_dir / "agents"
        global_agents.mkdir(parents=True, exist_ok=True)
        for agent_file in sorted(internal_agents.iterdir()):
            if not agent_file.is_file() or agent_file.suffix != ".md":
                continue
            target = global_agents / agent_file.name
            if target.exists():
                continue
            # Check for non-prefixed version from prior seed
            if agent_file.name.startswith("_"):
                non_prefixed = global_agents / agent_file.name[1:]
                if non_prefixed.exists():
                    continue
            shutil.copy2(agent_file, target)
            seeded = True

    # Seed modes: copy each internal mode .md if not already present.
    # Same underscore-prefix logic as agents above.
    internal_modes = internal_dir / "modes"
    if internal_modes.exists():
        global_modes = global_dir / "modes"
        global_modes.mkdir(parents=True, exist_ok=True)
        for mode_file in sorted(internal_modes.iterdir()):
            if not mode_file.is_file() or mode_file.suffix != ".md":
                continue
            target = global_modes / mode_file.name
            if target.exists():
                continue
            # Check for non-prefixed version from prior seed
            if mode_file.name.startswith("_"):
                non_prefixed = global_modes / mode_file.name[1:]
                if non_prefixed.exists():
                    continue
            shutil.copy2(mode_file, target)
            seeded = True

    return seeded


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


def resolve_hooks(
    project_dir: pathlib.Path | None,
    global_dir: pathlib.Path | None,
    internal_dir: pathlib.Path | None = None,
) -> list[HookDef]:
    """Load hooks from all tiers and concatenate (additive merge).

    Unlike skills/agents, hooks do NOT shadow by name — all hooks from
    all tiers fire. This ensures both project and global safety hooks execute.
    """
    if internal_dir is None:
        internal_dir = INTERNAL_DIR
    all_hooks: list[HookDef] = []
    for tier_dir in [
        internal_dir / "hooks" if internal_dir else None,
        global_dir / "hooks" if global_dir else None,
        project_dir / "hooks" if project_dir else None,
    ]:
        if tier_dir is None:
            continue
        all_hooks.extend(load_hooks_dir(tier_dir))
    return all_hooks


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
    for tier_dir in [
        internal_dir / "skills" if internal_dir else None,
        global_dir / "skills" if global_dir else None,
        project_dir / "skills" if project_dir else None,
    ]:
        if tier_dir is None:
            continue
        for skill in load_skills_dir(tier_dir):
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
         internal_dir / "agents.md" if internal_dir else None),
        (global_dir / "agents" if global_dir else None,
         global_dir / "agents.md" if global_dir else None),
        (project_dir / "agents" if project_dir else None,
         project_dir / "agents.md" if project_dir else None),
    ]
    for agents_dir, agents_md in tiers:
        if agents_dir is None:
            continue
        # Within each tier: flat file first, directory second (directory wins).
        tier_agents: dict[str, AgentDef] = {}
        if agents_md is not None:
            for agent in load_agents(agents_md):
                tier_agents[agent.name] = agent
        for agent in load_agents_dir(agents_dir):
            tier_agents[agent.name] = agent
        seen.update(tier_agents)
    return list(seen.values())


def resolve_modes(
    project_dir: pathlib.Path | None,
    global_dir: pathlib.Path | None,
    internal_dir: pathlib.Path | None = None,
) -> list[ModeRef]:
    """Merge modes across tiers. Project shadows global shadows internal by name."""
    if internal_dir is None:
        internal_dir = INTERNAL_DIR
    seen: dict[str, ModeRef] = {}
    for tier_dir in [
        internal_dir / "modes" if internal_dir else None,
        global_dir / "modes" if global_dir else None,
        project_dir / "modes" if project_dir else None,
    ]:
        if tier_dir is None:
            continue
        for mode in load_modes_dir(tier_dir):
            seen[mode.name] = mode
    return list(seen.values())


def resolve_mcp_configs(
    project_dir: pathlib.Path | None,
    global_dir: pathlib.Path | None,
    internal_dir: pathlib.Path | None = None,
) -> list[McpServerConfig]:
    """Merge MCP configs across tiers. Project shadows global shadows internal by name."""
    if internal_dir is None:
        internal_dir = INTERNAL_DIR
    seen: dict[str, McpServerConfig] = {}
    for tier_dir in [
        internal_dir if internal_dir else None,
        global_dir,
        project_dir,
    ]:
        if tier_dir is None:
            continue
        mcp_path = tier_dir / "mcp.json"
        try:
            for cfg in load_mcp_config(mcp_path):
                seen[cfg.name] = cfg
        except (json.JSONDecodeError, OSError) as exc:
            import sys
            print(f"[mcp] Warning: failed to load {mcp_path}: {exc}", file=sys.stderr)
    return list(seen.values())
