import dataclasses
from tigger.types import (
    Config, RunContext, Message, ToolCallRecord, ToolDef,
    TextChunk, ToolStartEvent, ToolEndEvent, PermissionRequest,
    TurnDoneEvent, AssistantMessage, TrustLevel, ProviderConfig,
    ModelConfig,
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
    assert cfg.context_limit == 128000
    assert cfg.permission_mode == "allow"   # was "auto"
    assert cfg.mode == "act"
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
    p = PermissionRequest(call_id="c", name="bash", args={})
    assert p.name == "bash"
    assert TurnDoneEvent(input_tokens=10, output_tokens=5).output_tokens == 5

def test_assistant_message():
    a = AssistantMessage(content="hi", tool_calls=[])
    assert a.content == "hi"

def test_trust_level_enum():
    assert TrustLevel.ALWAYS == "always"
    assert TrustLevel.READONLY == "readonly"

def test_run_context_has_trust_level():
    cfg = Config(base_url="http://x", model="m")
    ctx = RunContext(config=cfg, messages=[], system_prompt="s")
    assert ctx.trust_level == TrustLevel.READONLY

def test_config_mode_defaults_to_act():
    cfg = Config(base_url="http://x", model="m")
    assert cfg.mode == "act"

def test_config_permission_mode_default_is_allow():
    cfg = Config(base_url="http://x", model="m")
    assert cfg.permission_mode == "allow"


def test_provider_config_fields():
    pc = ProviderConfig(name="local", base_url="http://localhost:1234/v1",
                        api_key="local", models=["qwen3"])
    assert pc.name == "local"
    assert pc.base_url == "http://localhost:1234/v1"
    assert pc.api_key == "local"
    assert pc.models == ["qwen3"]


def test_provider_config_is_frozen():
    pc = ProviderConfig(name="x", base_url="http://x", api_key="k", models=["m"])
    import pytest
    with pytest.raises(AttributeError):
        pc.name = "y"


def test_config_has_providers_field():
    pc = ProviderConfig(name="loc", base_url="http://x/v1", api_key="local", models=["m"])
    cfg = Config(base_url="http://x/v1", model="m", providers={"loc": pc},
                 active_provider="loc")
    assert cfg.providers["loc"].base_url == "http://x/v1"
    assert cfg.active_provider == "loc"
    assert cfg.model == "m"


def test_config_providers_default_empty():
    cfg = Config(base_url="http://x", model="m")
    assert cfg.providers == {}
    assert cfg.active_provider == ""
    assert cfg.model == "m"


# --- ModelConfig tests ---

def test_model_config_defaults():
    mc = ModelConfig()
    assert mc.temperature is None
    assert mc.max_tokens is None
    assert mc.context_limit is None
    assert mc.top_p is None
    assert mc.thinking is None


def test_model_config_with_values():
    mc = ModelConfig(temperature=0.3, max_tokens=4096, context_limit=32000,
                     top_p=0.9, thinking=True)
    assert mc.temperature == 0.3
    assert mc.max_tokens == 4096
    assert mc.context_limit == 32000
    assert mc.top_p == 0.9
    assert mc.thinking is True


def test_provider_config_model_names_list():
    pc = ProviderConfig(name="x", base_url="http://x", api_key="k",
                        models=["m1", "m2"])
    assert pc.model_names == ["m1", "m2"]


def test_provider_config_model_names_dict():
    pc = ProviderConfig(name="x", base_url="http://x", api_key="k",
                        models={"m1": ModelConfig(), "m2": ModelConfig(temperature=0.5)})
    assert pc.model_names == ["m1", "m2"]
