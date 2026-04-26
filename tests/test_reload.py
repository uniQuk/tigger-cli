"""Tests for the reload orchestrator (`src/tigger/reload.py`).

These tests exercise the per-subsystem disk-rediscovery path and verify that:
- New, removed, and unchanged items are reflected in the per-subsystem delta
- Mutations happen in place (object identity preserved on the underlying lists)
- Per-subsystem failures don't poison other subsystems' updates
- The slash-command dict is refreshed in place when rebuilt
"""
from __future__ import annotations

import pathlib
import textwrap
from dataclasses import dataclass, field
from typing import Any

import pytest

from tigger import reload as reload_mod
from tigger import resolve as resolve_mod
from tigger.reload import reload_all


@pytest.fixture(autouse=True)
def _empty_internal_dir(tmp_path_factory, monkeypatch):
    """Suppress packaged bundled skills/agents/etc. from leaking into reloads.

    The real `INTERNAL_DIR` points at `src/tigger/internal/` which carries
    shipped skills and agents. Tests want a clean tier set.
    """
    empty = tmp_path_factory.mktemp("empty-internal")
    monkeypatch.setattr(resolve_mod, "INTERNAL_DIR", empty)


# --- fixtures ---------------------------------------------------------------

def _make_skill(base_dir: pathlib.Path, name: str) -> None:
    sd = base_dir / "skills" / name
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        ---
        Body for {name}.
    """))


def _make_agent(base_dir: pathlib.Path, name: str) -> None:
    ad = base_dir / "agents"
    ad.mkdir(parents=True, exist_ok=True)
    (ad / f"{name}.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: {name} agent
        tools: [read]
        ---
        Agent body.
    """))


def _make_mode(base_dir: pathlib.Path, name: str) -> None:
    md = base_dir / "modes"
    md.mkdir(parents=True, exist_ok=True)
    (md / f"{name}.md").write_text(f"---\nname: {name}\n---\nMode body.\n")


