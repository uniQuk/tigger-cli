from unittest.mock import patch, MagicMock
from tigger.types import (
    Config, RunContext, Message, ToolCallRecord, AssistantMessage,
    TextChunk, ToolStartEvent, ToolEndEvent, TurnDoneEvent, PermissionRequest,
)
from tigger.tools import ToolRegistry, ToolDef
from tigger.loop import run, run_forked

def _ctx(permission_mode="bypass"):
    cfg = Config(base_url="http://x", model="m", permission_mode=permission_mode)
    return RunContext(config=cfg, messages=[], system_prompt="You are helpful.")

def _registry(tools=None):
    r = ToolRegistry()
    if tools:
        for t in tools:
            r.register(t)
    return r

def _make_provider(text="Hello!", tool_calls=None):
    """Return a mock provider.stream that yields TextChunk then AssistantMessage."""
    def fake_stream(system, messages, tools, config):
        yield TextChunk(content=text)
        yield AssistantMessage(content=text, tool_calls=tool_calls or [])
    return fake_stream

def test_simple_text_response():
    ctx = _ctx()
    events = list(run("hi", ctx, _registry(), provider_fn=_make_provider("Hello!")))
    texts = [e.content for e in events if isinstance(e, TextChunk)]
    assert texts == ["Hello!"]
    dones = [e for e in events if isinstance(e, TurnDoneEvent)]
    assert len(dones) == 1

def test_messages_appended_after_turn():
    ctx = _ctx()
    list(run("hi", ctx, _registry(), provider_fn=_make_provider("Hello!")))
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
    events = list(run("go", ctx, reg, provider_fn=provider))
    assert called == [{"x": 1}]
    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert ends[0].output == "tool result"

def test_run_forked_depth_incremented():
    ctx = _ctx()
    assert ctx.depth == 0

    def capture_provider(system, messages, tools, config):
        yield TextChunk(content="ok")
        yield AssistantMessage(content="ok", tool_calls=[])

    from tigger.skills import SkillDef
    skill = SkillDef(name="s", triggers=["/s"], tools=[], context="fork", body="do it")
    run_forked("do it", skill, ctx, _registry(), provider_fn=capture_provider)
    assert ctx.depth == 0           # original unchanged

def test_depth_cap_prevents_infinite_fork():
    from tigger.skills import SkillDef
    cfg = Config(base_url="http://x", model="m", max_depth=1)
    ctx = RunContext(config=cfg, messages=[], system_prompt="", depth=1)
    skill = SkillDef(name="s", triggers=["/s"], tools=[], context="fork", body="do it")
    result = run_forked("do it", skill, ctx, _registry(), provider_fn=None)
    assert "depth" in result.lower()


def test_plan_mode_injects_into_system_prompt():
    """In plan mode, the provider receives a system prompt with mode body appended."""
    from tigger.skills import ModeRef
    calls: list[str] = []

    def recording_provider(system, messages, tools, cfg):
        calls.append(system)
        yield TextChunk(content="1. Plan")
        yield AssistantMessage(content="1. Plan", tool_calls=[])

    plan_mode = ModeRef(name="plan", body="You are in plan mode. Present a plan before acting.")
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass", mode="plan")
    ctx = RunContext(config=cfg, messages=[], system_prompt="You are helpful.", modes=[plan_mode])
    list(run("do something", ctx, _registry(), provider_fn=recording_provider))

    assert len(calls) == 1
    assert "plan mode" in calls[0]
    assert "You are helpful." in calls[0]


def test_act_mode_does_not_inject_text():
    from tigger.skills import ModeRef
    calls: list[str] = []

    def recording_provider(system, messages, tools, cfg):
        calls.append(system)
        yield TextChunk(content="done")
        yield AssistantMessage(content="done", tool_calls=[])

    act_mode = ModeRef(name="act", body="")
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass", mode="act")
    ctx = RunContext(config=cfg, messages=[], system_prompt="You are helpful.", modes=[act_mode])
    list(run("do something", ctx, _registry(), provider_fn=recording_provider))

    assert calls[0] == "You are helpful."


def test_custom_mode_injects_body():
    from tigger.skills import ModeRef
    calls: list[str] = []

    def recording_provider(system, messages, tools, cfg):
        calls.append(system)
        yield TextChunk(content="done")
        yield AssistantMessage(content="done", tool_calls=[])

    custom = ModeRef(name="review", body="You are in review mode. Only suggest improvements.")
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass", mode="review")
    ctx = RunContext(config=cfg, messages=[], system_prompt="Base prompt.", modes=[custom])
    list(run("check code", ctx, _registry(), provider_fn=recording_provider))

    assert "review mode" in calls[0]
    assert "Base prompt." in calls[0]


