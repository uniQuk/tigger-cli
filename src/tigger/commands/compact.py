from __future__ import annotations
from tigger.types import RunContext
from tigger.compaction import maybe_compact, estimate_tokens


def cmd_compact(args: str, ctx: RunContext, provider_fn) -> None:
    before = estimate_tokens(ctx.messages)
    ctx.messages = maybe_compact(ctx.messages, ctx.config, provider_fn, force=True)
    after = estimate_tokens(ctx.messages)
    print(f"Compacted: {before} → {after} estimated tokens")
