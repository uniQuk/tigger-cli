from __future__ import annotations
import dataclasses
from newcli.types import RunContext
from newcli.skills import AgentDef, SkillDef
from newcli.loop import run_forked
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

    agent_config = dataclasses.replace(ctx.config, model=agent.model or ctx.config.model)
    agent_ctx = RunContext(
        config=agent_config,
        messages=[],
        system_prompt=agent.system_prompt,
        depth=ctx.depth + 1,
        allowed_tools=agent.tools or None,
    )
    dummy_skill = SkillDef(name=agent_name, triggers=[], tools=agent.tools, context="fork", body="")
    result = run_forked(query, dummy_skill, ctx, registry, hooks, provider_fn)
    print(result)
