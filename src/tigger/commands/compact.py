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
        parts.append(f"snipped {result.snipped} tool results")
    if result.summarized:
        parts.append(f"summarized {result.summarized} messages")
    detail = ", ".join(parts) if parts else "no changes needed"
    ui.console.print(
        f"[dim]\u2713 Compacted[/dim] [dim]({detail})[/dim] "
        f"[cyan]{result.tokens_before:,}[/cyan] [dim]\u2192[/dim] "
        f"[cyan]{result.tokens_after:,}[/cyan] [dim]tokens[/dim]"
    )
