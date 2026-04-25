# src/tigger/main.py
from __future__ import annotations
import dataclasses
import pathlib
import shutil
import sys
import time
import httpx
from tigger.config import load_config, find_config, derive_provider_name
from tigger.types import RunContext, TrustLevel
from tigger.tools import ToolRegistry, register_all
from tigger.hooks import HookDef, HookRegistry, load_hooks, load_hooks_dir
from tigger.skills import match_skill
from tigger.resolve import (
    resolve_file, resolve_skills, resolve_agents, resolve_hooks, resolve_modes,
    is_global_config, seed_global, INTERNAL_DIR,
)
from tigger.memory import read_memory, format_for_prompt
from tigger.mcp import connect_all
from tigger.compaction import estimate_tokens
from tigger.types import ToolEndEvent, TurnDoneEvent
from tigger.loop import run, run_forked
from tigger.commands import load_builtin_commands
from tigger.input_processing import expand_file_refs
from tigger import provider as _provider
from tigger import trust as _trust
from tigger import ui
from tigger._constants import home_config_dir
from tigger.sessions import save_message, load_session, list_sessions, new_session_id, project_session_dir


@dataclasses.dataclass
class StartupResult:
    ctx: RunContext
    commands: dict
    skills: list
    agents: list
    registry: ToolRegistry
    hooks: HookRegistry              # legacy — RTK hook only
    hook_defs: list                   # new declarative hooks
    provider_fn: object
    config_path: pathlib.Path


