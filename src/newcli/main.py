# src/newcli/main.py
from __future__ import annotations
import dataclasses
import pathlib
import sys
import time
from newcli.config import load_config, find_config
from newcli.types import RunContext, TrustLevel
from newcli.tools import ToolRegistry, register_all
from newcli.hooks import load_hooks
from newcli.skills import load_skills, load_skills_dir, load_agents, match_skill
from newcli.memory import read_memory, format_for_prompt
from newcli.mcp import connect_all
from newcli.compaction import estimate_tokens
from newcli.loop import run, run_forked
from newcli.commands import load_builtin_commands
from newcli import provider as _provider
from newcli import trust as _trust
from newcli import ui
from newcli.types import TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent, TurnDoneEvent
from rich.markdown import Markdown


@dataclasses.dataclass
class StartupResult:
    ctx: RunContext
    commands: dict
    skills: list
    registry: object   # ToolRegistry
    hooks: object      # HookRegistry
    provider_fn: object  # Callable


def _prompt(ctx: RunContext) -> str:
    return "❯ "


def _fmt_args(args: dict) -> str:
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        sv = repr(v)
        if len(sv) > 60:
            sv = sv[:57] + "..."
        parts.append(f"{k}={sv}")
    return ", ".join(parts)


def _flush_text(text_buf: list[str]) -> None:
    """Render accumulated model text as Rich Markdown and clear the buffer."""
    if text_buf:
        ui.console.print(Markdown("".join(text_buf)))
        text_buf.clear()


def render_event(event, ctx: RunContext, output_chars: list[int], text_buf: list[str]) -> None:
    """Render one agent event to the terminal.

    ``output_chars`` is a 1-element mutable list accumulating character count.
    ``text_buf`` is a mutable list that collects TextChunk content; flushed as
    Rich Markdown before tool events and at turn end.
    """
    if isinstance(event, TextChunk):
        text_buf.append(event.content)
        output_chars[0] += len(event.content)
    elif isinstance(event, ToolStartEvent):
        _flush_text(text_buf)
        ui.console.print(f"\n[bold]⏺[/bold] [dim]{event.name}[/dim]({_fmt_args(event.args)})")
    elif isinstance(event, ToolEndEvent):
        # Only surface errors and denials — successful tool calls stay quiet.
        if not event.permitted:
            ui.console.print(f"  [dim]⎿[/dim]  [yellow](denied)[/yellow]")
        elif event.error:
            out = event.output[:120].replace("\n", " · ").rstrip(" · ")
            ui.console.print(f"  [dim]⎿[/dim]  [red]{out}[/red]")
    elif isinstance(event, PermissionEvent):
        event.granted = ui.ask_permission(event.name, event.args)
    elif isinstance(event, TurnDoneEvent):
        _flush_text(text_buf)
        print()


def startup(config_path: pathlib.Path | None = None) -> StartupResult:
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

    # 7-8. Skills + agents — prefer skills/ directory, fall back to skills.md
    skills_dir = ai_dir / "skills"
    if skills_dir.exists() and skills_dir.is_dir():
        skills = load_skills_dir(skills_dir)
    else:
        skills = load_skills(ai_dir / "skills.md")
    agents = load_agents(ai_dir / "agents.md")

    # 9. System prompt + memory
    # .ai/system.md overrides the built-in base prompt when present.
    _system_md = ai_dir / "system.md"
    if _system_md.exists():
        _base_system = _system_md.read_text().strip()
    else:
        _base_system = (
            "You are a helpful AI agent. "
            "Never use emojis in your responses unless the user explicitly asks for them. "
            "Use plain text, unicode symbols, or markdown formatting instead. "
            "When given a multi-step task, continue working through all steps until the task "
            "is fully complete — do not stop mid-task and wait for the user to say 'continue'."
        )
    memory_lines = read_memory(ai_dir / "memory.md")
    memory_section = format_for_prompt(memory_lines)
    system = (_base_system + ("\n\n" + memory_section if memory_section else "")).strip()

    # 10. Context
    ctx = RunContext(config=config, messages=[], system_prompt=system, trust_level=trust_level)

    # 11. Restrict tools for read-only trust level
    if trust_level == TrustLevel.READONLY:
        ctx.allowed_tools = [t.name for t in registry.all() if t.read_only]

    commands = load_builtin_commands(
        memory_path=ai_dir / "memory.md",
        skills=skills,
        agents=agents,
        registry=registry,
        hooks=hooks,
        provider_fn=_provider.stream,
    )

    return StartupResult(
        ctx=ctx,
        commands=commands,
        skills=skills,
        registry=registry,
        hooks=hooks,
        provider_fn=_provider.stream,
    )


