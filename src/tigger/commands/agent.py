from __future__ import annotations
import dataclasses
from newcli.types import RunContext
from newcli.skills import AgentDef
from newcli.tools import ToolRegistry
from newcli.hooks import HookRegistry


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
        from newcli.tools import ToolRegistry as _TR
        sub_registry = _TR()
        for name in agent.tools:
            t = registry.get(name)
            if t:
                sub_registry.register(t)
    else:
        sub_registry = registry

    from newcli.loop import run
    from newcli.types import TextChunk
    result_parts = []
    for event in run(query, agent_ctx, sub_registry, hooks, provider_fn=provider_fn):
        if isinstance(event, TextChunk):
            result_parts.append(event.content)
    print("".join(result_parts))
