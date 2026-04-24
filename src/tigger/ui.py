from __future__ import annotations
import pathlib
import random
import threading
import time
from collections import deque
from contextlib import contextmanager
from rich.console import Console
from rich.markdown import Markdown
from rich.theme import Theme
from tigger._spinners import SPINNER_MESSAGES
from tigger.types import RunContext, TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent, TurnDoneEvent, ThinkingEvent
from tigger._constants import CONFIG_DIR, home_config_dir

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
BATCHABLE_TOOLS = {"read", "glob", "grep"}

_activity_status = None


def _start_activity(message: str) -> None:
    """Start or update a live status spinner with the given message."""
    global _activity_status
    if _activity_status is not None:
        _activity_status.update(message)
    else:
        _activity_status = console.status(message, spinner="dots")
        _activity_status.start()


def _stop_activity() -> None:
    """Stop the live status spinner if one is running."""
    global _activity_status
    if _activity_status is not None:
        _activity_status.stop()
        _activity_status = None


def _tool_counter_message() -> str:
    """Build a live status message summarising buffered tool calls."""
    counts: dict[str, int] = {}
    for name, _ in _tool_buffer:
        counts[name] = counts.get(name, 0) + 1
    parts = ", ".join(f"{n}\u00d7{c}" if c > 1 else n for n, c in counts.items())
    total = len(_tool_buffer)
    return f"[dim]\u23fa {total} tool{'s' if total != 1 else ''} ({parts})[/dim]"

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
    """Print provider/model info and cwd below the logo."""
    rtk_badge = "  [green]rtk[/green]" if rtk else ""
    console.print(f"      [bold]{provider}[/bold] | [bold cyan]{model}[/bold cyan]{rtk_badge} [dim](/model to change)[/dim]")
    console.print(f"      [dim]{cwd}[/dim]")
    console.print()


def print_logo(provider: str | None = None, model: str | None = None, cwd: str | None = None, rtk: bool = False) -> None:
    """Print the logo with cat and startup info below."""
    logo_width = max(len(line) for line in _LOGO_LINES)
    for line in _LOGO_LINES:
        console.print(_gradient_line(line, logo_width), highlight=False)
    console.print()
    for cl in _CAT_LINES:
        console.print(f"      {cl}")
    console.print(f"      [bold]Tigger — AI Agent[/bold]")
    if provider is not None and model is not None and cwd is not None:
        print_startup_info(provider, model, cwd, rtk=rtk)
    else:
        console.print()


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


def print_turn_summary(tokens: int, elapsed: float) -> None:
    console.print(f"[dim]· {tokens} tokens · {format_duration(elapsed)}[/dim]")


def print_error(msg: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {msg}")


def print_info(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")


def ask_permission(name: str, args: dict) -> bool:
    """Prompt user to allow/deny a tool call. Returns True only if user types 'y'."""
    console.print(f"\n[yellow]Allow[/yellow] [bold]{name}[/bold]({args})?", end=" ")
    answer = input("[y/N] ").strip().lower()
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
    """
    msg = random.choice(SPINNER_MESSAGES)
    stop_event = threading.Event()

    with console.status("", spinner="dots") as status:
        def _tick() -> None:
            while not stop_event.is_set():
                elapsed = time.time() - start
                parts = [msg, f"{elapsed:.0f}s"]
                if token_counter and token_counter[0] > 0:
                    tok = token_counter[0] // 4
                    parts.append(f"↓ {tok} tokens")
                status.update(f"[dim]{' · '.join(parts)}[/dim]")
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


def _flush_tool_buffer() -> None:
    """Render buffered tool calls as a grouped block and clear the buffer."""
    if not _tool_buffer:
        return

    lines: list[str] = []
    i = 0
    while i < len(_tool_buffer):
        name, preview = _tool_buffer[i]
        # Batch consecutive entries with the same batchable name.
        if name in BATCHABLE_TOOLS:
            previews = [preview]
            j = i + 1
            while j < len(_tool_buffer) and _tool_buffer[j][0] == name:
                previews.append(_tool_buffer[j][1])
                j += 1
            if len(previews) <= _MAX_BATCH_ITEMS:
                lines.append(f"  [dim]{name}:[/dim] {', '.join(previews)}")
            else:
                shown = ', '.join(previews[:_MAX_BATCH_ITEMS])
                extra = len(previews) - _MAX_BATCH_ITEMS
                lines.append(f"  [dim]{name}:[/dim] {shown} (+{extra} more)")
            i = j
        else:
            lines.append(f"  [dim]{name}:[/dim] {preview}")
            i += 1

    console.print("[dim]──────── tools ────────[/dim]")
    for line in lines:
        console.print(line)
    console.print("[dim]───────────────────────[/dim]")
    _tool_buffer.clear()


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
        console.print(Markdown("".join(text_buf)))
        text_buf.clear()


def render_event(event, ctx: RunContext, output_chars: list[int], text_buf: list[str]) -> None:
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
    elif isinstance(event, ToolStartEvent):
        _flush_text(text_buf)
        recent_tools.append(event.name)
        _tool_buffer.append((event.name, _extract_preview(event.name, event.args)))
        _start_activity(_tool_counter_message())
    elif isinstance(event, ToolEndEvent):
        # Only surface errors and denials — successful tool calls stay quiet.
        if not event.permitted:
            _stop_activity()
            console.print(f"  [dim]⎿[/dim]  [yellow](denied)[/yellow]")
        elif event.error:
            _stop_activity()
            out = event.output[:120].replace("\n", " · ").rstrip(" · ")
            console.print(f"  [dim]⎿[/dim]  [red]{out}[/red]")
    elif isinstance(event, PermissionEvent):
        _stop_activity()
        event.granted = ask_permission(event.name, event.args)
    elif isinstance(event, ThinkingEvent):
        _stop_activity()
        _flush_tool_buffer()
        _flush_text(text_buf)
        msg = random.choice(SPINNER_MESSAGES)
        _start_activity(f"[dim]{msg}[/dim]")
    elif isinstance(event, TurnDoneEvent):
        _stop_activity()
        _flush_tool_buffer()
        _flush_text(text_buf)
        print()