def _toolbar(ctx: RunContext) -> str:
    used = estimate_tokens(ctx.messages)
    return (
        f" {ctx.config.model}"
        f"  mode:{ctx.config.mode}"
        f"  perm:{ctx.config.permission_mode}"
        f"  {used}/{ctx.config.context_limit} tok"
    )


def repl(result: StartupResult) -> None:
    ctx = result.ctx
    commands = result.commands
    skills = result.skills
    registry = result.registry
    hooks = result.hooks
    provider_fn = result.provider_fn

    # Set up prompt_toolkit session with history and tab completion.
    # Falls back to plain input() if prompt_toolkit is unavailable.
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory, InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings
        from newcli.completer import NewcliCompleter

        history_path = pathlib.Path.home() / ".ai" / "history"
        try:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            _history = FileHistory(str(history_path))
        except OSError:
            _history = InMemoryHistory()

        # Tab accepts the first/current completion rather than cycling.
        _kb = KeyBindings()

        @_kb.add("tab")
        def _tab_accept(event):  # noqa: F811
            buf = event.current_buffer
            if buf.complete_state:
                comp = buf.complete_state.current_completion
                if comp is not None:
                    buf.apply_completion(comp)
                elif buf.complete_state.completions:
                    buf.apply_completion(buf.complete_state.completions[0])
            else:
                buf.start_completion(select_first=False)

        _session: PromptSession = PromptSession(
            history=_history,
            completer=NewcliCompleter(commands, skills, hooks),
            complete_while_typing=True,
            key_bindings=_kb,
        )

        def _get_input() -> str:
            return _session.prompt(_prompt(ctx), bottom_toolbar=lambda: _toolbar(ctx))

    except ImportError:
        ui.print_info("prompt_toolkit not installed — history and completion unavailable.")

        def _get_input() -> str:  # type: ignore[misc]
            return input(_prompt(ctx))

    while True:
        try:
            line = _get_input().strip()
        except (KeyboardInterrupt, EOFError):
            ui.print_info("\nBye.")
            break

        if not line:
            continue

        skill = match_skill(line, skills)
        if skill:
            if skill.context == "fork":
                query = skill.render(line)
                text = run_forked(query, skill, ctx, registry, hooks, provider_fn)
                print(text)
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

        # Run agent turn.
        # The clock starts here so elapsed time is continuous across thinking + streaming.
        turn_start = time.time()
        output_chars = [0]  # mutable accumulator passed through render_event
        text_buf: list[str] = []  # collects TextChunks; flushed as Rich Markdown
        event_gen = run(line, ctx, registry, hooks, provider_fn=provider_fn)

        # Spinner (with live elapsed-time counter) shows while waiting for first chunk.
        with ui.Spinner(turn_start):
            first_event = next(event_gen, None)

        if first_event is not None:
            render_event(first_event, ctx, output_chars, text_buf)
            for event in event_gen:
                render_event(event, ctx, output_chars, text_buf)

        elapsed = time.time() - turn_start
        ui.print_turn_summary(output_chars[0] // 4, elapsed)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="newcli")
    parser.add_argument("--mode", choices=["ask", "plan"], default=None)
    parser.add_argument("--permission", choices=["ask", "allow", "bypass"], dest="permission", default=None)
    parsed = parser.parse_args()

    result = startup()

    if parsed.mode is not None:
        result.ctx.config = dataclasses.replace(result.ctx.config, mode=parsed.mode)
    if parsed.permission is not None:
        result.ctx.config = dataclasses.replace(result.ctx.config, permission_mode=parsed.permission)

    repl(result)


if __name__ == "__main__":
    main()
