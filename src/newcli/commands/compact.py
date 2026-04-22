from __future__ import annotations
import dataclasses
from newcli.types import RunContext
from newcli.compaction import maybe_compact, estimate_tokens


def cmd_compact(args: str, ctx: RunContext, provider_fn) -> None:
    before = estimate_tokens(ctx.messages)
    # Force compaction by temporarily lowering the threshold
    low_limit_config = dataclasses.replace(ctx.config, context_limit=1)
    ctx.messages = maybe_compact(ctx.messages, low_limit_config, provider_fn)
    after = estimate_tokens(ctx.messages)
    print(f"Compacted: {before} → {after} estimated tokens")
