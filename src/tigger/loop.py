from __future__ import annotations

import os
import pathlib
import sys
import time
from collections.abc import Callable, Generator

from tigger.compaction import estimate_tokens, maybe_compact
from tigger.hooks import HookDef, evaluate_hooks
from tigger.permissions import check as permission_check
from tigger.tools import ToolRegistry
from tigger.types import (
    AssistantMessage,
    Message,
    PermissionRequest,
    RunContext,
    StreamProgress,
    TextChunk,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
    TurnDoneEvent,
)

Event = TextChunk | ToolStartEvent | ToolEndEvent | TurnDoneEvent | ThinkingEvent | StreamProgress
PermissionCallback = Callable[[PermissionRequest], bool]


def _active_mode_body(ctx: RunContext) -> str:
    """Return the body of the active mode, or empty string if not found."""
    for mode in ctx.modes:
        if mode.name == ctx.config.mode:
            return mode.body
    return ""


def _check_output_budget(tc, budget: int) -> str | None:
    """Return a formatted error string when *tc* busts *budget*, else None.

    Applies to write/edit tool calls. The check is per-call: each tool
    call gets its own fresh budget.
    """
    if budget <= 0:
        return None
    if tc.name == "write":
        content = tc.args.get("content")
        if isinstance(content, str) and len(content) > budget:
            path = tc.args.get("path", "<unknown>")
            return (
                f"Error: tool 'write' output exceeds the active output budget "
                f"({len(content)} > {budget} chars on field 'content'). "
                f"Write a small stub to '{path}' first, then use successive "
                f"'edit' calls to append the rest in chunks under {budget} "
                f"chars each. Do not retry this exact call — split the content."
            )
    elif tc.name == "edit":
        path = tc.args.get("path", "<unknown>")
        for field_name in ("new_string", "old_string"):
            val = tc.args.get(field_name)
            if isinstance(val, str) and len(val) > budget:
                return (
                    f"Error: tool 'edit' output exceeds the active output budget "
                    f"({len(val)} > {budget} chars on field '{field_name}'). "
                    f"Split the change into multiple smaller 'edit' calls on "
                    f"'{path}', each with payload fields under {budget} chars. "
                    f"Do not retry this exact call — split the content."
                )
    return None


def _lazy_tools_prompt_line(registry: ToolRegistry) -> str:
    """Build the per-turn prompt fragment listing lazy MCP tools by server.

    Returns "" when no lazy tools are registered, so eager-only sessions see no overhead.
    """
    lazy = registry.lazy_tools()
    if not lazy:
        return ""
    by_server: dict[str, list[str]] = {}
    for t in lazy:
        if t.name.startswith("mcp__"):
            rest = t.name[len("mcp__"):]
            if "__" in rest:
                server, tool = rest.split("__", 1)
            else:
                server, tool = "_unknown", rest
        else:
            server, tool = "_native", t.name
        by_server.setdefault(server, []).append(tool)
    lines = [
        f"Additional MCP tools available via mcp_promote('{server}'): {', '.join(tools)}"
        for server, tools in sorted(by_server.items())
    ]
    return "\n".join(lines)


