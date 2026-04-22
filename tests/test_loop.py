from unittest.mock import patch, MagicMock
from newcli.types import (
    Config, RunContext, Message, ToolCallRecord, AssistantMessage,
    TextChunk, ToolStartEvent, ToolEndEvent, TurnDoneEvent,
)
from newcli.tools import ToolRegistry, ToolDef
from newcli.hooks import HookRegistry
from newcli.loop import run, run_forked

def _ctx(permission_mode="bypass"):
    cfg = Config(base_url="http://x", model="m", permission_mode=permission_mode)
    return RunContext(config=cfg, messages=[], system_prompt="You are helpful.")

def _registry(tools=None):
    r = ToolRegistry()
    if tools:
        for t in tools:
            r.register(t)
    return r

def _hooks():
    return HookRegistry()

def _make_provider(text="Hello!", tool_calls=None):
    """Return a mock provider.stream that yields TextChunk then AssistantMessage."""
    def fake_stream(system, messages, tools, config):
        yield TextChunk(content=text)
        yield AssistantMessage(content=text, tool_calls=tool_calls or [])
    return fake_stream

def test_simple_text_response():
    ctx = _ctx()
    events = list(run("hi", ctx, _registry(), _hooks(), provider_fn=_make_provider("Hello!")))
    texts = [e.content for e in events if isinstance(e, TextChunk)]
    assert texts == ["Hello!"]
    dones = [e for e in events if isinstance(e, TurnDoneEvent)]
    assert len(dones) == 1

def test_messages_appended_after_turn():
    ctx = _ctx()
    list(run("hi", ctx, _registry(), _hooks(), provider_fn=_make_provider("Hello!")))
    assert len(ctx.messages) == 2   # user + assistant
    assert ctx.messages[0].role == "user"
    assert ctx.messages[1].role == "assistant"

def test_tool_call_executed():
    called = []
    def my_tool(args): called.append(args); return "tool result"
    t = ToolDef("my_tool", "", {"type": "object", "properties": {}}, func=my_tool)
    reg = _registry([t])

    tc = ToolCallRecord("c1", "my_tool", {"x": 1})
    first_call = True
    def provider(system, messages, tools, config):
        nonlocal first_call
        if first_call:
            first_call = False
            yield TextChunk(content="")
            yield AssistantMessage(content="", tool_calls=[tc])
        else:
            yield TextChunk(content="Done")
            yield AssistantMessage(content="Done", tool_calls=[])

    ctx = _ctx()
    events = list(run("go", ctx, reg, _hooks(), provider_fn=provider))
    assert called == [{"x": 1}]
    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert ends[0].output == "tool result"

def test_run_forked_depth_incremented():
    ctx = _ctx()
    assert ctx.depth == 0

    def capture_provider(system, messages, tools, config):
        yield TextChunk(content="ok")
        yield AssistantMessage(content="ok", tool_calls=[])

    from newcli.skills import SkillDef
    skill = SkillDef(name="s", triggers=["/s"], tools=[], context="fork", body="do it")
    run_forked("do it", skill, ctx, _registry(), _hooks(), provider_fn=capture_provider)
    assert ctx.depth == 0           # original unchanged

def test_depth_cap_prevents_infinite_fork():
    from newcli.skills import SkillDef
    cfg = Config(base_url="http://x", model="m", max_depth=1)
    ctx = RunContext(config=cfg, messages=[], system_prompt="", depth=1)
    skill = SkillDef(name="s", triggers=["/s"], tools=[], context="fork", body="do it")
    result = run_forked("do it", skill, ctx, _registry(), _hooks(), provider_fn=None)
    assert "depth" in result.lower()
