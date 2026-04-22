import dataclasses
from newcli.types import (
    Config, RunContext, Message, ToolCallRecord, ToolDef,
    TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent,
    TurnDoneEvent, AssistantMessage, TrustLevel,
)

def test_config_frozen():
    cfg = Config(base_url="http://localhost:11434/v1", model="qwen3")
    try:
        cfg.model = "other"
        assert False, "should have raised"
    except dataclasses.FrozenInstanceError:
        pass

def test_config_defaults():
    cfg = Config(base_url="http://x", model="m")
    assert cfg.api_key == "local"
    assert cfg.context_limit == 8192
    assert cfg.permission_mode == "allow"   # was "auto"
    assert cfg.mode == "ask"
    assert cfg.max_depth == 4
    assert cfg.max_retries == 2
    assert cfg.bash_safe_prefixes == []

def test_message_defaults():
    m = Message(role="user", content="hello")
    assert m.tool_calls == []
    assert m.tool_call_id is None
    assert m.name is None

def test_tool_call_record():
    r = ToolCallRecord(call_id="c1", name="read", args={"path": "/x"})
    assert r.call_id == "c1"

def test_run_context_defaults():
    cfg = Config(base_url="http://x", model="m")
    ctx = RunContext(config=cfg, messages=[], system_prompt="s")
    assert ctx.depth == 0
    assert ctx.turn == 0
    assert ctx.allowed_tools is None

def test_events():
    assert TextChunk(content="hi").content == "hi"
    assert ToolStartEvent(call_id="c", name="read", args={}).name == "read"
    e = ToolEndEvent(call_id="c", name="read", output="data")
    assert not e.error and e.permitted
    p = PermissionEvent(call_id="c", name="bash", args={})
    assert not p.granted
    assert TurnDoneEvent(input_tokens=10, output_tokens=5).output_tokens == 5

def test_assistant_message():
    a = AssistantMessage(content="hi", tool_calls=[])
    assert a.content == "hi"

def test_trust_level_enum():
    assert TrustLevel.SESSION == "session"
    assert TrustLevel.ALWAYS == "always"
    assert TrustLevel.READONLY == "readonly"

def test_run_context_has_trust_level():
    cfg = Config(base_url="http://x", model="m")
    ctx = RunContext(config=cfg, messages=[], system_prompt="s")
    assert ctx.trust_level == TrustLevel.SESSION

def test_config_mode_defaults_to_ask():
    cfg = Config(base_url="http://x", model="m")
    assert cfg.mode == "ask"

def test_config_permission_mode_default_is_allow():
    cfg = Config(base_url="http://x", model="m")
    assert cfg.permission_mode == "allow"