def _make_hook(base_dir: pathlib.Path, name: str) -> None:
    hd = base_dir / "hooks"
    hd.mkdir(parents=True, exist_ok=True)
    (hd / f"{name}.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        event: PreToolUse
        action: log
        ---
        Hook body.
    """))


@dataclass
class _RunCtxStub:
    modes: list = field(default_factory=list)
    config: Any = None


@dataclass
class _StartupStub:
    """Minimal StartupResult lookalike with the fields reload_all reads."""
    ctx: _RunCtxStub
    commands: dict
    skills: list
    agents: list
    hook_defs: list
    registry: Any = None
    provider_fn: Any = None
    config_path: pathlib.Path | None = None
    summaries_dir: pathlib.Path | None = None
    summary_dir: pathlib.Path | None = None
    project_dir: pathlib.Path | None = None
    global_dir: pathlib.Path | None = None
    memory_path: pathlib.Path | None = None
    mcp_configs: list = field(default_factory=list)


def _make_stub(project: pathlib.Path, global_: pathlib.Path,
               *, commands: dict | None = None) -> _StartupStub:
    return _StartupStub(
        ctx=_RunCtxStub(),
        commands={} if commands is None else commands,
        skills=[],
        agents=[],
        hook_defs=[],
        project_dir=project,
        global_dir=global_,
        memory_path=project / "memory.md",
        config_path=project / "config.json",
    )


def _stub_load_builtin_commands(monkeypatch, fn=None):
    """Replace `tigger.commands.load_builtin_commands` with `fn` (or default).

    `reload.py` imports `load_builtin_commands` lazily inside `reload_all()` to
    avoid a startup-time circular import, so the patch target is the source
    module, not `tigger.reload`.
    """
    import tigger.commands as commands_mod
    if fn is None:
        def fn(**kw):
            d = {"clear": object(), "skills": object(), "agent": object()}
            for s in kw.get("skills") or []:
                d[s.name] = object()
            return d
    monkeypatch.setattr(commands_mod, "load_builtin_commands", fn)


# --- skills -----------------------------------------------------------------

def test_reload_picks_up_new_skill(tmp_path, monkeypatch):
    project, global_ = tmp_path / "p", tmp_path / "g"
    project.mkdir()
    global_.mkdir()
    _make_skill(global_, "alpha")
    _stub_load_builtin_commands(monkeypatch)
    stub = _make_stub(project, global_)

    # Initial state — pretend a prior reload already loaded "alpha".
    from tigger.resolve import resolve_skills
    stub.skills.extend(resolve_skills(project, global_))
    skills_id = id(stub.skills)

    _make_skill(project, "beta")
    report = reload_all(stub)

    delta = report.get("skills")
    assert delta is not None and delta.ok
    assert "beta" in delta.added
    assert delta.removed == []
    assert {s.name for s in stub.skills} == {"alpha", "beta"}
    assert id(stub.skills) == skills_id  # mutated in place


def test_reload_drops_removed_skill(tmp_path, monkeypatch):
    project, global_ = tmp_path / "p", tmp_path / "g"
    project.mkdir()
    global_.mkdir()
    _make_skill(project, "gone")
    _stub_load_builtin_commands(monkeypatch)
    stub = _make_stub(project, global_)
    from tigger.resolve import resolve_skills
    stub.skills.extend(resolve_skills(project, global_))

    # Remove the skill from disk.
    (project / "skills" / "gone" / "SKILL.md").unlink()
    (project / "skills" / "gone").rmdir()

    report = reload_all(stub)
    delta = report.get("skills")
    assert delta.ok
    assert delta.removed == ["gone"]
    assert delta.added == []
    assert stub.skills == []


def test_reload_no_changes_yields_empty_delta(tmp_path, monkeypatch):
    project, global_ = tmp_path / "p", tmp_path / "g"
    project.mkdir()
    global_.mkdir()
    _make_skill(global_, "stable")
    _stub_load_builtin_commands(monkeypatch)
    stub = _make_stub(project, global_)
    from tigger.resolve import resolve_skills
    stub.skills.extend(resolve_skills(project, global_))

    report = reload_all(stub)
    delta = report.get("skills")
    assert delta.ok
    assert delta.added == [] and delta.removed == []
    assert delta.previous_count == delta.new_count == 1
    assert not delta.changed


# --- shadowing --------------------------------------------------------------

def test_reload_honours_project_shadowing_for_skills(tmp_path, monkeypatch):
    project, global_ = tmp_path / "p", tmp_path / "g"
    project.mkdir()
    global_.mkdir()
    _make_skill(project, "shared")
    _make_skill(global_, "shared")
    _stub_load_builtin_commands(monkeypatch)
    stub = _make_stub(project, global_)

    report = reload_all(stub)
    assert report.get("skills").new_count == 1
    assert {s.name for s in stub.skills} == {"shared"}
    # Project tier should win — folder path lives under project_dir.
    skill = stub.skills[0]
    assert skill.folder is not None
    assert str(skill.folder).startswith(str(project))


# --- hooks (additive) -------------------------------------------------------

def test_reload_hooks_are_additive_across_tiers(tmp_path, monkeypatch):
    project, global_ = tmp_path / "p", tmp_path / "g"
    project.mkdir()
    global_.mkdir()
    _make_hook(project, "proj-hook")
    _make_hook(global_, "user-hook")
    _stub_load_builtin_commands(monkeypatch)
    stub = _make_stub(project, global_)

    report = reload_all(stub)
    delta = report.get("hooks")
    assert delta.ok
    assert delta.new_count == 2
    assert {h.name for h in stub.hook_defs} == {"proj-hook", "user-hook"}


# --- agents / modes / mcp ---------------------------------------------------

def test_reload_picks_up_new_agent_and_mode(tmp_path, monkeypatch):
    project, global_ = tmp_path / "p", tmp_path / "g"
    project.mkdir()
    global_.mkdir()
    _make_agent(project, "researcher")
    _make_mode(project, "plan")
    _stub_load_builtin_commands(monkeypatch)
    stub = _make_stub(project, global_)

    report = reload_all(stub)
    assert "researcher" in report.get("agents").added
    assert "plan" in report.get("modes").added
    assert {a.name for a in stub.agents} == {"researcher"}
    assert {m.name for m in stub.ctx.modes} == {"plan"}


def test_reload_mcp_config_refresh(tmp_path, monkeypatch):
    project, global_ = tmp_path / "p", tmp_path / "g"
    project.mkdir()
    global_.mkdir()
    (global_ / "mcp.json").write_text(
        '{"servers": {"server-a": {"command": ["echo", "hi"]}}}'
    )
    _stub_load_builtin_commands(monkeypatch)
    stub = _make_stub(project, global_)

    report = reload_all(stub)
    delta = report.get("mcp")
    assert delta.ok
    assert "server-a" in delta.added
    assert {c.name for c in stub.mcp_configs} == {"server-a"}


# --- failure isolation ------------------------------------------------------

def test_reload_isolates_per_subsystem_failure(tmp_path, monkeypatch):
    project, global_ = tmp_path / "p", tmp_path / "g"
    project.mkdir()
    global_.mkdir()
    _make_skill(project, "good-skill")
    _make_agent(project, "good-agent")
    _stub_load_builtin_commands(monkeypatch)
    stub = _make_stub(project, global_)

    # Make the hooks resolver explode while leaving the rest intact.
    def boom(*_a, **_kw):
        raise RuntimeError("simulated hook loader failure")
    monkeypatch.setattr(reload_mod, "resolve_hooks", boom)
    # Capture pre-state of hook list reference.
    pre_hooks_id = id(stub.hook_defs)

    report = reload_all(stub)
    hooks_delta = report.get("hooks")
    skills_delta = report.get("skills")
    agents_delta = report.get("agents")

    assert not hooks_delta.ok
    assert "simulated hook loader failure" in hooks_delta.error
    assert id(stub.hook_defs) == pre_hooks_id  # untouched
    assert stub.hook_defs == []

    # Other subsystems still updated.
    assert skills_delta.ok and "good-skill" in skills_delta.added
    assert agents_delta.ok and "good-agent" in agents_delta.added
    assert report.any_failed


def test_reload_command_rebuild_failure_preserves_prior_dict(tmp_path, monkeypatch):
    project, global_ = tmp_path / "p", tmp_path / "g"
    project.mkdir()
    global_.mkdir()

    # Pre-existing command dict — must remain after a rebuild failure.
    initial = {"clear": object(), "help": object()}
    stub = _make_stub(project, global_, commands=initial)
    cmd_dict_id = id(stub.commands)
    initial_keys = set(stub.commands.keys())

    def fail(**_kw):
        raise ValueError("commands rebuild kaboom")
    import tigger.commands as commands_mod
    monkeypatch.setattr(commands_mod, "load_builtin_commands", fail)

    report = reload_all(stub)
    delta = report.get("commands")
    assert delta is not None and not delta.ok
    assert "commands rebuild kaboom" in delta.error
    assert id(stub.commands) == cmd_dict_id  # same dict object
    assert set(stub.commands.keys()) == initial_keys


# --- in-place mutation contract --------------------------------------------

def test_reload_mutates_commands_dict_in_place(tmp_path, monkeypatch):
    project, global_ = tmp_path / "p", tmp_path / "g"
    project.mkdir()
    global_.mkdir()
    _make_skill(project, "added-skill")

    def fake_loader(**kw):
        # Return a fresh dict whose contents differ from the prior dict.
        return {"clear": object(), "skills": object(), "added-skill": object()}
    _stub_load_builtin_commands(monkeypatch, fake_loader)

    stub = _make_stub(project, global_, commands={"clear": "old", "stale": "x"})
    cmd_dict_id = id(stub.commands)

    reload_all(stub)
    assert id(stub.commands) == cmd_dict_id  # in place
    assert "stale" not in stub.commands       # cleared
    assert "added-skill" in stub.commands     # populated


def test_reload_refuses_when_session_predates_reload_support(tmp_path):
    # Both project_dir and global_dir missing — old session shape.
    stub = _StartupStub(
        ctx=_RunCtxStub(),
        commands={},
        skills=[],
        agents=[],
        hook_defs=[],
        project_dir=None,
        global_dir=None,
    )
    with pytest.raises(RuntimeError, match="missing project_dir"):
        reload_all(stub)


# --- report shape -----------------------------------------------------------

def test_report_lists_every_subsystem_and_commands(tmp_path, monkeypatch):
    project, global_ = tmp_path / "p", tmp_path / "g"
    project.mkdir()
    global_.mkdir()
    _stub_load_builtin_commands(monkeypatch)
    stub = _make_stub(project, global_)

    report = reload_all(stub)
    names = [d.name for d in report.deltas]
    assert names == ["skills", "hooks", "agents", "modes", "mcp", "commands"]
    assert all(d.ok for d in report.deltas)
    assert not report.any_failed
