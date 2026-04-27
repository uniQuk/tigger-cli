from __future__ import annotations

import json
import os
import sys
from collections.abc import Generator

import httpx
from openai import OpenAI

from tigger.types import AssistantMessage, Config, Message, StreamProgress, TextChunk, ThinkingEvent, ToolCallRecord

_perf_kwargs_logged = False

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
        if not raw_args:
            # Empty arguments string almost always means the stream was cut
            # off (max_tokens hit) before any args were emitted. Surface this
            # as a parse error so the dispatcher returns the truncation hint
            # instead of an unhelpful "missing required argument(s)".
            args = {}
            parse_error_bytes = 0
        else:
            try:
                args = json.loads(raw_args)
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
) -> Generator[TextChunk | AssistantMessage | ThinkingEvent | StreamProgress, None, None]:
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
    if config.top_p is not None:
        kwargs["top_p"] = config.top_p
    if config.presence_penalty is not None:
        kwargs["presence_penalty"] = config.presence_penalty
    if config.frequency_penalty is not None:
        kwargs["frequency_penalty"] = config.frequency_penalty
    # Vendor-specific params (Qwen via vLLM/SGLang/LM Studio) ride in extra_body.
    extra_body: dict = {}
    if config.top_k is not None:
        extra_body["top_k"] = config.top_k
    if config.min_p is not None:
        extra_body["min_p"] = config.min_p
    if config.repetition_penalty is not None:
        extra_body["repetition_penalty"] = config.repetition_penalty
    if config.chat_template_kwargs:
        extra_body["chat_template_kwargs"] = dict(config.chat_template_kwargs)
    if extra_body:
        kwargs["extra_body"] = extra_body
    if tools:
        kwargs["tools"] = tools

    collected_text = ""
    collected_thinking = ""
    collected_tool_calls: list[dict] = []
    tool_call_signalled = False
    input_tokens = 0
    output_tokens = 0
    finish_reason = ""
    pending_progress = 0  # coalesce StreamProgress: flush every ~200 chars

    # Request usage stats if the provider supports it; fall back without on error.
    kwargs["stream_options"] = {"include_usage": True}

    # One-shot diagnostic: when TIGGER_PERF is set, print the outgoing kwargs
    # (minus the messages payload) so we can confirm max_tokens, top_p, etc.
    # are actually being sent to the local server.
    global _perf_kwargs_logged
    if not _perf_kwargs_logged and os.environ.get("TIGGER_PERF", "").strip():
        diag = {k: v for k, v in kwargs.items() if k != "messages"}
        diag["_messages_count"] = len(kwargs.get("messages", []))
        sys.stderr.write(f"[perf] outgoing kwargs: {json.dumps(diag, default=str)}\n")
        sys.stderr.flush()
        _perf_kwargs_logged = True

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
            # Some OpenAI-compatible servers (vLLM/SGLang/LM Studio for Qwen)
                # emit reasoning as a separate `reasoning_content` field rather
                # than wrapping it in <think> tags inside `content`. Capture it
                # so we can re-send it for preserve_thinking / KV-cache reuse.
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                collected_thinking += reasoning
                pending_progress += len(reasoning)
                if pending_progress >= 200:
                    yield StreamProgress(chars=pending_progress)
                    pending_progress = 0
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
                        pending_progress += len(tc_chunk.function.name)
                    if tc_chunk.function.arguments:
                        collected_tool_calls[idx]["function"]["arguments"] += tc_chunk.function.arguments
                        pending_progress += len(tc_chunk.function.arguments)
                    if pending_progress >= 200:
                        yield StreamProgress(chars=pending_progress)
                        pending_progress = 0
    except Exception:
        if collected_text:
            yield TextChunk(content="\n[response interrupted, retrying]\n")
        raise

    if pending_progress:
        yield StreamProgress(chars=pending_progress)

    # If reasoning came in via the separate field and isn't already wrapped
    # in <think> tags inside content, prepend it so it persists in history.
    final_content = collected_text
    if collected_thinking and "<think>" not in collected_text:
        final_content = f"<think>\n{collected_thinking}\n</think>\n\n{collected_text}"

    yield AssistantMessage(
        content=final_content,
        tool_calls=openai_tool_calls_to_records(collected_tool_calls),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=finish_reason,
    )
