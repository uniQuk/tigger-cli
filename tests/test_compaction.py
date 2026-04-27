import pytest
from tigger.types import Config, Message, ToolCallRecord
from tigger.compaction import (
    CompactResult,
    estimate_tokens,
    maybe_compact,
    snip_old_results,
    snip_old_tool_args,
)

def _cfg(**kw):
    return Config(base_url="http://x", model="m", **kw)

def _msg(role, content):
    return Message(role=role, content=content)

def _tool_msg(content):
    m = Message(role="tool", content=content, tool_call_id="c1", name="bash")
    return m

def test_estimate_tokens_empty():
    assert estimate_tokens([]) == 0

def test_estimate_tokens_rough():
    msgs = [_msg("user", "hello world")]
    t = estimate_tokens(msgs)
    assert 1 <= t <= 10

def test_snip_old_results_no_op_short():
    msgs = [_msg("user", "hi"), _tool_msg("small result")]
    result, snipped = snip_old_results(msgs)
    assert result == msgs
    assert snipped == 0

def test_snip_removes_old_tool_results():
    old = [_tool_msg("x" * 500) for _ in range(20)]
    recent = [_msg("user", "final question"), _msg("assistant", "final answer")]
    msgs = old + recent
    result, snipped = snip_old_results(msgs)
    assert estimate_tokens(result) < estimate_tokens(msgs)
    assert result[-2].content == "final question"
    assert snipped > 0

def test_snip_returns_correct_count():
    old = [_tool_msg("x" * 500) for _ in range(8)]
    recent = [_msg("user", "q")]
    msgs = old + recent
    result, snipped = snip_old_results(msgs)
    # boundary = max(1, 9 * 3 // 4) = 6, so 6 old messages in old portion
    # all 6 have content > 200 chars
    assert snipped == 6

def test_maybe_compact_noop_under_threshold():
    cfg = _cfg(context_limit=8192)
    msgs = [_msg("user", "short")]
    result, cr = maybe_compact(msgs, cfg, provider_fn=None)
    assert result == msgs
    assert isinstance(cr, CompactResult)
    assert cr.snipped == 0
    assert cr.summarized == 0
    assert cr.tokens_before == cr.tokens_after

def test_maybe_compact_layer1_triggers():
    cfg = _cfg(context_limit=100)
    msgs = [_tool_msg("x" * 300) for _ in range(5)]
    result, cr = maybe_compact(msgs, cfg, provider_fn=None)
    assert estimate_tokens(result) <= estimate_tokens(msgs)
    assert isinstance(cr, CompactResult)
    assert cr.tokens_before >= cr.tokens_after

def test_maybe_compact_returns_compact_result_with_snip_count():
    cfg = _cfg(context_limit=100)
    msgs = [_tool_msg("x" * 300) for _ in range(8)]
    result, cr = maybe_compact(msgs, cfg, provider_fn=None)
    assert cr.snipped > 0
    assert cr.summarized == 0


def _assistant_with_tool_call(name: str, args: dict) -> Message:
    return Message(
        role="assistant",
        content="",
        tool_calls=[ToolCallRecord(call_id="c1", name=name, args=args)],
    )


def test_snip_old_tool_args_replaces_large_write_content():
    big_content = "x" * 5000
    msgs = [
        _msg("user", "do it"),
        _assistant_with_tool_call("write", {"path": "/a.html", "content": big_content}),
        _tool_msg("ok"),
        _assistant_with_tool_call("edit", {"path": "/a.html", "old_string": "<a/>", "new_string": "<b/>"}),
        _tool_msg("ok"),
        _assistant_with_tool_call("write", {"path": "/b.html", "content": "small"}),
    ]
    out, snipped = snip_old_tool_args(msgs)
    assert snipped == 1
    # Old write payload was replaced with placeholder; path preserved
    old_write = out[1].tool_calls[0].args
    assert old_write["path"] == "/a.html"
    assert "snipped" in old_write["content"]
    assert "5000" in old_write["content"]
    # Recent assistant turns left intact
    assert out[-1].tool_calls[0].args["content"] == "small"


def test_snip_old_tool_args_replaces_large_edit_strings():
    big_new = "y" * 4000
    msgs = [
        _msg("user", "go"),
        _assistant_with_tool_call("edit", {"path": "/a", "old_string": "x", "new_string": big_new}),
        _tool_msg("ok"),
        _assistant_with_tool_call("edit", {"path": "/a", "old_string": "p", "new_string": "q"}),
        _tool_msg("ok"),
        _assistant_with_tool_call("edit", {"path": "/a", "old_string": "r", "new_string": "s"}),
    ]
    out, snipped = snip_old_tool_args(msgs)
    assert snipped == 1
    snipped_args = out[1].tool_calls[0].args
    assert snipped_args["path"] == "/a"
    assert "snipped" in snipped_args["new_string"]
    # Untouched fields stay intact
    assert snipped_args["old_string"] == "x"


def test_snip_old_tool_args_keeps_recent_assistant_turns():
    # Even with huge args, the most recent assistant turns are not snipped.
    big = "z" * 5000
    msgs = [
        _msg("user", "go"),
        _assistant_with_tool_call("write", {"path": "/a", "content": big}),
        _tool_msg("ok"),
        _assistant_with_tool_call("write", {"path": "/b", "content": big}),
    ]
    out, snipped = snip_old_tool_args(msgs)
    # Only one assistant turn (the older one) should survive snipping.
    # With keep_recent=2, both should survive when there are exactly 2.
    assert snipped == 0
    assert out[1].tool_calls[0].args["content"] == big
    assert out[-1].tool_calls[0].args["content"] == big


