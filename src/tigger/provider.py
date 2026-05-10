from __future__ import annotations

import json
import os
import sys
from collections.abc import Generator

import httpx
from openai import OpenAI

from tigger.types import (
    AssistantMessage,
    Config,
    Message,
    StreamProgress,
    TextChunk,
    ThinkingEvent,
    ToolCallRecord,
)

_perf_kwargs_logged = False

# Wire-model ids for which we've already emitted the "server ignored
# enable_thinking=False" warning. Dedup is per-process: re-warning every
# turn would drown out real output, but once per model is useful signal.
_thinking_ignored_warned: set[str] = set()

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


# Stub threshold for large file-write tool args. Content above this size is
# replaced with a reference stub on the wire-send path (history retains the
# full payload). 2048 chars matches the brainstorm decision: large enough
# to avoid stubbing routine small writes, small enough to catch the dominant
# 28KB-HTML-write case from tigger-perf3.tsv.
_WRITE_STUB_THRESHOLD = 2048


def _stub_large_write_args(messages: list[Message]) -> list[Message]:
    """Return a new list where successful large write/edit tool args are stubbed.

    For each assistant message with `tool_calls`, find the matching tool
    result message (by `tool_call_id`). When the tool is `write` or `edit`,
    the result content does not start with `Error:`, and the relevant arg
    field exceeds `_WRITE_STUB_THRESHOLD` chars, replace that arg field
    with a reference stub in the wire copy. The input list and its
    ToolCallRecord instances are never mutated.
    """
    if not messages:
        return messages

    # Index successful tool results by call_id for O(1) lookup.
    success_results: dict[str, str] = {}
    for m in messages:
        if m.role == "tool" and m.tool_call_id and not m.content.startswith("Error:"):
            success_results[m.tool_call_id] = m.content

    out: list[Message] = []
    for m in messages:
        if m.role != "assistant" or not m.tool_calls:
            out.append(m)
            continue
        new_tcs: list[ToolCallRecord] = []
        message_changed = False
        for tc in m.tool_calls:
            if (
                tc.name in ("write", "edit")
                and tc.call_id in success_results
            ):
                stubbed = _maybe_stub_write_args(tc)
                if stubbed is not tc:
                    message_changed = True
                new_tcs.append(stubbed)
            else:
                new_tcs.append(tc)
        if message_changed:
            out.append(Message(
                role=m.role,
                content=m.content,
                tool_calls=new_tcs,
                tool_call_id=m.tool_call_id,
                name=m.name,
            ))
        else:
            out.append(m)
    return out


