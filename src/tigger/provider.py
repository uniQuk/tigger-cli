from __future__ import annotations

import json
from collections.abc import Generator

import httpx
from openai import OpenAI

from tigger.types import AssistantMessage, Config, Message, TextChunk, ThinkingEvent, ToolCallRecord

_client_cache: dict[tuple[str, str, int], OpenAI] = {}


def _get_client(base_url: str, api_key: str, read_timeout: int) -> OpenAI:
    key = (base_url, api_key, read_timeout)
    if key not in _client_cache:
        # read_timeout <= 0 disables the read ceiling entirely (useful for slow
        # local models that can sit silent for long periods during thinking).
        read = None if read_timeout <= 0 else read_timeout
        timeout = httpx.Timeout(connect=30, read=read, write=30, pool=30)
        _client_cache[key] = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    return _client_cache[key]


def messages_to_openai(messages: list[Message]) -> list[dict]:
    """Convert neutral Message list to OpenAI wire format."""
    result = []
    for m in messages:
        if m.role == "tool":
            result.append({
                "role": "tool",
                "content": m.content,
                "tool_call_id": m.tool_call_id,
            })
        elif m.tool_calls:
            result.append({
                "role": m.role,
                "content": m.content,
                "tool_calls": [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.args),
                        },
                    }
                    for tc in m.tool_calls
                ],
            })
        else:
            result.append({"role": m.role, "content": m.content})
    return result


def openai_tool_calls_to_records(raw: list[dict]) -> list[ToolCallRecord]:
    records = []
    for tc in raw:
        fn = tc.get("function", {})
        raw_args = fn.get("arguments", "") or ""
        parse_error_bytes: int | None = None
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            args = {}
            parse_error_bytes = len(raw_args)
        records.append(ToolCallRecord(
            call_id=tc.get("id", ""),
            name=fn.get("name", ""),
            args=args,
            parse_error_bytes=parse_error_bytes,
        ))
    return records


def stream(
    system: str,
    messages: list[Message],
    tools: list[dict],
    config: Config,
) -> Generator[TextChunk | AssistantMessage | ThinkingEvent, None, None]:
    """Stream a chat completion. Yields TextChunk during streaming, then AssistantMessage."""
    client = _get_client(config.base_url, config.api_key, config.read_timeout)
    openai_messages = [{"role": "system", "content": system}] + messages_to_openai(messages)
    kwargs: dict = dict(
        model=config.model,
        messages=openai_messages,
        temperature=config.temperature,
        stream=True,
    )
    if config.max_tokens > 0:
        kwargs["max_tokens"] = config.max_tokens
    if tools:
        kwargs["tools"] = tools

    collected_text = ""
    collected_tool_calls: list[dict] = []
    tool_call_signalled = False
    input_tokens = 0
    output_tokens = 0
    finish_reason = ""

    # Request usage stats if the provider supports it; fall back without on error.
    kwargs["stream_options"] = {"include_usage": True}
    try:
        response = client.chat.completions.create(**kwargs)
    except Exception:
        kwargs.pop("stream_options", None)
        response = client.chat.completions.create(**kwargs)
    try:
        for chunk in response:
            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens or 0
                output_tokens = chunk.usage.completion_tokens or 0
            choice = chunk.choices[0] if chunk.choices else None
            if choice and choice.finish_reason:
                finish_reason = choice.finish_reason
            delta = choice.delta if choice else None
            if delta is None:
                continue
            if delta.content:
                collected_text += delta.content
                yield TextChunk(content=delta.content)
            if delta.tool_calls:
                if not tool_call_signalled:
                    tool_call_signalled = True
                    yield ThinkingEvent()
                for tc_chunk in delta.tool_calls:
                    idx = tc_chunk.index
                    while len(collected_tool_calls) <= idx:
                        collected_tool_calls.append({"id": "", "function": {"name": "", "arguments": ""}})
                    if tc_chunk.id:
                        collected_tool_calls[idx]["id"] = tc_chunk.id
                    if tc_chunk.function.name:
                        collected_tool_calls[idx]["function"]["name"] += tc_chunk.function.name
                    if tc_chunk.function.arguments:
                        collected_tool_calls[idx]["function"]["arguments"] += tc_chunk.function.arguments
    except Exception:
        if collected_text:
            yield TextChunk(content="\n[response interrupted, retrying]\n")
        raise

    yield AssistantMessage(
        content=collected_text,
        tool_calls=openai_tool_calls_to_records(collected_tool_calls),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=finish_reason,
    )
