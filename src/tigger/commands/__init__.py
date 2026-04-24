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
from tigger.commands import summary as summary_cmd
from tigger.commands import init as init_cmd
from tigger.commands import rtk as rtk_cmd


COMMAND_DESCRIPTIONS: dict[str, str] = {
    "clear": "Clear message history",
    "tokens": "Show token usage",
    "model": "Switch model or provider",
    "mode": "Switch mode (ask/plan)",
    "permission": "Set permission mode",
    "memory": "View, search, or delete memory entries",
    "remember": "Save a note to memory",
    "compact": "Compact conversation history",
    "skills": "List loaded skills",
    "agent": "Run or list agents",
    "provider": "Manage providers",
    "summary": "Save session summary to markdown",
    "init": "Scaffold project files in .tigger/",
    "rtk": "RTK token optimization (on/off/gain)",
    "help": "Show this help",
}

COMMAND_HELP: dict[str, str] = {
    "model": "Usage:\n  /model              — interactive picker\n  /model <name>       — switch by model name\n  /model prov/model   — switch by provider/model",
    "mode": "Usage: /mode <ask|plan>\n  ask  — normal conversation\n  plan — write plan before executing",
    "permission": "Usage: /permission <ask|allow|bypass>",
    "memory": "Usage:\n  /memory             — list all entries\n  /memory search <q>  — search entries\n  /memory delete <n>  — delete entry by number\n  /memory clear       — delete all entries",
    "compact": "Usage: /compact\n  Force compaction of conversation history.",
    "agent": "Usage:\n  /agent             — list available agents\n  /agent <name> <q>  — run agent with query\n\nAgents are defined in .tigger/agents.md using YAML frontmatter:\n\n  ---\n  name: my-agent\n  tools: [read, glob, grep]\n  ---\n  System prompt for the agent.",
    "provider": "Usage:\n  /provider           — list providers\n  /provider add       — add a new provider",
    "summary": "Usage: /summary\n  Save a structured summary of the current session to .tigger/summaries/.",
    "init": "Usage: /init\n  Create template files in .tigger/: agents.md, system.md, hooks.py, skills/.\n  Existing files are never overwritten.",
    "rtk": "Usage:\n  /rtk              — show RTK status\n  /rtk on           — enable RTK proxy\n  /rtk off          — disable RTK proxy\n  /rtk gain         — show token savings\n  /rtk gain --history — show command savings history\n\nRTK (Rust Token Killer) proxies shell commands to reduce token output by 60-90%.\nhttps://github.com/rtk-ai/rtk",
    "help": "Usage: /help [command]\n  Show help for a specific command, or list all commands.",
}


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
        "summary":    partial(summary_cmd.cmd_summary, tigger_dir=memory_path.parent, provider_fn=provider_fn),
        "init":       init_cmd.cmd_init,
        "rtk":        rtk_cmd.cmd_rtk,
    }
    d["help"] = partial(misc.cmd_help, commands=d, skills=skills)
    return d
