"""Dispatcher-gate tests for output budget enforcement (Unit 2)."""
from __future__ import annotations


from tigger.loop import _check_output_budget, run, run_forked
from tigger.skills import SkillDef
from tigger.tools import ToolDef, ToolRegistry
from tigger.types import (
    AssistantMessage,
    Config,
    RunContext,
    TextChunk,
    ToolCallRecord,
    ToolEndEvent,
    ToolStartEvent,
)


def _ctx(*, output_budget=None, output_budget_default=0, max_tokens=0) -> RunContext:
    cfg = Config(
        base_url="http://x",
        model="m",
        permission_mode="bypass",
        output_budget_default=output_budget_default,
        max_tokens=max_tokens,
    )
    return RunContext(
        config=cfg, messages=[], system_prompt="sys", output_budget=output_budget,
    )


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(ToolDef(
        name="write",
        description="",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        func=lambda args: f"wrote {args['path']}",
    ))
    reg.register(ToolDef(
        name="edit",
        description="",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        func=lambda args: f"edited {args['path']}",
    ))
    reg.register(ToolDef(
        name="read",
        description="",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        func=lambda args: "file content",
    ))
    return reg


def _provider_with_calls(calls_per_turn: list[list[ToolCallRecord]]):
    """Yield specified tool calls each turn, then stop."""
    state = {"turn": 0}

    def fake(system, messages, tools, config, environment=None):
        i = state["turn"]
        state["turn"] += 1
        yield TextChunk(content="")
        if i < len(calls_per_turn):
            yield AssistantMessage(content="", tool_calls=calls_per_turn[i])
        else:
            yield AssistantMessage(content="done", tool_calls=[])

    return fake


# ── _check_output_budget pure function ────────────────────────────────────

def test_check_disabled_when_budget_zero():
    tc = ToolCallRecord("c1", "write", {"path": "/a", "content": "x" * 10000})
    assert _check_output_budget(tc, 0) is None


def test_check_passes_small_write():
    tc = ToolCallRecord("c1", "write", {"path": "/a", "content": "small"})
    assert _check_output_budget(tc, 2048) is None


def test_check_rejects_large_write():
    tc = ToolCallRecord("c1", "write", {"path": "/a.html", "content": "x" * 5000})
    err = _check_output_budget(tc, 2048)
    assert err is not None
    assert "5000" in err
    assert "2048" in err
    assert "/a.html" in err
    assert "stub" in err.lower()


def test_check_rejects_large_edit_new_string():
    tc = ToolCallRecord("c1", "edit", {
        "path": "/a", "old_string": "x", "new_string": "y" * 5000,
    })
    err = _check_output_budget(tc, 2048)
    assert err is not None
    assert "5000" in err
    assert "new_string" in err


def test_check_rejects_large_edit_old_string():
    tc = ToolCallRecord("c1", "edit", {
        "path": "/a", "old_string": "y" * 5000, "new_string": "z",
    })
    err = _check_output_budget(tc, 2048)
    assert err is not None
    assert "old_string" in err


def test_check_ignores_read():
    tc = ToolCallRecord("c1", "read", {"path": "/a" * 5000})
    assert _check_output_budget(tc, 2048) is None


# ── Dispatcher gate via run() ─────────────────────────────────────────────

def test_gate_dispatches_normally_when_under_budget():
    tc = ToolCallRecord("c1", "write", {"path": "/a", "content": "small"})
    ctx = _ctx(output_budget=2048)
    events = list(run("go", ctx, _registry(),
                       provider_fn=_provider_with_calls([[tc]])))
    starts = [e for e in events if isinstance(e, ToolStartEvent)]
    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert len(starts) == 1
    assert len(ends) == 1
    assert ends[0].error is False


def test_gate_rejects_oversized_write_no_filesystem_touch(tmp_path):
    target = tmp_path / "huge.html"
    big = "x" * 5000
    tc = ToolCallRecord("c1", "write", {"path": str(target), "content": big})
    ctx = _ctx(output_budget=2048)
    events = list(run("go", ctx, _registry(),
                       provider_fn=_provider_with_calls([[tc]])))
    # No ToolStartEvent — gate fires before dispatch.
    assert not any(isinstance(e, ToolStartEvent) for e in events)
    # ToolEndEvent with error=True.
    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert len(ends) == 1
    assert ends[0].error is True
    assert "5000" in ends[0].output
    assert "2048" in ends[0].output
    # Filesystem untouched.
    assert not target.exists()


