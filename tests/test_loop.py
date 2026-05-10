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

def test_parallel_tool_dispatch_preserves_order():
    """Multiple read-only tool calls in a single turn should run via the
    parallel fast-path AND surface ordered ToolEndEvents + ordered tool
    messages, since the wire format pairs each result with its tool_call_id.
    """
    import threading
    import time as _time

    barrier = threading.Barrier(3)
    started_at: list[float] = []

    def slow_read(args):
        started_at.append(_time.monotonic())
        # Synchronise threads so we can prove they ran concurrently.
        barrier.wait(timeout=2.0)
        return f"out:{args['n']}"

    t = ToolDef(
        "slow_read", "", {"type": "object", "properties": {"n": {"type": "integer"}}},
        func=slow_read, read_only=True,
    )
    reg = _registry([t])
    tcs = [
        ToolCallRecord("c1", "slow_read", {"n": 1}),
        ToolCallRecord("c2", "slow_read", {"n": 2}),
        ToolCallRecord("c3", "slow_read", {"n": 3}),
    ]
    first = True
    def provider(system, messages, tools, config):
        nonlocal first
        if first:
            first = False
            yield AssistantMessage(content="", tool_calls=tcs)
        else:
            yield AssistantMessage(content="done", tool_calls=[])

    ctx = _ctx()  # bypass mode → permitted without callback
    events = list(run("go", ctx, reg, provider_fn=provider))

    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    # Ordering preserved on the wire even though execution overlapped.
    assert [e.call_id for e in ends] == ["c1", "c2", "c3"]
    assert [e.output for e in ends] == ["out:1", "out:2", "out:3"]
    # And in ctx.messages — each tool result follows the assistant turn in
    # tool_calls index order.
    tool_msgs = [m for m in ctx.messages if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["c1", "c2", "c3"]
    # Concurrency proof — without parallel dispatch the barrier would deadlock.
    assert len(started_at) == 3


def test_serial_path_when_any_tool_is_not_read_only():
    """A turn that mixes read-only and side-effect tools must NOT use the
    parallel fast-path — falls through to the existing sequential dispatcher
    so PreToolUse hooks, permission re-checks, and write ordering all work
    unchanged.
    """
    order: list[str] = []
    def reader(args): order.append(f"r{args['n']}"); return "r"
    def writer(args): order.append(f"w{args['n']}"); return "w"
    reg = _registry([
        ToolDef("reader", "", {"type": "object", "properties": {"n": {"type": "integer"}}},
                func=reader, read_only=True),
        ToolDef("writer", "", {"type": "object", "properties": {"n": {"type": "integer"}}},
                func=writer, read_only=False),
    ])
    tcs = [
        ToolCallRecord("c1", "reader", {"n": 1}),
        ToolCallRecord("c2", "writer", {"n": 2}),
        ToolCallRecord("c3", "reader", {"n": 3}),
    ]
    first = True
    def provider(system, messages, tools, config):
        nonlocal first
        if first:
            first = False
            yield AssistantMessage(content="", tool_calls=tcs)
        else:
            yield AssistantMessage(content="done", tool_calls=[])
    ctx = _ctx()
    list(run("go", ctx, reg, provider_fn=provider))
    # Sequential execution → strict in-order
    assert order == ["r1", "w2", "r3"]


def test_run_forked_depth_incremented():
    ctx = _ctx()
    assert ctx.depth == 0

    def capture_provider(system, messages, tools, config):
        yield TextChunk(content="ok")
        yield AssistantMessage(content="ok", tool_calls=[])

    from tigger.skills import SkillDef
    skill = SkillDef(name="s", triggers=["/s"], tools=[], context="fork", body="do it")
    list(run_forked("do it", skill, ctx, _registry(), provider_fn=capture_provider))
    assert ctx.depth == 0           # original unchanged

def test_depth_cap_prevents_infinite_fork():
    from tigger.skills import SkillDef
    cfg = Config(base_url="http://x", model="m", max_depth=1)
    ctx = RunContext(config=cfg, messages=[], system_prompt="", depth=1)
    skill = SkillDef(name="s", triggers=["/s"], tools=[], context="fork", body="do it")
    events = list(run_forked("do it", skill, ctx, _registry(), provider_fn=None))
    text = "".join(e.content for e in events if isinstance(e, TextChunk))
    assert "depth" in text.lower()


def test_plan_mode_injects_via_environment_kwarg():
    """Plan-mode body rides as the environment kwarg; system stays stable."""
    from tigger.skills import ModeRef
    systems: list[str] = []
    envs: list[str | None] = []

    def recording_provider(system, messages, tools, cfg, environment=None):
        systems.append(system)
        envs.append(environment)
        yield TextChunk(content="1. Plan")
        yield AssistantMessage(content="1. Plan", tool_calls=[])

    plan_mode = ModeRef(name="plan", body="You are in plan mode. Present a plan before acting.")
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass", mode="plan")
    ctx = RunContext(config=cfg, messages=[], system_prompt="You are helpful.", modes=[plan_mode])
    list(run("do something", ctx, _registry(), provider_fn=recording_provider))

    assert systems == ["You are helpful."]
    assert envs[0] is not None and "plan mode" in envs[0]


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
    """Mode body is delivered via the environment kwarg, not the system prompt.

    Keeping the system prompt bytewise stable across turns is what enables
    KV-cache reuse on the provider side.
    """
    from tigger.skills import ModeRef
    systems: list[str] = []
    envs: list[str | None] = []

    def recording_provider(system, messages, tools, cfg, environment=None):
        systems.append(system)
        envs.append(environment)
        yield TextChunk(content="done")
        yield AssistantMessage(content="done", tool_calls=[])

    custom = ModeRef(name="review", body="You are in review mode. Only suggest improvements.")
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass", mode="review")
    ctx = RunContext(config=cfg, messages=[], system_prompt="Base prompt.", modes=[custom])
    list(run("check code", ctx, _registry(), provider_fn=recording_provider))

    assert systems[0] == "Base prompt."
    assert envs[0] is not None and "review mode" in envs[0]


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
    """Lazy MCP tools are listed via the environment kwarg, not in system."""
    systems: list[str] = []
    envs: list[str | None] = []

    def provider(system, messages, tools, cfg, environment=None):
        systems.append(system)
        envs.append(environment)
        yield TextChunk(content="ok")
        yield AssistantMessage(content="ok", tool_calls=[])

    reg = _registry([
        _lazy_tool("mcp__playwright__navigate"),
        _lazy_tool("mcp__playwright__click"),
        _lazy_tool("mcp__github__search"),
    ])
    ctx = _ctx()
    list(run("hi", ctx, reg, provider_fn=provider))
    assert systems[0] == "You are helpful."
    env = envs[0]
    assert env is not None
    for needle in ("mcp_promote", "playwright", "github", "navigate", "click", "search"):
        assert needle in env


def test_lazy_line_and_mode_body_combine_in_environment():
    from tigger.skills import ModeRef
    systems: list[str] = []
    envs: list[str | None] = []

    def provider(system, messages, tools, cfg, environment=None):
        systems.append(system)
        envs.append(environment)
        yield TextChunk(content="ok")
        yield AssistantMessage(content="ok", tool_calls=[])

    plan_mode = ModeRef(name="plan", body="You are in plan mode.")
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass", mode="plan")
    ctx = RunContext(config=cfg, messages=[], system_prompt="Base.", modes=[plan_mode])
    reg = _registry([_lazy_tool("mcp__pw__navigate")])
    list(run("hi", ctx, reg, provider_fn=provider))

    assert systems[0] == "Base."
    env = envs[0]
    assert env is not None
    mode_idx = env.index("plan mode")
    lazy_idx = env.index("mcp_promote")
    assert mode_idx < lazy_idx



def test_stop_after_write_breaks_after_successful_write():
    """ctx.stop_after_write=True → loop exits as soon as a write tool call
    succeeds, before the model gets another turn to second-guess itself.
    """
    write_tc = ToolCallRecord("c1", "write", {"path": "/tmp/x", "content": "hello"})
    turns_seen = 0
    def provider(system, messages, tools, config):
        nonlocal turns_seen
        turns_seen += 1
        if turns_seen == 1:
            yield AssistantMessage(content="writing", tool_calls=[write_tc])
        else:
            # Should never be reached when stop_after_write trips.
            yield AssistantMessage(content="should not be called", tool_calls=[])

    captured: list[dict] = []
    def fake_write(args):
        captured.append(args)
        return f"Written: {args['path']}"
    reg = _registry([
        ToolDef("write", "", {"type": "object", "properties": {}}, func=fake_write),
    ])

    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(
        config=cfg, messages=[], system_prompt="x", stop_after_write=True,
    )
    list(run("go", ctx, reg, provider_fn=provider))

    # Provider was only called once — the second turn never happened.
    assert turns_seen == 1
    # The write tool actually ran and its result is on the message tape.
    assert captured == [{"path": "/tmp/x", "content": "hello"}]
    tool_msgs = [m for m in ctx.messages if m.role == "tool"]
    assert tool_msgs and tool_msgs[-1].content.startswith("Written:")


def test_stop_after_write_does_not_trigger_on_failed_write():
    """Failed writes (e.g. file-already-exists) must NOT trip stop_after_write,
    otherwise the model can't recover from a transient error.
    """
    write_tc = ToolCallRecord("c1", "write", {"path": "/tmp/x"})
    turns_seen = 0
    def provider(system, messages, tools, config):
        nonlocal turns_seen
        turns_seen += 1
        if turns_seen == 1:
            yield AssistantMessage(content="", tool_calls=[write_tc])
        else:
            yield AssistantMessage(content="recovered", tool_calls=[])
    reg = _registry([
        ToolDef("write", "", {"type": "object", "properties": {}},
                func=lambda _: "Error: file already exists"),
    ])
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(
        config=cfg, messages=[], system_prompt="x", stop_after_write=True,
    )
    list(run("go", ctx, reg, provider_fn=provider))
    # The model got a second turn to recover from the error.
    assert turns_seen == 2


def test_chat_template_kwargs_override_passed_to_provider():
    """When ctx.chat_template_kwargs is set, the merged dict reaches the
    provider via an effective Config — overriding workspace defaults at
    the key level (skill wins) without dropping unrelated keys.
    """
    seen_configs: list[dict] = []
    def provider(system, messages, tools, config):
        seen_configs.append(dict(config.chat_template_kwargs))
        yield AssistantMessage(content="ok", tool_calls=[])

    cfg = Config(
        base_url="http://x", model="m", permission_mode="bypass",
        chat_template_kwargs={"enable_thinking": True, "preserve_thinking": True},
    )
    ctx = RunContext(
        config=cfg, messages=[], system_prompt="x",
        chat_template_kwargs={"enable_thinking": False},
    )
    list(run("go", ctx, _registry(), provider_fn=provider))

    assert seen_configs == [{
        "enable_thinking": False,        # skill override won
        "preserve_thinking": True,       # workspace key preserved
    }]


def test_chat_template_kwargs_unset_passes_workspace_config_unchanged():
    seen_configs: list[Config] = []
    def provider(system, messages, tools, config):
        seen_configs.append(config)
        yield AssistantMessage(content="ok", tool_calls=[])
    cfg = Config(
        base_url="http://x", model="m", permission_mode="bypass",
        chat_template_kwargs={"enable_thinking": True},
    )
    ctx = RunContext(config=cfg, messages=[], system_prompt="x")
    list(run("go", ctx, _registry(), provider_fn=provider))
    # Identity check — no replace() happened, the same frozen Config was forwarded.
    assert seen_configs[0] is cfg


def test_tool_cutoff_recovery_capped_at_one(capsys):
    """Two consecutive tool-cutoffs must not loop forever — the loop bails
    after the single allowed recovery and logs a clear stderr message.
    """
    truncated_tc = ToolCallRecord("c1", "write", {}, parse_error_bytes=0)
    turns_seen = 0
    def provider(system, messages, tools, config):
        nonlocal turns_seen
        turns_seen += 1
        # Always return a truncated tool call so the loop is forced to
        # re-enter the recovery branch on every turn.
        yield AssistantMessage(content="", tool_calls=[truncated_tc])
    reg = _registry([
        ToolDef("write", "", {"type": "object", "properties": {}},
                func=lambda _: "ok"),
    ])
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(config=cfg, messages=[], system_prompt="x")
    list(run("go", ctx, reg, provider_fn=provider))

    # 1 original turn + 1 recovery turn = 2 provider calls, then we abort.
    assert turns_seen == 2
    err = capsys.readouterr().err
    assert "tool call truncated mid-stream" in err
    assert "tool call truncated again after recovery" in err


def test_stop_after_write_does_not_stop_on_truncation_recovery_stub():
    """After a cut-off write, the retry may intentionally create a stub.
    stop_after_write must not terminate there; the model needs another turn
    to continue with edits or final recovery.
    """
    truncated_tc = ToolCallRecord("c1", "write", {}, parse_error_bytes=0)
    stub_tc = ToolCallRecord(
        "c2", "write", {"path": "/tmp/architecture.html", "content": "<html>"}
    )
    turns_seen = 0

    def provider(system, messages, tools, config):
        nonlocal turns_seen
        turns_seen += 1
        if turns_seen == 1:
            yield AssistantMessage(content="", tool_calls=[truncated_tc])
        elif turns_seen == 2:
            yield AssistantMessage(content="", tool_calls=[stub_tc])
        else:
            yield AssistantMessage(content="done", tool_calls=[])

    writes: list[dict] = []

    def fake_write(args):
        writes.append(args)
        return f"Written: {args['path']}"

    reg = _registry([
        ToolDef("write", "", {"type": "object", "properties": {}}, func=fake_write),
    ])
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(
        config=cfg, messages=[], system_prompt="x", stop_after_write=True,
    )

    list(run("go", ctx, reg, provider_fn=provider))

    assert writes == [{"path": "/tmp/architecture.html", "content": "<html>"}]
    assert turns_seen == 3


def test_stall_watchdog_fires_when_stream_silent(monkeypatch, capsys):
    """When a chunk doesn't arrive within the watchdog window, a heartbeat
    line lands on stderr. We use a 1-second window via the env var so the
    test stays fast.
    """
    import time as _time
    monkeypatch.setenv("TIGGER_STALL_SECS", "0")  # disabled by default
    # Re-import to refresh the module-level constant.
    import importlib
    import tigger.loop as _loop
    importlib.reload(_loop)
    monkeypatch.setattr(_loop, "_STALL_HEARTBEAT_SECS", 1)

    def slow_provider(system, messages, tools, config):
        # First yield is delayed — watchdog should fire at least once.
        _time.sleep(1.5)
        yield AssistantMessage(content="ok", tool_calls=[])
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(config=cfg, messages=[], system_prompt="x")
    list(_loop.run("go", ctx, _loop.ToolRegistry(), provider_fn=slow_provider))
    err = capsys.readouterr().err
    assert "still thinking" in err


def test_compaction_summarization_emits_stderr_notice(monkeypatch, capsys):
    """When maybe_compact summarises messages, loop should print a notice on stderr."""
    from tigger import loop as loop_mod
    from tigger.compaction import CompactResult
    from tigger.types import (
        AssistantMessage,
        Config,
        Message,
        RunContext,
        TrustLevel,
    )

    fake_result = CompactResult(
        snipped=0, summarized=4, tokens_before=108_000, tokens_after=24_000,
    )

    def fake_compact(messages, config, provider_fn, *, summaries_dir=None, **kwargs):
        return messages, fake_result

    monkeypatch.setattr(loop_mod, "maybe_compact", fake_compact)

    def fake_provider(system, messages, tools, config):
        yield AssistantMessage(content="ok", tool_calls=[])

    cfg = Config(base_url="http://x", model="m", api_key="k")
    ctx = RunContext(config=cfg, messages=[Message(role="user", content="hi")],
                     system_prompt="", trust_level=TrustLevel.ALWAYS)
    list(loop_mod.run("go", ctx, loop_mod.ToolRegistry(), provider_fn=fake_provider))

    err = capsys.readouterr().err
    assert "compacted 4 messages" in err
    assert "108,000" in err
    assert "24,000" in err


def test_compaction_no_op_emits_no_notice(monkeypatch, capsys):
    """When maybe_compact does nothing, the loop should stay quiet on stderr."""
    from tigger import loop as loop_mod
    from tigger.compaction import CompactResult
    from tigger.types import (
        AssistantMessage,
        Config,
        Message,
        RunContext,
        TrustLevel,
    )

    fake_result = CompactResult(
        snipped=0, summarized=0, tokens_before=10_000, tokens_after=10_000,
    )

    def fake_compact(messages, config, provider_fn, *, summaries_dir=None, **kwargs):
        return messages, fake_result

    monkeypatch.setattr(loop_mod, "maybe_compact", fake_compact)

    def fake_provider(system, messages, tools, config):
        yield AssistantMessage(content="ok", tool_calls=[])

    cfg = Config(base_url="http://x", model="m", api_key="k")
    ctx = RunContext(config=cfg, messages=[Message(role="user", content="hi")],
                     system_prompt="", trust_level=TrustLevel.ALWAYS)
    list(loop_mod.run("go", ctx, loop_mod.ToolRegistry(), provider_fn=fake_provider))

    err = capsys.readouterr().err
    assert "compacted" not in err


def test_empty_response_retry_emits_stderr_notice(monkeypatch, capsys):
    """When the provider yields no AssistantMessage, the loop should announce the retry."""
    from tigger.types import (
        AssistantMessage,
        Config,
        Message,
        RunContext,
        TrustLevel,
    )
    from tigger.loop import run as _run
    from tigger.tools import ToolRegistry

    call = [0]

    def flaky_provider(system, messages, tools, config):
        call[0] += 1
        if call[0] == 1:
            # Yield nothing — simulates empty response.
            return
            yield
        yield AssistantMessage(content="now I'm here", tool_calls=[])

    cfg = Config(base_url="http://x", model="m", api_key="k", max_retries=2)
    ctx = RunContext(config=cfg, messages=[Message(role="user", content="hi")],
                     system_prompt="", trust_level=TrustLevel.ALWAYS)
    list(_run("go", ctx, ToolRegistry(), provider_fn=flaky_provider))

    err = capsys.readouterr().err
    assert "empty response" in err
    assert "retrying" in err


def test_empty_response_giveup_emits_stderr_notice(monkeypatch, capsys):
    """When retries exhaust, the loop should announce the give-up."""
    from tigger.types import (
        Config,
        Message,
        RunContext,
        TrustLevel,
    )
    from tigger.loop import run as _run
    from tigger.tools import ToolRegistry

    def empty_provider(system, messages, tools, config):
        return
        yield  # makes it a generator

    cfg = Config(base_url="http://x", model="m", api_key="k", max_retries=1)
    ctx = RunContext(config=cfg, messages=[Message(role="user", content="hi")],
                     system_prompt="", trust_level=TrustLevel.ALWAYS)
    list(_run("go", ctx, ToolRegistry(), provider_fn=empty_provider))

    err = capsys.readouterr().err
    assert "giving up" in err
