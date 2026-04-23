from __future__ import annotations
import datetime
import pathlib
from tigger.types import RunContext, Message, TextChunk


def cmd_summary(args: str, ctx: RunContext, tigger_dir: pathlib.Path, provider_fn) -> None:
    if not ctx.messages:
        print("No conversation to summarize.")
        return

    prompt = (
        "Summarize the current conversation session. Structure your response as:\n\n"
        "## Overall Goal\nWhat the user is trying to accomplish\n\n"
        "## Key Knowledge\nImportant facts, decisions, and discoveries\n\n"
        "## Recent Actions\nWhat was done and the results\n\n"
        "## Current Plan\nNext steps or pending work\n\n"
        "Conversation:\n"
        + "\n".join(f"{m.role}: {m.content[:1000]}" for m in ctx.messages)
    )

    parts: list[str] = []
    for chunk in provider_fn(
        "You are a session summarizer. Output clear, structured markdown.",
        [Message(role="user", content=prompt)],
        [],
        ctx.config,
    ):
        if isinstance(chunk, TextChunk):
            parts.append(chunk.content)
    summary = "".join(parts)

    summaries_dir = tigger_dir / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out_path = summaries_dir / f"{timestamp}.md"
    out_path.write_text(summary)
    print(f"Summary saved to {out_path}")
