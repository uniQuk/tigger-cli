"""In-session reload of skills, hooks, agents, modes, slash commands, and MCP config.

Re-runs disk discovery for each plugin subsystem and swaps the new values into
the live `StartupResult` *in place*. Mutating in place rather than reassigning
is required because the running REPL, prompt completer, and partial-closure
command handlers all hold list/dict references by identity — replacing the
attribute would leave them pointing at stale containers.

This module is pure orchestration: no UI calls, no subprocess control. The
`/reload-plugins` command (`commands/reload_plugins.py`) renders the report.

MCP subprocess lifecycle is deliberately untouched. We refresh the config list
that drives discovery; already-running servers stay connected. New servers
become known via `mcp_configs`; whether they auto-connect depends on
`tigger.mcp` startup behaviour, which is currently eager (see Unit 3).
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from tigger.resolve import (
    resolve_agents,
    resolve_hooks,
    resolve_mcp_configs,
    resolve_modes,
    resolve_skills,
)

if TYPE_CHECKING:
    from tigger.main import StartupResult


@dataclasses.dataclass
class SubsystemDelta:
    """Per-subsystem reload outcome."""
    name: str
    previous_count: int = 0
    new_count: int = 0
    added: list[str] = dataclasses.field(default_factory=list)
    removed: list[str] = dataclasses.field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def changed(self) -> bool:
        return bool(self.added) or bool(self.removed)


@dataclasses.dataclass
class ReloadReport:
    """Aggregate result of a `/reload-plugins` invocation."""
    deltas: list[SubsystemDelta] = dataclasses.field(default_factory=list)

    def add(self, delta: SubsystemDelta) -> None:
        self.deltas.append(delta)

    def get(self, name: str) -> SubsystemDelta | None:
        for d in self.deltas:
            if d.name == name:
                return d
        return None

    @property
    def any_failed(self) -> bool:
        return any(not d.ok for d in self.deltas)


def _names(items: list[Any]) -> list[str]:
    return [getattr(it, "name", str(it)) for it in items]


def _reload_list(
    name: str,
    target: list[Any],
    loader: Callable[[], list[Any]],
) -> SubsystemDelta:
    """Reload one list-shaped subsystem; mutate `target` in place on success."""
    prev_names = _names(target)
    try:
        fresh = loader()
    except Exception as exc:  # noqa: BLE001 — surface in report, don't crash session
        return SubsystemDelta(
            name=name,
            previous_count=len(prev_names),
            new_count=len(prev_names),
            error=f"{type(exc).__name__}: {exc}",
        )
    new_names = _names(fresh)
    target[:] = fresh
    prev_set = set(prev_names)
    new_set = set(new_names)
    return SubsystemDelta(
        name=name,
        previous_count=len(prev_names),
        new_count=len(new_names),
        added=sorted(new_set - prev_set),
        removed=sorted(prev_set - new_set),
    )


def reload_all(result: StartupResult) -> ReloadReport:
    """Re-discover plugins from disk and swap them into `result` in place.

    Each subsystem reloads independently: a failure in one leaves prior state
    intact and is reported alongside successful subsystems. The slash-command
    dispatcher only runs between turns, so callers do not need a mid-turn
    guard.
    """
    # Deferred imports — `tigger.commands` already imports the
    # `/reload-plugins` handler, which in turn imports this module.
    from tigger.commands import bind_reload_command, load_builtin_commands

    if result.project_dir is None and result.global_dir is None:
        raise RuntimeError(
            "Cannot reload: StartupResult is missing project_dir and global_dir. "
            "This indicates the session was started before reload support was added."
        )

    report = ReloadReport()
    project_dir = result.project_dir
    global_dir = result.global_dir

    report.add(_reload_list(
        "skills", result.skills,
        lambda: resolve_skills(project_dir, global_dir),
    ))
    report.add(_reload_list(
        "hooks", result.hook_defs,
        lambda: resolve_hooks(project_dir, global_dir),
    ))
    report.add(_reload_list(
        "agents", result.agents,
        lambda: resolve_agents(project_dir, global_dir),
    ))
    report.add(_reload_list(
        "modes", result.ctx.modes,
        lambda: resolve_modes(project_dir, global_dir),
    ))
    mcp_delta = _reload_list(
        "mcp", result.mcp_configs,
        lambda: resolve_mcp_configs(project_dir, global_dir),
    )
    report.add(mcp_delta)
    # Spawn any newly added servers; existing ones are left running.
    if mcp_delta.ok and mcp_delta.added:
        try:
            from tigger.mcp import connect_new
            connect_new(result.registry, result.mcp_configs)
        except Exception as exc:  # noqa: BLE001
            mcp_delta.error = (
                f"config refreshed but connect_new failed: "
                f"{type(exc).__name__}: {exc}"
            )

    # Rebuild the slash-command dict so newly registered handlers (e.g. dynamic
    # mode commands) appear and stale ones drop out. Mutate in place so the
    # REPL's captured reference and the prompt completer keep working.
    prev_cmds = sorted(result.commands.keys())
    try:
        new_commands = load_builtin_commands(
            memory_path=result.memory_path,
            config_path=result.config_path,
            skills=result.skills,
            agents=result.agents,
            registry=result.registry,
            provider_fn=result.provider_fn,
            summary_dir=result.summary_dir,
            modes=result.ctx.modes,
            hook_defs=result.hook_defs,
        )
    except Exception as exc:  # noqa: BLE001
        report.add(SubsystemDelta(
            name="commands",
            previous_count=len(prev_cmds),
            new_count=len(prev_cmds),
            error=f"{type(exc).__name__}: {exc}",
        ))
        return report

    # Re-bind /reload-plugins so it survives the rebuild. load_builtin_commands
    # has no back-reference to `result`, so the binding is layered on after.
    bind_reload_command(new_commands, result)
    new_cmd_names = sorted(new_commands.keys())
    result.commands.clear()
    result.commands.update(new_commands)
    prev_set = set(prev_cmds)
    new_set = set(new_cmd_names)
    report.add(SubsystemDelta(
        name="commands",
        previous_count=len(prev_cmds),
        new_count=len(new_cmd_names),
        added=sorted(new_set - prev_set),
        removed=sorted(prev_set - new_set),
    ))
    return report
