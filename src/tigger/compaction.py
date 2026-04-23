from __future__ import annotations
from typing import Callable
from newcli.types import Message, Config, TextChunk

# Cache encoder at module level — get_encoding() is expensive on first call.
try:
    import tiktoken as _tiktoken
    _enc = _tiktoken.get_encoding("cl100k_base")
except ImportError:
    _enc = None


def estimate_tokens(messages: list[Message]) -> int:
    """Token count via tiktoken (cl100k_base) if available, else chars/3.5."""
    if _enc is not None:
        return sum(len(_enc.encode(m.content)) for m in messages)
    total = sum(len(m.content) for m in messages)
    return int(total / 3.5)


def _split_old_recent(messages: list[Message]) -> tuple[list[Message], list[Message]]:
    """Split messages at the 75% boundary into (old, recent)."""
    boundary = max(1, len(messages) * 3 // 4)
    return messages[:boundary], messages[boundary:]


def snip_old_results(messages: list[Message]) -> list[Message]:
    """Layer 1: replace old tool results with short placeholder (no LLM call)."""
    if not messages:
        return messages
    old, recent = _split_old_recent(messages)
    compacted = []
    for m in old:
        if m.role == "tool" and len(m.content) > 200:
            compacted.append(Message(
                role=m.role,
                content="[tool result snipped during compaction]",
                tool_call_id=m.tool_call_id,
                name=m.name,
            ))
        else:
            compacted.append(m)
    return compacted + recent


def summarize_old(
    messages: list[Message],
    config: Config,
    provider_fn: Callable,
) -> list[Message]:
    """Layer 2: LLM-summarize old portion of history (real API call)."""
    if not messages or provider_fn is None:
        return messages
    old, recent = _split_old_recent(messages)
    prompt = (
        "Summarize the following conversation history concisely. "
        "Preserve key facts, decisions, and file paths mentioned.\n\n"
        + "\n".join(f"{m.role}: {m.content[:500]}" for m in old)
    )
    parts: list[str] = []
    for chunk in provider_fn(
        "You are a concise summarizer.",
        [Message(role="user", content=prompt)],
        [],
        config,
    ):
        if isinstance(chunk, TextChunk):
            parts.append(chunk.content)
    summary = "".join(parts)
    return [Message(role="user", content=f"[Conversation summary]\n{summary}")] + recent


def maybe_compact(
    messages: list[Message],
    config: Config,
    provider_fn: Callable | None,
    force: bool = False,
) -> list[Message]:
    """Compact if above 70% of context_limit (or forced). Returns (possibly shorter) list."""
    threshold = config.context_limit * 0.7
    if not force and estimate_tokens(messages) < threshold:
        return messages
    messages = snip_old_results(messages)
    if not force and estimate_tokens(messages) < threshold:
        return messages
    if provider_fn is not None:
        messages = summarize_old(messages, config, provider_fn)
    return messages
