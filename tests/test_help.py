"""Tests for the help system (Unit 2)."""
from __future__ import annotations
from functools import partial
from tigger.commands.misc import cmd_help
from tigger.commands import COMMAND_DESCRIPTIONS, COMMAND_HELP
from tigger.types import RunContext


def _make_ctx() -> RunContext:
    """Create a minimal RunContext for testing."""
    from tigger.types import Config
    cfg = Config(base_url="http://localhost", model="test-model", context_limit=4096)
    return RunContext(config=cfg, messages=[], system_prompt="")


def _make_commands() -> dict:
    """Return a small commands dict for testing."""
    return {
        "help": lambda args, ctx: None,
        "model": lambda args, ctx: None,
        "agent": lambda args, ctx: None,
    }


class TestHelpNoArgs:
    def test_lists_commands_with_descriptions(self, capsys):
        cmds = _make_commands()
        cmd_help(args="", ctx=_make_ctx(), commands=cmds, skills=[])
        out = capsys.readouterr().out
        assert "/help" in out
        assert "/model" in out
        assert "/agent" in out
        # Descriptions should appear
        assert COMMAND_DESCRIPTIONS["help"] in out
        assert COMMAND_DESCRIPTIONS["model"] in out
        assert COMMAND_DESCRIPTIONS["agent"] in out

    def test_lists_skills(self, capsys):
        class FakeSkill:
            triggers = ["/foo", "/bar"]
            name = "Fake Skill"
        cmds = _make_commands()
        cmd_help(args="", ctx=_make_ctx(), commands=cmds, skills=[FakeSkill()])
        out = capsys.readouterr().out
        assert "Fake Skill" in out
        assert "/foo" in out


class TestHelpInternalFiltering:
    def test_hides_internal_skills_by_default(self, capsys):
        class UserSkill:
            triggers = ["/user"]
            name = "user-skill"
        class InternalSkill:
            triggers = ["/_debug"]
            name = "_debug"
        cmds = _make_commands()
        cmd_help(args="", ctx=_make_ctx(), commands=cmds,
                 skills=[UserSkill(), InternalSkill()])
        out = capsys.readouterr().out
        assert "user-skill" in out
        assert "/_debug" not in out  # internal skill trigger hidden

    def test_all_flag_shows_internal_skills(self, capsys):
        class InternalSkill:
            triggers = ["/_debug"]
            name = "_debug"
        cmds = _make_commands()
        cmd_help(args="--all", ctx=_make_ctx(), commands=cmds,
                 skills=[InternalSkill()])
        out = capsys.readouterr().out
        assert "_debug" in out
        assert "(internal)" in out

    def test_shows_agents(self, capsys):
        class FakeAgent:
            name = "test-engineer"
            description = "Bug reproduction agent"
        cmds = _make_commands()
        cmd_help(args="", ctx=_make_ctx(), commands=cmds,
                 skills=[], agents=[FakeAgent()])
        out = capsys.readouterr().out
        assert "test-engineer" in out
        assert "Bug reproduction agent" in out

    def test_hides_internal_agents_by_default(self, capsys):
        class InternalAgent:
            name = "_test-engineer"
            description = "Bug reproduction"
        cmds = _make_commands()
        cmd_help(args="", ctx=_make_ctx(), commands=cmds,
                 skills=[], agents=[InternalAgent()])
        out = capsys.readouterr().out
        assert "_test-engineer" not in out

    def test_all_flag_shows_internal_agents(self, capsys):
        class InternalAgent:
            name = "_test-engineer"
            description = "Bug reproduction"
        cmds = _make_commands()
        cmd_help(args="--all", ctx=_make_ctx(), commands=cmds,
                 skills=[], agents=[InternalAgent()])
        out = capsys.readouterr().out
        assert "_test-engineer" in out
        assert "(internal)" in out

    def test_no_agents_omits_section(self, capsys):
        cmds = _make_commands()
        cmd_help(args="", ctx=_make_ctx(), commands=cmds, skills=[])
        out = capsys.readouterr().out
        assert "Loaded agents:" not in out

    def test_all_internal_skills_hidden_in_default(self, capsys):
        class InternalSkill:
            triggers = ["/_debug"]
            name = "_debug"
        cmds = _make_commands()
        cmd_help(args="", ctx=_make_ctx(), commands=cmds,
                 skills=[InternalSkill()])
        out = capsys.readouterr().out
        assert "Loaded skills:" not in out


class TestHelpWithArgs:
    def test_model_detail(self, capsys):
        cmds = _make_commands()
        cmd_help(args="model", ctx=_make_ctx(), commands=cmds, skills=[])
        out = capsys.readouterr().out
        assert "/model" in out
        assert "interactive picker" in out

    def test_agent_detail(self, capsys):
        cmds = _make_commands()
        cmd_help(args="agent", ctx=_make_ctx(), commands=cmds, skills=[])
        out = capsys.readouterr().out
        assert "agents.md" in out
        assert "YAML frontmatter" in out

    def test_unknown_command(self, capsys):
        cmds = _make_commands()
        cmd_help(args="nonexistent", ctx=_make_ctx(), commands=cmds, skills=[])
        out = capsys.readouterr().out
        assert "Unknown command:" in out
        assert "nonexistent" in out
