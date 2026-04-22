# src/newcli/main.py
from __future__ import annotations
import pathlib, sys
from newcli.config import load_config, find_config
from newcli.types import RunContext
from newcli.tools import ToolRegistry, register_all
from newcli.hooks import load_hooks
from newcli.skills import load_skills, load_agents, match_skill
from newcli.memory import read_memory, format_for_prompt
from newcli.mcp import connect_all
from newcli.compaction import estimate_tokens
from newcli.loop import run, run_forked
from newcli.commands import load_builtin_commands
from newcli import provider as _provider
from newcli.types import TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent, TurnDoneEvent


def status_line(ctx: RunContext) -> str:
    used = estimate_tokens(ctx.messages)
    limit = ctx.config.context_limit
    return f"[{ctx.config.model} · {used}/{limit} tokens] "


def render_event(event, ctx: RunContext) -> None:
    if isinstance(event, TextChunk):
        print(event.content, end="", flush=True)
    elif isinstance(event, ToolStartEvent):
        print(f"\n[tool] {event.name}({event.args})", flush=True)
    elif isinstance(event, ToolEndEvent):
        status = "denied" if not event.permitted else ("error" if event.error else "ok")
        print(f"[tool] {event.name} → {status}: {event.output[:120]}", flush=True)
    elif isinstance(event, PermissionEvent):
        answer = input(f"\nAllow {event.name}({event.args})? [y/N] ").strip().lower()
        event.granted = answer == "y"
    elif isinstance(event, TurnDoneEvent):
        print()   # newline after streamed text


def _make_provider_fn(config):
    def provider_fn(system, messages, tools, cfg):
        return _provider.stream(system, messages, tools, cfg)
    return provider_fn


def startup(config_path: pathlib.Path | None = None):
    # 1. Find and load config
    if config_path is None:
        config_path = find_config(pathlib.Path.cwd())
    if config_path is None:
        print("Error: no .ai/config.json found. Create one in your project or ~/.ai/")
        sys.exit(1)

    ai_dir = config_path.parent
    config = load_config(config_path)

    # 2-4. Tool registry
    registry = ToolRegistry()
    register_all(registry)

    # 5. MCP
    connect_all(registry, ai_dir / "mcp.json")

    # 6. Hooks
    hooks = load_hooks(ai_dir / "hooks.py")

    # 7-8. Skills + agents
    skills = load_skills(ai_dir / "skills.md")
    agents = load_agents(ai_dir / "agents.md")

    # 9. System prompt
    memory_lines = read_memory(ai_dir / "memory.md")
    memory_section = format_for_prompt(memory_lines)
    system = f"You are a helpful AI agent.\n\n{memory_section}".strip()

    # 10. Context
    ctx = RunContext(config=config, messages=[], system_prompt=system)

    provider_fn = _make_provider_fn(config)

    commands = load_builtin_commands(
        memory_path=ai_dir / "memory.md",
        skills=skills,
        agents=agents,
        registry=registry,
        hooks=hooks,
        provider_fn=provider_fn,
    )

    return ctx, commands, skills, registry, hooks, provider_fn


def repl(ctx: RunContext, commands: dict, skills: list, registry, hooks, provider_fn) -> None:
    while True:
        try:
            line = input(status_line(ctx) + "> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break

        if not line:
            continue

        # Skill trigger check
        skill = match_skill(line, skills)
        if skill:
            if skill.context == "fork":
                query = skill.render(line)
                result = run_forked(query, skill, ctx, registry, hooks, provider_fn)
                print(result)
                continue
            else:
                line = skill.render(line)

        # Slash command
        if line.startswith("/"):
            name, _, args = line[1:].partition(" ")
            handler = commands.get(name)
            if handler:
                handler(args, ctx)
            else:
                print(f"Unknown command: /{name}. Type /help for list.")
            continue

        # Agent query
        for event in run(line, ctx, registry, hooks, provider_fn=provider_fn):
            render_event(event, ctx)


def main() -> None:
    ctx, commands, skills, registry, hooks, provider_fn = startup()
    repl(ctx, commands, skills, registry, hooks, provider_fn)


if __name__ == "__main__":
    main()
