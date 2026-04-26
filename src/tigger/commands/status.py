from __future__ import annotations

import pathlib

from tigger._constants import home_config_dir
from tigger.hooks import HookDef
from tigger.resolve import INTERNAL_DIR
from tigger.skills import AgentDef, SkillDef
from tigger.types import RunContext


def _tier_label(source: pathlib.Path | None) -> str:
    """Return a human-readable tier label based on the source path."""
    if source is None:
        return "unknown"
    resolved = source.resolve()
    try:
        resolved.relative_to(INTERNAL_DIR.resolve())
        return "internal"
    except ValueError:
        pass
    try:
        resolved.relative_to(home_config_dir().resolve())
        return "user"
    except ValueError:
        pass
    return "project"


def cmd_status(
    args: str,
    ctx: RunContext,
    *,
    config_path: pathlib.Path,
    skills: list[SkillDef],
    agents: list[AgentDef],
    hook_defs: list[HookDef],
    memory_path: pathlib.Path,
) -> None:
    """Print the resolved runtime configuration."""
    cfg = ctx.config
    provider = cfg.active_provider
    if not provider:
        from tigger.config import derive_provider_name
        provider = derive_provider_name(cfg.base_url)

    # -- Config --
    print("\n  Config")
    print(f"    path:       {config_path}")
    print(f"    provider:   {provider}")
    print(f"    model:      {cfg.model}")
    print(f"    mode:       {cfg.mode}")
    print(f"    permission: {cfg.permission_mode}")
    print(f"    memory:     {memory_path}")

    # -- Skills --
    print(f"\n  Skills ({len(skills)})")
    if skills:
        for s in sorted(skills, key=lambda s: s.name):
            tier = _tier_label(s.folder)
            triggers = ", ".join(s.triggers)
            print(f"    {s.name:<20} [{tier}]  triggers: {triggers}")
    else:
        print("    (none)")

    # -- Agents --
    print(f"\n  Agents ({len(agents)})")
    if agents:
        for a in sorted(agents, key=lambda a: a.name):
            desc = f" — {a.description}" if a.description else ""
            print(f"    {a.name}{desc}")
    else:
        print("    (none)")

    # -- Hooks --
    print(f"\n  Hooks ({len(hook_defs)})")
    if hook_defs:
        for h in hook_defs:
            tier = _tier_label(h.source_path)
            enabled = "" if h.enabled else "  (disabled)"
            print(
                f"    {h.name:<20} [{tier}]  {h.event} "
                f"matcher={h.matcher} action={h.action}{enabled}"
            )
    else:
        print("    (none)")

    print()
