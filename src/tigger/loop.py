from __future__ import annotations

import copy
import os
import pathlib
import sys
import threading
import time
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor

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

# Cap on parallel tool dispatch. Bounded to keep filesystem/io load reasonable
# on local model boxes that often share CPU with the inference engine. Tunable
# via TIGGER_PARALLEL_TOOLS env if you want to experiment without a code edit.
_PARALLEL_TOOL_WORKERS = max(
    1, int(os.environ.get("TIGGER_PARALLEL_TOOLS", "4"))
)

# Stall-detection: if no streaming chunk arrives for this long, print a
# heartbeat to stderr so the user can tell tigger from the model getting
# stuck. 0 disables. Tunable per-session without a code edit.
_STALL_HEARTBEAT_SECS = max(
    0, int(os.environ.get("TIGGER_STALL_SECS", "60"))
)

# Default hard ceiling for large string tool arguments. This is intentionally
# below many model max_tokens settings: local OpenAI-compatible servers often
# buffer function-call arguments internally, so one huge write/edit can look
# silent for many minutes and then be rejected. Keep chunks small unless the
# user deliberately opts into bigger tool args.
_TOOL_ARG_BUDGET_CAP = max(
    1024, int(os.environ.get("TIGGER_TOOL_ARG_BUDGET", "4096"))
)


class _StallWatchdog:
    """Daemon-thread watchdog that prints a heartbeat when the model goes
    silent for too long. Reset() on each streaming chunk.

    Local OpenAI-compatible servers can hang silently — the HTTP connection
    stays open but no chunks arrive. Without this, tigger looks identical
    to a healthy slow turn. The watchdog flips that back into observable
    user-facing output.
    """

    def __init__(self, label: str, interval: int) -> None:
        self._label = label
        self._interval = interval
        self._last = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._interval <= 0:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def reset(self) -> None:
        self._last = time.monotonic()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)

    def _run(self) -> None:
        # Only escalate the message past this threshold — short silences are
        # normal for thinking models that buffer the <think> block server-side.
        loud_after = 180
        while not self._stop.wait(self._interval):
            silent = time.monotonic() - self._last
            if silent < self._interval:
                continue
            if silent >= loud_after:
                sys.stderr.write(
                    f"… still waiting on the model ({silent:.0f}s, "
                    f"{self._label}). Ctrl-C to abort.\n"
                )
            else:
                sys.stderr.write(
                    f"… still thinking ({silent:.0f}s, {self._label})\n"
                )
            sys.stderr.flush()

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


def _effective_output_budget(configured_budget: int, max_tokens: int) -> int:
    """Return the per-call write/edit char budget for this run.

    A large skill budget is only useful when the provider also has enough
    completion budget to emit the JSON tool call. With small max_tokens values,
    especially local Qwen tool-call streams, overlarge write payloads burn an
    entire generation and arrive as empty/truncated arguments. Cap the accepted
    payload below the model output budget so the loop forces chunking earlier.
    """
    if configured_budget <= 0:
        return configured_budget
    caps = [configured_budget, _TOOL_ARG_BUDGET_CAP]
    if max_tokens > 0:
        caps.append(max_tokens)
    return min(caps)


def _with_output_budget_schema_limits(schemas: list[dict], budget: int) -> list[dict]:
    """Return tool schemas with maxLength applied to large write/edit fields."""
    if budget <= 0:
        return schemas
    out: list[dict] = []
    for schema in schemas:
        fn = schema.get("function", {})
        name = fn.get("name")
        if name not in {"write", "edit"}:
            out.append(schema)
            continue
        new_schema = copy.deepcopy(schema)
        props = (
            new_schema
            .get("function", {})
            .get("parameters", {})
            .get("properties", {})
        )
        if name == "write" and isinstance(props.get("content"), dict):
            props["content"]["maxLength"] = budget
            props["content"]["description"] = (
                f"File content to write. Must be <= {budget} characters; "
                "for larger files write a small stub with anchors, then edit "
                "one section at a time."
            )
        elif name == "edit":
            for field_name in ("old_string", "new_string"):
                if isinstance(props.get(field_name), dict):
                    props[field_name]["maxLength"] = budget
            if isinstance(props.get("new_string"), dict):
                props["new_string"]["description"] = (
                    f"Replacement text. Must be <= {budget} characters; split "
                    "larger changes into multiple targeted edits."
                )
        out.append(new_schema)
    return out


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


