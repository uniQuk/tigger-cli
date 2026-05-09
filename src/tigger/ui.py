from __future__ import annotations

import pathlib
import random
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

from tigger._constants import CONFIG_DIR, home_config_dir
from tigger._spinners import pick_message
from tigger.types import (
    PermissionRequest,
    StreamProgress,
    TextChunk,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
    TurnDoneEvent,
)

_THEME = Theme({
    "markdown.code": "bold #ffb300",
    "markdown.code_block": "#ff8c00",
    "markdown.h1": "bold #ffb300",
    "markdown.h2": "bold #ff8c00",
    "markdown.h3": "bold #ff6600",
    "markdown.strong": "bold #ffb300",
    "markdown.emph": "italic #ff8c00",
})

console = Console(theme=_THEME)

recent_tools: deque[str] = deque(maxlen=5)

_tool_buffer: list[tuple[str, str]] = []
# Parallel lists matched by index. Filled at ToolStart (call_id + "") and
# updated at ToolEnd by call_id lookup. Cleared together when the buffer
# flushes. ``_tool_details`` carries multi-line content (e.g. an edit diff)
# rendered as an indented block below the entry.
_tool_call_ids: list[str] = []
_tool_summaries: list[str] = []
_tool_details: list[str] = []
BATCHABLE_TOOLS = {"read", "glob", "grep"}

_activity_status = None
_activity_stop = None
_activity_thread = None
_turn_start: float | None = None
_turn_token_counter: list[int] | None = None


def set_turn_start(start: float | None, token_counter: list[int] | None = None) -> None:
    """Record the wall-clock start of the current turn so live spinners can show elapsed time and tokens."""
    global _turn_start, _turn_token_counter
    _turn_start = start
    _turn_token_counter = token_counter


def _start_activity(message: str, *, rotate: bool = False) -> None:
    """Start or update a live status spinner.

    Always runs a background ticker so the elapsed-time counter stays live,
    even between tool calls. When *rotate* is True, the message also cycles
    through random spinner messages every 2.5-5s.
    """
    global _activity_status, _activity_stop, _activity_thread
    # Stop any existing ticker thread but keep the status object alive
    if _activity_stop is not None:
        _activity_stop.set()
        if _activity_thread is not None:
            _activity_thread.join(timeout=0.3)
        _activity_stop = None
        _activity_thread = None

    if _activity_status is None:
        _activity_status = console.status("", spinner="dots")
        _activity_status.start()

    _activity_stop = threading.Event()

    def _tick() -> None:
        msg = message
        next_change = time.time() + random.uniform(2.5, 5.0)
        while not _activity_stop.is_set():
            now = time.time()
            if rotate and now >= next_change:
                msg = pick_message()
                next_change = now + random.uniform(2.5, 5.0)
            # Snapshot module globals — set_turn_start may clear them mid-tick.
            ts = _turn_start
            tc = _turn_token_counter
            parts = [msg]
            if ts is not None:
                parts.append(format_elapsed(now - ts))
            if tc and tc[0] > 0:
                parts.append(f"↓ {tc[0] // 4} tokens")
            _activity_status.update(f"[#999999]{' · '.join(parts)}[/]")
            _activity_stop.wait(0.5)

    _activity_thread = threading.Thread(target=_tick, daemon=True)
    _activity_thread.start()


def _stop_activity() -> None:
    """Stop the live status spinner if one is running."""
    global _activity_status, _activity_stop, _activity_thread
    if _activity_stop is not None:
        _activity_stop.set()
        if _activity_thread is not None:
            _activity_thread.join(timeout=0.3)
        _activity_stop = None
        _activity_thread = None
    if _activity_status is not None:
        _activity_status.stop()
        _activity_status = None


def _tool_counter_message() -> str:
    """Build a live status message summarising buffered tool calls.

    When exactly one tool is active, show its preview (Claude-style):
    ``\u25cf Read(loop.py)``. With multiple, fall back to a grouped count:
    ``\u25cf 3 tools (read\u00d72, grep)``.
    """
    if not _tool_buffer:
        return ""
    if len(_tool_buffer) == 1:
        name, preview = _tool_buffer[0]
        nice = name.capitalize()
        if preview:
            return f"[#999999]\u23fa {nice}({preview})[/]"
        return f"[#999999]\u23fa {nice}[/]"
    counts: dict[str, int] = {}
    for name, _ in _tool_buffer:
        counts[name] = counts.get(name, 0) + 1
    parts = ", ".join(f"{n}\u00d7{c}" if c > 1 else n for n, c in counts.items())
    total = len(_tool_buffer)
    return f"[#999999]\u23fa {total} tools ({parts})[/]"

