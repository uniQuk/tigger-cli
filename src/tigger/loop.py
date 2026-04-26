from __future__ import annotations

import pathlib
from collections.abc import Callable, Generator

from tigger.compaction import maybe_compact
from tigger.hooks import HookDef, evaluate_hooks
from tigger.permissions import check as permission_check
from tigger.tools import ToolRegistry
from tigger.types import (
    AssistantMessage,
    Message,
    PermissionRequest,
    RunContext,
    TextChunk,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
    TurnDoneEvent,
)

Event = TextChunk | ToolStartEvent | ToolEndEvent | TurnDoneEvent | ThinkingEvent
PermissionCallback = Callable[[PermissionRequest], bool]


def _active_mode_body(ctx: RunContext) -> str:
    """Return the body of the active mode, or empty string if not found."""
    for mode in ctx.modes:
        if mode.name == ctx.config.mode:
            return mode.body
    return ""


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

    retries = 0
    max_retries = ctx.config.max_retries
    continuations = 0
    max_continuations = 3  # cap auto-continue chain to avoid runaway loops

    while True:
        ctx.messages, _ = maybe_compact(ctx.messages, ctx.config, provider_fn,
                                        summaries_dir=summaries_dir)

        tools_schemas = [
            s for s in registry.schemas()
            if allowed is None or s["function"]["name"] in allowed
        ]

        system = ctx.system_prompt
        mode_body = _active_mode_body(ctx)
        if mode_body:
            system += "\n\n" + mode_body
        lazy_line = _lazy_tools_prompt_line(registry)
        if lazy_line:
            system += "\n\n" + lazy_line
        stream = provider_fn(system, ctx.messages, tools_schemas, ctx.config)
        assistant_msg: AssistantMessage | None = None

        for chunk in stream:
            if isinstance(chunk, TextChunk):
                yield chunk
            elif isinstance(chunk, ThinkingEvent):
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
) -> Generator[Event, None, None]:
    """Run *query* in a forked context (isolated message history, depth+1). Yields events."""
    if ctx.depth >= ctx.config.max_depth:
        yield TextChunk(content=f"Error: max agent depth ({ctx.config.max_depth}) reached — cannot fork.")
        return

    allowed = skill.tools if skill.tools else None
    forked = RunContext(
        config=ctx.config,
        messages=[],
        system_prompt=ctx.system_prompt,
        depth=ctx.depth + 1,
        allowed_tools=allowed,
        trust_level=ctx.trust_level,
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