def test_gate_caps_large_budget_to_tool_arg_ceiling(tmp_path):
    target = tmp_path / "too-large-for-model.html"
    content = "x" * 5000
    tc = ToolCallRecord("c1", "write", {"path": str(target), "content": content})
    ctx = _ctx(output_budget=32768, max_tokens=8192)
    events = list(run("go", ctx, _registry(),
                      provider_fn=_provider_with_calls([[tc]])))

    assert not any(isinstance(e, ToolStartEvent) for e in events)
    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert len(ends) == 1
    assert ends[0].error is True
    assert "5000 > 4096" in ends[0].output
    assert not target.exists()


def test_tool_arg_ceiling_caps_schema_when_max_tokens_unbounded():
    """The 4096-char hard ceiling applies to write/edit schemas even when the
    user-configured budget is huge and max_tokens is unbounded — matching the
    ceiling enforced when max_tokens is set."""
    seen_tools: list[list[dict]] = []

    def provider(system, messages, tools, config, environment=None):
        seen_tools.append(tools)
        yield AssistantMessage(content="done", tool_calls=[])

    ctx = _ctx(output_budget=32768, max_tokens=0)
    list(run("go", ctx, _registry(), provider_fn=provider))

    by_name = {s["function"]["name"]: s for s in seen_tools[0]}
    write_content = (
        by_name["write"]["function"]["parameters"]["properties"]["content"]
    )
    assert write_content["maxLength"] == 4096


def test_active_output_budget_is_applied_to_tool_schemas():
    seen_tools: list[list[dict]] = []

    def provider(system, messages, tools, config, environment=None):
        seen_tools.append(tools)
        yield AssistantMessage(content="done", tool_calls=[])

    ctx = _ctx(output_budget=32768, max_tokens=8192)
    list(run("go", ctx, _registry(), provider_fn=provider))

    by_name = {s["function"]["name"]: s for s in seen_tools[0]}
    write_content = (
        by_name["write"]["function"]["parameters"]["properties"]["content"]
    )
    edit_props = by_name["edit"]["function"]["parameters"]["properties"]
    assert write_content["maxLength"] == 4096
    assert edit_props["old_string"]["maxLength"] == 4096
    assert edit_props["new_string"]["maxLength"] == 4096


def test_gate_rejects_oversized_edit():
    tc = ToolCallRecord("c1", "edit", {
        "path": "/a", "old_string": "x", "new_string": "y" * 5000,
    })
    ctx = _ctx(output_budget=2048)
    events = list(run("go", ctx, _registry(),
                       provider_fn=_provider_with_calls([[tc]])))
    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert len(ends) == 1
    assert ends[0].error is True
    assert "new_string" in ends[0].output


def test_gate_only_applies_to_write_edit():
    tc = ToolCallRecord("c1", "read", {"path": "/anything"})
    ctx = _ctx(output_budget=10)  # absurdly small budget
    events = list(run("go", ctx, _registry(),
                       provider_fn=_provider_with_calls([[tc]])))
    # Read dispatches fine despite tiny budget.
    starts = [e for e in events if isinstance(e, ToolStartEvent)]
    assert len(starts) == 1


def test_gate_disabled_when_budget_zero():
    tc = ToolCallRecord("c1", "write", {"path": "/a", "content": "x" * 10000})
    ctx = _ctx(output_budget=0)  # explicit disable
    events = list(run("go", ctx, _registry(),
                       provider_fn=_provider_with_calls([[tc]])))
    starts = [e for e in events if isinstance(e, ToolStartEvent)]
    assert len(starts) == 1  # dispatched


def test_gate_falls_back_to_config_default():
    """ctx.output_budget=None means use config.output_budget_default."""
    tc = ToolCallRecord("c1", "write", {"path": "/a", "content": "x" * 5000})
    ctx = _ctx(output_budget=None, output_budget_default=2048)
    events = list(run("go", ctx, _registry(),
                       provider_fn=_provider_with_calls([[tc]])))
    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert ends[0].error is True


def test_gate_no_skill_no_default_no_enforcement():
    tc = ToolCallRecord("c1", "write", {"path": "/a", "content": "x" * 5000})
    ctx = _ctx(output_budget=None, output_budget_default=0)
    events = list(run("go", ctx, _registry(),
                       provider_fn=_provider_with_calls([[tc]])))
    starts = [e for e in events if isinstance(e, ToolStartEvent)]
    assert len(starts) == 1


