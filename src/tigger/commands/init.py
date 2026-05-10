from __future__ import annotations

import json
import pathlib
import shutil

from tigger._constants import CONFIG_DIR, home_config_dir
from tigger.resolve import seed_global
from tigger.types import RunContext

BUNDLED_ASSETS = pathlib.Path(__file__).resolve().parent.parent / "assets"

# Templates for project-level .tigger/ scaffolding only.
# Global (~/.tigger/) is seeded from internal skills/agents instead.
#
# NOTE: we deliberately do NOT seed a project-level `system.md`.
# `resolve.resolve_file` returns the first existing tier (project >
# global > bundled), so any project `system.md` *replaces* the bundled
# 100+ line default. A 3-line placeholder claiming to "prepend" was
# silently disabling the real system prompt and degrading model
# behaviour. Users who want a custom prompt should copy
# `src/tigger/assets/system.md` and edit it explicitly.
_TEMPLATES: dict[str, str] = {}

_DIR_TEMPLATES = {
    "skills": {
        "SKILL.md": '''---
name: example-skill
triggers:
  - /example
context: inline
---
This is an example skill. Replace this with your skill content.
''',
    },
    "agents": {
        "example-agent.md": '''---
name: example-agent
description: Describe when to use this agent
tools:
  - read
  - glob
  - grep
---
You are a helpful agent. Describe your purpose here.
''',
    },
    "hooks": {
        "example-hook.md": '''---
name: example-hook
event: PreToolUse
matcher: ".*"
action: warn
enabled: false
---
Example hook (disabled). Set `enabled: true` and edit matcher/body to use it.
''',
    },
    "modes": {
        "example-mode.md": '''---
name: example
---
You are in example mode. Replace this with your mode behaviour.
''',
    },
}


def _write(path: pathlib.Path, content: str, force: bool) -> bool:
    """Write *content* to *path*. Returns True if written, False if skipped."""
    if path.exists() and not force:
        return False
    path.write_text(content)
    return True


def _backfill_missing(existing: dict, defaults: dict) -> list[str]:
    """Recursively add keys from *defaults* that are absent in *existing*.

    Mutates *existing*. Returns a list of dotted paths that were added.
    User values are never overwritten.
    """
    added: list[str] = []
    for key, default_val in defaults.items():
        if key not in existing:
            existing[key] = default_val
            added.append(key)
        elif isinstance(default_val, dict) and isinstance(existing[key], dict):
            for sub in _backfill_missing(existing[key], default_val):
                added.append(f"{key}.{sub}")
    return added


def _seed_or_backfill_config(target: pathlib.Path, example: pathlib.Path,
                              force: bool = False) -> tuple[str, list[str]]:
    """Create config.json from *example* if absent. With *force*, overwrite.
    Otherwise, backfill missing keys without touching existing values.

    Returns (status, details) where status is one of:
      "created"      — file was absent, copied from example
      "overwritten"  — force=True and file existed, replaced with example
      "backfilled"   — file existed; missing keys added (details lists them)
      "unchanged"    — file existed and had no missing keys
    """
    if not example.exists():
        return ("unchanged", [])
    if not target.exists():
        shutil.copy2(example, target)
        return ("created", [])
    if force:
        target.unlink()
        shutil.copy2(example, target)
        return ("overwritten", [])
    try:
        existing = json.loads(target.read_text())
        defaults = json.loads(example.read_text())
    except json.JSONDecodeError:
        return ("unchanged", [])
    if not isinstance(existing, dict) or not isinstance(defaults, dict):
        return ("unchanged", [])
    added = _backfill_missing(existing, defaults)
    if added:
        target.write_text(json.dumps(existing, indent=2) + "\n")
        return ("backfilled", added)
    return ("unchanged", [])


