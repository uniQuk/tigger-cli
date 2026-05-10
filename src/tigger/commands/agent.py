from __future__ import annotations

import dataclasses

from tigger.skills import AgentDef
from tigger.tools import ToolRegistry
from tigger.types import Message, RunContext


def cmd_agent(
    args: str,
    ctx: RunContext,
    agents: list[AgentDef],
    registry: ToolRegistry,
    provider_fn,
    hook_defs: list | None = None,
) -> None:
    from tigger.ui import console

    parts = args.strip().split(maxsplit=1)
    if len(parts) < 2:
        console.print("[dim]Usage:[/dim] /agent <name> <query>")
        return
    agent_name, query = parts
    agent = next((a for a in agents if a.name == agent_name), None)
    if agent is None:
        names = [a.name for a in agents]
        console.print(
            f"[red]Unknown agent[/red] {agent_name!r}. "
            f"[dim]Available:[/dim] {', '.join(names) if names else '(none)'}"
        )
        return

    if ctx.depth >= ctx.config.max_depth:
        console.print(
            f"[red]Max agent depth ({ctx.config.max_depth}) reached.[/red]"
        )
        return

    agent_config = dataclasses.replace(ctx.config, model=agent.model or ctx.config.model)
    agent_ctx = RunContext(
        config=agent_config,
        messages=[],
        system_prompt=agent.system_prompt,
        depth=ctx.depth + 1,
        allowed_tools=agent.tools or None,
    )

    # Build sub-registry restricted to agent's tool list
    if agent.tools:
        from tigger.tools import ToolRegistry as _TR
        sub_registry = _TR()
        for name in agent.tools:
            t = registry.get(name)
            if t:
                sub_registry.register(t)
    else:
        sub_registry = registry

    from tigger.loop import run
    from tigger.types import TextChunk
    result_parts = []
    for event in run(query, agent_ctx, sub_registry, provider_fn=provider_fn, hook_defs=hook_defs):
        if isinstance(event, TextChunk):
            result_parts.append(event.content)
    result = "".join(result_parts)
    # Render the agent's reply through Markdown so it matches the assistant's
    # streamed output style instead of looking like a raw print().
    from rich.markdown import Markdown
    if result.strip():
        console.print(Markdown(result))
    ctx.messages.append(Message(
        role="user",
        content=f"[Agent result from {agent_name}]:\n{result}",
    ))