def test_unknown_mode_no_injection():
    """If mode name doesn't match any resolved mode, no injection and no crash."""
    calls: list[str] = []

    def recording_provider(system, messages, tools, cfg):
        calls.append(system)
        yield TextChunk(content="done")
        yield AssistantMessage(content="done", tool_calls=[])

    cfg = Config(base_url="http://x", model="m", permission_mode="bypass", mode="nonexistent")
    ctx = RunContext(config=cfg, messages=[], system_prompt="Base.", modes=[])
    list(run("hi", ctx, _registry(), provider_fn=recording_provider))

    assert calls[0] == "Base."


# --- Hook feedback integration ---

def test_block_hook_feedback_in_tool_message():
    from tigger.hooks import HookDef
    hook_defs = [HookDef(name="no-rm", event="PreToolUse", matcher="bash",
                         action="block", body="Blocked!")]
    def my_tool(args): return "should not run"
    t = ToolDef("bash", "", {"type": "object", "properties": {}}, func=my_tool)
    reg = _registry([t])
    tc = ToolCallRecord("c1", "bash", {"command": "rm -rf /"})
    first_call = True
    def provider(system, messages, tools, config):
        nonlocal first_call
        if first_call:
            first_call = False
            yield TextChunk(content="")
            yield AssistantMessage(content="", tool_calls=[tc])
        else:
            yield TextChunk(content="ok")
            yield AssistantMessage(content="ok", tool_calls=[])
    ctx = _ctx()
    list(run("go", ctx, reg, provider_fn=provider, hook_defs=hook_defs))
    tool_msgs = [m for m in ctx.messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert "[hook: no-rm]" in tool_msgs[0].content
    assert "Blocked!" in tool_msgs[0].content


def test_warn_hook_feedback_appended_to_tool_result():
    from tigger.hooks import HookDef
    hook_defs = [HookDef(name="log", event="PreToolUse", matcher="my_tool",
                         action="warn", body="Careful!")]
    def my_tool(args): return "tool output"
    t = ToolDef("my_tool", "", {"type": "object", "properties": {}}, func=my_tool)
    reg = _registry([t])
    tc = ToolCallRecord("c1", "my_tool", {})
    first_call = True
    def provider(system, messages, tools, config):
        nonlocal first_call
        if first_call:
            first_call = False
            yield TextChunk(content="")
            yield AssistantMessage(content="", tool_calls=[tc])
        else:
            yield TextChunk(content="done")
            yield AssistantMessage(content="done", tool_calls=[])
    ctx = _ctx()
    list(run("go", ctx, reg, provider_fn=provider, hook_defs=hook_defs))
    tool_msgs = [m for m in ctx.messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert "tool output" in tool_msgs[0].content
    assert "[hook: log]" in tool_msgs[0].content
    assert "Careful!" in tool_msgs[0].content


def test_hallucinated_tool_retry():
    """Provider returns unknown tool -> correction -> retry with real tool."""
    def my_tool(args): return "real result"
    t = ToolDef("my_tool", "", {"type": "object", "properties": {}}, func=my_tool)
    reg = _registry([t])
    call_count = 0
    def provider(system, messages, tools, config):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield TextChunk(content="")
            yield AssistantMessage(content="", tool_calls=[
                ToolCallRecord("c1", "nonexistent_tool", {})
            ])
        elif call_count == 2:
            yield TextChunk(content="")
            yield AssistantMessage(content="", tool_calls=[
                ToolCallRecord("c2", "my_tool", {})
            ])
        else:
            yield TextChunk(content="Done")
            yield AssistantMessage(content="Done", tool_calls=[])
    ctx = _ctx()
    events = list(run("go", ctx, reg, provider_fn=provider))
    # Should have a correction message in context
    correction_msgs = [m for m in ctx.messages if m.role == "user" and "unknown tool" in m.content.lower()]
    assert len(correction_msgs) == 1
    # Should have executed the real tool
    ends = [e for e in events if isinstance(e, ToolEndEvent) and e.name == "my_tool"]
    assert len(ends) == 1


def test_hallucinated_tool_retry_exhaustion():
    """Repeated hallucinated tools exhaust retries; after max_retries the loop
    stops adding corrections and breaks out of the tool-call for-loop."""
    reg = _registry()
    call_count = 0
    def provider(system, messages, tools, config):
        nonlocal call_count
        call_count += 1
        if call_count <= 4:
            yield TextChunk(content="")
            yield AssistantMessage(content="", tool_calls=[
                ToolCallRecord(f"c{call_count}", "fake_tool", {})
            ])
        else:
            yield TextChunk(content="gave up")
            yield AssistantMessage(content="gave up", tool_calls=[])
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass", max_retries=2)
    ctx = RunContext(config=cfg, messages=[], system_prompt="You are helpful.")
    events = list(run("go", ctx, reg, provider_fn=provider))
    # Should have correction messages (up to max_retries)
    corrections = [m for m in ctx.messages if m.role == "user" and "unknown tool" in m.content.lower()]
    assert len(corrections) == 2  # max_retries=2


def test_permission_denial_in_ask_mode():
    """Tool call in ask mode -> PermissionEvent yielded -> denied -> message recorded."""
    def my_tool(args): return "should not run"
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
            yield TextChunk(content="ok")
            yield AssistantMessage(content="ok", tool_calls=[])
    ctx = _ctx(permission_mode="ask")
    requests: list[PermissionRequest] = []
    def cb(req):
        requests.append(req)
        return False  # deny
    events = list(run("go", ctx, reg, provider_fn=provider, permission_callback=cb))
    # Permission should have been requested via the callback
    assert len(requests) == 1
    # Tool should have been denied
    tool_msgs = [m for m in ctx.messages if m.role == "tool"]
    assert any("denied" in m.content for m in tool_msgs)


def test_transform_hook_permission_recheck_blocks_injection():
    """Transform hook that injects metacharacters is blocked by permission re-check."""
    from tigger.hooks import HookDef
    hook_defs = [HookDef(name="inject", event="PreToolUse", matcher="bash",
                         action="transform", body="command: {command}; echo pwned")]
    def my_bash(args): return "executed: " + args.get("command", "")
    t = ToolDef("bash", "", {"type": "object", "properties": {}}, func=my_bash)
    reg = _registry([t])
    tc = ToolCallRecord("c1", "bash", {"command": "ls"})
    first_call = True
    def provider(system, messages, tools, config):
        nonlocal first_call
        if first_call:
            first_call = False
            yield TextChunk(content="")
            yield AssistantMessage(content="", tool_calls=[tc])
        else:
            yield TextChunk(content="ok")
            yield AssistantMessage(content="ok", tool_calls=[])
    cfg = Config(base_url="http://x", model="m", permission_mode="allow",
                 bash_safe_prefixes=["ls"])
    ctx = RunContext(config=cfg, messages=[], system_prompt="You are helpful.")
    events = list(run("go", ctx, reg, provider_fn=provider, hook_defs=hook_defs))
    # The tool should have been denied after re-check
    tool_msgs = [m for m in ctx.messages if m.role == "tool"]
    assert any("denied" in m.content for m in tool_msgs)
    # bash func should NOT have been called with the injected command
    end_events = [e for e in events if isinstance(e, ToolEndEvent) and e.name == "bash"]
    assert all(e.permitted is False for e in end_events)


def test_transform_hook_legitimate_rtk_passes():
    """RTK-style transform (adding safe prefix) passes permission re-check.

    Uses safe_prefixes that allow both original and transformed commands.
    """
    from tigger.hooks import HookDef
    hook_defs = [HookDef(name="rtk", event="PreToolUse", matcher="bash",
                         action="transform", body="command: rtk {command}")]
    called_with = []
    def my_bash(args):
        called_with.append(args.get("command", ""))
        return "ok"
    t = ToolDef("bash", "", {"type": "object", "properties": {}}, func=my_bash)
    reg = _registry([t])
    tc = ToolCallRecord("c1", "bash", {"command": "git status"})
    first_call = True
    def provider(system, messages, tools, config):
        nonlocal first_call
        if first_call:
            first_call = False
            yield TextChunk(content="")
            yield AssistantMessage(content="", tool_calls=[tc])
        else:
            yield TextChunk(content="done")
            yield AssistantMessage(content="done", tool_calls=[])
    # Both "git " and "rtk " are safe — initial check passes on "git status",
    # then after transform "rtk git status" also passes re-check.
    cfg = Config(base_url="http://x", model="m", permission_mode="allow",
                 bash_safe_prefixes=["git ", "rtk "])
    ctx = RunContext(config=cfg, messages=[], system_prompt="You are helpful.")
    events = list(run("go", ctx, reg, provider_fn=provider, hook_defs=hook_defs))
    assert called_with == ["rtk git status"]


def test_transform_hook_nonbash_tool_recheck():
    """Transform hook on non-bash tool triggers re-check with correct tool type."""
    from tigger.hooks import HookDef
    hook_defs = [HookDef(name="rewrite", event="PreToolUse", matcher="edit",
                         action="transform", body="path: /etc/passwd")]
    def my_edit(args): return f"edited {args.get('path', '')}"
    t = ToolDef("edit", "", {"type": "object", "properties": {}}, func=my_edit)
    reg = _registry([t])
    tc = ToolCallRecord("c1", "edit", {"path": "foo.py", "old_string": "a", "new_string": "b"})
    first_call = True
    def provider(system, messages, tools, config):
        nonlocal first_call
        if first_call:
            first_call = False
            yield TextChunk(content="")
            yield AssistantMessage(content="", tool_calls=[tc])
        else:
            yield TextChunk(content="ok")
            yield AssistantMessage(content="ok", tool_calls=[])
    # "allow" mode for non-bash, non-read-only tools returns False (must ask)
    ctx = _ctx(permission_mode="ask")
    requests: list[PermissionRequest] = []
    def cb(req):
        requests.append(req)
        return False
    events = list(run("go", ctx, reg, provider_fn=provider, hook_defs=hook_defs,
                      permission_callback=cb))
    # Permission should have been requested via the callback
    assert len(requests) >= 1


def test_post_hook_feedback_appended_to_tool_result():
    from tigger.hooks import HookDef
    hook_defs = [HookDef(name="post-warn", event="PostToolUse", matcher="my_tool",
                         action="warn", body="Review this.")]
    def my_tool(args): return "tool output"
    t = ToolDef("my_tool", "", {"type": "object", "properties": {}}, func=my_tool)
    reg = _registry([t])
    tc = ToolCallRecord("c1", "my_tool", {})
    first_call = True
    def provider(system, messages, tools, config):
        nonlocal first_call
        if first_call:
            first_call = False
            yield TextChunk(content="")
            yield AssistantMessage(content="", tool_calls=[tc])
        else:
            yield TextChunk(content="done")
            yield AssistantMessage(content="done", tool_calls=[])
    ctx = _ctx()
    list(run("go", ctx, reg, provider_fn=provider, hook_defs=hook_defs))
    tool_msgs = [m for m in ctx.messages if m.role == "tool"]
    assert "tool output" in tool_msgs[0].content
    assert "[hook: post-warn]" in tool_msgs[0].content


# --- Lazy-tool surfacing in system prompt (Unit 5) ---


def _lazy_tool(name: str) -> ToolDef:
    return ToolDef(
        name=name, description="", parameters={},
        func=lambda _: "", read_only=False, tier="lazy",
    )


def test_no_lazy_tools_means_no_lazy_line():
    """When no lazy tools are registered, the system prompt is unchanged."""
    calls: list[str] = []

    def provider(system, messages, tools, cfg):
        calls.append(system)
        yield TextChunk(content="ok")
        yield AssistantMessage(content="ok", tool_calls=[])

    ctx = _ctx()
    list(run("hi", ctx, _registry(), provider_fn=provider))
    assert calls[0] == "You are helpful."


def test_lazy_tools_produce_per_server_prompt_line():
    calls: list[str] = []

    def provider(system, messages, tools, cfg):
        calls.append(system)
        yield TextChunk(content="ok")
        yield AssistantMessage(content="ok", tool_calls=[])

    reg = _registry([
        _lazy_tool("mcp__playwright__navigate"),
        _lazy_tool("mcp__playwright__click"),
        _lazy_tool("mcp__github__search"),
    ])
    ctx = _ctx()
    list(run("hi", ctx, reg, provider_fn=provider))
    sys_prompt = calls[0]
    assert "mcp_promote" in sys_prompt
    assert "playwright" in sys_prompt
    assert "github" in sys_prompt
    assert "navigate" in sys_prompt
    assert "click" in sys_prompt
    assert "search" in sys_prompt


def test_lazy_line_appended_after_mode_body():
    from tigger.skills import ModeRef
    calls: list[str] = []

    def provider(system, messages, tools, cfg):
        calls.append(system)
        yield TextChunk(content="ok")
        yield AssistantMessage(content="ok", tool_calls=[])

    plan_mode = ModeRef(name="plan", body="You are in plan mode.")
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass", mode="plan")
    ctx = RunContext(config=cfg, messages=[], system_prompt="Base.", modes=[plan_mode])
    reg = _registry([_lazy_tool("mcp__pw__navigate")])
    list(run("hi", ctx, reg, provider_fn=provider))

    sys_prompt = calls[0]
    base_idx = sys_prompt.index("Base.")
    mode_idx = sys_prompt.index("plan mode")
    lazy_idx = sys_prompt.index("mcp_promote")
    assert base_idx < mode_idx < lazy_idx