def _can_parallelize_tools(
    tool_calls,
    registry: ToolRegistry,
    ctx: RunContext,
    hook_defs: list[HookDef] | None,
) -> bool:
    """Return True when a batch of tool calls can be safely run in parallel.

    Conservative gate: every call must be resolvable, read-only, free of
    parse-truncation errors, and already permitted under the current mode
    without a callback prompt. Hooks force serial execution because PreToolUse
    transforms must apply in order and PostToolUse may have ordering side
    effects (logs, counters). The single-call case is also serial — there's
    nothing to overlap.
    """
    if len(tool_calls) < 2:
        return False
    if hook_defs:
        return False
    for tc in tool_calls:
        if tc.parse_error_bytes is not None:
            return False
        tool = registry.get(tc.name)
        if tool is None or not tool.read_only:
            return False
        if not permission_check(
            tool,
            ctx.config.permission_mode,
            tc.args,
            bash_safe_prefixes=ctx.config.bash_safe_prefixes,
        ):
            return False
    return True


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
    active_output_budget = _effective_output_budget(
        active_output_budget,
        ctx.config.max_tokens,
    )

    # Build an effective Config that merges any skill-level chat_template_kwargs
    # override on top of the workspace defaults. Done once per run() — Config
    # is frozen and the override is fixed for the duration of the skill fork.
    effective_config = ctx.config
    if ctx.chat_template_kwargs:
        from dataclasses import replace as _dc_replace
        merged = {
            **(ctx.config.chat_template_kwargs or {}),
            **ctx.chat_template_kwargs,
        }
        effective_config = _dc_replace(ctx.config, chat_template_kwargs=merged)

    retries = 0
    max_retries = ctx.config.max_retries
    continuations = 0
    max_continuations = 3  # cap auto-continue chain (text length-cutoff)
    # Tool-call cutoff recovery is capped separately — the failure mode is
    # different from text-length cutoffs. When the model's tool-arg stream
    # gets dropped (LM Studio q4 quants do this), one nudge is plenty; if it
    # fails twice the model is thrashing and the user needs to intervene.
    tool_cutoff_continuations = 0
    max_tool_cutoff_continuations = 1
    recovering_from_tool_cutoff = False

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
        # One-shot caveat about cache_hit_estimate. Most local OpenAI-compatible
        # servers (vLLM, SGLang, LM Studio) report `prompt_tokens` as the full
        # prefill count regardless of how many tokens were served from the
        # prefix cache, which makes our delta-based heuristic unreliable.
        # Treat `wall_s / output_tokens` and the `[perf] prefill-dominant`
        # warning as the authoritative signals.
        sys.stderr.write(
            "[perf] note: cache_hit_estimate is heuristic — local OpenAI-compatible "
            "servers report full prompt_tokens regardless of prefix-cache hits. "
            "Trust wall_s/output_tokens and prefill-dominant warnings.\n"
        )
        sys.stderr.flush()
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
        ctx.messages, compact_result = maybe_compact(
            ctx.messages, ctx.config, provider_fn, summaries_dir=summaries_dir,
        )
        compact_elapsed = time.monotonic() - compact_start
        # Surface compaction so users notice their context just shrank. The
        # stall-watchdog pattern (plain stderr) keeps this UI-agnostic.
        if compact_result.summarized > 0:
            n = compact_result.summarized
            sys.stderr.write(
                f"… compacted {n} message{'s' if n != 1 else ''} "
                f"({compact_result.tokens_before:,} → "
                f"{compact_result.tokens_after:,} tokens)\n"
            )
            sys.stderr.flush()

        tools_schemas = [
            s for s in registry.schemas()
            if allowed is None or s["function"]["name"] in allowed
        ]
        tools_schemas = _with_output_budget_schema_limits(
            tools_schemas,
            active_output_budget,
        )

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
        if active_output_budget > 0:
            env_parts.append(
                "Active write/edit payload budget: "
                f"{active_output_budget} chars per tool call. "
                "Keep write.content and edit old_string/new_string fields under "
                "this limit; use stub-then-edit for larger files."
            )
        environment = "\n\n".join(env_parts) if env_parts else None
        # Pass `environment` as a keyword arg only when set, so non-tigger
        # callers of provider_fn (e.g. compaction.summarize_old) and test
        # fakes with the legacy 4-arg signature keep working unchanged.
        if environment is not None:
            stream = provider_fn(
                system, ctx.messages, tools_schemas, effective_config,
                environment=environment,
            )
        else:
            stream = provider_fn(system, ctx.messages, tools_schemas, effective_config)
        assistant_msg: AssistantMessage | None = None

        watchdog = _StallWatchdog(
            label=f"turn {ctx.turn + 1}",
            interval=_STALL_HEARTBEAT_SECS,
        )
        watchdog.start()
        try:
            for chunk in stream:
                watchdog.reset()
                if isinstance(chunk, TextChunk):
                    yield chunk
                elif isinstance(chunk, ThinkingEvent):
                    yield chunk
                elif isinstance(chunk, StreamProgress):
                    yield chunk
                elif isinstance(chunk, AssistantMessage):
                    assistant_msg = chunk
        finally:
            watchdog.stop()

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
        wrote_target = False  # set when a successful `write` call lands this turn

        # Fast path: when every call in the batch is read-only, permitted
        # without a prompt, and free of hooks, dispatch in parallel via a
        # thread pool. This is the dominant pattern for local-model agent
        # turns that emit several `read`/`glob`/`grep` calls at once and is
        # the single biggest wall-time win when each tool waits on syscalls
        # rather than CPU. Falls through to the sequential path on any
        # disqualifying call (writes, bash, denied perms, hooks, truncation).
        if _can_parallelize_tools(
            assistant_msg.tool_calls, registry, ctx, hook_defs
        ):
            for tc in assistant_msg.tool_calls:
                yield ToolStartEvent(call_id=tc.call_id, name=tc.name, args=tc.args)
            workers = min(_PARALLEL_TOOL_WORKERS, len(assistant_msg.tool_calls))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [
                    ex.submit(
                        registry.execute, tc.name, tc.args, tc.parse_error_bytes
                    )
                    for tc in assistant_msg.tool_calls
                ]
                results = [f.result() for f in futures]
            for tc, result in zip(assistant_msg.tool_calls, results):
                yield ToolEndEvent(
                    call_id=tc.call_id, name=tc.name, output=result.output,
                    error=result.error,
                )
                ctx.messages.append(Message(
                    role="tool",
                    content=result.output,
                    tool_call_id=tc.call_id,
                    name=tc.name,
                ))
            yield ThinkingEvent()
            continue

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
            if tc.name == "write" and not result.error:
                wrote_target = True

        if hallucinated:
            yield ThinkingEvent()
            continue

        # If any tool call was cut off mid-stream by max_tokens, nudge the
        # model toward a chunked-write strategy. Capped tightly because two
        # consecutive truncations almost always mean the model is thrashing.
        if truncated_call:
            if tool_cutoff_continuations < max_tool_cutoff_continuations:
                tool_cutoff_continuations += 1
                recovering_from_tool_cutoff = True
                sys.stderr.write(
                    f"[loop] tool call truncated mid-stream — appending "
                    f"chunked-write hint and retrying "
                    f"({tool_cutoff_continuations}/{max_tool_cutoff_continuations}). "
                    f"If this happens twice in a row your provider is dropping "
                    f"tool-call deltas; consider switching quant or backend.\n"
                )
                sys.stderr.flush()
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
            else:
                sys.stderr.write(
                    "[loop] tool call truncated again after recovery — giving "
                    "up to avoid an infinite retry loop. Aborting this turn.\n"
                )
                sys.stderr.flush()
                break

        # Per-skill stop_after_write: end the run as soon as a `write` tool
        # call succeeds, before handing control back to the model. Prevents
        # post-write recovery loops where the model second-guesses its own
        # output and burns minutes re-reading or retrying. Tool results have
        # already been appended above, so the wire format remains valid for
        # any caller that re-uses ctx.messages.
        #
        # Exception: after a tool-call truncation, the recovery hint tells the
        # model to switch to stub-then-edit. In that recovery mode, the first
        # successful `write` is often only a skeleton; stopping there leaves a
        # partial artifact on disk. Let the model continue with edit chunks.
        if ctx.stop_after_write and wrote_target and not recovering_from_tool_cutoff:
            break

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
        chat_template_kwargs=skill.chat_template_kwargs,
        stop_after_write=skill.stop_after_write,
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
