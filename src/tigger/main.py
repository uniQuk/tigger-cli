# src/tigger/main.py
from __future__ import annotations

import dataclasses
import pathlib
import shutil
import sys
import time

import httpx
import openai

from tigger import provider as _provider
from tigger import trust as _trust
from tigger import ui
from tigger._constants import home_config_dir
from tigger.commands import bind_reload_command, load_builtin_commands
from tigger.compaction import estimate_tokens, load_recent_summary
from tigger.config import derive_provider_name, find_config, load_config
from tigger.hooks import RTK_HOOK_NAME, HookDef, set_hook_enabled
from tigger.input_processing import expand_file_refs
from tigger.loop import run, run_forked
from tigger.mcp import McpServerConfig, connect_all
from tigger.memory import format_for_prompt, read_memory
from tigger.resolve import (
    is_global_config,
    resolve_agents,
    resolve_file,
    resolve_hooks,
    resolve_mcp_configs,
    resolve_modes,
    resolve_skills,
    seed_global,
)
from tigger.sessions import (
    list_sessions,
    load_session,
    new_session_id,
    project_session_dir,
    save_message,
)
from tigger.skills import match_skill
from tigger.tools import ToolRegistry, register_all
from tigger.types import RunContext, TextChunk, ToolEndEvent, TrustLevel, TurnDoneEvent


@dataclasses.dataclass
class StartupResult:
    ctx: RunContext
    commands: dict
    skills: list
    agents: list
    registry: ToolRegistry
    hook_defs: list[HookDef]
    provider_fn: object
    config_path: pathlib.Path
    summaries_dir: pathlib.Path | None = None
    # Fields below support in-session reload (`/reload-plugins`).
    project_dir: pathlib.Path | None = None
    global_dir: pathlib.Path | None = None
    memory_path: pathlib.Path | None = None
    summary_dir: pathlib.Path | None = None
    mcp_configs: list[McpServerConfig] = dataclasses.field(default_factory=list)
    # Set true at startup when load_recent_summary returned content; consumers
    # show a dim "↺ recent context loaded" hint so users aren't surprised that
    # the model remembers yesterday's session.
    has_recent_summary: bool = False


