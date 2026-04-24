from __future__ import annotations
import json
from typing import Generator
import httpx
from openai import OpenAI
from tigger.types import Config, Message, AssistantMessage, ToolCallRecord, TextChunk, ThinkingEvent

_client_cache: dict[tuple[str, str], OpenAI] = {}

# Short connect timeout, long read timeout for streaming (models may think for minutes).
_DEFAULT_TIMEOUT = httpx.Timeout(connect=30, read=300, write=30, pool=30)


def _get_client(base_url: str, api_key: str) -> OpenAI:
    key = (base_url, api_key)
    if key not in _client_cache:
        _client_cache[key] = OpenAI(base_url=base_url, api_key=api_key, timeout=_DEFAULT_TIMEOUT)
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
        try:
            args = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}
        records.append(ToolCallRecord(
            call_id=tc.get("id", ""),
            name=tc["function"]["name"],
            args=args,
        ))
    return records


def stream(
    system: str,
    messages: list[Message],
    tools: list[dict],
    config: Config,
) -> Generator[TextChunk | AssistantMessage | ThinkingEvent, None, None]:
    """Stream a chat completion. Yields TextChunk during streaming, then AssistantMessage."""
    client = _get_client(config.base_url, config.api_key)
    openai_messages = [{"role": "system", "content": system}] + messages_to_openai(messages)
    kwargs: dict = dict(
        model=config.model,
        messages=openai_messages,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        stream=True,
    )
    if tools:
        kwargs["tools"] = tools

    collected_text = ""
    collected_tool_calls: list[dict] = []
    tool_call_signalled = False

    response = client.chat.completions.create(**kwargs)
    for chunk in response:
        delta = chunk.choices[0].delta if chunk.choices else None
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

    yield AssistantMessage(
        content=collected_text,
        tool_calls=openai_tool_calls_to_records(collected_tool_calls),
    )
