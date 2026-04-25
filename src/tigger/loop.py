from __future__ import annotations
import pathlib
from typing import Callable, Generator
from tigger.types import (
    Config, RunContext, Message, ToolCallRecord, AssistantMessage,
    TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent, TurnDoneEvent,
    ThinkingEvent,
)
from tigger.tools import ToolRegistry
from tigger.hooks import HookDef, evaluate_hooks
from tigger.permissions import check as permission_check
from tigger.compaction import maybe_compact

Event = TextChunk | ToolStartEvent | ToolEndEvent | PermissionEvent | TurnDoneEvent | ThinkingEvent


def _active_mode_body(ctx: RunContext) -> str:
    """Return the body of the active mode, or empty string if not found."""
    for mode in ctx.modes:
        if mode.name == ctx.config.mode:
            return mode.body
    return ""


def run(
    query: str,
    ctx: RunContext,
    registry: ToolRegistry,
    provider_fn: Callable,
    hook_defs: list[HookDef] | None = None,
    summaries_dir: pathlib.Path | None = None,
) -> Generator[Event, None, None]:
    """Drive a full multi-turn agent exchange. Yields events; mutates ctx.messages in place."""
    ctx.messages.append(Message(role="user", content=query))

    allowed = set(ctx.allowed_tools) if ctx.allowed_tools is not None else None

    retries = 0
    max_retries = ctx.config.max_retries

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
            ctx.messages.append(Message(role="user", content="Your last response was empty. Please try again."))
            continue

        # Record assistant turn
        ctx.messages.append(Message(
            role="assistant",
            content=assistant_msg.content,
            tool_calls=assistant_msg.tool_calls,
        ))
        yield TurnDoneEvent(input_tokens=0, output_tokens=0)

        if not assistant_msg.tool_calls:
            break

        # Execute each tool call
        hallucinated = False
        for tc in assistant_msg.tool_calls:
            tool = registry.get(tc.name)
            if tool is None:
                if retries >= max_retries:
                    break
                retries += 1
                correction = f"You used unknown tool '{tc.name}'. Available: {[t.name for t in registry.all()]}."
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
                perm_event = PermissionEvent(call_id=tc.call_id, name=tc.name, args=tc.args)
                yield perm_event
                permitted = perm_event.granted

            if not permitted:
                yield ToolEndEvent(call_id=tc.call_id, name=tc.name, output="(denied)", permitted=False)
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

            yield ToolStartEvent(call_id=tc.call_id, name=tc.name, args=tc.args)
            output = registry.execute(tc.name, tc.args)
            end_event = ToolEndEvent(
                call_id=tc.call_id, name=tc.name, output=output,
                error=output.startswith("Error:"),
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

        if hallucinated:
            yield ThinkingEvent()
            continue
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
) -> str:
    """Run *query* in a forked context (isolated message history, depth+1). Returns result string."""
    if ctx.depth >= ctx.config.max_depth:
        return f"Error: max agent depth ({ctx.config.max_depth}) reached — cannot fork."

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
        return "(no provider available for forked skill)"

    result_parts = []
    for event in run(query, forked, sub_registry, provider_fn=provider_fn,
                      hook_defs=hook_defs, summaries_dir=None):
        if isinstance(event, TextChunk):
            result_parts.append(event.content)

    return "".join(result_parts)