_LOGO_LINES = [
    " ████████╗██╗  ██████╗  ██████╗ ███████╗██████╗ ",
    "    ██╔══╝██║ ██╔════╝ ██╔════╝ ██╔════╝██╔══██╗",
    "    ██║   ██║ ██║  ███╗██║  ███╗█████╗  ██████╔╝",
    "    ██║   ██║ ██║   ██║██║   ██║██╔══╝  ██╔══██╗",
    "    ██║   ██║ ╚██████╔╝╚██████╔╝███████╗██║  ██║",
    "    ╚═╝   ╚═╝  ╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝",
]

_CAT_LINES = [
    r" /\_/\ ",
    r"( o.o )",
    r" > ^ < ",
]


def _gradient_line(line: str, max_width: int) -> str:
    """Render one logo line with an amber→orange-red left-to-right gradient."""
    out = []
    for col, ch in enumerate(line):
        if ch == " ":
            out.append(" ")
        else:
            t = col / max(max_width - 1, 1)
            r = 255
            g = int(179 + (69 - 179) * t)   # 179 (#b3) → 69 (#45)
            b = 0
            out.append(f"[#{r:02x}{g:02x}{b:02x}]{ch}[/]")
    return "".join(out)


def print_startup_info(provider: str, model: str, cwd: str, rtk: bool = False) -> None:
    """Print provider/model info, cwd, and a usage tip below the logo."""
    rtk_badge = "  [green]rtk[/green]" if rtk else ""
    console.print(
        f"      [bold]{provider}[/bold] | [bold cyan]{model}[/bold cyan]{rtk_badge} "
        "[dim](/model to change)[/dim]"
    )
    console.print(f"      [dim]{cwd}[/dim]")
    console.print(
        "      [dim]tip:[/dim] [cyan]/help[/cyan][dim] for commands · "
        "type a message to chat[/dim]"
    )
    console.print()


def print_logo(provider: str | None = None, model: str | None = None, cwd: str | None = None, rtk: bool = False) -> None:
    """Print the logo with cat and startup info below."""
    logo_width = max(len(line) for line in _LOGO_LINES)
    for line in _LOGO_LINES:
        console.print(_gradient_line(line, logo_width), highlight=False)
    console.print()
    for cl in _CAT_LINES:
        console.print(f"      {cl}")
    console.print("      [bold]Tigger — AI Agent[/bold]")
    if provider is not None and model is not None and cwd is not None:
        print_startup_info(provider, model, cwd, rtk=rtk)
    else:
        console.print()


def format_elapsed(seconds: float) -> str:
    """Compact elapsed-time format for live spinners: 42s, 5m 12s, 23m, 1h 4m."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 600:
        return f"{s // 60}m {s % 60}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h {(s % 3600) // 60}m"


def format_duration(seconds: float) -> str:
    """Format seconds into human-friendly duration: 2.3s, 11m 36s, 1h 2m."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m = int(seconds) // 60
        s = int(seconds) % 60
        return f"{m}m {s}s"
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    return f"{h}h {m}m"