def startup(
    config_path: pathlib.Path | None = None,
    *,
    interactive: bool = True,
    auto_trust: bool = False,
    quiet: bool = False,
) -> StartupResult:
    """Run startup.

    interactive: when False, skip the interactive trust prompt; assume
    untrusted unless the workspace is already trusted or auto_trust is set.
    auto_trust: when True, grant TrustLevel.ALWAYS without prompting (used
    by --trust).
    quiet: when True, suppress the welcome banner and per-subsystem startup
    notices (MCP connect summary, recent-summary load). Used by ``--once``
    so scripted callers get a clean stdout containing only the answer.
    """
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
        if auto_trust:
            # --trust flag: opt in without prompting.
            _trust.write_trusted(cwd, global_dir / "trusted_paths.json")
            trust_level = TrustLevel.ALWAYS
        elif interactive:
            choice = ui.ask_trust_prompt(cwd)
            if choice == "always":
                _trust.write_trusted(cwd, global_dir / "trusted_paths.json")
                trust_level = TrustLevel.ALWAYS
            else:
                trust_level = TrustLevel.READONLY
        else:
            # Non-interactive (e.g. piped --once) and no explicit --trust:
            # auto-deny. Safer default than deadlocking on input().
            trust_level = TrustLevel.READONLY

    # 3. Logo + startup info (skipped in quiet mode for clean scripted output)
    _rtk_available = shutil.which("rtk") is not None
    _rtk_enabled = config.rtk or _rtk_available
    if not quiet:
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

    # 5. MCP — 3-tier merge (project > global > internal), name-based shadowing
    mcp_configs = resolve_mcp_configs(project_dir, global_dir)
    if mcp_configs:
        if quiet:
            # Silence MCP startup chatter for scripted --once callers. Briefly
            # swap the shared console out for a discarding one so connect_all's
            # console.print calls go nowhere; warnings still go to stderr.
            from io import StringIO
            from rich.console import Console as _Console
            _orig = ui.console
            ui.console = _Console(file=StringIO(), highlight=False)
            try:
                connect_all(registry, mcp_configs)
            finally:
                ui.console = _orig
        else:
            connect_all(registry, mcp_configs)

    # 6. Hooks — declarative markdown hooks from hooks/ directories (additive merge)
    hook_defs = resolve_hooks(project_dir, global_dir)

    # 6a. RTK auto-detection — enable if rtk binary is found and not explicitly disabled
    if not config.rtk and shutil.which("rtk"):
        config = dataclasses.replace(config, rtk=True)

    # 6b. RTK hook control — disable _rtk-rewrite hook if RTK is off
    if not config.rtk:
        set_hook_enabled(hook_defs, RTK_HOOK_NAME, False)

    # 7-8. Skills + agents + modes — 3-tier merge (project > global > internal)
    skills = resolve_skills(project_dir, global_dir)
    agents = resolve_agents(project_dir, global_dir)
    modes = resolve_modes(project_dir, global_dir)

    # Warn on skill triggers that collide with built-in /-commands.
    from tigger.commands import COMMAND_DESCRIPTIONS
    from tigger.skills import warn_on_command_collisions
    warn_on_command_collisions(skills, list(COMMAND_DESCRIPTIONS.keys()))

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
    # `system_prompt_extra` (config.json) is appended AFTER the base system
    # prompt and memory. Lets users add project- or workspace-specific
    # instructions without copy-pasting the full bundled prompt.
    extra = (config.system_prompt_extra or "").strip()
    parts = [_base_system]
    if memory_section:
        parts.append(memory_section)
    if extra:
        parts.append(extra)
    system = "\n\n".join(parts).strip()

    # 10. Context
    ctx = RunContext(config=config, messages=[], system_prompt=system, trust_level=trust_level, modes=modes)

    # 11. Restrict tools for read-only trust level
    if trust_level == TrustLevel.READONLY:
        ctx.allowed_tools = [t.name for t in registry.all() if t.read_only]

    # Summary dir: project-scoped if available, else global.
    summary_dir = project_dir if project_dir is not None else global_dir
    _summaries_dir = summary_dir / "summaries"

    # 11b. Inject recent compaction summary as orientation context
    _prev_summary = load_recent_summary(_summaries_dir)
    _has_recent_summary = bool(_prev_summary)
    if _prev_summary:
        ctx.system_prompt = f"[Previous session context]\n{_prev_summary}\n\n{ctx.system_prompt}"
        if not quiet:
            # Surface that we silently rehydrated context — otherwise users
            # get spooked when the model "remembers" yesterday's task.
            ui.console.print(
                "      [dim]↺ recent session context loaded[/dim]"
            )

    commands = load_builtin_commands(
        memory_path=memory_path,
        config_path=config_path,
        skills=skills,
        agents=agents,
        registry=registry,
        provider_fn=_provider.stream,
        summary_dir=summary_dir,
        modes=modes,
        hook_defs=hook_defs,
    )

    result = StartupResult(
        ctx=ctx,
        commands=commands,
        skills=skills,
        agents=agents,
        registry=registry,
        hook_defs=hook_defs,
        provider_fn=_provider.stream,
        config_path=config_path,
        summaries_dir=_summaries_dir,
        project_dir=project_dir,
        global_dir=global_dir,
        memory_path=memory_path,
        summary_dir=summary_dir,
        mcp_configs=mcp_configs,
        has_recent_summary=_has_recent_summary,
    )
    bind_reload_command(commands, result)
    return result


def _toolbar(ctx: RunContext) -> str:
    used = estimate_tokens(ctx.messages)
    limit = ctx.config.context_limit
    pct = (used / limit * 100) if limit else 0
    tools_str = ""
    if ui.recent_tools:
        tools_str = f"  tools: {', '.join(ui.recent_tools)}"
    rtk_str = "  rtk" if ctx.config.rtk else ""
    return (
        f" {ctx.config.model_name or ctx.config.model}"
        f"  mode:{ctx.config.mode}"
        f"  perm:{ctx.config.permission_mode}"
        f"  {pct:.1f}% context"
        f"{rtk_str}"
        f"{tools_str}"
    )


