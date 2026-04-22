# src/newcli/main.py
from __future__ import annotations
import dataclasses
import pathlib
import sys
from newcli.config import load_config, find_config
from newcli.types import RunContext, TrustLevel
from newcli.tools import ToolRegistry, register_all
from newcli.hooks import load_hooks
from newcli.skills import load_skills, load_agents, match_skill
from newcli.memory import read_memory, format_for_prompt
from newcli.mcp import connect_all
from newcli.compaction import estimate_tokens
from newcli.loop import run, run_forked
from newcli.commands import load_builtin_commands
from newcli import provider as _provider
from newcli import trust as _trust
from newcli import ui
from newcli.types import TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent, TurnDoneEvent


def _prompt(ctx: RunContext) -> str:
    used = estimate_tokens(ctx.messages)
    return (
        f"[{ctx.config.model} · {used}/{ctx.config.context_limit} tokens"
        f" · {ctx.config.mode}/{ctx.config.permission_mode}] > "
    )


def render_event(event, ctx: RunContext) -> None:
    if isinstance(event, TextChunk):
        print(event.content, end="", flush=True)
    elif isinstance(event, ToolStartEvent):
        ui.print_tool_start(event.name, event.args)
    elif isinstance(event, ToolEndEvent):
        status = "denied" if not event.permitted else ("error" if event.error else "ok")
        ui.print_tool_end(event.name, status, event.output)
    elif isinstance(event, PermissionEvent):
        event.granted = ui.ask_permission(event.name, event.args)
    elif isinstance(event, TurnDoneEvent):
        print()


def _make_provider_fn(config):
    def provider_fn(system, messages, tools, cfg):
        return _provider.stream(system, messages, tools, cfg)
    return provider_fn


def startup(config_path: pathlib.Path | None = None):
    # 1. Find and load config
    if config_path is None:
        config_path = find_config(pathlib.Path.cwd())
    if config_path is None:
        ui.print_error("no .ai/config.json found. Create one in your project or ~/.ai/")
        sys.exit(1)

    ai_dir = config_path.parent
    config = load_config(config_path)

    # 2. Workspace trust check
    cwd = pathlib.Path.cwd()
    trust_level = _trust.check_trust(cwd)
    if trust_level is None:
        choice = ui.ask_trust_prompt(cwd)
        if choice == "always":
            _trust.write_trusted(cwd, pathlib.Path.home() / ".ai" / "trusted_paths.json")
            trust_level = TrustLevel.ALWAYS
        elif choice == "session":
            trust_level = TrustLevel.SESSION
        else:
            trust_level = TrustLevel.READONLY

    # 3. Logo
    ui.print_logo()

    # 4. Tool registry
    registry = ToolRegistry()
    register_all(registry)

    # 5. MCP
    connect_all(registry, ai_dir / "mcp.json")

    # 6. Hooks
    hooks = load_hooks(ai_dir / "hooks.py")

    # 7-8. Skills + agents
    skills = load_skills(ai_dir / "skills.md")
    agents = load_agents(ai_dir / "agents.md")

    # 9. System prompt + memory
    memory_lines = read_memory(ai_dir / "memory.md")
    memory_section = format_for_prompt(memory_lines)
    system = f"You are a helpful AI agent.\n\n{memory_section}".strip()

    # 10. Context
    ctx = RunContext(config=config, messages=[], system_prompt=system, trust_level=trust_level)

    # 11. Restrict tools for read-only trust level
    if trust_level == TrustLevel.READONLY:
        ctx.allowed_tools = [t.name for t in registry.all() if t.read_only]

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
            line = input(_prompt(ctx)).strip()
        except (KeyboardInterrupt, EOFError):
            ui.print_info("\nBye.")
            break

        if not line:
            continue

        skill = match_skill(line, skills)
        if skill:
            if skill.context == "fork":
                query = skill.render(line)
                result = run_forked(query, skill, ctx, registry, hooks, provider_fn)
                print(result)
                continue
            else:
                line = skill.render(line)

        if line.startswith("/"):
            name, _, args = line[1:].partition(" ")
            handler = commands.get(name)
            if handler:
                handler(args, ctx)
            else:
                ui.print_error(f"Unknown command: /{name}. Type /help for list.")
            continue

        # Spinner wraps the wait for first event; stops as soon as first event arrives
        event_gen = run(line, ctx, registry, hooks, provider_fn=provider_fn)
        with ui.Spinner():
            first_event = next(event_gen, None)
        if first_event is not None:
            render_event(first_event, ctx)
        for event in event_gen:
            render_event(event, ctx)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="newcli")
    parser.add_argument("--mode", choices=["ask", "plan"], default=None)
    parser.add_argument("--permission", choices=["ask", "allow", "bypass"], dest="permission", default=None)
    parsed = parser.parse_args()

    ctx, commands, skills, registry, hooks, provider_fn = startup()

    if parsed.mode is not None:
        ctx.config = dataclasses.replace(ctx.config, mode=parsed.mode)
    if parsed.permission is not None:
        ctx.config = dataclasses.replace(ctx.config, permission_mode=parsed.permission)

    repl(ctx, commands, skills, registry, hooks, provider_fn)


if __name__ == "__main__":
    main()
