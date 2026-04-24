# src/tigger/main.py
from __future__ import annotations
import dataclasses
import pathlib
import sys
import time
from tigger.config import load_config, find_config, derive_provider_name
from tigger.types import RunContext, TrustLevel
from tigger.tools import ToolRegistry, register_all
from tigger.hooks import HookRegistry, load_hooks
from tigger.skills import load_skills, load_skills_dir, load_agents, match_skill
from tigger.memory import read_memory, format_for_prompt
from tigger.mcp import connect_all
from tigger.compaction import estimate_tokens
from tigger.loop import run, run_forked
from tigger.commands import load_builtin_commands
from tigger.input_processing import expand_file_refs
from tigger import provider as _provider
from tigger import trust as _trust
from tigger import ui
from tigger._constants import home_config_dir
from tigger.sessions import save_message, load_session, list_sessions, new_session_id


@dataclasses.dataclass
class StartupResult:
    ctx: RunContext
    commands: dict
    skills: list
    registry: ToolRegistry
    hooks: HookRegistry
    provider_fn: object
    config_path: pathlib.Path


def startup(config_path: pathlib.Path | None = None) -> StartupResult:
    # 1. Find and load config
    if config_path is None:
        config_path = find_config(pathlib.Path.cwd())
    if config_path is None:
        config_path, _ = ui.run_setup_wizard(project_dir=pathlib.Path.cwd())

    tigger_dir = config_path.parent
    config = load_config(config_path)

    # 2. Workspace trust check
    cwd = pathlib.Path.cwd()
    trust_level = _trust.check_trust(cwd)
    if trust_level is None:
        choice = ui.ask_trust_prompt(cwd)
        if choice == "always":
            _trust.write_trusted(cwd, home_config_dir() / "trusted_paths.json")
            trust_level = TrustLevel.ALWAYS
        else:
            trust_level = TrustLevel.READONLY

    # 3. Logo + startup info (side-by-side when terminal is wide enough)
    ui.print_logo(
        provider=config.active_provider or derive_provider_name(config.base_url),
        model=config.model,
        cwd=str(cwd),
    )

    # 4. Tool registry
    registry = ToolRegistry()
    memory_path = tigger_dir / "memory.md"
    register_all(registry, memory_path=memory_path)

    # 5. MCP
    connect_all(registry, tigger_dir / "mcp.json")

    # 6. Hooks
    hooks = load_hooks(tigger_dir / "hooks.py")

    # 7-8. Skills + agents — prefer skills/ directory, fall back to skills.md
    skills_dir = tigger_dir / "skills"
    if skills_dir.exists() and skills_dir.is_dir():
        skills = load_skills_dir(skills_dir)
    else:
        skills = load_skills(tigger_dir / "skills.md")
    agents = load_agents(tigger_dir / "agents.md")

    # 9. System prompt + memory
    # .tigger/system.md overrides the built-in base prompt when present.
    _system_md = tigger_dir / "system.md"
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
    memory_lines = read_memory(tigger_dir / "memory.md")
    memory_section = format_for_prompt(memory_lines)
    system = (_base_system + ("\n\n" + memory_section if memory_section else "")).strip()

    # 10. Context
    ctx = RunContext(config=config, messages=[], system_prompt=system, trust_level=trust_level)

    # 11. Restrict tools for read-only trust level
    if trust_level == TrustLevel.READONLY:
        ctx.allowed_tools = [t.name for t in registry.all() if t.read_only]

    commands = load_builtin_commands(
        memory_path=tigger_dir / "memory.md",
        config_path=config_path,
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
        config_path=config_path,
    )


def _toolbar(ctx: RunContext) -> str:
    used = estimate_tokens(ctx.messages)
    limit = ctx.config.context_limit
    pct = (used / limit * 100) if limit else 0
    tools_str = ""
    if ui.recent_tools:
        tools_str = f"  tools: {', '.join(ui.recent_tools)}"
    return (
        f" {ctx.config.model}"
        f"  mode:{ctx.config.mode}"
        f"  perm:{ctx.config.permission_mode}"
        f"  {pct:.1f}% context"
        f"{tools_str}"
    )