def _show_exit(stats: ui.SessionStats, session_id: str | None, ctx: RunContext) -> None:
    """Print the session summary panel on exit."""
    if stats.turns == 0 and stats.tool_calls == 0:
        # Match the cat motif from the welcome banner — three short lines feel
        # more on-brand than a terse "Bye.". Use style= rather than inline
        # markup because the cat ASCII contains backslashes that confuse the
        # bracket parser.
        ui.console.print()
        ui.console.print(r"       /\_/\ ", style="dim", highlight=False, markup=False)
        ui.console.print(r"      ( -.- )   bye…", style="dim italic", highlight=False, markup=False)
        ui.console.print(r"       > ^ < ", style="dim", highlight=False, markup=False)
        ui.console.print()
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
    agents = result.agents
    registry = result.registry
    hook_defs = result.hook_defs
    provider_fn = result.provider_fn
    summaries_dir = result.summaries_dir

    # Session tracking: how many messages existed before this REPL turn.
    _saved_count = len(ctx.messages)
    stats = ui.SessionStats()
    if ctx.config.rtk:
        stats.snapshot_rtk()

    # Set up prompt_toolkit session with history and tab completion.
    # Falls back to plain input() if prompt_toolkit is unavailable.
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import HTML
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
        def _tab_accept(event):
            buf = event.current_buffer
            if buf.complete_state:
                comp = buf.complete_state.current_completion
                if comp is not None:
                    buf.apply_completion(comp)
                elif buf.complete_state.completions:
                    buf.apply_completion(buf.complete_state.completions[0])
            else:
                buf.start_completion(select_first=False)

        @_kb.add("s-tab")
        def _shift_tab_mode(event):
            """Cycle through available modes alphabetically."""
            mode_names = sorted(m.name for m in ctx.modes)
            if len(mode_names) <= 1:
                return
            current = ctx.config.mode
            try:
                idx = mode_names.index(current)
            except ValueError:
                idx = -1
            next_idx = (idx + 1) % len(mode_names)
            ctx.config = dataclasses.replace(ctx.config, mode=mode_names[next_idx])
            event.app.invalidate()

        # Pick a hint at REPL start so returning users discover features over
        # time \u2014 Tab completion, /commands, @file inclusion, /compact, etc.
        import random as _random
        _PLACEHOLDER_HINTS = [
            "Type your message or @path/to/file",
            "Tab to autocomplete /commands and @paths",
            "/help shows every available command",
            "Type @file.py to inline a file",
            "/compact summarises older turns",
            "/skills lists matched-by-trigger workflows",
            "/status shows your runtime config",
        ]
        _PLACEHOLDER = _random.choice(_PLACEHOLDER_HINTS)
        # Rule width tracks the longest hint so it doesn't shrink unexpectedly.
        _RULE = "\u2500" * len("\u276f " + max(_PLACEHOLDER_HINTS, key=len))

        _pt_style = PTStyle.from_dict({
            "bottom-toolbar": "noreverse #888888",
        })

        def _bottom_toolbar():
            # HTML lets us colour the context % independently of the rest.
            from html import escape
            used = estimate_tokens(ctx.messages)
            limit = ctx.config.context_limit
            pct = (used / limit * 100) if limit else 0
            if pct >= 80:
                pct_colour = "#ff4444"
            elif pct >= 50:
                pct_colour = "#ffaa00"
            else:
                pct_colour = "#5fd75f"
            model = ctx.config.model_name or ctx.config.model
            tools_html = ""
            if ui.recent_tools:
                tools_html = (
                    f'  <style fg="#999999">tools:</style> '
                    f'<style fg="#ce5cb1">{escape(", ".join(ui.recent_tools))}</style>'
                )
            rtk_html = '  <style fg="#5fd75f">rtk</style>' if ctx.config.rtk else ""
            return HTML(
                f' <style fg="#5fcfff">{escape(model)}</style>'
                f'  <style fg="#999999">mode:</style>{escape(ctx.config.mode)}'
                f'  <style fg="#999999">perm:</style>{escape(ctx.config.permission_mode)}'
                f'  <style fg="{pct_colour}">{pct:.1f}% ctx</style>'
                f'{rtk_html}'
                f'{tools_html}'
            )

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
            # Cyan \u276f matches the cyan-for-action convention used everywhere
            # else (slash commands, switch confirmations, etc.).
            return _session.prompt(HTML('<style fg="#5fcfff">\u276f</style> '))

    except ImportError:
        ui.console.print(
            "      [dim]prompt_toolkit not installed — "
            "history and completion unavailable.[/dim]"
        )

        def _get_input() -> str:  # type: ignore[misc]
            cols = ui.console.width or 80
            print("\033[90m" + "\u2500" * cols + "\033[0m")
            # Cyan \u276f via raw ANSI (no prompt_toolkit available here).
            return input("\033[38;5;87m\u276f\033[0m ")

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
        injected_files: list[tuple[str, int]] = []
        line = expand_file_refs(line, injected=injected_files)
        if injected_files:
            def _fmt_size(n: int) -> str:
                if n >= 1024:
                    return f"{n / 1024:.1f}KB"
                return f"{n}B"
            summary = ", ".join(
                f"@{p} [dim]({_fmt_size(n)})[/dim]" for p, n in injected_files
            )
            ui.console.print(f"[dim]↪ included[/dim] {summary}")

        skill = match_skill(line, skills)
        forked_skill = None
        forked_agent = None
        if skill:
            if skill.context == "fork":
                forked_skill = skill
                if skill.agent:
                    forked_agent = next(
                        (a for a in agents if a.name == skill.agent), None,
                    )
                    if forked_agent is None:
                        ui.print_error(
                            f"Skill {skill.name!r} references agent "
                            f"{skill.agent!r} which was not found; "
                            "running with default skill context instead."
                        )
                line = skill.render(line)
            else:
                line = skill.render(line)
            # Surface that a skill matched so the user isn't surprised when
            # their prompt is reinterpreted. Forked skills get the ↳ glyph
            # to hint at the sub-agent jump.
            arrow = "↳" if skill.context == "fork" else "↪"
            mode_tag = " [dim](forked)[/dim]" if skill.context == "fork" else ""
            ui.console.print(
                f"[dim]{arrow} skill:[/dim] [magenta]{skill.name}[/magenta]{mode_tag}"
            )

        if line.startswith("/") and not forked_skill:
            name, _, args = line[1:].partition(" ")
            handler = commands.get(name)
            if handler:
                handler(args, ctx)
            else:
                # Suggest a close match (Levenshtein-ish via difflib) so
                # /halp → /help, /toks → /tokens. Cuts off at a 0.6 ratio
                # to avoid wild guesses.
                import difflib
                matches = difflib.get_close_matches(
                    name, list(commands.keys()), n=1, cutoff=0.6,
                )
                hint = (
                    f" Did you mean [cyan]/{matches[0]}[/cyan]?"
                    if matches else " [dim]Type[/dim] [cyan]/help[/cyan] [dim]for list.[/dim]"
                )
                ui.console.print(
                    f"[bold red]Error:[/bold red] Unknown command: "
                    f"[cyan]/{name}[/cyan].{hint}"
                )
            continue

        # Run agent turn.
        turn_start = time.time()
        output_chars = [0]
        ui.set_turn_start(turn_start, output_chars)
        text_buf: list[str] = []
        # Real output-token count from the provider, summed across every
        # TurnDoneEvent in this turn (a single user prompt can drive multiple
        # model calls when tools fire). Falls back to the chars/4 estimate
        # below if the provider omitted the usage payload.
        real_output_tokens = 0

        try:
            if forked_skill:
                event_gen = run_forked(line, forked_skill, ctx, registry,
                                       provider_fn=provider_fn, hook_defs=hook_defs,
                                       permission_callback=ui.ask_permission,
                                       agent=forked_agent)
            else:
                event_gen = run(line, ctx, registry, provider_fn=provider_fn,
                               hook_defs=hook_defs, summaries_dir=summaries_dir,
                               permission_callback=ui.ask_permission)

            with ui.Spinner(turn_start, token_counter=output_chars):
                first_event = next(event_gen, None)

            if first_event is not None:
                if isinstance(first_event, ToolEndEvent):
                    stats.record_tool_end(first_event)
                elif isinstance(first_event, TurnDoneEvent):
                    stats.turns += 1
                    real_output_tokens += first_event.output_tokens
                ui.render_event(first_event, output_chars, text_buf)
                for event in event_gen:
                    if isinstance(event, ToolEndEvent):
                        stats.record_tool_end(event)
                    elif isinstance(event, TurnDoneEvent):
                        stats.turns += 1
                        real_output_tokens += event.output_tokens
                    ui.render_event(event, output_chars, text_buf)
        except KeyboardInterrupt:
            ui._stop_activity()
            ui._stop_live()
            ui._reset_tool_buffer()
            elapsed = time.time() - turn_start
            partial = real_output_tokens or (output_chars[0] // 4)
            parts = [ui.format_duration(elapsed)]
            if partial:
                parts.append(f"~{partial} tokens streamed")
            ui.console.print(
                f"\n[yellow]↩ interrupted[/yellow] [dim]· {' · '.join(parts)}[/dim]"
            )
            continue
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError) as exc:
            ui._stop_activity()
            ui._stop_live()
            ui._reset_tool_buffer()
            ui.print_error_panel(
                "Network error",
                str(exc),
                hint=f"Check that {ctx.config.base_url} is reachable.",
            )
            continue
        except openai.APIError as exc:
            ui._stop_activity()
            ui._stop_live()
            ui._reset_tool_buffer()
            msg = str(exc)
            if "UndefinedValue" in msg or "jinja" in msg.lower():
                hint = (
                    "The model's chat template can't render the request. "
                    "Common causes: the model doesn't support `tools`, "
                    "or it doesn't recognise the `chat_template_kwargs` "
                    "being sent. Try a lmstudio-community variant, "
                    "set `\"disable_tools\": true` on this model in "
                    "config.json to run it chat-only, or switch via /model."
                )
            else:
                hint = "Try /model to switch, or wait and retry."
            ui.print_error_panel("Provider rejected request", msg, hint=hint)
            continue
        except Exception as exc:
            if "TimeoutError" in type(exc).__name__ or "timed out" in str(exc).lower():
                ui._stop_activity()
                ui._stop_live()
                ui._reset_tool_buffer()
                ui.print_error_panel(
                    "Request timed out",
                    "The model server didn't respond.",
                    hint=f"Is {ctx.config.base_url} running?",
                )
            else:
                raise
            continue

        # Prefer the provider's reported token count when present; fall back
        # to chars/4 only when the server didn't include usage info.
        turn_tokens = real_output_tokens or (output_chars[0] // 4)
        stats.output_tokens += turn_tokens
        elapsed = time.time() - turn_start
        ui.set_turn_start(None)
        ctx_used = estimate_tokens(ctx.messages)
        ctx_limit = ctx.config.context_limit
        ctx_pct = int(ctx_used / ctx_limit * 100) if ctx_limit else None
        ui.print_turn_summary(turn_tokens, elapsed, context_pct=ctx_pct)

        # Persist new messages to the session file.
        if session_id and session_dir:
            for msg in ctx.messages[_saved_count:]:
                save_message(session_dir, session_id, msg)
            _saved_count = len(ctx.messages)


def main() -> None:
    import argparse
    # Resolve installed package version for --version. Falls back gracefully
    # if running from a source checkout without an installed dist.
    try:
        from importlib.metadata import version as _pkg_version
        _version = _pkg_version("tigger-code")
    except Exception:
        _version = "0.1.0"
    parser = argparse.ArgumentParser(
        prog="tigger-code",
        description="Tigger — minimal AI agent CLI. "
                    "Built on the OpenAI-compatible API; works with local "
                    "(LM Studio, Ollama) and cloud endpoints.",
        epilog=(
            "Examples:\n"
            "  tigger-code                              # interactive REPL\n"
            "  tigger-code -c                           # resume the most recent session\n"
            "  tigger-code -q                           # interactive without the welcome banner\n"
            "  tigger-code --once 'hello'               # single turn; stdout=answer\n"
            "  tigger-code --once 'summarise @main.py' > out.md   # pipe-friendly\n"
            "\n"
            "Exit codes (--once):  0 ok · 1 empty response · 2 network/provider · 130 SIGINT\n"
            "Inside the REPL: /help for commands, Tab to complete, @path/to/file to "
            "inline a file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"tigger-code {_version}",
    )
    parser.add_argument(
        "--mode", default=None, metavar="NAME",
        help="Override the active mode (e.g. act, plan); reads from .tigger/modes/",
    )
    parser.add_argument(
        "--permission",
        choices=["ask", "allow", "bypass"],
        dest="permission", default=None,
        help="Override permission gate: ask=prompt each tool, "
             "allow=permit safe-listed prefixes, bypass=permit everything",
    )
    parser.add_argument("-c", "--continue", dest="resume", action="store_true",
                        help="Resume the most recent session")
    parser.add_argument("--once", metavar="PROMPT",
                        help="Run a single agent turn non-interactively and exit. "
                             "Stdout = answer only; conventional exit codes.")
    parser.add_argument("--trust", action="store_true",
                        help="Mark the current workspace as trusted without prompting")
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Skip the logo, cat, MCP, and recent-summary notices on startup. "
             "REPL still runs.",
    )
    parser.add_argument(
        "--no-think", action="store_true",
        help="Disable thinking mode for this invocation "
             "(chat_template_kwargs.enable_thinking=False). "
             "Useful with --once for fast non-thinking responses.",
    )
    parser.add_argument(
        "--model", default=None, metavar="NAME",
        help="Override the model wire id sent to the provider for this "
             "invocation. Useful with --once for A/B testing different "
             "models on the same endpoint.",
    )
    parsed = parser.parse_args()

    # Detect interactive context: only prompt for trust when stdin is a TTY.
    # A piped --once invocation in CI/scripts would otherwise deadlock on input().
    is_interactive = sys.stdin.isatty()

    try:
        result = startup(
            interactive=is_interactive,
            auto_trust=parsed.trust,
            quiet=parsed.once is not None or parsed.quiet,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        # Pick a hint based on the error type so the panel suggests an
        # actionable next step rather than just dumping the exception.
        if isinstance(exc, FileNotFoundError):
            hint = (
                "Run `tigger-code` from a directory with a .tigger/config.json "
                "or create ~/.tigger/config.json. `tigger-code /init --global` "
                "scaffolds the user-level layout."
            )
        elif isinstance(exc, ValueError):
            hint = "Check .tigger/config.json for malformed JSON or invalid keys."
        else:
            hint = "Check filesystem permissions on .tigger/ and ~/.tigger/."
        ui.print_error_panel("Startup failed", str(exc), hint=hint)
        sys.exit(1)

    if parsed.mode is not None:
        from tigger.config import _MODE_RENAME
        mode = _MODE_RENAME.get(parsed.mode, parsed.mode)
        result.ctx.config = dataclasses.replace(result.ctx.config, mode=mode)
    if parsed.permission is not None:
        result.ctx.config = dataclasses.replace(result.ctx.config, permission_mode=parsed.permission)
    if parsed.model is not None:
        # Restrict CLI override to configured models so this flag can't be
        # used to call arbitrary wire ids the endpoint happens to expose.
        # Tries provider/model first, then falls back to slug-search — slugs
        # like "qwen/qwen3.6-35b-a3b" contain '/' so the provider-prefix
        # parse can fail and we still need the slug match.
        from tigger.config import switch_model
        cfg = result.ctx.config
        target = parsed.model
        chosen: tuple[str, str] | None = None
        if "/" in target:
            prov_name, model_name = target.split("/", 1)
            if prov_name in cfg.providers and model_name in cfg.providers[prov_name].model_names:
                chosen = (prov_name, model_name)
        if chosen is None:
            matches = [
                (p, target) for p, prov in cfg.providers.items()
                if target in prov.model_names
            ]
            if len(matches) == 1:
                chosen = matches[0]
            elif len(matches) > 1:
                ui.print_error(
                    f"--model {target!r} matches multiple providers; "
                    f"use provider/model form: {', '.join(f'{p}/{target}' for p, _ in matches)}"
                )
                sys.exit(1)
        if chosen is None:
            available = sorted({m for prov in cfg.providers.values() for m in prov.model_names})
            ui.print_error(
                f"--model {target!r}: not in any configured provider. "
                f"Available: {', '.join(available)}"
            )
            sys.exit(1)
        result.ctx.config = switch_model(cfg, *chosen)
    if parsed.no_think:
        # Mirror /think off (iter 79) — flip enable_thinking before any turn runs.
        # Must run AFTER --model: switch_model copies the target's per-model
        # chat_template_kwargs onto the config, so --no-think before --model
        # was silently overwritten on the qwen3.6-27b-thinking slug.
        # No-op for non-Qwen models: gemma/llama jinja templates reject
        # `enable_thinking` with a cryptic UndefinedValue error.
        existing = result.ctx.config.chat_template_kwargs or {}
        if "enable_thinking" in existing:
            kwargs = dict(existing)
            kwargs["enable_thinking"] = False
            result.ctx.config = dataclasses.replace(
                result.ctx.config, chat_template_kwargs=kwargs,
            )

    # Validate mode against resolved mode names
    mode_names = {m.name for m in result.ctx.modes}
    if mode_names and result.ctx.config.mode not in mode_names:
        ui.print_error(
            f"Unknown mode {result.ctx.config.mode!r}. "
            f"Available: {', '.join(sorted(mode_names))}. Falling back to 'act'."
        )
        result.ctx.config = dataclasses.replace(result.ctx.config, mode="act")

    # --once: single non-interactive turn
    if parsed.once is not None:
        # Reasoning models often prefix their reply with leading whitespace
        # (e.g. "\n\n<answer>"). Strip those leading newlines so scripted
        # callers don't have to .strip() every result themselves.
        seen_content = False
        last_ended_with_newline = False
        try:
            for event in run(parsed.once, result.ctx, result.registry,
                             provider_fn=result.provider_fn,
                             hook_defs=result.hook_defs):
                if isinstance(event, TextChunk):
                    content = event.content
                    if not seen_content:
                        content = content.lstrip()
                        if not content:
                            continue
                        seen_content = True
                    print(content, end="", flush=True)
                    last_ended_with_newline = content.endswith("\n")
        except KeyboardInterrupt:
            sys.stderr.write("interrupted\n")
            sys.exit(130)
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError) as exc:
            sys.stderr.write(f"network error: {exc}\n")
            sys.exit(2)
        except openai.APIError as exc:
            msg = str(exc)
            sys.stderr.write(f"provider rejected request: {msg}\n")
            if "UndefinedValue" in msg or "jinja" in msg.lower():
                sys.stderr.write(
                    "hint: the model's chat template can't render the "
                    "request — likely no `tools` support or unknown "
                    "chat_template_kwargs. Try a lmstudio-community "
                    "variant, or set `\"disable_tools\": true` on this "
                    "model in config.json to run it chat-only.\n"
                )
            sys.exit(2)
        except Exception as exc:
            if "TimeoutError" in type(exc).__name__ or "timed out" in str(exc).lower():
                sys.stderr.write("request timed out\n")
                sys.exit(2)
            raise
        if not seen_content:
            sys.stderr.write("empty response\n")
            sys.exit(1)
        # Only emit a trailing newline if the model's last chunk didn't
        # already end with one. Avoids spurious blank lines in piped output
        # when the response is multi-line.
        if not last_ended_with_newline:
            print()
        sys.exit(0)

    # Session setup
    session_dir = project_session_dir(home_config_dir(), pathlib.Path.cwd().resolve())
    session_id: str | None = None

    if parsed.resume:
        sessions = list_sessions(session_dir)
        if sessions:
            latest = sessions[0]
            result.ctx.messages = load_session(latest.path)
            session_id = latest.timestamp
            stamp = ui.format_session_id(session_id)
            ctx_used = estimate_tokens(result.ctx.messages)
            ui.console.print(
                f"[dim]✓ Resumed[/dim] [cyan]{stamp}[/cyan] "
                f"[dim]·[/dim] [bold]{latest.message_count}[/bold] "
                f"[dim]message{'s' if latest.message_count != 1 else ''} "
                f"·[/dim] [dim]{ctx_used:,} tokens[/dim]"
            )
        else:
            ui.console.print(
                "[dim]No previous sessions found — starting fresh.[/dim]"
            )
            session_id = new_session_id()
    else:
        session_id = new_session_id()

    repl(result, session_id=session_id, session_dir=session_dir)


if __name__ == "__main__":
    main()
