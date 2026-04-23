import pytest
from tigger.types import Config, Message
from tigger.compaction import estimate_tokens, snip_old_results, maybe_compact, CompactResult

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


def test_estimate_tokens_uses_tiktoken_when_available():
    pytest.importorskip("tiktoken")
    msgs = [_msg("user", "hello world this is a test message")]
    t = estimate_tokens(msgs)
    assert isinstance(t, int) and t > 0


def test_estimate_tokens_fallback_when_tiktoken_missing(monkeypatch):
    import builtins
    real_import = builtins.__import__
    def patched_import(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", patched_import)
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
    assert result[0].content.startswith("[Conversation summary]")
    assert "summary text" in result[0].content
    assert summarized == 6  # 75% of 8 = 6 old messages


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
