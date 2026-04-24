from __future__ import annotations
import functools
import pathlib
from typing import Callable, Generator
from tigger.types import (
    Config, RunContext, Message, ToolCallRecord, AssistantMessage,
    TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent, TurnDoneEvent,
    ThinkingEvent,
)
from tigger.tools import ToolRegistry
from tigger.hooks import HookRegistry, run_before, run_after
from tigger.permissions import check as permission_check
from tigger.compaction import maybe_compact

Event = TextChunk | ToolStartEvent | ToolEndEvent | PermissionEvent | TurnDoneEvent | ThinkingEvent

_ASSETS_DIR = pathlib.Path(__file__).parent / "assets"


@functools.lru_cache(maxsize=1)
def _load_plan_mode_text() -> str:
    """Load plan-mode prompt text from the packaged asset file."""
    plan_mode_path = _ASSETS_DIR / "plan_mode.md"
    if not plan_mode_path.exists():
        raise FileNotFoundError(
            f"Missing plan-mode asset: {plan_mode_path}. "
            "This file should be packaged with tigger-code."
        )
    return plan_mode_path.read_text().strip()


def run(
    query: str,
    ctx: RunContext,
    registry: ToolRegistry,
    hooks: HookRegistry,
    provider_fn: Callable,
) -> Generator[Event, None, None]:
    """Drive a full multi-turn agent exchange. Yields events; mutates ctx.messages in place."""
    ctx.messages.append(Message(role="user", content=query))

    allowed = set(ctx.allowed_tools) if ctx.allowed_tools is not None else None

    retries = 0
    max_retries = ctx.config.max_retries

    while True:
        ctx.messages, _ = maybe_compact(ctx.messages, ctx.config, provider_fn)

        tools_schemas = [
            s for s in registry.schemas()
            if allowed is None or s["function"]["name"] in allowed
        ]

        system = ctx.system_prompt
        if ctx.config.mode == "plan":
            system += "\n\n" + _load_plan_mode_text()
        stream = provider_fn(system, ctx.messages, tools_schemas, ctx.config)
        assistant_msg: AssistantMessage | None = None

        for chunk in stream:
            if isinstance(chunk, TextChunk):
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

            tc = run_before(tc, ctx, hooks)
            yield ToolStartEvent(call_id=tc.call_id, name=tc.name, args=tc.args)
            output = registry.execute(tc.name, tc.args)
            end_event = ToolEndEvent(
                call_id=tc.call_id, name=tc.name, output=output,
                error=output.startswith("Error:"),
            )
            end_event = run_after(end_event, ctx, hooks)
            yield end_event

            ctx.messages.append(Message(
                role="tool",
                content=end_event.output,
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
    hooks: HookRegistry,
    provider_fn: Callable | None,
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
    for event in run(query, forked, sub_registry, hooks, provider_fn=provider_fn):
        if isinstance(event, TextChunk):
            result_parts.append(event.content)

    return "".join(result_parts)
