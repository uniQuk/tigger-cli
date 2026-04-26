from __future__ import annotations

import pathlib
import time

from tigger import ui
from tigger.compaction import maybe_compact
from tigger.types import RunContext


def cmd_compact(
    args: str,
    ctx: RunContext,
    provider_fn,
    summaries_dir: pathlib.Path | None = None,
) -> None:
    with ui.Spinner(time.time()):
        ctx.messages, result = maybe_compact(ctx.messages, ctx.config, provider_fn, force=True,
                                             summaries_dir=summaries_dir)
    parts: list[str] = []
    if result.snipped:
        parts.append(f"Snipped {result.snipped} tool results")
    if result.summarized:
        parts.append(f"summarized {result.summarized} messages")
    if parts:
        detail = ", ".join(parts)
        print(f"{detail}: {result.tokens_before} \u2192 {result.tokens_after} tokens")
    else:
        print(f"Compacted: {result.tokens_before} \u2192 {result.tokens_after} tokens")