def repl(result: StartupResult, session_id: str | None = None, session_dir: pathlib.Path | None = None) -> None:
    ctx = result.ctx
    commands = result.commands
    skills = result.skills
    registry = result.registry
    hooks = result.hooks
    provider_fn = result.provider_fn

    # Session tracking: how many messages existed before this REPL turn.
    _saved_count = len(ctx.messages)

    # Set up prompt_toolkit session with history and tab completion.
    # Falls back to plain input() if prompt_toolkit is unavailable.
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import HTML, FormattedText
        from prompt_toolkit.history import FileHistory, InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.styles import Style as PTStyle
        from tigger.completer import TiggerCompleter

        history_path = home_config_dir() / "history"
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

        _PLACEHOLDER = "Type your message or @path/to/file"
        _RULE = "\u2500" * len("\u276f " + _PLACEHOLDER)

        _pt_style = PTStyle.from_dict({
            "bottom-toolbar": "noreverse #888888",
        })

        def _bottom_toolbar() -> str:
            return " " + _toolbar(ctx)

        _session: PromptSession = PromptSession(
            history=_history,
            completer=TiggerCompleter(commands, skills),
            complete_while_typing=True,
            key_bindings=_kb,
            placeholder=HTML(f'<style fg="#666666">{_PLACEHOLDER}</style>'),
            style=_pt_style,
            bottom_toolbar=_bottom_toolbar,
            reserve_space_for_menu=4,
        )

        # Fix the buffer window to not extend height, closing the gap
        # between prompt and bottom toolbar (Questionary pattern).
        try:
            _buf = _session.layout.container.get_children()[0].content.get_children()[1].content
            _buf.dont_extend_height = True
        except (IndexError, AttributeError):
            pass

        # Disable prompt_toolkit's broken non-fullscreen resize handler
        # (upstream bug #1933). Set BEFORE prompt() so attach_winch_signal_handler
        # captures our no-op instead of the original method.
        _session.app._on_resize = lambda: None

        def _get_input() -> str:
            ui.console.print(f"[dim]{_RULE}[/dim]")
            return _session.prompt("\u276f ")

    except ImportError:
        ui.print_info("prompt_toolkit not installed — history and completion unavailable.")

        def _get_input() -> str:  # type: ignore[misc]
            cols = ui.console.width or 80
            print("\033[90m" + "\u2500" * cols + "\033[0m")
            return input("\u276f ")

    while True:
        try:
            line = _get_input().strip()
        except (KeyboardInterrupt, EOFError):
            ui.print_info("\nBye.")
            break

        if not line:
            continue

        if line in ("exit", "quit", "/exit", "/quit"):
            ui.print_info("Bye.")
            break

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

        # Expand @file references before sending to agent.
        line = expand_file_refs(line)

        # Run agent turn.
        turn_start = time.time()
        output_chars = [0]
        text_buf: list[str] = []

        try:
            event_gen = run(line, ctx, registry, hooks, provider_fn=provider_fn)

            with ui.Spinner(turn_start, token_counter=output_chars):
                first_event = next(event_gen, None)

            if first_event is not None:
                ui.render_event(first_event, ctx, output_chars, text_buf)
                for event in event_gen:
                    ui.render_event(event, ctx, output_chars, text_buf)
        except KeyboardInterrupt:
            ui._stop_activity()
            ui.print_info("\n(interrupted)")
            continue

        elapsed = time.time() - turn_start
        ui.print_turn_summary(output_chars[0] // 4, elapsed)

        # Persist new messages to the session file.
        if session_id and session_dir:
            for msg in ctx.messages[_saved_count:]:
                save_message(session_dir, session_id, msg)
            _saved_count = len(ctx.messages)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="tigger-code")
    parser.add_argument("--mode", choices=["ask", "plan"], default=None)
    parser.add_argument("--permission", choices=["ask", "allow", "bypass"], dest="permission", default=None)
    parser.add_argument("-c", "--continue", dest="resume", action="store_true",
                        help="Resume the most recent session")
    parsed = parser.parse_args()

    result = startup()

    if parsed.mode is not None:
        result.ctx.config = dataclasses.replace(result.ctx.config, mode=parsed.mode)
    if parsed.permission is not None:
        result.ctx.config = dataclasses.replace(result.ctx.config, permission_mode=parsed.permission)

    # Session setup
    session_dir = result.config_path.parent / "sessions"
    session_id: str | None = None

    if parsed.resume:
        sessions = list_sessions(session_dir)
        if sessions:
            latest = sessions[0]
            result.ctx.messages = load_session(latest.path)
            session_id = latest.timestamp
            ui.print_info(f"Resumed session {session_id} with {latest.message_count} messages")
        else:
            ui.print_info("No previous sessions found. Starting new session.")
            session_id = new_session_id()
    else:
        session_id = new_session_id()

    repl(result, session_id=session_id, session_dir=session_dir)


if __name__ == "__main__":
    main()
