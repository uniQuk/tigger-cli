from __future__ import annotations
import pathlib
from functools import partial
from tigger.types import RunContext
from tigger.tools import ToolRegistry
from tigger.hooks import HookRegistry
from tigger.skills import AgentDef, SkillDef
from tigger.commands import misc, agent as agent_cmd, compact as compact_cmd, skills as skills_cmd
from tigger.commands import memory as mem_cmd
from tigger.commands import provider as provider_cmd


def load_builtin_commands(
    memory_path: pathlib.Path,
    config_path: pathlib.Path,
    skills: list[SkillDef],
    agents: list[AgentDef],
    registry: ToolRegistry,
    hooks: HookRegistry,
    provider_fn,
) -> dict:
    """Return a dict mapping command name → handler callable with (args, ctx) signature."""
    d: dict = {
        "clear":      misc.cmd_clear,
        "tokens":     misc.cmd_tokens,
        "model":      misc.cmd_model,
        "mode":       misc.cmd_mode,
        "permission": misc.cmd_permission,
        "memory":     partial(mem_cmd.cmd_memory, memory_path=memory_path),
        "remember":   partial(mem_cmd.cmd_remember, memory_path=memory_path),
        "compact":    partial(compact_cmd.cmd_compact, provider_fn=provider_fn),
        "skills":     partial(skills_cmd.cmd_skills, skills=skills),
        "agent":      partial(agent_cmd.cmd_agent, agents=agents, registry=registry, hooks=hooks, provider_fn=provider_fn),
        "provider":   partial(provider_cmd.cmd_provider, config_path=config_path),
    }
    d["help"] = partial(misc.cmd_help, commands=d, skills=skills)
    return d
