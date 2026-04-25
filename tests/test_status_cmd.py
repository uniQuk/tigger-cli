from __future__ import annotations
import pathlib
from functools import partial
from tigger.types import Config, RunContext
from tigger.skills import SkillDef, AgentDef
from tigger.hooks import HookDef
from tigger.commands.status import cmd_status, _tier_label


def _ctx(**overrides):
    cfg_defaults = dict(base_url="http://localhost:8080", model="test-model")
    cfg_defaults.update(overrides)
    return RunContext(config=Config(**cfg_defaults), messages=[], system_prompt="")


def _make_handler(config_path, skills=None, agents=None, hook_defs=None, memory_path=None):
    return partial(
        cmd_status,
        config_path=config_path,
        skills=skills or [],
        agents=agents or [],
        hook_defs=hook_defs or [],
        memory_path=memory_path or config_path.parent / "memory.md",
    )


def test_status_shows_config(tmp_path, capsys):
    config_path = tmp_path / ".tigger" / "config.yaml"
    handler = _make_handler(config_path)
    handler("", _ctx())
    out = capsys.readouterr().out
    assert "Config" in out
    assert str(config_path) in out
    assert "test-model" in out


def test_status_shows_provider(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    ctx = _ctx(active_provider="openai")
    handler = _make_handler(config_path)
    handler("", ctx)
    out = capsys.readouterr().out
    assert "openai" in out


def test_status_shows_skills(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    skills = [
        SkillDef(name="my-skill", triggers=["/my-skill"], tools=[], context="inline", body="test", folder=tmp_path),
    ]
    handler = _make_handler(config_path, skills=skills)
    handler("", _ctx())
    out = capsys.readouterr().out
    assert "Skills (1)" in out
    assert "my-skill" in out
    assert "/my-skill" in out


def test_status_shows_agents(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    agents = [
        AgentDef(name="test-agent", system_prompt="do stuff", tools=["read"], description="A test agent"),
    ]
    handler = _make_handler(config_path, agents=agents)
    handler("", _ctx())
    out = capsys.readouterr().out
    assert "Agents (1)" in out
    assert "test-agent" in out
    assert "A test agent" in out


def test_status_shows_hooks(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    hook_defs = [
        HookDef(name="block-rm", event="PreToolUse", matcher="bash", action="block", body="no rm", source_path=tmp_path / "hooks"),
    ]
    handler = _make_handler(config_path, hook_defs=hook_defs)
    handler("", _ctx())
    out = capsys.readouterr().out
    assert "Hooks (1)" in out
    assert "block-rm" in out
    assert "PreToolUse" in out
    assert "action=block" in out


def test_status_shows_disabled_hook(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    hook_defs = [
        HookDef(name="off-hook", event="PostToolUse", enabled=False, source_path=tmp_path),
    ]
    handler = _make_handler(config_path, hook_defs=hook_defs)
    handler("", _ctx())
    out = capsys.readouterr().out
    assert "(disabled)" in out


def test_status_empty_lists(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    handler = _make_handler(config_path)
    handler("", _ctx())
    out = capsys.readouterr().out
    assert "Skills (0)" in out
    assert "Agents (0)" in out
    assert "Hooks (0)" in out
    assert "(none)" in out


def test_status_shows_memory_path(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    mem = tmp_path / "memory.md"
    handler = _make_handler(config_path, memory_path=mem)
    handler("", _ctx())
    out = capsys.readouterr().out
    assert str(mem) in out


def test_tier_label_internal(monkeypatch):
    from tigger.resolve import INTERNAL_DIR
    assert _tier_label(INTERNAL_DIR / "skills" / "debug") == "internal"


def test_tier_label_user(tmp_path, monkeypatch):
    monkeypatch.setattr("tigger.commands.status.home_config_dir", lambda: tmp_path)
    assert _tier_label(tmp_path / "skills" / "foo") == "user"


def test_tier_label_project():
    assert _tier_label(pathlib.Path("/some/project/.tigger/skills/bar")) == "project"


def test_tier_label_none():
    assert _tier_label(None) == "unknown"
