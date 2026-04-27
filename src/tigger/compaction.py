from __future__ import annotations

import datetime
import pathlib
from collections.abc import Callable
from typing import NamedTuple

from tigger.types import Config, Message, TextChunk, ToolCallRecord


class CompactResult(NamedTuple):
    snipped: int
    summarized: int
    tokens_before: int
    tokens_after: int

# Cache encoder at module level — get_encoding() is expensive on first call.
try:
    import tiktoken as _tiktoken
    _enc = _tiktoken.get_encoding("cl100k_base")
except ImportError:
    _enc = None


_token_cache: tuple[int, int, int] = (0, 0, 0)  # (len, char_total, token_count)


def estimate_tokens(messages: list[Message]) -> int:
    """Token count via tiktoken (cl100k_base) if available, else chars/3.5.

    Cached by (message count, total chars) — a cheap fingerprint that avoids
    the old id()-based key's correctness issues while still protecting the
    toolbar repaint hot path from redundant tiktoken encoding.
    """
    global _token_cache
    n = len(messages)
    chars = sum(len(m.content) for m in messages)
    cached_n, cached_chars, cached_result = _token_cache
    if n == cached_n and chars == cached_chars:
        return cached_result
    if _enc is not None:
        result = sum(len(_enc.encode(m.content)) for m in messages)
    else:
        result = int(chars / 3.5)
    _token_cache = (n, chars, result)
    return result