def startup(config_path: pathlib.Path | None = None) -> StartupResult:
    # 1. Find and load config
    if config_path is None:
        config_path = find_config(pathlib.Path.cwd())
    if config_path is None:
        config_path, _ = ui.run_setup_wizard(project_dir=pathlib.Path.cwd())

    config = load_config(config_path)

    # 1b. Derive 3-tier resolution directories
    global_dir = home_config_dir()
    bundled_dir = pathlib.Path(__file__).parent / "assets"
    if is_global_config(config_path):
        project_dir = None
    else:
        project_dir = config_path.parent

    # 1c. Seed ~/.tigger/ with internal skills/agents on first run
    seed_global(global_dir)

    # 2. Workspace trust check
    cwd = pathlib.Path.cwd()
    trust_level = _trust.check_trust(cwd)
    if trust_level is None:
        choice = ui.ask_trust_prompt(cwd)
        if choice == "always":
            _trust.write_trusted(cwd, global_dir / "trusted_paths.json")
            trust_level = TrustLevel.ALWAYS
        else:
            trust_level = TrustLevel.READONLY

    # 3. Logo + startup info
    _rtk_available = shutil.which("rtk") is not None
    _rtk_enabled = config.rtk or _rtk_available
    ui.print_logo(
        provider=config.active_provider or derive_provider_name(config.base_url),
        model=config.model,
        cwd=str(cwd),
        rtk=_rtk_enabled,
    )

    # 4. Tool registry + memory
    # Memory write path: project if available, else global. Resolved once.
    if project_dir is not None:
        memory_path = project_dir / "memory.md"
    else:
        memory_path = global_dir / "memory.md"
    registry = ToolRegistry()
    register_all(registry, memory_path=memory_path)

    # 5. MCP — override semantics (first found wins)
    mcp_path = resolve_file("mcp.json", project_dir, global_dir)
    if mcp_path:
        connect_all(registry, mcp_path)

    # 6. Hooks — declarative markdown hooks from hooks/ directories (additive merge)
    hook_defs = resolve_hooks(project_dir, global_dir)

    # 6a. Legacy hooks.py deprecation warning
    for _dir in [d for d in (project_dir, global_dir) if d is not None]:
        _legacy = _dir / "hooks.py"
        if _legacy.exists():
            ui.print_info(
                f"[hooks] Deprecated: {_legacy}\n"
                "  hooks.py is no longer supported. "
                "Use hooks/ directory with .md files instead.\n"
                "  Run /hookify to create hooks from natural language, "
                "or see /help hooks for the format."
            )

    # Legacy HookRegistry — only used for RTK hook (mutates args, not supported by declarative hooks)
    hooks = HookRegistry()

    # 6b. RTK auto-detection — enable if rtk binary is found and not explicitly disabled
    if not config.rtk and shutil.which("rtk"):
        config = dataclasses.replace(config, rtk=True)

    # 6c. RTK before-hook — always registered, checks ctx.config.rtk at runtime
    #     so /rtk on|off works without restart
    def _rtk_before_hook(call, ctx):
        if ctx.config.rtk and not call.args.get("command", "").startswith("rtk "):
            call.args["command"] = f"rtk {call.args['command']}"
        return call
    hooks.before.setdefault("bash", []).append(_rtk_before_hook)

    # 7-8. Skills + agents + modes — 3-tier merge (project > global > internal)
    skills = resolve_skills(project_dir, global_dir)
    agents = resolve_agents(project_dir, global_dir)
    modes = resolve_modes(project_dir, global_dir)

    # 9. System prompt + memory — override semantics
    _system_path = resolve_file("system.md", project_dir, global_dir, bundled_dir)
    if _system_path is None:
        raise FileNotFoundError(
            f"Missing system prompt asset: {bundled_dir / 'system.md'}. "
            "This file should be packaged with tigger-code."
        )
    _base_system = _system_path.read_text().strip()
    _memory_read_path = resolve_file("memory.md", project_dir, global_dir)
    memory_lines = read_memory(_memory_read_path) if _memory_read_path else []
    memory_section = format_for_prompt(memory_lines)
    system = (_base_system + ("\n\n" + memory_section if memory_section else "")).strip()

    # 10. Context
    ctx = RunContext(config=config, messages=[], system_prompt=system, trust_level=trust_level, modes=modes)

    # 11. Restrict tools for read-only trust level
    if trust_level == TrustLevel.READONLY:
        ctx.allowed_tools = [t.name for t in registry.all() if t.read_only]

    # Summary dir: project-scoped if available, else global.
    summary_dir = project_dir if project_dir is not None else global_dir

    commands = load_builtin_commands(
        memory_path=memory_path,
        config_path=config_path,
        skills=skills,
        agents=agents,
        registry=registry,
        hooks=hooks,
        provider_fn=_provider.stream,
        summary_dir=summary_dir,
    )

    return StartupResult(
        ctx=ctx,
        commands=commands,
        skills=skills,
        agents=agents,
        registry=registry,
        hooks=hooks,
        hook_defs=hook_defs,
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
    rtk_str = "  rtk" if ctx.config.rtk else ""
    return (
        f" {ctx.config.model}"
        f"  mode:{ctx.config.mode}"
        f"  perm:{ctx.config.permission_mode}"
        f"  {pct:.1f}% context"
        f"{rtk_str}"
        f"{tools_str}"
    )


def _show_exit(stats: ui.SessionStats, session_id: str | None, ctx: RunContext) -> None:
    """Print the session summary panel on exit."""
    if stats.turns == 0 and stats.tool_calls == 0:
        ui.print_info("\nBye.")
        return
    ui.print_session_summary(
        stats=stats,
        session_id=session_id,
        model=ctx.config.model,
        rtk_enabled=ctx.config.rtk,
    )


def repl(result: StartupResult, session_id: str | None = None, session_dir: pathlib.Path | None = None) -> None:
    ctx = result.ctx
    commands = result.commands
    skills = result.skills
    registry = result.registry
    hooks = result.hooks
    hook_defs = result.hook_defs
    provider_fn = result.provider_fn

    # Session tracking: how many messages existed before this REPL turn.
    _saved_count = len(ctx.messages)
    stats = ui.SessionStats()
    if ctx.config.rtk:
        stats.snapshot_rtk()

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
            _show_exit(stats, session_id, ctx)
            break

        if not line:
            continue

        if line in ("exit", "quit", "/exit", "/quit"):
            _show_exit(stats, session_id, ctx)
            break

        # Expand @file references in raw user input before skill/command processing.
        # Must happen before skill.render() to avoid mangling skill content
        # that contains @ characters (e.g. @on_before decorator examples).
        line = expand_file_refs(line)

        skill = match_skill(line, skills)
        if skill:
            if skill.context == "fork":
                query = skill.render(line)
                text = run_forked(query, skill, ctx, registry, hooks, provider_fn,
                                  hook_defs=hook_defs)
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
        turn_start = time.time()
        output_chars = [0]
        text_buf: list[str] = []

        try:
            event_gen = run(line, ctx, registry, hooks, provider_fn=provider_fn,
                           hook_defs=hook_defs)

            with ui.Spinner(turn_start, token_counter=output_chars):
                first_event = next(event_gen, None)

            if first_event is not None:
                if isinstance(first_event, ToolEndEvent):
                    stats.record_tool_end(first_event)
                elif isinstance(first_event, TurnDoneEvent):
                    stats.turns += 1
                ui.render_event(first_event, ctx, output_chars, text_buf)
                for event in event_gen:
                    if isinstance(event, ToolEndEvent):
                        stats.record_tool_end(event)
                    elif isinstance(event, TurnDoneEvent):
                        stats.turns += 1
                    ui.render_event(event, ctx, output_chars, text_buf)
        except KeyboardInterrupt:
            ui._stop_activity()
            ui.print_info("\n(interrupted)")
            continue
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError) as exc:
            ui._stop_activity()
            ui.print_error(f"Network error: {exc}")
            continue
        except Exception as exc:
            if "TimeoutError" in type(exc).__name__ or "timed out" in str(exc).lower():
                ui._stop_activity()
                ui.print_error(f"Request timed out — is the model server running?")
            else:
                raise
            continue

        turn_tokens = output_chars[0] // 4
        stats.output_tokens += turn_tokens
        elapsed = time.time() - turn_start
        ui.print_turn_summary(turn_tokens, elapsed)

        # Persist new messages to the session file.
        if session_id and session_dir:
            for msg in ctx.messages[_saved_count:]:
                save_message(session_dir, session_id, msg)
            _saved_count = len(ctx.messages)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="tigger-code")
    parser.add_argument("--mode", default=None)
    parser.add_argument("--permission", choices=["ask", "allow", "bypass"], dest="permission", default=None)
    parser.add_argument("-c", "--continue", dest="resume", action="store_true",
                        help="Resume the most recent session")
    parsed = parser.parse_args()

    result = startup()

    if parsed.mode is not None:
        from tigger.config import _MODE_RENAME
        mode = _MODE_RENAME.get(parsed.mode, parsed.mode)
        result.ctx.config = dataclasses.replace(result.ctx.config, mode=mode)
    if parsed.permission is not None:
        result.ctx.config = dataclasses.replace(result.ctx.config, permission_mode=parsed.permission)

    # Validate mode against resolved mode names
    mode_names = {m.name for m in result.ctx.modes}
    if mode_names and result.ctx.config.mode not in mode_names:
        ui.print_error(
            f"Unknown mode {result.ctx.config.mode!r}. "
            f"Available: {', '.join(sorted(mode_names))}. Falling back to 'act'."
        )
        result.ctx.config = dataclasses.replace(result.ctx.config, mode="act")

    # Session setup
    session_dir = project_session_dir(home_config_dir(), pathlib.Path.cwd().resolve())
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
