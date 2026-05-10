"""Wire-format tests for prefix-stable provider serialization (R1, R3)."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from tigger.provider import stream
from tigger.types import Config, Message, ToolCallRecord


def _cfg() -> Config:
    return Config(base_url="http://x", model="m", read_timeout=0)


def _capture_outgoing(*, environment: str | None = None) -> list[dict]:
    """Run `stream` with a mocked client and return the openai_messages payload."""
    captured: dict = {}

    fake_client = MagicMock()
    fake_response = iter([])  # empty stream — we only care about the request

    def create(**kwargs):
        captured["messages"] = kwargs["messages"]
        return fake_response

    fake_client.chat.completions.create = create

    with patch("tigger.provider._get_client", return_value=fake_client):
        gen = stream(
            "sys",
            [Message(role="user", content="hello")],
            [],
            _cfg(),
            environment=environment,
        )
        # Drain the generator. The empty fake response means no AssistantMessage
        # is yielded, but the underlying create() call still happens during the
        # try/except in stream().
        for _ in gen:
            pass
    return captured["messages"]


def test_stream_no_environment_omits_tail_message():
    msgs = _capture_outgoing(environment=None)
    # Just system + the one user message; no env tail.
    assert msgs == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]


def test_stream_with_environment_appends_wrapped_user_message():
    msgs = _capture_outgoing(environment="act\n\nLazy MCP tools: foo")
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "hello"}
    # Tail is a synthetic user message wrapped in <environment> tags.
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"].startswith("<environment>")
    assert msgs[-1]["content"].endswith("</environment>")
    assert "act" in msgs[-1]["content"]
    assert "Lazy MCP tools: foo" in msgs[-1]["content"]


def test_stream_system_bytes_stable_across_calls():
    """Two calls with same system + different environment must produce same system bytes."""
    msgs1 = _capture_outgoing(environment="act")
    msgs2 = _capture_outgoing(environment="plan")
    assert msgs1[0] == msgs2[0]  # system message identical
    # Only the env tail differs.
    assert msgs1[-1] != msgs2[-1]


def test_stream_empty_environment_string_omits_tail():
    """Empty string is falsy — no tail message."""
    msgs = _capture_outgoing(environment="")
    assert all("<environment>" not in m["content"] for m in msgs)


# ── R4–R6: Stub large file-write tool args after success ───────────────────

from tigger.provider import _stub_large_write_args


def _assistant_with_tool_call(call_id: str, name: str, args: dict) -> Message:
    return Message(
        role="assistant",
        content="",
        tool_calls=[ToolCallRecord(call_id=call_id, name=name, args=args)],
    )


def _tool_result(call_id: str, content: str = "ok") -> Message:
    return Message(role="tool", content=content, tool_call_id=call_id, name="write")


def test_stub_replaces_large_successful_write():
    big = "x" * 5000
    msgs = [
        Message(role="user", content="go"),
        _assistant_with_tool_call("c1", "write", {"path": "/a.html", "content": big}),
        _tool_result("c1"),
    ]
    out = _stub_large_write_args(msgs)
    stubbed_args = out[1].tool_calls[0].args
    assert stubbed_args["content"] == "[wrote 5000 chars to /a.html]"
    assert stubbed_args["path"] == "/a.html"
    # In-memory history untouched.
    assert msgs[1].tool_calls[0].args["content"] == big


def test_stub_skips_small_writes():
    msgs = [
        Message(role="user", content="go"),
        _assistant_with_tool_call("c1", "write", {"path": "/a", "content": "small"}),
        _tool_result("c1"),
    ]
    out = _stub_large_write_args(msgs)
    assert out[1] is msgs[1]


def test_stub_skips_failed_writes():
    big = "x" * 5000
    msgs = [
        Message(role="user", content="go"),
        _assistant_with_tool_call("c1", "write", {"path": "/a", "content": big}),
        _tool_result("c1", content="Error: file already exists"),
    ]
    out = _stub_large_write_args(msgs)
    assert out[1].tool_calls[0].args["content"] == big  # NOT stubbed


def test_stub_skips_pending_writes_no_result_yet():
    big = "x" * 5000
    msgs = [
        Message(role="user", content="go"),
        _assistant_with_tool_call("c1", "write", {"path": "/a", "content": big}),
        # No matching tool result message — call still pending.
    ]
    out = _stub_large_write_args(msgs)
    assert out[1].tool_calls[0].args["content"] == big


def test_stub_replaces_large_edit_new_string():
    big_new = "y" * 4000
    msgs = [
        Message(role="user", content="go"),
        _assistant_with_tool_call("c1", "edit", {
            "path": "/a", "old_string": "x", "new_string": big_new,
        }),
        _tool_result("c1"),
    ]
    out = _stub_large_write_args(msgs)
    args = out[1].tool_calls[0].args
    assert args["new_string"] == "[edited /a, +4000/-1 chars]"
    assert args["old_string"] == "x"  # small field preserved
    assert args["path"] == "/a"


def test_stub_boundary_exactly_at_threshold_not_stubbed():
    """Strict greater-than: content of exactly 2048 chars stays."""
    content = "x" * 2048
    msgs = [
        Message(role="user", content="go"),
        _assistant_with_tool_call("c1", "write", {"path": "/a", "content": content}),
        _tool_result("c1"),
    ]
    out = _stub_large_write_args(msgs)
    assert out[1].tool_calls[0].args["content"] == content


def _stream_chunk(content=None, reasoning=None, finish=None):
    """Build a minimal SSE-shaped chunk for the openai-python iter."""
    delta = MagicMock()
    delta.content = content
    delta.reasoning_content = reasoning
    delta.tool_calls = None
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish
    chunk = MagicMock()
    chunk.choices = [choice]
    chunk.usage = None
    return chunk


def _run_stream_with_chunks(chunks, *, config: Config):
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = iter(chunks)
    final = None
    with patch("tigger.provider._get_client", return_value=fake_client):
        from tigger.types import AssistantMessage
        for ev in stream("sys", [Message(role="user", content="go")], [], config):
            if isinstance(ev, AssistantMessage):
                final = ev
    return final


def test_reasoning_dropped_when_thinking_disabled():
    """Iter-4: when chat_template_kwargs.enable_thinking is False, reasoning
    tokens emitted by the server (Qwen3.6-27b family on LM Studio) must NOT
    be wrapped into the message history."""
    cfg = Config(
        base_url="http://x", model="m", read_timeout=0,
        chat_template_kwargs={"enable_thinking": False, "preserve_thinking": False},
    )
    chunks = [
        _stream_chunk(reasoning="Let me think..."),
        _stream_chunk(content="answer"),
        _stream_chunk(finish="stop"),
    ]
    msg = _run_stream_with_chunks(chunks, config=cfg)
    assert msg is not None
    assert "<think>" not in msg.content
    assert msg.content == "answer"


def test_reasoning_wrapped_when_thinking_enabled():
    """Default / explicit enable_thinking=True keeps the wrap (history shows
    reasoning so the UI can re-render it)."""
    cfg = Config(
        base_url="http://x", model="m", read_timeout=0,
        chat_template_kwargs={"enable_thinking": True},
    )
    chunks = [
        _stream_chunk(reasoning="hmm"),
        _stream_chunk(content="answer"),
        _stream_chunk(finish="stop"),
    ]
    msg = _run_stream_with_chunks(chunks, config=cfg)
    assert msg is not None
    assert msg.content.startswith("<think>")
    assert "hmm" in msg.content
    assert msg.content.endswith("answer")


def test_stub_two_turn_history_only_old_write_stubbed_via_stream():
    """Integration: across the wire, a two-turn sequence with a 28KB write
    in turn 1 has the assistant tool_call args replaced with a stub on the
    next call's payload. The first call still sends the full content."""
    big = "x" * 5000
    msgs_after_turn1 = [
        Message(role="user", content="write the file"),
        _assistant_with_tool_call("c1", "write", {"path": "/a.html", "content": big}),
        _tool_result("c1"),
        Message(role="user", content="now read it"),
    ]
    captured: dict = {}
    fake_client = MagicMock()
    def create(**kwargs):
        captured["messages"] = kwargs["messages"]
        return iter([])
    fake_client.chat.completions.create = create
    with patch("tigger.provider._get_client", return_value=fake_client):
        for _ in stream("sys", msgs_after_turn1, [], _cfg()):
            pass
    # Turn 2 wire payload: the assistant tool_call's content is the stub.
    assistant_wire = next(m for m in captured["messages"] if m["role"] == "assistant")
    import json as _json
    args = _json.loads(assistant_wire["tool_calls"][0]["function"]["arguments"])
    assert args["content"] == "[wrote 5000 chars to /a.html]"