def cmd_init(args: str, ctx: RunContext) -> None:
    tokens = args.split()
    is_global = "--global" in tokens
    force = "--force" in tokens

    if is_global:
        global_dir = home_config_dir()
        global_dir.mkdir(parents=True, exist_ok=True)
        seeded = seed_global(global_dir, force=force)

        # system.md: copy if absent (or overwrite with --force).
        bundled_system = BUNDLED_ASSETS / "system.md"
        target_system = global_dir / "system.md"
        extras_copied = []
        if bundled_system.exists() and (force or not target_system.exists()):
            shutil.copy2(bundled_system, target_system)
            extras_copied.append("system.md")

        # config.json: backfill missing keys; --force overwrites entirely.
        cfg_status, cfg_added = _seed_or_backfill_config(
            global_dir / "config.json", BUNDLED_ASSETS / "config.example.json", force=force,
        )
        if cfg_status in ("created", "overwritten"):
            extras_copied.append("config.json")

        from tigger.ui import console
        if seeded or extras_copied:
            verb = "Re-seeded" if force else "Seeded"
            extras = (" + " + ", ".join(extras_copied)) if extras_copied else ""
            console.print(
                f"[dim]✓[/dim] {verb} [cyan]{global_dir}[/cyan] "
                f"[dim]from internal skills, agents, modes, hooks{extras}.[/dim]",
                soft_wrap=True,
            )
        elif cfg_status != "backfilled":
            console.print(
                f"[cyan]{global_dir}[/cyan] [dim]already populated — nothing new to seed.[/dim]",
                soft_wrap=True,
            )
            console.print(
                "  [dim]Use[/dim] [cyan]--force[/cyan] [dim]to overwrite existing files.[/dim]"
            )
        if cfg_status == "backfilled":
            console.print(
                f"  [dim]config.json: backfilled missing keys[/dim] "
                f"([yellow]{', '.join(cfg_added)}[/yellow])"
            )
        console.print(
            "  [dim]Skills and agents are live copies you can edit freely.[/dim]"
        )
        console.print(
            "  [dim]New internal skills from upgrades will be added automatically.[/dim]"
        )
        return

    tigger_dir = pathlib.Path.cwd() / CONFIG_DIR
    tigger_dir.mkdir(parents=True, exist_ok=True)

    created = []
    overwritten = []
    skipped = []

    for name, content in _TEMPLATES.items():
        path = tigger_dir / name
        existed = path.exists()
        if _write(path, content, force):
            (overwritten if existed else created).append(name)
        else:
            skipped.append(name)

    # config.json: backfill missing keys; --force overwrites entirely.
    cfg_status, cfg_added = _seed_or_backfill_config(
        tigger_dir / "config.json", BUNDLED_ASSETS / "config.example.json", force=force,
    )
    if cfg_status == "created":
        created.append("config.json")
    elif cfg_status == "overwritten":
        overwritten.append("config.json")
    elif cfg_status == "unchanged":
        skipped.append("config.json")

    for dirname, files in _DIR_TEMPLATES.items():
        dirpath = tigger_dir / dirname
        dirpath.mkdir(exist_ok=True)
        for name, content in files.items():
            path = dirpath / name
            label = f"{dirname}/{name}"
            existed = path.exists()
            if _write(path, content, force):
                (overwritten if existed else created).append(label)
            else:
                skipped.append(label)

    from tigger.ui import console
    if created:
        console.print(
            f"[dim]✓[/dim] Scaffolded [cyan]{tigger_dir}[/cyan][dim]:[/dim]",
            soft_wrap=True,
        )
        console.print(
            f"  [dim]Created:[/dim] [green]{', '.join(created)}[/green]"
        )
    if overwritten:
        console.print(
            f"  [dim]Overwritten (--force):[/dim] [yellow]{', '.join(overwritten)}[/yellow]"
        )
    if skipped:
        console.print(
            f"  [dim]Skipped (already exist):[/dim] {', '.join(skipped)}"
        )
        if not force:
            console.print(
                "  [dim]Use[/dim] [cyan]--force[/cyan] [dim]to overwrite.[/dim]"
            )
    if cfg_status == "backfilled":
        console.print(
            f"  [dim]config.json: backfilled missing keys[/dim] "
            f"([yellow]{', '.join(cfg_added)}[/yellow])"
        )
    if not created and not overwritten and not skipped and cfg_status != "backfilled":
        console.print("[dim]Nothing to do.[/dim]")
