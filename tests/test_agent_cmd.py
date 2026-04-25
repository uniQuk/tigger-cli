from __future__ import annotations
from unittest.mock import patch
from tigger.types import Config, RunContext, TextChunk, AssistantMessage
from tigger.tools import ToolRegistry
from tigger.hooks import HookRegistry
from tigger.skills import AgentDef
from tigger.commands.agent import cmd_agent


def _ctx():
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    return RunContext(config=cfg, messages=[], system_prompt="test")


def _agent(name="test-agent", tools=None):
    return AgentDef(name=name, system_prompt="You are a test agent.", tools=tools or [])


def _make_provider(text="agent output"):
    def fake_stream(system, messages, tools, config):
        yield TextChunk(content=text)
        yield AssistantMessage(content=text, tool_calls=[])
    return fake_stream


def test_agent_result_reinjected_into_parent_messages(capsys):
    ctx = _ctx()
    agents = [_agent()]
    registry = ToolRegistry()
    hooks = HookRegistry()
    cmd_agent("test-agent do something", ctx, agents, registry, hooks, _make_provider("found a bug"))

    # Result should be printed to stdout
    out = capsys.readouterr().out
    assert "found a bug" in out

    # Result should be re-injected into parent ctx.messages
    assert len(ctx.messages) == 1
    msg = ctx.messages[0]
    assert msg.role == "user"
    assert "[Agent result from test-agent]:" in msg.content
    assert "found a bug" in msg.content


def test_agent_unknown_name_no_injection(capsys):
    ctx = _ctx()
    cmd_agent("nonexistent query", ctx, [], ToolRegistry(), HookRegistry(), _make_provider())
    assert ctx.messages == []
    assert "Unknown agent" in capsys.readouterr().out


def test_agent_no_args_no_injection(capsys):
    ctx = _ctx()
    cmd_agent("", ctx, [], ToolRegistry(), HookRegistry(), _make_provider())
    assert ctx.messages == []
    assert "Usage" in capsys.readouterr().out


def test_agent_max_depth_no_injection(capsys):
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass", max_depth=1)
    ctx = RunContext(config=cfg, messages=[], system_prompt="test", depth=1)
    agents = [_agent()]
    cmd_agent("test-agent query", ctx, agents, ToolRegistry(), HookRegistry(), _make_provider())
    assert ctx.messages == []
    assert "max agent depth" in capsys.readouterr().out
