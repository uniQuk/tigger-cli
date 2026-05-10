"""3-tier resource resolution: project .tigger/ > user ~/.tigger/ > package internal/."""
from __future__ import annotations

import json
import pathlib
import shutil
from collections.abc import Callable, Iterable
from typing import TypeVar

from tigger._constants import home_config_dir
from tigger.hooks import HookDef, load_hooks_dir
from tigger.mcp import McpServerConfig, load_mcp_config
from tigger.skills import (
    AgentDef,
    ModeRef,
    SkillDef,
    load_agents,
    load_agents_dir,
    load_modes_dir,
    load_skills_dir,
)

INTERNAL_DIR = pathlib.Path(__file__).parent / "internal"

T = TypeVar("T")


def is_global_config(config_path: pathlib.Path) -> bool:
    """Return True if *config_path* is under ~/.tigger/."""
    try:
        config_path.resolve().relative_to(home_config_dir().resolve())
        return True
    except ValueError:
        return False


def _seed_tier(internal_subdir: pathlib.Path, target_subdir: pathlib.Path,
               is_file: bool, force: bool = False) -> bool:
    """Copy items from *internal_subdir* to *target_subdir* if absent.

    Underscore-prefixed items are skipped when the non-prefixed variant
    already exists (legacy of a prior seed). When *force* is True, existing
    targets are overwritten. Returns True if anything copied.
    """
    if not internal_subdir.exists():
        return False
    target_subdir.mkdir(parents=True, exist_ok=True)
    seeded = False
    for src in sorted(internal_subdir.iterdir()):
        if is_file:
            if not src.is_file() or src.suffix != ".md":
                continue
        else:
            if not src.is_dir():
                continue
        target = target_subdir / src.name
        if target.exists() and not force:
            continue
        if src.name.startswith("_") and not force:
            non_prefixed = target_subdir / src.name[1:]
            if non_prefixed.exists():
                continue
        if is_file:
            if target.exists() and force:
                target.unlink()
            shutil.copy2(src, target)
        else:
            if target.exists() and force:
                shutil.rmtree(target)
            shutil.copytree(src, target)
        seeded = True
    return seeded


def seed_global(global_dir: pathlib.Path, internal_dir: pathlib.Path | None = None,
                force: bool = False) -> bool:
    """Copy internal skills/agents/modes/hooks to ~/.tigger/ if they don't exist yet.

    Returns True if anything was seeded, False if global already populated.
    This runs once on first launch — after that, ~/.tigger/ is the living
    copy that the user and tigger can edit freely.
    """
    if internal_dir is None:
        internal_dir = INTERNAL_DIR
    seeded = False
    seeded |= _seed_tier(internal_dir / "skills", global_dir / "skills", is_file=False, force=force)
    seeded |= _seed_tier(internal_dir / "agents", global_dir / "agents", is_file=True, force=force)
    seeded |= _seed_tier(internal_dir / "modes",  global_dir / "modes",  is_file=True, force=force)
    seeded |= _seed_tier(internal_dir / "hooks",  global_dir / "hooks",  is_file=True, force=force)
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


def _tier_paths(
    project_dir: pathlib.Path | None,
    global_dir: pathlib.Path | None,
    internal_dir: pathlib.Path | None,
    subdir: str,
) -> list[pathlib.Path]:
    """Return existing tier paths in priority order: internal → global → project."""
    return [
        d / subdir for d in (internal_dir, global_dir, project_dir)
        if d is not None
    ]


def _merge_tiers(
    tiers: Iterable[pathlib.Path],
    loader: Callable[[pathlib.Path], Iterable[T]],
    key: Callable[[T], str] = lambda x: x.name,  # type: ignore[attr-defined]
) -> list[T]:
    """Iterate tiers in priority order; later tiers shadow earlier by key."""
    seen: dict[str, T] = {}
    for tier in tiers:
        for item in loader(tier):
            seen[key(item)] = item
    return list(seen.values())


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
    for tier in _tier_paths(project_dir, global_dir, internal_dir, "hooks"):
        all_hooks.extend(load_hooks_dir(tier))
    return all_hooks


def resolve_skills(
    project_dir: pathlib.Path | None,
    global_dir: pathlib.Path | None,
    internal_dir: pathlib.Path | None = None,
) -> list[SkillDef]:
    """Merge skills across tiers. Project shadows global shadows internal by name."""
    if internal_dir is None:
        internal_dir = INTERNAL_DIR
    return _merge_tiers(
        _tier_paths(project_dir, global_dir, internal_dir, "skills"),
        load_skills_dir,
    )


def resolve_agents(
    project_dir: pathlib.Path | None,
    global_dir: pathlib.Path | None,
    internal_dir: pathlib.Path | None = None,
) -> list[AgentDef]:
    """Merge agents across tiers. Project shadows global shadows internal by name.

    Within each tier, flat agents.md is loaded first, then directory agents
    (directory wins on name collision).
    """
    if internal_dir is None:
        internal_dir = INTERNAL_DIR

    def tier_loader(agents_dir: pathlib.Path) -> list[AgentDef]:
        tier_agents: dict[str, AgentDef] = {}
        agents_md = agents_dir.parent / "agents.md"
        if agents_md.exists():
            for agent in load_agents(agents_md):
                tier_agents[agent.name] = agent
        for agent in load_agents_dir(agents_dir):
            tier_agents[agent.name] = agent
        return list(tier_agents.values())

    return _merge_tiers(
        _tier_paths(project_dir, global_dir, internal_dir, "agents"),
        tier_loader,
    )


def resolve_modes(
    project_dir: pathlib.Path | None,
    global_dir: pathlib.Path | None,
    internal_dir: pathlib.Path | None = None,
) -> list[ModeRef]:
    """Merge modes across tiers. Project shadows global shadows internal by name."""
    if internal_dir is None:
        internal_dir = INTERNAL_DIR
    return _merge_tiers(
        _tier_paths(project_dir, global_dir, internal_dir, "modes"),
        load_modes_dir,
    )


def resolve_mcp_configs(
    project_dir: pathlib.Path | None,
    global_dir: pathlib.Path | None,
    internal_dir: pathlib.Path | None = None,
) -> list[McpServerConfig]:
    """Merge MCP configs across tiers. Project shadows global shadows internal by name."""
    if internal_dir is None:
        internal_dir = INTERNAL_DIR

    def loader(tier_dir: pathlib.Path) -> list[McpServerConfig]:
        mcp_path = tier_dir / "mcp.json"
        try:
            return load_mcp_config(mcp_path)
        except (json.JSONDecodeError, OSError) as exc:
            # Match the iter-40/41 [mcp] prefix theming used in mcp.py.
            from tigger.ui import console
            console.print(
                f"      [yellow]\\[mcp] Warning:[/yellow] failed to load "
                f"[cyan]{mcp_path}[/cyan]: [red]{exc}[/red]"
            )
            return []

    # mcp.json sits at the root of each tier (no subdirectory).
    tiers = [d for d in (internal_dir, global_dir, project_dir) if d is not None]
    return _merge_tiers(tiers, loader)
