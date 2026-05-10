"""Tests for the `/reload-plugins` handler and its summary renderer."""
from __future__ import annotations

import io
from contextlib import redirect_stdout
from dataclasses import dataclass

from tigger.commands.reload_plugins import (
    cmd_reload_plugins,
    render_report,
)
from tigger.reload import ReloadReport, SubsystemDelta


def _make_report(**deltas: SubsystemDelta) -> ReloadReport:
    r = ReloadReport()
    for _, delta in deltas.items():
        r.add(delta)
    return r


def test_render_report_zero_delta_omits_suffix():
    r = _make_report(skills=SubsystemDelta(name="skills",
                                           previous_count=12, new_count=12))
    line = render_report(r)
    assert line == "Skills: 12"


def test_render_report_added_only():
    r = _make_report(skills=SubsystemDelta(
        name="skills", previous_count=10, new_count=12,
        added=["a", "b"],
    ))
    assert render_report(r) == "Skills: 12 (+2)"


def test_render_report_removed_only():
    r = _make_report(skills=SubsystemDelta(
        name="skills", previous_count=12, new_count=11, removed=["x"],
    ))
    assert render_report(r) == "Skills: 11 (-1)"


def test_render_report_added_and_removed():
    r = _make_report(skills=SubsystemDelta(
        name="skills", previous_count=12, new_count=13,
        added=["a", "b"], removed=["x"],
    ))
    assert render_report(r) == "Skills: 13 (+2, -1)"


def test_render_report_mcp_shows_config_only_semantics():
    r = _make_report(mcp=SubsystemDelta(
        name="mcp", previous_count=2, new_count=3, added=["new-srv"],
    ))
    line = render_report(r)
    assert "MCP: 3" in line
    assert "+1 config" in line
    assert "0 restarted" in line


def test_render_report_failed_subsystem_inlined():
    r = _make_report(
        skills=SubsystemDelta(name="skills", previous_count=5, new_count=5),
        hooks=SubsystemDelta(name="hooks", previous_count=2, new_count=2,
                             error="RuntimeError: boom"),
    )
    line = render_report(r)
    assert "Skills: 5" in line
    assert "Hooks: ! RuntimeError: boom" in line


def test_render_report_orders_subsystems():
    r = _make_report(
        mcp=SubsystemDelta(name="mcp", previous_count=1, new_count=1),
        skills=SubsystemDelta(name="skills", previous_count=2, new_count=2),
        commands=SubsystemDelta(name="commands", previous_count=10, new_count=10),
    )
    line = render_report(r)
    # Skills before Commands before MCP per the renderer's fixed order.
    assert line.index("Skills") < line.index("Commands") < line.index("MCP")


# --- handler integration ---------------------------------------------------

@dataclass
class _FakeResult:
    project_dir: object = None
    global_dir: object = None


def test_handler_prints_summary(monkeypatch):
    fake = _FakeResult()

    def fake_reload(_result):
        return _make_report(
            skills=SubsystemDelta(name="skills", previous_count=10, new_count=12,
                                  added=["a", "b"]),
        )
    import tigger.commands.reload_plugins as mod
    monkeypatch.setattr(mod, "reload_all", fake_reload)

    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_reload_plugins("", ctx=None, result=fake)
    out = buf.getvalue()
    assert "Skills: 12 (+2)" in out


def test_handler_appends_failure_lines(monkeypatch):
    fake = _FakeResult()

    def fake_reload(_result):
        return _make_report(
            skills=SubsystemDelta(name="skills", previous_count=5, new_count=5),
            hooks=SubsystemDelta(name="hooks", previous_count=2, new_count=2,
                                 error="ValueError: bad hook"),
        )
    import tigger.commands.reload_plugins as mod
    monkeypatch.setattr(mod, "reload_all", fake_reload)

    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_reload_plugins("", ctx=None, result=fake)
    out = buf.getvalue()
    # Inline indicator (the "! ValueError" still appears inside render_report's
    # delta line) + per-failure detail line (now prefixed with ✗ glyph).
    assert "! ValueError: bad hook" in out
    assert "✗ hooks:" in out
    assert "ValueError: bad hook" in out


def test_handler_handles_runtime_error_from_orchestrator(monkeypatch):
    fake = _FakeResult()

    def boom(_result):
        raise RuntimeError("StartupResult is missing project_dir")
    import tigger.commands.reload_plugins as mod
    monkeypatch.setattr(mod, "reload_all", boom)

    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_reload_plugins("", ctx=None, result=fake)
    assert "Reload failed" in buf.getvalue()


# --- registration ----------------------------------------------------------

def test_reload_plugins_appears_in_command_descriptions():
    from tigger.commands import COMMAND_DESCRIPTIONS, COMMAND_HELP
    assert "reload-plugins" in COMMAND_DESCRIPTIONS
    assert "reload-plugins" in COMMAND_HELP


def test_bind_reload_command_registers_handler():
    from tigger.commands import bind_reload_command
    cmds: dict = {}
    sentinel = object()
    bind_reload_command(cmds, sentinel)
    assert "reload-plugins" in cmds
    assert callable(cmds["reload-plugins"])