def test_gate_two_busts_in_same_turn_independent():
    tc1 = ToolCallRecord("c1", "edit", {
        "path": "/a", "old_string": "x", "new_string": "y" * 5000,
    })
    tc2 = ToolCallRecord("c2", "edit", {
        "path": "/b", "old_string": "x", "new_string": "z" * 5000,
    })
    ctx = _ctx(output_budget=2048)
    events = list(run("go", ctx, _registry(),
                       provider_fn=_provider_with_calls([[tc1, tc2]])))
    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert len(ends) == 2
    assert all(e.error for e in ends)


def test_gate_bust_then_success_in_same_turn():
    """Per-call independence: a bust does not prevent later calls in the same turn."""
    tc1 = ToolCallRecord("c1", "edit", {
        "path": "/a", "old_string": "x", "new_string": "y" * 5000,
    })
    tc2 = ToolCallRecord("c2", "edit", {
        "path": "/a", "old_string": "x", "new_string": "small",
    })
    ctx = _ctx(output_budget=2048)
    events = list(run("go", ctx, _registry(),
                       provider_fn=_provider_with_calls([[tc1, tc2]])))
    starts = [e for e in events if isinstance(e, ToolStartEvent)]
    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert len(starts) == 1  # only the second call dispatched
    assert starts[0].call_id == "c2"
    assert len(ends) == 2  # both produced an end event
    assert ends[0].error is True   # first busted
    assert ends[1].error is False  # second succeeded


# ── run_forked budget resolution ──────────────────────────────────────────

def test_run_forked_uses_skill_budget():
    """A skill with output_budget set determines the forked context's budget."""
    skill = SkillDef(
        name="s",
        triggers=["/s"],
        tools=[],
        context="fork",
        body="do",
        output_budget=2048,
    )
    parent = _ctx(output_budget=None, output_budget_default=8192)
    captured_budget: dict = {}

    # Fake provider checks the budget by attempting an oversized write.
    tc = ToolCallRecord("c1", "write", {"path": "/a", "content": "x" * 5000})
    state = {"turn": 0}

    def fake(system, messages, tools, config, environment=None):
        state["turn"] += 1
        yield TextChunk(content="")
        if state["turn"] == 1:
            yield AssistantMessage(content="", tool_calls=[tc])
        else:
            yield AssistantMessage(content="done", tool_calls=[])

    events = list(run_forked("do", skill, parent, _registry(), provider_fn=fake))
    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    # 5000 > skill's 2048 → bust. 5000 < parent default 8192 → would NOT bust.
    # If skill budget wins, we get an error.
    assert ends[0].error is True
    assert "2048" in ends[0].output


def test_run_forked_falls_back_to_config_default_when_skill_unset():
    skill = SkillDef(
        name="s",
        triggers=["/s"],
        tools=[],
        context="fork",
        body="do",
        output_budget=None,  # not declared
    )
    parent = _ctx(output_budget=None, output_budget_default=2048)
    tc = ToolCallRecord("c1", "write", {"path": "/a", "content": "x" * 5000})
    state = {"turn": 0}

    def fake(system, messages, tools, config, environment=None):
        state["turn"] += 1
        yield TextChunk(content="")
        if state["turn"] == 1:
            yield AssistantMessage(content="", tool_calls=[tc])
        else:
            yield AssistantMessage(content="done", tool_calls=[])

    events = list(run_forked("do", skill, parent, _registry(), provider_fn=fake))
    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert ends[0].error is True


def test_run_forked_unbounded_skill_disables_gate():
    """output_budget=None on the skill plus default=0 means unenforced."""
    skill = SkillDef(
        name="s",
        triggers=["/s"],
        tools=[],
        context="fork",
        body="do",
        output_budget=None,
    )
    parent = _ctx(output_budget=None, output_budget_default=0)
    tc = ToolCallRecord("c1", "write", {"path": "/a", "content": "x" * 5000})
    state = {"turn": 0}

    def fake(system, messages, tools, config, environment=None):
        state["turn"] += 1
        yield TextChunk(content="")
        if state["turn"] == 1:
            yield AssistantMessage(content="", tool_calls=[tc])
        else:
            yield AssistantMessage(content="done", tool_calls=[])

    events = list(run_forked("do", skill, parent, _registry(), provider_fn=fake))
    starts = [e for e in events if isinstance(e, ToolStartEvent)]
    assert len(starts) == 1
