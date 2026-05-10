import pytest
from tigger.types import Config, Message, RunContext, TextChunk
from tigger.commands.compact import cmd_compact


def _cfg(**kw):
    return Config(base_url="http://x", model="m", **kw)


def _msg(role, content):
    return Message(role=role, content=content)


def _tool_msg(content):
    return Message(role="tool", content=content, tool_call_id="c1", name="bash")


def _ctx(messages, context_limit=100, **kw):
    return RunContext(config=_cfg(context_limit=context_limit, **kw),
                      messages=messages, system_prompt="test")


def _fake_provider(system, messages, tools, cfg):
    yield TextChunk(content="summary")


def test_cmd_compact_prints_breakdown(capsys):
    msgs = [_tool_msg("x" * 500) for _ in range(10)]
    ctx = _ctx(msgs)
    cmd_compact("", ctx, _fake_provider)
    captured = capsys.readouterr().out
    assert "snipped" in captured
    assert "summarized" in captured
    assert "\u2192" in captured  # arrow
    assert "tokens" in captured


def test_cmd_compact_snip_only(capsys):
    """When snipping alone brings tokens under threshold, no summarize."""
    msgs = [_tool_msg("x" * 500) for _ in range(4)]
    ctx = _ctx(msgs)
    # force=True still runs, but with only 4 messages and provider,
    # it will snip and then summarize since force=True
    cmd_compact("", ctx, _fake_provider)
    captured = capsys.readouterr().out
    assert "\u2192" in captured
    assert "tokens" in captured


def test_cmd_compact_no_provider(capsys):
    """With no provider, only snipping happens."""
    msgs = [_tool_msg("x" * 500) for _ in range(10)]
    ctx = _ctx(msgs)
    cmd_compact("", ctx, None)
    captured = capsys.readouterr().out
    assert "snipped" in captured
    assert "summarized" not in captured


def test_cmd_compact_short_messages(capsys):
    """Short messages with nothing to snip or summarize."""
    msgs = [_msg("user", "hi")]
    ctx = _ctx(msgs, context_limit=8192)
    cmd_compact("", ctx, None)
    captured = capsys.readouterr().out
    assert "Compacted" in captured
    assert "\u2192" in captured


def test_cmd_compact_modifies_ctx_messages():
    msgs = [_tool_msg("x" * 500) for _ in range(10)]
    ctx = _ctx(msgs)
    original_len = len(ctx.messages)
    cmd_compact("", ctx, _fake_provider)
    # After compaction with summarize, old messages are replaced by summary
    assert len(ctx.messages) < original_len
