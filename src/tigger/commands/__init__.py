from __future__ import annotations
import pathlib
import sys
from functools import partial
from tigger.types import RunContext
from tigger.tools import ToolRegistry
from tigger.hooks import HookDef
from tigger.skills import AgentDef, ModeRef, SkillDef
from tigger.commands import misc, agent as agent_cmd, compact as compact_cmd, skills as skills_cmd
from tigger.commands import memory as mem_cmd
from tigger.commands import provider as provider_cmd
from tigger.commands import summary as summary_cmd
from tigger.commands import init as init_cmd
from tigger.commands import rtk as rtk_cmd
from tigger.commands import status as status_cmd


COMMAND_DESCRIPTIONS: dict[str, str] = {
    "clear": "Clear message history",
    "tokens": "Show token usage",
    "model": "Switch model or provider",
    "mode": "Switch mode (act/plan/...)",
    "permission": "Set permission mode",
    "memory": "View, search, or delete memory entries",
    "remember": "Save a note to memory",
    "compact": "Compact conversation history",
    "skills": "List or preview loaded skills",
    "agent": "Run or list agents",
    "provider": "Manage providers",
    "summary": "Save session summary to markdown",
    "init": "Scaffold project files in .tigger/",
    "rtk": "RTK token optimization (on/off/gain)",
    "status": "Show resolved runtime configuration",
    "help": "Show this help",
}

COMMAND_HELP: dict[str, str] = {
    "skills": "Usage:\n  /skills              — list loaded skills\n  /skills preview <n>  — show fully rendered prompt for a skill",
    "model": "Usage:\n  /model              — interactive picker\n  /model <name>       — switch by model name\n  /model prov/model   — switch by provider/model",
    "mode": "Usage: /mode [name]\n  Show current mode and available modes, or switch to a mode by name.\n  Modes are loaded from .tigger/modes/ directories.",
    "permission": "Usage: /permission <ask|allow|bypass>",
    "memory": "Usage:\n  /memory             — list all entries\n  /memory search <q>  — search entries\n  /memory delete <n>  — delete entry by number\n  /memory clear       — delete all entries",
    "compact": "Usage: /compact\n  Force compaction of conversation history.",
    "agent": "Usage:\n  /agent             — list available agents\n  /agent <name> <q>  — run agent with query\n\nAgents are defined in .tigger/agents.md using YAML frontmatter:\n\n  ---\n  name: my-agent\n  tools: [read, glob, grep]\n  ---\n  System prompt for the agent.",
    "provider": "Usage:\n  /provider           — list providers\n  /provider add       — add a new provider",
    "summary": "Usage: /summary\n  Save a structured summary of the current session to .tigger/summaries/.",
    "init": "Usage: /init [--global]\n  Create template files in .tigger/: system.md, skills/, agents/, hooks/, modes/.\n  --global  Scaffold ~/.tigger/ instead of the project directory.\n  Existing files are never overwritten.",
    "rtk": "Usage:\n  /rtk                  — show RTK status\n  /rtk on               — enable RTK proxy\n  /rtk off              — disable RTK proxy\n  /rtk gain             — show project token savings\n  /rtk gain --history   — per-command savings history\n  /rtk gain --graph     — daily savings graph\n\nRTK (Rust Token Killer) proxies shell commands to reduce token output by 60-90%.\n/rtk gain is scoped to the current project by default.\nhttps://github.com/rtk-ai/rtk",
    "status": "Usage: /status\n  Print the resolved runtime configuration: config path, provider/model,\n  loaded skills (with tier annotations), agents, and active hooks.",
    "help": "Usage: /help [command] [--all]\n  Show help for a specific command, or list all commands.\n  --all  Include internal (bundled) skills and agents.",
}


def load_builtin_commands(
    memory_path: pathlib.Path,
    config_path: pathlib.Path,
    skills: list[SkillDef],
    agents: list[AgentDef],
    registry: ToolRegistry,
    provider_fn,
    summary_dir: pathlib.Path | None = None,
    modes: list[ModeRef] | None = None,
    hook_defs: list[HookDef] | None = None,
) -> dict:
    """Return a dict mapping command name → handler callable with (args, ctx) signature."""
    if modes is None:
        modes = []
    if hook_defs is None:
        hook_defs = []
    d: dict = {
        "clear":      misc.cmd_clear,
        "tokens":     misc.cmd_tokens,
        "model":      misc.cmd_model,
        "mode":       partial(misc.cmd_mode, modes=modes),
        "permission": misc.cmd_permission,
        "memory":     partial(mem_cmd.cmd_memory, memory_path=memory_path),
        "remember":   partial(mem_cmd.cmd_remember, memory_path=memory_path),
        "compact":    partial(compact_cmd.cmd_compact, provider_fn=provider_fn,
                             summaries_dir=(summary_dir / "summaries") if summary_dir else None),
        "skills":     partial(skills_cmd.cmd_skills, skills=skills),
        "agent":      partial(agent_cmd.cmd_agent, agents=agents, registry=registry, provider_fn=provider_fn, hook_defs=hook_defs),
        "provider":   partial(provider_cmd.cmd_provider, config_path=config_path),
        "summary":    partial(summary_cmd.cmd_summary, tigger_dir=summary_dir or memory_path.parent, provider_fn=provider_fn),
        "init":       init_cmd.cmd_init,
        "rtk":        partial(rtk_cmd.cmd_rtk, hook_defs=hook_defs),
        "status":     partial(status_cmd.cmd_status, config_path=config_path, skills=skills, agents=agents, hook_defs=hook_defs, memory_path=memory_path),
    }

    # Register dynamic mode commands: /<mode_name> switches to that mode
    def _switch_mode(args: str, ctx, *, mode_name: str, modes_list: list):
        misc.cmd_mode(mode_name, ctx, modes=modes_list)

    for mode in modes:
        if mode.name in d:
            print(
                f"Warning: mode {mode.name!r} collides with built-in command; "
                f"use /mode {mode.name} instead",
                file=sys.stderr,
            )
            continue
        d[mode.name] = partial(_switch_mode, mode_name=mode.name, modes_list=modes)
        COMMAND_DESCRIPTIONS[mode.name] = f"Switch to {mode.name} mode"

    d["help"] = partial(misc.cmd_help, commands=d, skills=skills, agents=agents)
    return d
