"""`/reload-plugins` — re-discover skills, hooks, agents, modes, commands, MCP."""
from __future__ import annotations

from tigger.reload import ReloadReport, reload_all
from tigger.types import RunContext


def _format_delta(label: str, delta) -> str:
    if not delta.ok:
        return f"{label}: ! {delta.error}"
    parts: list[str] = []
    if delta.added:
        parts.append(f"+{len(delta.added)}")
    if delta.removed:
        parts.append(f"-{len(delta.removed)}")
    suffix = f" ({', '.join(parts)})" if parts else ""
    return f"{label}: {delta.new_count}{suffix}"


def render_report(report: ReloadReport) -> str:
    """Build the one-line summary string. Pure for testability."""
    order = [
        ("skills", "Skills"),
        ("hooks", "Hooks"),
        ("agents", "Agents"),
        ("modes", "Modes"),
        ("commands", "Commands"),
        ("mcp", "MCP"),
    ]
    pieces: list[str] = []
    for key, label in order:
        delta = report.get(key)
        if delta is None:
            continue
        if key == "mcp" and delta.ok:
            # Make the "config-only refresh" semantics visible.
            extras = []
            if delta.added:
                extras.append(f"+{len(delta.added)} config")
            if delta.removed:
                extras.append(f"-{len(delta.removed)} config")
            extras.append("0 restarted")
            pieces.append(f"{label}: {delta.new_count} ({', '.join(extras)})")
        else:
            pieces.append(_format_delta(label, delta))
    return " · ".join(pieces)


def cmd_reload_plugins(args: str, ctx: RunContext, *, result) -> None:
    """Reload all plugin subsystems from disk into the running session.

    `result` is the live `StartupResult`; reload mutates its lists/dict in
    place so the running REPL and prompt completer see the new state.
    Dispatched only between turns (the slash-command dispatcher in
    `repl()` runs at the input prompt, never mid-turn), so no extra
    in-flight guard is needed.
    """
    try:
        report = reload_all(result)
    except RuntimeError as exc:
        print(f"Reload failed: {exc}")
        return

    print(render_report(report))

    if report.any_failed:
        print()
        for delta in report.deltas:
            if not delta.ok:
                print(f"  ! {delta.name}: {delta.error}")
