"""Wire-format tests for prefix-stable provider serialization (R1, R3)."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from tigger.provider import stream
from tigger.types import AssistantMessage, Config, Message, ToolCallRecord


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