def run(
    query: str,
    ctx: RunContext,
    registry: ToolRegistry,
    provider_fn: Callable,
    hook_defs: list[HookDef] | None = None,
    summaries_dir: pathlib.Path | None = None,
    permission_callback: PermissionCallback | None = None,
) -> Generator[Event, None, None]:
    """Drive a full multi-turn agent exchange. Yields events; mutates ctx.messages in place."""
    ctx.messages.append(Message(role="user", content=query))

    allowed = set(ctx.allowed_tools) if ctx.allowed_tools is not None else None

    # Resolve the active per-call output budget for write/edit tool args.
    # Per-execution-context value (set by run_forked from the active skill)
    # wins; falls back to the workspace default. 0 disables the gate.
    active_output_budget = (
        ctx.output_budget
        if ctx.output_budget is not None
        else ctx.config.output_budget_default
    )

    retries = 0
    max_retries = ctx.config.max_retries
    continuations = 0
    max_continuations = 3  # cap auto-continue chain to avoid runaway loops

    # Opt-in per-turn perf logging — set TIGGER_PERF=1 (or a path) to enable.
    # Logs turn duration, token counts, and message-list size to stderr or a
    # file. Helps diagnose why long runs (e.g. chunked-write recoveries) are
    # slow: full-prompt reprocessing, compaction stalls, or model latency.
    perf_env = os.environ.get("TIGGER_PERF", "").strip()
    perf_log: object | None = None
    perf_path: pathlib.Path | None = None
    if perf_env:
        if perf_env in {"1", "true", "stderr"}:
            perf_log = sys.stderr
        else:
            perf_path = pathlib.Path(perf_env).expanduser()
            perf_path.parent.mkdir(parents=True, exist_ok=True)
        if perf_log is None and perf_path is not None and not perf_path.exists():
            perf_path.write_text(
                "ts\tturn\twall_s\tcompact_s\tinput_tokens\toutput_tokens\t"
                "msgs\tprompt_chars\tfinish_reason\ttool_calls\tcontinuations\t"
                "delta_chars\ttokens_per_sec\tcache_hit_estimate\n"
            )
    perf_turn = 0
    # Cross-turn state for the new perf columns. Both start at 0 so the first
    # turn reports delta_chars == prompt_chars and cache_hit_estimate == 0
    # (no prior turn to compare against).
    last_prompt_chars = 0
    last_input_tokens = 0

    while True:
        turn_start = time.monotonic()
        compact_start = time.monotonic()
        ctx.messages, _ = maybe_compact(ctx.messages, ctx.config, provider_fn,
                                        summaries_dir=summaries_dir)
        compact_elapsed = time.monotonic() - compact_start

        tools_schemas = [
            s for s in registry.schemas()
            if allowed is None or s["function"]["name"] in allowed
        ]

        # System prompt stays bytewise stable across turns within a session.
        # Dynamic per-turn content (active mode body, lazy MCP tool listing)
        # is passed separately so the provider can inject it as an
        # <environment> tail message — keeping the prompt prefix cacheable.
        system = ctx.system_prompt
        env_parts: list[str] = []
        mode_body = _active_mode_body(ctx)
        if mode_body:
            env_parts.append(mode_body)
        lazy_line = _lazy_tools_prompt_line(registry)
        if lazy_line:
            env_parts.append(lazy_line)
        environment = "\n\n".join(env_parts) if env_parts else None
        # Pass `environment` as a keyword arg only when set, so non-tigger
        # callers of provider_fn (e.g. compaction.summarize_old) and test
        # fakes with the legacy 4-arg signature keep working unchanged.
        if environment is not None:
            stream = provider_fn(
                system, ctx.messages, tools_schemas, ctx.config,
                environment=environment,
            )
        else:
            stream = provider_fn(system, ctx.messages, tools_schemas, ctx.config)
        assistant_msg: AssistantMessage | None = None

        for chunk in stream:
            if isinstance(chunk, TextChunk):
                yield chunk
            elif isinstance(chunk, ThinkingEvent):
                yield chunk
            elif isinstance(chunk, StreamProgress):
                yield chunk
            elif isinstance(chunk, AssistantMessage):
                assistant_msg = chunk

        if assistant_msg is None:
            if retries >= max_retries:
                break
            retries += 1
            ctx.messages.append(Message(
                role="user",
                content="Your last response was empty. Please try again.",
            ))
            continue

        # Record assistant turn
        ctx.messages.append(Message(
            role="assistant",
            content=assistant_msg.content,
            tool_calls=assistant_msg.tool_calls,
        ))
        yield TurnDoneEvent(
            input_tokens=assistant_msg.input_tokens,
            output_tokens=assistant_msg.output_tokens,
        )

        if perf_env:
            perf_turn += 1
            wall = time.monotonic() - turn_start
            prompt_chars = sum(len(m.content) for m in ctx.messages)
            local_tokens = (
                assistant_msg.input_tokens
                if assistant_msg.input_tokens
                else estimate_tokens(ctx.messages)
            )
            # New per-turn metrics for KV-cache reuse diagnosis.
            delta_chars = prompt_chars - last_prompt_chars
            tokens_per_sec = assistant_msg.output_tokens / max(wall, 0.001)
            # Heuristic only: when input_tokens reported by the server stays
            # close across turns despite a growing prompt, prefix caching is
            # likely active. Documented caveat — wall_s remains authoritative.
            if perf_turn == 1 or local_tokens <= 0:
                cache_hit_estimate = 0.0
            else:
                fresh = max(local_tokens - last_input_tokens, 0)
                ratio = fresh / max(local_tokens, 1)
                cache_hit_estimate = max(0.0, min(1.0, 1.0 - ratio))
            row = (
                f"{int(time.time())}\t{perf_turn}\t{wall:.2f}\t"
                f"{compact_elapsed:.2f}\t{local_tokens}\t"
                f"{assistant_msg.output_tokens}\t{len(ctx.messages)}\t"
                f"{prompt_chars}\t{assistant_msg.finish_reason or '-'}\t"
                f"{len(assistant_msg.tool_calls)}\t{continuations}\t"
                f"{delta_chars}\t{tokens_per_sec:.2f}\t"
                f"{cache_hit_estimate:.3f}\n"
            )
            if perf_log is not None:
                perf_log.write(f"[perf] {row}")
                perf_log.flush()
            elif perf_path is not None:
                with perf_path.open("a") as f:
                    f.write(row)
            # Prefill-dominance warning: long wall time relative to output on
            # a small-delta turn signals the provider re-prefilled despite
            # little new prompt. Indicates broken prefix caching.
            if (
                wall / max(assistant_msg.output_tokens, 1) > 1.5
                and delta_chars < 4096
            ):
                sys.stderr.write(
                    f"[perf] prefill-dominant turn {perf_turn}: "
                    f"wall={wall:.1f}s out={assistant_msg.output_tokens}tok "
                    f"delta_chars={delta_chars}\n"
                )
                sys.stderr.flush()
            last_prompt_chars = prompt_chars
            last_input_tokens = local_tokens

        if not assistant_msg.tool_calls:
            # Auto-continue when the model was cut off mid-text by max_tokens.
            # Inject a synthetic user prompt and let the next turn pick up.
            if (
                assistant_msg.finish_reason == "length"
                and continuations < max_continuations
            ):
                continuations += 1
                ctx.messages.append(Message(
                    role="user",
                    content=(
                        "Your previous response was cut off by the output token "
                        "limit. Continue exactly where you left off — do not "
                        "repeat content already produced, do not summarise, do "
                        "not add preamble. Resume the next character."
                    ),
                ))
                continue
            break

        # Execute each tool call
        hallucinated = False
        truncated_call = False
        for tc in assistant_msg.tool_calls:
            tool = registry.get(tc.name)
            if tool is None:
                if retries >= max_retries:
                    break
                retries += 1
                available = ", ".join(t.name for t in registry.all())
                correction = (
                    f"You used unknown tool '{tc.name}'. Available: {available}."
                )
                ctx.messages.append(Message(role="user", content=correction))
                hallucinated = True
                break

            permitted = permission_check(
                tool,
                ctx.config.permission_mode,
                tc.args,
                bash_safe_prefixes=ctx.config.bash_safe_prefixes,
            )
            if not permitted:
                if permission_callback is not None:
                    permitted = permission_callback(
                        PermissionRequest(call_id=tc.call_id, name=tc.name, args=tc.args)
                    )

            if not permitted:
                yield ToolEndEvent(
                    call_id=tc.call_id, name=tc.name, output="(denied)", permitted=False,
                )
                ctx.messages.append(Message(
                    role="tool",
                    content="(tool call denied by user)",
                    tool_call_id=tc.call_id,
                    name=tc.name,
                ))
                continue

            # Declarative hooks (PreToolUse) — block/warn/transform before execution
            pre_hook_feedback: list[str] = []
            if hook_defs:
                _hook_ctx = {"tool_name": tc.name, "tool_args": tc.args}
                _hook_result = evaluate_hooks("PreToolUse", _hook_ctx, hook_defs)
                for msg in _hook_result.messages:
                    print(f"[hook] {msg}")
                if _hook_result.blocked:
                    block_content = "(tool call blocked by hook)"
                    if _hook_result.feedback:
                        block_content += "\n\n" + "\n\n".join(_hook_result.feedback)
                    yield ToolEndEvent(
                        call_id=tc.call_id, name=tc.name,
                        output="(blocked by hook)", permitted=False,
                    )
                    ctx.messages.append(Message(
                        role="tool",
                        content=block_content,
                        tool_call_id=tc.call_id,
                        name=tc.name,
                    ))
                    continue
                pre_hook_feedback = _hook_result.feedback
                # Re-validate permissions if a transform hook mutated the args.
                if _hook_result.transformed:
                    re_permitted = permission_check(
                        tool,
                        ctx.config.permission_mode,
                        tc.args,
                        bash_safe_prefixes=ctx.config.bash_safe_prefixes,
                    )
                    if not re_permitted and permission_callback is not None:
                        re_permitted = permission_callback(
                            PermissionRequest(call_id=tc.call_id, name=tc.name, args=tc.args)
                        )
                    if not re_permitted:
                        yield ToolEndEvent(
                    call_id=tc.call_id, name=tc.name, output="(denied)", permitted=False,
                )
                        ctx.messages.append(Message(
                            role="tool",
                            content="(tool call denied by user)",
                            tool_call_id=tc.call_id,
                            name=tc.name,
                        ))
                        continue

            # Output-budget gate: reject oversized write/edit payloads before
            # touching the filesystem. The model gets a structured retry hint
            # pointing at the stub-then-edit pattern.
            budget_error = _check_output_budget(tc, active_output_budget)
            if budget_error is not None:
                yield ToolEndEvent(
                    call_id=tc.call_id, name=tc.name,
                    output=budget_error, error=True,
                )
                ctx.messages.append(Message(
                    role="tool",
                    content=budget_error,
                    tool_call_id=tc.call_id,
                    name=tc.name,
                ))
                continue

            yield ToolStartEvent(call_id=tc.call_id, name=tc.name, args=tc.args)
            result = registry.execute(tc.name, tc.args, tc.parse_error_bytes)
            end_event = ToolEndEvent(
                call_id=tc.call_id, name=tc.name, output=result.output,
                error=result.error,
            )

            # Declarative hooks (PostToolUse) — warn after execution
            post_hook_feedback: list[str] = []
            if hook_defs:
                _post_ctx = {"tool_name": tc.name, "tool_args": tc.args}
                _post_result = evaluate_hooks("PostToolUse", _post_ctx, hook_defs)
                for msg in _post_result.messages:
                    print(f"[hook] {msg}")
                post_hook_feedback = _post_result.feedback

            yield end_event

            tool_content = end_event.output
            all_feedback = pre_hook_feedback + post_hook_feedback
            if all_feedback:
                tool_content += "\n\n" + "\n\n".join(all_feedback)
            ctx.messages.append(Message(
                role="tool",
                content=tool_content,
                tool_call_id=tc.call_id,
                name=tc.name,
            ))

            if tc.parse_error_bytes is not None:
                truncated_call = True

        if hallucinated:
            yield ThinkingEvent()
            continue

        # If any tool call was cut off mid-stream by max_tokens, nudge the
        # model toward a chunked-write strategy. Bounded by the same
        # continuations cap as the text-truncation path.
        if truncated_call and continuations < max_continuations:
            continuations += 1
            ctx.messages.append(Message(
                role="user",
                content=(
                    "One of your tool calls was cut off by the output token "
                    "limit before its arguments finished streaming. Do not "
                    "retry the same large call. Instead: for new files, "
                    "write a small stub first (e.g. an empty skeleton), then "
                    "append the rest in successive `edit` calls. For existing "
                    "files, use `edit` with targeted replacements rather than "
                    "rewriting the whole file. Continue from where you left off."
                ),
            ))

        # normal round: loop back for model to process tool results
        yield ThinkingEvent()

    ctx.turn += 1