def _maybe_stub_write_args(tc: ToolCallRecord) -> ToolCallRecord:
    """Return a new ToolCallRecord with stubbed args, or `tc` unchanged."""
    if tc.name == "write":
        content = tc.args.get("content")
        path = tc.args.get("path", "")
        if isinstance(content, str) and len(content) > _WRITE_STUB_THRESHOLD:
            return ToolCallRecord(
                call_id=tc.call_id,
                name=tc.name,
                args={
                    "path": path,
                    "content": f"[wrote {len(content)} chars to {path}]",
                },
                parse_error_bytes=tc.parse_error_bytes,
            )
    elif tc.name == "edit":
        path = tc.args.get("path", "")
        old_string = tc.args.get("old_string", "")
        new_string = tc.args.get("new_string", "")
        old_len = len(old_string) if isinstance(old_string, str) else 0
        new_len = len(new_string) if isinstance(new_string, str) else 0
        if old_len > _WRITE_STUB_THRESHOLD or new_len > _WRITE_STUB_THRESHOLD:
            new_args = dict(tc.args)
            stub = f"[edited {path}, +{new_len}/-{old_len} chars]"
            if new_len > _WRITE_STUB_THRESHOLD:
                new_args["new_string"] = stub
            if old_len > _WRITE_STUB_THRESHOLD:
                new_args["old_string"] = stub
            return ToolCallRecord(
                call_id=tc.call_id,
                name=tc.name,
                args=new_args,
                parse_error_bytes=tc.parse_error_bytes,
            )
    return tc


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
    *,
    environment: str | None = None,
) -> Generator[TextChunk | AssistantMessage | ThinkingEvent | StreamProgress, None, None]:
    """Stream a chat completion. Yields TextChunk during streaming, then AssistantMessage.

    `environment` carries dynamic per-turn context (active mode body, lazy
    MCP tool listing) that used to be concatenated onto the system prompt.
    Pulling it out keeps the system message bytewise stable across turns so
    the provider can reuse its KV cache prefix; the dynamic content rides
    as a synthetic <environment>...</environment> user message appended to
    the tail of the conversation.
    """
    client = _get_client(config.base_url, config.api_key, config.read_timeout)
    # Wire-side rewrite: stub large successful write/edit payloads so the
    # prompt prefix stops growing monotonically across turns. The in-memory
    # history (`messages`) keeps full payloads — recovery is via re-read.
    wire_messages = _stub_large_write_args(messages)
    openai_messages = [{"role": "system", "content": system}] + messages_to_openai(wire_messages)
    if environment:
        openai_messages.append({
            "role": "user",
            "content": f"<environment>\n{environment}\n</environment>",
        })
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
    saw_finish = False
    post_finish_chunks = 0

    # Request usage stats if the provider supports it; fall back without on error.
    kwargs["stream_options"] = {"include_usage": True}

    # One-shot diagnostic: when TIGGER_PERF is set, print the outgoing kwargs
    # (minus the messages and tools payloads) so we can confirm max_tokens,
    # top_p, chat_template_kwargs etc. are actually being sent. Tool schemas
    # were ~6KB of stderr noise per call drowning out the bits we care about.
    global _perf_kwargs_logged
    if not _perf_kwargs_logged and os.environ.get("TIGGER_PERF", "").strip():
        diag = {k: v for k, v in kwargs.items() if k not in ("messages", "tools")}
        diag["_messages_count"] = len(kwargs.get("messages", []))
        diag["_tools_count"] = len(kwargs.get("tools", []) or [])
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
                if saw_finish:
                    # Got the post-finish usage payload — LM Studio is known
                    # to omit the `data: [DONE]` SSE terminator after this,
                    # which would hang the SDK iterator forever. Break now.
                    break
            choice = chunk.choices[0] if chunk.choices else None
            if choice and choice.finish_reason:
                finish_reason = choice.finish_reason
                saw_finish = True
            delta = choice.delta if choice else None
            if delta is None:
                if saw_finish:
                    post_finish_chunks += 1
                    # Fallback: if no usage chunk arrives within a couple of
                    # post-finish empty chunks, give up waiting.
                    if post_finish_chunks >= 2:
                        break
                continue
            # Some OpenAI-compatible servers (vLLM/SGLang/LM Studio for Qwen)
            # emit reasoning as a separate `reasoning_content` field rather
            # than wrapping it in <think> tags inside `content`. Capture it
            # so we can re-send it for preserve_thinking / KV-cache reuse.
            # Yield a heartbeat on every delta — the watchdog in loop.py uses
            # any chunk arrival as activity, so coalescing here would let the
            # watchdog falsely fire during slow tool-call argument streaming.
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                collected_thinking += reasoning
                yield StreamProgress(chars=len(reasoning))
            if delta.content:
                collected_text += delta.content
                yield TextChunk(content=delta.content)
            if delta.tool_calls:
                if not tool_call_signalled:
                    tool_call_signalled = True
                    yield ThinkingEvent()
                delta_chars = 0
                for tc_chunk in delta.tool_calls:
                    idx = tc_chunk.index
                    while len(collected_tool_calls) <= idx:
                        collected_tool_calls.append({"id": "", "function": {"name": "", "arguments": ""}})
                    if tc_chunk.id:
                        collected_tool_calls[idx]["id"] = tc_chunk.id
                    if tc_chunk.function.name:
                        collected_tool_calls[idx]["function"]["name"] += tc_chunk.function.name
                        delta_chars += len(tc_chunk.function.name)
                    if tc_chunk.function.arguments:
                        collected_tool_calls[idx]["function"]["arguments"] += tc_chunk.function.arguments
                        delta_chars += len(tc_chunk.function.arguments)
                if delta_chars:
                    yield StreamProgress(chars=delta_chars)
    except Exception:
        if collected_text:
            yield TextChunk(content="\n[response interrupted, retrying]\n")
        raise

    # Diagnostic: if any tool call surfaced a name but no arguments, dump the
    # full collected_tool_calls dict to stderr. Some local servers (LM Studio
    # q4 quants, vLLM under load) split tool-call deltas in non-spec ways
    # that the OpenAI Python SDK silently drops. This lets us see which
    # field went missing and correlate with the server's own packet log.
    for idx, tc in enumerate(collected_tool_calls):
        name = tc.get("function", {}).get("name", "")
        args_str = tc.get("function", {}).get("arguments", "") or ""
        if name and not args_str:
            sys.stderr.write(
                f"[provider] empty-args after stream finished: "
                f"idx={idx} id={tc.get('id', '')!r} name={name!r} "
                f"finish_reason={finish_reason!r} "
                f"input_tokens={input_tokens} output_tokens={output_tokens} "
                f"raw={tc!r}\n"
            )
            sys.stderr.flush()

    # If reasoning came in via the separate field and isn't already wrapped
    # in <think> tags inside content, prepend it so it persists in history —
    # UNLESS the user explicitly disabled thinking. Qwen3.6-27b on LM Studio
    # streams reasoning_content even with enable_thinking=False; preserving
    # those tokens bloats /tokens, compaction, and per-turn token estimates
    # for behaviour the user opted out of.
    final_content = collected_text
    if collected_thinking and "<think>" not in collected_text:
        enable_thinking = (config.chat_template_kwargs or {}).get("enable_thinking", True)
        if enable_thinking is not False:
            final_content = f"<think>\n{collected_thinking}\n</think>\n\n{collected_text}"
        elif config.model not in _thinking_ignored_warned:
            # User asked for no thinking, but the server streamed it anyway
            # (Qwen3.6-27b on LM Studio reproducer). Tigger drops the
            # reasoning from history, but the model already paid the latency
            # cost generating it — flag the footgun so the user can cap
            # max_tokens or switch to a non-thinking model variant.
            _thinking_ignored_warned.add(config.model)
            think_chars = len(collected_thinking)
            think_tok_est = think_chars // 4
            sys.stderr.write(
                f"[provider] {config.model!r}: server streamed "
                f"reasoning_content (~{think_tok_est} tok / {think_chars} "
                f"chars this turn) despite "
                f"chat_template_kwargs.enable_thinking=False. Reasoning "
                f"is dropped from history, but the model still spent "
                f"latency generating it. Cap max_tokens or switch to a "
                f"non-thinking model variant.\n"
            )
            sys.stderr.flush()

    yield AssistantMessage(
        content=final_content,
        tool_calls=openai_tool_calls_to_records(collected_tool_calls),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=finish_reason,
    )
