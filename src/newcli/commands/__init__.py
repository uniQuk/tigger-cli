from __future__ import annotations
import pathlib
from newcli.types import RunContext
from newcli.tools import ToolRegistry
from newcli.hooks import HookRegistry
from newcli.skills import AgentDef, SkillDef
from newcli.commands import misc, agent as agent_cmd, compact as compact_cmd, skills as skills_cmd
from newcli.commands import memory as mem_cmd


def load_builtin_commands(
    memory_path: pathlib.Path,
    skills: list[SkillDef],
    agents: list[AgentDef],
    registry: ToolRegistry,
    hooks: HookRegistry,
    provider_fn,
) -> dict:
    """Return a dict mapping command name → handler callable with (args, ctx) signature."""
    d: dict = {}
    d.update({
        "clear":      lambda args, ctx: misc.cmd_clear(args, ctx),
        "tokens":     lambda args, ctx: misc.cmd_tokens(args, ctx),
        "model":      lambda args, ctx: misc.cmd_model(args, ctx),
        "mode":       lambda args, ctx: misc.cmd_mode(args, ctx),
        "permission": lambda args, ctx: misc.cmd_permission(args, ctx),
        "memory":     lambda args, ctx: mem_cmd.cmd_memory(args, ctx, memory_path),
        "remember":   lambda args, ctx: mem_cmd.cmd_remember(args, ctx, memory_path),
        "compact":    lambda args, ctx: compact_cmd.cmd_compact(args, ctx, provider_fn),
        "skills":     lambda args, ctx: skills_cmd.cmd_skills(args, ctx, skills),
        "agent":      lambda args, ctx: agent_cmd.cmd_agent(args, ctx, agents, registry, hooks, provider_fn),
    })
    d["help"] = lambda args, ctx: misc.cmd_help(args, ctx, commands=d, skills=skills)
    return d