def run_forked(
    query: str,
    skill,                          # SkillDef — imported lazily to avoid circular
    ctx: RunContext,
    registry: ToolRegistry,
    provider_fn: Callable | None,
    hook_defs: list[HookDef] | None = None,
    permission_callback: PermissionCallback | None = None,
    agent=None,                     # AgentDef — when set, overrides system prompt + tools
) -> Generator[Event, None, None]:
    """Run *query* in a forked context (isolated message history, depth+1). Yields events.

    When *agent* is provided, the forked context uses the agent's system prompt
    and tool list instead of inheriting from the parent. This gives skills a
    way to delegate to a focused, smaller-prompt sub-agent (much better
    KV-cache reuse on local models).
    """
    if ctx.depth >= ctx.config.max_depth:
        yield TextChunk(content=f"Error: max agent depth ({ctx.config.max_depth}) reached — cannot fork.")
        return

    # Tool restriction: agent wins, then skill, then no restriction.
    if agent is not None and agent.tools:
        allowed = list(agent.tools)
    elif skill.tools:
        allowed = list(skill.tools)
    else:
        allowed = None

    system_prompt = agent.system_prompt if agent is not None else ctx.system_prompt
    # Resolve the per-call output budget for the forked context. Skill
    # frontmatter wins; falls back to the workspace default when the skill
    # doesn't declare one. Agents do not override budget — skills own this.
    if skill.output_budget is not None:
        forked_budget: int | None = skill.output_budget
    else:
        forked_budget = ctx.config.output_budget_default
    forked = RunContext(
        config=ctx.config,
        messages=[],
        system_prompt=system_prompt,
        depth=ctx.depth + 1,
        allowed_tools=allowed,
        trust_level=ctx.trust_level,
        output_budget=forked_budget,
    )

    # Restrict registry to skill's tool list if specified
    if allowed:
        from tigger.tools import ToolRegistry as _TR
        sub_registry = _TR()
        for name in allowed:
            t = registry.get(name)
            if t:
                sub_registry.register(t)
    else:
        sub_registry = registry

    if provider_fn is None:
        yield TextChunk(content="(no provider available for forked skill)")
        return

    yield from run(query, forked, sub_registry, provider_fn=provider_fn,
                   hook_defs=hook_defs, summaries_dir=None,
                   permission_callback=permission_callback)