def _split_old_recent(messages: list[Message]) -> tuple[list[Message], list[Message]]:
    """Split messages at the 75% boundary into (old, recent)."""
    boundary = max(1, len(messages) * 3 // 4)
    return messages[:boundary], messages[boundary:]


def snip_old_results(messages: list[Message]) -> tuple[list[Message], int]:
    """Layer 1: replace old tool results with short placeholder (no LLM call).

    Returns (compacted_messages, snipped_count).
    """
    if not messages:
        return messages, 0
    old, recent = _split_old_recent(messages)
    compacted = []
    snipped = 0
    for m in old:
        if m.role == "tool" and len(m.content) > 200:
            compacted.append(Message(
                role=m.role,
                content="[tool result snipped during compaction]",
                tool_call_id=m.tool_call_id,
                name=m.name,
            ))
            snipped += 1
        else:
            compacted.append(m)
    return compacted + recent, snipped


# Always-on snipping: replace large write/edit arguments in old assistant
# tool_calls with a placeholder. The model needs to see *that* it issued an
# edit on a path, but doesn't need the original new_string (often thousands
# of tokens) for any later reasoning — the next tool result already reflects
# the file's current state. Without this, every prior edit's full payload is
# reprocessed every turn. Cheap (no LLM call), runs on every turn.

# How many of the most recent assistant turns to leave fully intact. The
# model likely needs the immediately-preceding edit args to coordinate
# follow-up edits; older ones are dead weight.
_KEEP_RECENT_ASSISTANT_TURNS = 2

# Per-arg-field snip threshold (chars). Smaller payloads aren't worth the
# placeholder overhead, and we want to leave most ordinary tool calls alone.
_ARG_SNIP_THRESHOLD = 1000


def _snip_tool_call_args(tc: ToolCallRecord) -> tuple[ToolCallRecord, bool]:
    """Return (possibly new) ToolCallRecord with large write/edit args replaced.

    Pure: never mutates the input. Returns the original instance unchanged
    when no snipping applies, so callers can detect whether anything changed
    via identity comparison.
    """
    if tc.name == "write":
        content = tc.args.get("content")
        if isinstance(content, str) and len(content) > _ARG_SNIP_THRESHOLD:
            new_args = {
                "path": tc.args.get("path", ""),
                "content": f"[snipped: {len(content)} chars]",
            }
            return ToolCallRecord(
                call_id=tc.call_id,
                name=tc.name,
                args=new_args,
                parse_error_bytes=tc.parse_error_bytes,
            ), True
    elif tc.name == "edit":
        new_args = dict(tc.args)
        changed = False
        for field_name in ("old_string", "new_string"):
            val = new_args.get(field_name)
            if isinstance(val, str) and len(val) > _ARG_SNIP_THRESHOLD:
                new_args[field_name] = f"[snipped: {len(val)} chars]"
                changed = True
        if changed:
            return ToolCallRecord(
                call_id=tc.call_id,
                name=tc.name,
                args=new_args,
                parse_error_bytes=tc.parse_error_bytes,
            ), True
    return tc, False


def snip_old_tool_args(messages: list[Message]) -> tuple[list[Message], int]:
    """Snip large write/edit arg payloads from old assistant tool_calls.

    Pure: returns a new list with replacement Message and ToolCallRecord
    instances where snipping applies. Messages outside the snip window pass
    through by reference. The input list and the original ToolCallRecords
    inside it are never mutated, so the in-memory history retained by
    `RunContext.messages` keeps full payloads available for `/compact`,
    replay, and any future compaction passes.

    Returns (new_messages_list, snipped_count). `snipped_count` counts
    individual arg fields replaced, matching the legacy semantics.
    """
    if not messages:
        return messages, 0

    # Find the cutoff: keep the last N assistant turns intact.
    assistant_indices = [
        i for i, m in enumerate(messages)
        if m.role == "assistant" and m.tool_calls
    ]
    if len(assistant_indices) <= _KEEP_RECENT_ASSISTANT_TURNS:
        return messages, 0
    cutoff = assistant_indices[-_KEEP_RECENT_ASSISTANT_TURNS]

    snipped = 0
    out: list[Message] = []
    for idx, m in enumerate(messages):
        if idx >= cutoff or m.role != "assistant" or not m.tool_calls:
            out.append(m)
            continue
        new_tcs: list[ToolCallRecord] = []
        message_changed = False
        for tc in m.tool_calls:
            new_tc, changed = _snip_tool_call_args(tc)
            if changed:
                snipped += 1
                message_changed = True
            new_tcs.append(new_tc)
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
    return out, snipped


def summarize_old(
    messages: list[Message],
    config: Config,
    provider_fn: Callable,
) -> tuple[list[Message], int]:
    """Layer 2: LLM-summarize old portion of history (real API call).

    Returns (compacted_messages, summarized_count).
    """
    if not messages or provider_fn is None:
        return messages, 0
    old, recent = _split_old_recent(messages)
    prompt = (
        "Summarize the following conversation into a structured snapshot. "
        "Use the XML format below. Be concise but preserve actionable details.\n\n"
        "<conversation>\n"
        + "\n".join(f"<message role=\"{m.role}\">{m.content}</message>" for m in old)
        + "\n</conversation>\n\n"
        "Respond with:\n"
        "<state_snapshot>\n"
        "  <overall_goal>What the user is trying to accomplish</overall_goal>\n"
        "  <key_knowledge>Important facts, decisions, file paths discovered</key_knowledge>\n"
        "  <file_system_state>Files created, modified, or referenced</file_system_state>\n"
        "  <recent_actions>What was done recently and their results</recent_actions>\n"
        "  <current_plan>Next steps or pending work</current_plan>\n"
        "</state_snapshot>"
    )
    parts: list[str] = []
    for chunk in provider_fn(
        "You are a precise conversation summarizer. Output only the requested XML structure.",
        [Message(role="user", content=prompt)],
        [],
        config,
    ):
        if isinstance(chunk, TextChunk):
            parts.append(chunk.content)
    summary = "".join(parts)
    return [Message(role="system", content=f"[Conversation summary]\n{summary}")] + recent, len(old)


def persist_summary(summary: str, summaries_dir: pathlib.Path) -> pathlib.Path:
    """Write a compaction summary to disk and return the file path."""
    summaries_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out_path = summaries_dir / f"{timestamp}.md"
    out_path.write_text(summary)
    return out_path


def load_recent_summary(summaries_dir: pathlib.Path, max_age_hours: int = 24) -> str | None:
    """Return the content of the most recent summary if it's within *max_age_hours*, else None."""
    if not summaries_dir.is_dir():
        return None
    files = sorted(summaries_dir.glob("*.md"), reverse=True)
    if not files:
        return None
    latest = files[0]
    # Parse timestamp from filename: YYYY-MM-DD-HHMMSS.md
    try:
        ts = datetime.datetime.strptime(latest.stem, "%Y-%m-%d-%H%M%S")
    except ValueError:
        return None
    age = datetime.datetime.now() - ts
    if age.total_seconds() > max_age_hours * 3600:
        return None
    return latest.read_text()


def maybe_compact(
    messages: list[Message],
    config: Config,
    provider_fn: Callable | None,
    force: bool = False,
    summaries_dir: pathlib.Path | None = None,
) -> tuple[list[Message], CompactResult]:
    """Compact if above 70% of context_limit (or forced).

    Returns (possibly shorter message list, CompactResult).
    """
    tokens_before = estimate_tokens(messages)
    messages, arg_snipped = snip_old_tool_args(messages)

    # 0.85 instead of 0.70 — our cl100k_base estimator undercounts tokens for
    # non-Claude tokenizers (e.g. Qwen), so a lower threshold compacts too
    # eagerly and triggers an extra summarization model call mid-task.
    threshold = config.context_limit * 0.85
    if not force and tokens_before < threshold:
        return messages, CompactResult(snipped=arg_snipped, summarized=0,
                                       tokens_before=tokens_before,
                                       tokens_after=tokens_before)
    messages, snipped = snip_old_results(messages)
    if not force and estimate_tokens(messages) < threshold * 0.95:
        tokens_after = estimate_tokens(messages)
        return messages, CompactResult(snipped=snipped, summarized=0,
                                       tokens_before=tokens_before,
                                       tokens_after=tokens_after)
    summarized = 0
    if provider_fn is not None:
        messages, summarized = summarize_old(messages, config, provider_fn)
        # Persist the summary snapshot to disk when a summaries directory is configured.
        if summarized > 0 and summaries_dir is not None:
            # The summary text is in the first message's content, after the prefix.
            summary_text = messages[0].content.removeprefix("[Conversation summary]\n")
            persist_summary(summary_text, summaries_dir)
    tokens_after = estimate_tokens(messages)
    return messages, CompactResult(snipped=snipped, summarized=summarized,
                                   tokens_before=tokens_before,
                                   tokens_after=tokens_after)