def test_snip_old_tool_args_ignores_non_write_edit_tools():
    msgs = [
        _msg("user", "go"),
        _assistant_with_tool_call("read", {"path": "/a"}),
        _tool_msg("ok"),
        _assistant_with_tool_call("edit", {"path": "/a", "old_string": "p", "new_string": "q"}),
        _tool_msg("ok"),
        _assistant_with_tool_call("edit", {"path": "/a", "old_string": "r", "new_string": "s"}),
    ]
    out, snipped = snip_old_tool_args(msgs)
    assert snipped == 0
    # Read args left alone regardless of size
    assert out[1].tool_calls[0].args == {"path": "/a"}


def test_estimate_tokens_uses_tiktoken_when_available():
    pytest.importorskip("tiktoken")
    msgs = [_msg("user", "hello world this is a test message")]
    t = estimate_tokens(msgs)
    assert isinstance(t, int) and t > 0


def test_estimate_tokens_fallback_when_tiktoken_missing(monkeypatch):
    from tigger import compaction
    monkeypatch.setattr(compaction, "_enc", None)
    # Use a fresh list so the cache doesn't mask the fallback path.
    msgs = [_msg("user", "hello")]
    t = estimate_tokens(msgs)
    assert t == int(len("hello") / 3.5)


def test_summarize_old_calls_provider_with_correct_signature():
    from tigger.compaction import summarize_old
    call_args: list = []

    def fake_provider(system, messages, tools, cfg):
        call_args.extend([system, messages, tools, cfg])
        from tigger.types import TextChunk
        yield TextChunk(content="summary text")

    cfg = _cfg()
    msgs = [_msg("user", f"msg{i}") for i in range(8)]
    result, summarized = summarize_old(msgs, cfg, fake_provider)

    assert len(call_args) == 4           # system, messages, tools, cfg
    assert isinstance(call_args[0], str)
    assert isinstance(call_args[1], list)
    assert call_args[2] == []            # no tools passed
    assert result[0].role == "system"
    assert result[0].content.startswith("[Conversation summary]")
    assert "summary text" in result[0].content
    assert summarized == 6  # 75% of 8 = 6 old messages

    # Verify structured XML prompt
    prompt_content = call_args[1][0].content
    assert "<conversation>" in prompt_content
    assert "<state_snapshot>" in prompt_content
    assert "precise conversation summarizer" in call_args[0]


def test_summarize_old_does_not_truncate_long_messages():
    from tigger.compaction import summarize_old

    captured_prompt: list[str] = []

    def fake_provider(system, messages, tools, cfg):
        captured_prompt.append(messages[0].content)
        from tigger.types import TextChunk
        yield TextChunk(content="summary")

    cfg = _cfg()
    long_content = "x" * 700
    msgs = [_msg("user", long_content)] + [_msg("user", f"msg{i}") for i in range(7)]
    summarize_old(msgs, cfg, fake_provider)

    # Full 700-char content should appear in the prompt, not truncated to 500
    assert long_content in captured_prompt[0]


def test_summarize_old_uses_structured_prompt():
    from tigger.compaction import summarize_old

    captured: dict = {}

    def fake_provider(system, messages, tools, cfg):
        captured["system"] = system
        captured["prompt"] = messages[0].content
        from tigger.types import TextChunk
        yield TextChunk(content="summary")

    cfg = _cfg()
    msgs = [_msg("user", f"msg{i}") for i in range(8)]
    summarize_old(msgs, cfg, fake_provider)

    prompt = captured["prompt"]
    assert "<conversation>" in prompt
    assert "</conversation>" in prompt
    assert '<message role="user">' in prompt
    assert "</message>" in prompt
    assert "<state_snapshot>" in prompt
    assert "<overall_goal>" in prompt
    assert "<key_knowledge>" in prompt
    assert "<file_system_state>" in prompt
    assert "<recent_actions>" in prompt
    assert "<current_plan>" in prompt
    assert "</state_snapshot>" in prompt


def test_estimate_tokens_cached_on_same_list():
    """Two calls with same list return same result (cache hit)."""
    msgs = [_msg("user", "hello world this is a test")]
    t1 = estimate_tokens(msgs)
    t2 = estimate_tokens(msgs)
    assert t1 == t2


def test_estimate_tokens_invalidated_on_append():
    """Appending a message changes len(), invalidating the cache."""
    msgs = [_msg("user", "hello")]
    t1 = estimate_tokens(msgs)
    msgs.append(_msg("assistant", "world with more tokens"))
    t2 = estimate_tokens(msgs)
    assert t2 > t1


def test_estimate_tokens_invalidated_on_replacement():
    """Replacing the list entirely (new id) gives fresh count."""
    msgs = [_msg("user", "hello")]
    t1 = estimate_tokens(msgs)
    msgs2 = [_msg("user", "hello"), _msg("assistant", "world with more tokens")]
    t2 = estimate_tokens(msgs2)
    assert t2 > t1


def test_maybe_compact_with_summarize():
    from tigger.types import TextChunk

    def fake_provider(system, messages, tools, cfg):
        yield TextChunk(content="summary")

    cfg = _cfg(context_limit=100)
    msgs = [_tool_msg("x" * 300) for _ in range(8)]
    result, cr = maybe_compact(msgs, cfg, fake_provider)
    assert cr.snipped > 0
    assert cr.summarized > 0
    assert cr.tokens_before > cr.tokens_after
