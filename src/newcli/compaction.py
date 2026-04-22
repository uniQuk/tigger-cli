from __future__ import annotations
from typing import Callable
from newcli.types import Message, Config


def estimate_tokens(messages: list[Message]) -> int:
    """Rough token estimate: total chars / 3.5."""
    total = sum(len(m.content) for m in messages)
    return int(total / 3.5)


def snip_old_results(messages: list[Message]) -> list[Message]:
    """Layer 1: replace old tool results with short placeholder (no LLM call)."""
    if not messages:
        return messages
    boundary = max(1, len(messages) * 3 // 4)
    old, recent = messages[:boundary], messages[boundary:]
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
    boundary = max(1, len(messages) * 3 // 4)
    old, recent = messages[:boundary], messages[boundary:]
    summary_prompt = (
        "Summarize the following conversation history concisely. "
        "Preserve key facts, decisions, and file paths mentioned.\n\n"
        + "\n".join(f"{m.role}: {m.content[:500]}" for m in old)
    )
    summary = provider_fn(summary_prompt)
    summary_msg = Message(role="user", content=f"[Conversation summary]\n{summary}")
    return [summary_msg] + recent


def maybe_compact(
    messages: list[Message],
    config: Config,
    provider_fn: Callable | None,
) -> list[Message]:
    """Compact if above 70% of context_limit. Returns (possibly shorter) list."""
    threshold = config.context_limit * 0.7
    if estimate_tokens(messages) < threshold:
        return messages
    messages = snip_old_results(messages)
    if estimate_tokens(messages) < threshold:
        return messages
    if provider_fn is not None:
        messages = summarize_old(messages, config, provider_fn)
    return messages
