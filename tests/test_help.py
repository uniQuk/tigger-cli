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
        assert "Unknown command: nonexistent" in out
