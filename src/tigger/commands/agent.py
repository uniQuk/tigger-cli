from __future__ import annotations
import dataclasses
from tigger.types import Message, RunContext
from tigger.skills import AgentDef
from tigger.tools import ToolRegistry
from tigger.hooks import HookRegistry


def cmd_agent(
    args: str,
    ctx: RunContext,
    agents: list[AgentDef],
    registry: ToolRegistry,
    hooks: HookRegistry,
    provider_fn,
) -> None:
    parts = args.strip().split(maxsplit=1)
    if len(parts) < 2:
        print("Usage: /agent <name> <query>")
        return
    agent_name, query = parts
    agent = next((a for a in agents if a.name == agent_name), None)
    if agent is None:
        names = [a.name for a in agents]
        print(f"Unknown agent '{agent_name}'. Available: {names}")
        return

    if ctx.depth >= ctx.config.max_depth:
        print(f"Error: max agent depth ({ctx.config.max_depth}) reached.")
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
    for event in run(query, agent_ctx, sub_registry, hooks, provider_fn=provider_fn):
        if isinstance(event, TextChunk):
            result_parts.append(event.content)
    result = "".join(result_parts)
    print(result)
    ctx.messages.append(Message(
        role="user",
        content=f"[Agent result from {agent_name}]:\n{result}",
    ))
