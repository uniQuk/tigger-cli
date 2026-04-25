from __future__ import annotations
import datetime
import pathlib
from typing import Callable, NamedTuple
from tigger.types import Message, Config, TextChunk


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
    return [Message(role="user", content=f"[Conversation summary]\n{summary}")] + recent, len(old)


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
    threshold = config.context_limit * 0.7
    if not force and tokens_before < threshold:
        return messages, CompactResult(snipped=0, summarized=0,
                                       tokens_before=tokens_before,
                                       tokens_after=tokens_before)
    messages, snipped = snip_old_results(messages)
    if not force and estimate_tokens(messages) < threshold:
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