def _rtk_project_totals() -> tuple[int, int, int] | None:
    """Query RTK for project-scoped totals. Returns (saved, input, output) or None."""
    if not shutil.which("rtk"):
        return None
    try:
        result = subprocess.run(
            ["rtk", "gain", "--project", "--format", "json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        import json
        data = json.loads(result.stdout)
        summary = data.get("summary", {})
        return (
            summary.get("total_saved", 0),
            summary.get("total_input", 0),
            summary.get("total_output", 0),
        )
    except Exception:
        return None


@dataclass
class SessionStats:
    """Tracks session-level metrics for the exit summary."""
    start_time: float = field(default_factory=time.time)
    turns: int = 0
    tool_calls: int = 0
    tool_success: int = 0
    tool_errors: int = 0
    tool_denied: int = 0
    output_tokens: int = 0
    tool_names: dict[str, int] = field(default_factory=dict)
    rtk_saved_at_start: int = 0
    rtk_input_at_start: int = 0

    def record_tool_end(self, event: ToolEndEvent) -> None:
        self.tool_calls += 1
        if not event.permitted:
            self.tool_denied += 1
        elif event.error:
            self.tool_errors += 1
        else:
            self.tool_success += 1
        self.tool_names[event.name] = self.tool_names.get(event.name, 0) + 1

    def snapshot_rtk(self) -> None:
        """Capture RTK totals at session start for diffing on exit."""
        totals = _rtk_project_totals()
        if totals:
            self.rtk_saved_at_start, self.rtk_input_at_start, _ = totals

    def rtk_session_savings(self) -> tuple[int, float] | None:
        """Return (tokens_saved, pct) for this session only, or None."""
        totals = _rtk_project_totals()
        if totals is None:
            return None
        saved_now, input_now, _ = totals
        session_saved = saved_now - self.rtk_saved_at_start
        session_input = input_now - self.rtk_input_at_start
        if session_saved <= 0:
            return None
        pct = session_saved / session_input * 100 if session_input > 0 else 0
        return session_saved, pct


def print_session_summary(
    stats: SessionStats,
    session_id: str | None,
    model: str,
    rtk_enabled: bool,
) -> None:
    """Print a boxed session summary on exit."""
    wall = time.time() - stats.start_time
    lines: list[str] = []

    lines.append("[bold]Session Summary[/bold]")
    lines.append("")

    if session_id:
        lines.append(f"  Session:       {session_id}")
    lines.append(f"  Model:         {model}")
    lines.append(f"  Duration:      {format_duration(wall)}")
    lines.append(f"  Turns:         {stats.turns}")
    lines.append(f"  Output:        ~{stats.output_tokens:,} tokens")

    if stats.tool_calls > 0:
        lines.append("")
        pct = stats.tool_success / stats.tool_calls * 100 if stats.tool_calls else 0
        lines.append(f"  Tools:         {stats.tool_calls}  "
                      f"( [green]\u2713 {stats.tool_success}[/green]"
                      f"  [red]\u2717 {stats.tool_errors}[/red]"
                      f"  [yellow]\u2298 {stats.tool_denied}[/yellow] )")
        lines.append(f"  Success:       {pct:.0f}%")

        # Top tools breakdown
        top = sorted(stats.tool_names.items(), key=lambda x: x[1], reverse=True)[:5]
        if top:
            breakdown = ", ".join(f"{n} \u00d7{c}" if c > 1 else n for n, c in top)
            lines.append(f"  Top tools:     {breakdown}")

    if rtk_enabled:
        rtk_savings = stats.rtk_session_savings()
        if rtk_savings:
            saved, pct = rtk_savings
            lines.append("")
            lines.append(f"  [green]RTK:[/green]          {saved:,} tokens saved ({pct:.0f}%)")

    if session_id:
        lines.append("")
        lines.append("  [dim]Resume: tigger-code -c[/dim]")

    console.print()
    console.print(Panel(
        "\n".join(lines),
        border_style="dim",
        padding=(1, 2),
    ))


def print_turn_summary(tokens: int, elapsed: float) -> None:
    console.print(f"[dim]· {tokens} tokens · {format_duration(elapsed)}[/dim]")


def print_error(msg: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {msg}")


def print_info(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")


def ask_permission(request: PermissionRequest) -> bool:
    """Prompt user to allow/deny a tool call. Returns True only if user types 'y'.

    Renders a Rich Panel with a concise tool-call preview (using the same
    helper as the live spinner) so writes/edits with multi-KB content don't
    flood the prompt with escaped JSON. Designed for use as the loop's
    ``permission_callback``.
    """
    _stop_activity()
    preview = _extract_preview(request.name, request.args)
    title = f"[bold]{request.name.capitalize()}[/bold]"
    if preview:
        title = f"{title}([cyan]{preview}[/cyan])"
    panel = Panel(
        "[yellow]Allow this tool call?[/yellow]",
        title=title,
        title_align="left",
        border_style="yellow",
        padding=(0, 1),
    )
    console.print()
    console.print(panel)
    answer = input("  [y/N] ").strip().lower()
    return answer == "y"


def run_setup_wizard(project_dir: pathlib.Path) -> tuple[pathlib.Path, dict]:
    """Interactive first-run setup. Returns (config_path, config_data)."""
    from tigger.config import derive_provider_name, write_config
    from tigger.types import Config, ProviderConfig

    console.print("\n[bold]No config found.[/bold] Let's set up your first provider.\n")

    base_url = input("  Base URL (e.g. http://localhost:1234/v1): ").strip()
    api_key = input("  API key (Enter for 'local'): ").strip() or "local"
    model = input("  Model name (e.g. qwen3, gpt-4o): ").strip()
    location = input(f"  Save to [P]roject or [u]ser (~/{CONFIG_DIR}/)? [P/u]: ").strip().lower()

    provider_name = derive_provider_name(base_url)
    prov = ProviderConfig(name=provider_name, base_url=base_url,
                          api_key=api_key, models=[model])

    if location == "u":
        tigger_dir = home_config_dir()
    else:
        tigger_dir = project_dir / CONFIG_DIR

    config = Config(
        base_url=base_url,
        model=model,
        api_key=api_key,
        providers={provider_name: prov},
        active_provider=provider_name,
    )
    config_path = tigger_dir / "config.json"
    write_config(config_path, config)

    console.print(f"\n  [green]Config saved to {config_path}[/green]\n")
    return config_path, {}


def ask_trust_prompt(cwd: pathlib.Path) -> str:
    """Y/N workspace trust prompt. Returns 'always' (trust + persist) or 'deny' (read-only)."""
    console.print(f"\n[yellow bold]Trust workspace:[/yellow bold] {cwd}")
    while True:
        choice = input("  Continue? [Y/n] ").strip().lower()
        if choice in ("y", ""):
            return "always"
        if choice == "n":
            return "deny"


@contextmanager
def Spinner(start: float, token_counter: list[int] | None = None):
    """
    Show an animated spinner with a live elapsed-time counter while the model
    is thinking. Optionally shows streaming token count.

    Message rotates on a random interval (5-15s) so it feels alive
    without being distracting.
    """
    msg = pick_message()
    stop_event = threading.Event()
    next_change = time.time() + random.uniform(10.0, 30.0)

    with console.status("", spinner="dots") as status:
        def _tick() -> None:
            nonlocal msg, next_change
            while not stop_event.is_set():
                now = time.time()
                if now >= next_change:
                    msg = pick_message()
                    next_change = now + random.uniform(5.0, 15.0)
                elapsed = now - start
                parts = [msg, format_elapsed(elapsed)]
                if token_counter and token_counter[0] > 0:
                    tok = token_counter[0] // 4
                    parts.append(f"↓ {tok} tokens")
                status.update(f"[#999999]{' · '.join(parts)}[/]")
                stop_event.wait(0.1)

        t = threading.Thread(target=_tick, daemon=True)
        t.start()
        try:
            yield
        finally:
            stop_event.set()
            t.join(timeout=0.5)


def _extract_preview(name: str, args: dict) -> str:
    """Return a concise human-readable preview string for a tool call."""
    if name == "read" and "path" in args:
        return pathlib.PurePosixPath(args["path"]).name
    if name == "glob" and "pattern" in args:
        return args["pattern"]
    if name == "grep" and "pattern" in args:
        return f'"{args["pattern"]}"'
    if name == "bash" and "command" in args:
        cmd = args["command"]
        return cmd if len(cmd) <= 60 else cmd[:57] + "..."
    if name in ("write", "edit") and "path" in args:
        # Show just the path — content/diffs are too large for a one-line preview.
        return pathlib.PurePosixPath(str(args["path"])).name
    # Fallback: truncated key=value summary.
    parts = []
    for k, v in args.items():
        sv = repr(v)
        if len(sv) > 40:
            sv = sv[:37] + "..."
        parts.append(f"{k}={sv}")
    preview = ", ".join(parts)
    return preview if len(preview) <= 60 else preview[:57] + "..."


_MAX_BATCH_ITEMS = 5


def _make_edit_diff(args: dict, max_lines: int = 20) -> str:
    """Build a compact unified diff for an edit tool call's args.

    Returns the diff text (with hunk headers) or "" if there's nothing useful
    to show. Truncates beyond ``max_lines`` so a multi-KB replace doesn't
    swamp the buffer flush.
    """
    import difflib

    old = args.get("old_string", "")
    new = args.get("new_string", "")
    path = args.get("path", "")
    if not isinstance(old, str) or not isinstance(new, str):
        return ""
    if old == new:
        return ""
    diff_lines = list(difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile=path,
        tofile=path,
        lineterm="",
        n=2,
    ))
    if not diff_lines:
        return ""
    # Drop the leading +++ / --- header — we already know which file.
    body = [line for line in diff_lines if not line.startswith(("+++", "---"))]
    if len(body) > max_lines:
        extra = len(body) - max_lines
        body = body[:max_lines] + [f"... ({extra} more diff lines)"]
    return "\n".join(body)


def _render_diff_lines(diff_text: str) -> list[str]:
    """Colourise diff lines for the buffer flush. Returns Rich-marked-up lines."""
    out: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            out.append(f"      [cyan]{line}[/cyan]")
        elif line.startswith("+"):
            out.append(f"      [green]{line}[/green]")
        elif line.startswith("-"):
            out.append(f"      [red]{line}[/red]")
        else:
            out.append(f"      [dim]{line}[/dim]")
    return out


def _summarize_tool_output(name: str, output: str) -> str:
    """Build a short Claude-style output summary for the buffered tool flush.

    For multi-line output, returns ``"N lines"``. For a single short line,
    returns the truncated line itself. Returns ``""`` when there's nothing
    worth showing.
    """
    if not output:
        return ""
    output = output.rstrip("\n")
    if not output:
        return ""
    lines = output.split("\n")
    n = len(lines)
    if n == 1:
        first = lines[0].strip()
        if not first:
            return ""
        return first if len(first) <= 60 else first[:57] + "..."
    if name == "grep":
        return f"{n} matches"
    if name == "glob":
        return f"{n} files"
    return f"{n} lines"


def _entry_with_summary(preview: str, summary: str) -> str:
    """Format a single buffered entry's preview, optionally with a dim summary."""
    if summary:
        return f"{preview} [dim]({summary})[/dim]"
    return preview


def _flush_tool_buffer() -> None:
    """Render buffered tool calls as a grouped block and clear the buffer.

    Each entry can carry a Claude-style output summary (e.g. ``421 lines``)
    captured at ToolEnd. Summaries render inline next to the preview.
    """
    if not _tool_buffer:
        return

    # Pad parallel lists defensively in case a caller seeded _tool_buffer
    # directly (some tests do).
    while len(_tool_summaries) < len(_tool_buffer):
        _tool_summaries.append("")
    while len(_tool_details) < len(_tool_buffer):
        _tool_details.append("")

    lines: list[str] = []
    i = 0
    while i < len(_tool_buffer):
        name, preview = _tool_buffer[i]
        summary = _tool_summaries[i]
        # Batch consecutive entries with the same batchable name.
        if name in BATCHABLE_TOOLS:
            entries = [_entry_with_summary(preview, summary)]
            j = i + 1
            while j < len(_tool_buffer) and _tool_buffer[j][0] == name:
                entries.append(_entry_with_summary(_tool_buffer[j][1], _tool_summaries[j]))
                j += 1
            if len(entries) <= _MAX_BATCH_ITEMS:
                lines.append(f"  [dim]{name}:[/dim] {', '.join(entries)}")
            else:
                shown = ', '.join(entries[:_MAX_BATCH_ITEMS])
                extra = len(entries) - _MAX_BATCH_ITEMS
                lines.append(f"  [dim]{name}:[/dim] {shown} (+{extra} more)")
            i = j
        else:
            lines.append(f"  [dim]{name}:[/dim] {_entry_with_summary(preview, summary)}")
            if _tool_details[i]:
                lines.extend(_render_diff_lines(_tool_details[i]))
            i += 1

    console.print("[dim]──────── tools ────────[/dim]")
    for line in lines:
        console.print(line)
    console.print("[dim]───────────────────────[/dim]")
    _tool_buffer.clear()
    _tool_call_ids.clear()
    _tool_summaries.clear()
    _tool_details.clear()


_THINK_RE = re.compile(r"<think>(.*?)</think>\s*", re.DOTALL)


def _split_think(text: str) -> list[tuple[str, str]]:
    """Split a stream into ('think', body) and ('text', body) segments in order.

    Reasoning models that emit ``<think>...</think>`` inline in content would
    otherwise be silently dropped by the Markdown renderer (HTML stripping).
    Pulling them out lets us render thinking dimmed so the user can see it
    happened, while everything else still goes through Markdown.
    """
    segments: list[tuple[str, str]] = []
    pos = 0
    for m in _THINK_RE.finditer(text):
        if m.start() > pos:
            segments.append(("text", text[pos:m.start()]))
        segments.append(("think", m.group(1).strip()))
        pos = m.end()
    if pos < len(text):
        segments.append(("text", text[pos:]))
    return segments


def _build_text_renderable(text: str):
    """Compose a Group of rendered segments (think dimmed, body as Markdown)."""
    blocks = []
    for kind, body in _split_think(text):
        if not body.strip():
            continue
        if kind == "think":
            preview = body if len(body) <= 600 else body[:597] + "..."
            blocks.append(Text.from_markup(f"[dim italic]{preview}[/dim italic]"))
        else:
            blocks.append(Markdown(body))
    return Group(*blocks)


# Live display used to stream assistant text chunk-by-chunk. When the next
# non-text event (tool / think / turn-done) arrives, the live is stopped —
# the last frame stays in place and ``text_buf`` is cleared.
_live: Live | None = None


def _start_or_update_live(text_buf: list[str]) -> None:
    """Start a Live and/or update its renderable to the current text buffer.

    Called on every TextChunk so the user sees text as it streams.
    """
    global _live
    if not text_buf:
        return
    full = "".join(text_buf)
    renderable = _build_text_renderable(full)
    if _live is None:
        _live = Live(
            renderable,
            console=console,
            refresh_per_second=12,
            transient=False,
            vertical_overflow="visible",
        )
        _live.start()
    else:
        _live.update(renderable)


def _flush_text(text_buf: list[str]) -> None:
    """Finalise streamed text and clear the buffer.

    If a streaming Live is active (the common path from TextChunk handling),
    stop it — the last frame stays on screen. Otherwise (direct callers,
    tests) render the accumulated text explicitly so behaviour matches the
    streaming path.
    """
    global _live
    if _live is not None:
        # Last live frame already shows the full content; keep it.
        _live.stop()
        _live = None
        text_buf.clear()
        return
    if not text_buf:
        return
    full = "".join(text_buf)
    console.print(_build_text_renderable(full))
    text_buf.clear()


def render_event(event, output_chars: list[int], text_buf: list[str]) -> None:
    """Render one agent event to the terminal.

    ``output_chars`` is a 1-element mutable list accumulating character count.
    ``text_buf`` is a mutable list that collects TextChunk content; flushed as
    Rich Markdown before tool events and at turn end.
    """
    if isinstance(event, TextChunk):
        _stop_activity()
        _flush_tool_buffer()
        text_buf.append(event.content)
        output_chars[0] += len(event.content)
        # Live-stream the text so the user sees it appear chunk-by-chunk
        # instead of waiting for the next non-text event to flush.
        _start_or_update_live(text_buf)
    elif isinstance(event, StreamProgress):
        output_chars[0] += event.chars
        # Reasoning streaming arrives as StreamProgress without TextChunks. Keep
        # the user oriented: if no activity spinner is up, start one so a long
        # think looks alive instead of silent.
        if _activity_status is None:
            _start_activity(pick_message(), rotate=True)
    elif isinstance(event, ToolStartEvent):
        _flush_text(text_buf)
        recent_tools.append(event.name)
        _tool_buffer.append((event.name, _extract_preview(event.name, event.args)))
        _tool_call_ids.append(event.call_id)
        _tool_summaries.append("")
        # For edits, capture a unified diff up-front from the args. We'll
        # discard it again at ToolEnd if the edit failed.
        _tool_details.append(_make_edit_diff(event.args) if event.name == "edit" else "")
        _start_activity(_tool_counter_message())
    elif isinstance(event, ToolEndEvent):
        _stop_activity()
        # Only surface errors and denials — successful tool calls stay quiet
        # and their output summary lands in the next buffer flush.
        if not event.permitted:
            console.print("  [dim]⎿[/dim]  [yellow](denied)[/yellow]")
        elif event.error:
            out = event.output[:120].replace("\n", " · ").rstrip(" · ")
            console.print(f"  [dim]⎿[/dim]  [red]{out}[/red]")
            try:
                idx = _tool_call_ids.index(event.call_id)
            except ValueError:
                idx = -1
            if 0 <= idx < len(_tool_details):
                _tool_details[idx] = ""  # don't render diff for failed edits
        else:
            try:
                idx = _tool_call_ids.index(event.call_id)
            except ValueError:
                idx = -1
            if 0 <= idx < len(_tool_summaries):
                _tool_summaries[idx] = _summarize_tool_output(event.name, event.output)
    elif isinstance(event, ThinkingEvent):
        _stop_activity()
        _flush_tool_buffer()
        _flush_text(text_buf)
        _start_activity(pick_message(), rotate=True)
    elif isinstance(event, TurnDoneEvent):
        _stop_activity()
        _flush_tool_buffer()
        _flush_text(text_buf)
        print()
