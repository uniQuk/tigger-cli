from __future__ import annotations
import pathlib
import random
import threading
import time
from contextlib import contextmanager
from rich.console import Console
from rich.markdown import Markdown
from rich.theme import Theme
from newcli._spinners import SPINNER_MESSAGES
from newcli.types import RunContext, TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent, TurnDoneEvent

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

_LOGO_LINES = [
    " ████████╗██╗  ██████╗  ██████╗ ███████╗██████╗ ",
    "    ██╔══╝██║ ██╔════╝ ██╔════╝ ██╔════╝██╔══██╗",
    "    ██║   ██║ ██║  ███╗██║  ███╗█████╗  ██████╔╝",
    "    ██║   ██║ ██║   ██║██║   ██║██╔══╝  ██╔══██╗",
    "    ██║   ██║ ╚██████╔╝╚██████╔╝███████╗██║  ██║",
    "    ╚═╝   ╚═╝  ╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝",
]

_LOGO_FOOTER = """\

      /\\_/\\      Tigger — AI Agent
     ( o.o )
      > ^ <      [dim]a minimal, clean CLI[/dim]
"""


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


def print_logo() -> None:
    max_width = max(len(line) for line in _LOGO_LINES)
    for line in _LOGO_LINES:
        console.print(_gradient_line(line, max_width), highlight=False)
    console.print(_LOGO_FOOTER)


def print_status(model: str, used: int, limit: int, mode: str, permission: str) -> None:
    console.print(
        f"[dim][[/dim][bold cyan]{model}[/bold cyan][dim]] "
        f"{used}/{limit} tokens · mode=[/dim][bold]{mode}[/bold]"
        f"[dim] · perm=[/dim][bold]{permission}[/bold]",
        end="",
    )


def print_tool_start(name: str, args: dict) -> None:
    args_str = ", ".join(f"{k}={repr(v)[:40]}" for k, v in args.items()) if args else ""
    console.print(f"\n[bold]⏺[/bold] [dim]{name}[/dim]({args_str})")


def print_tool_end(name: str, status: str, output: str) -> None:
    out = output[:200].replace("\n", "\n       ")
    if status == "error":
        console.print(f"  [dim]⎿[/dim]  [red]{out}[/red]")
    elif status == "denied":
        console.print(f"  [dim]⎿[/dim]  [yellow](denied)[/yellow]")
    else:
        console.print(f"  [dim]⎿[/dim]  [dim]{out}[/dim]")


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


def print_success(msg: str) -> None:
    console.print(f"[green]{msg}[/green]")


def ask_permission(name: str, args: dict) -> bool:
    """Prompt user to allow/deny a tool call. Returns True only if user types 'y'."""
    console.print(f"\n[yellow]Allow[/yellow] [bold]{name}[/bold]({args})?", end=" ")
    answer = input("[y/N] ").strip().lower()
    return answer == "y"


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
def Spinner(start: float):
    """
    Show an animated spinner with a live elapsed-time counter while the model
    is thinking (before the first streaming chunk arrives).

    ``start`` should be ``time.time()`` captured at the top of the turn so the
    elapsed time is continuous across thinking + streaming phases.
    """
    msg = random.choice(SPINNER_MESSAGES)
    stop_event = threading.Event()

    with console.status("", spinner="dots") as status:
        def _tick() -> None:
            while not stop_event.is_set():
                elapsed = time.time() - start
                status.update(f"[dim]{msg} · {elapsed:.0f}s[/dim]")
                stop_event.wait(0.1)

        t = threading.Thread(target=_tick, daemon=True)
        t.start()
        try:
            yield
        finally:
            stop_event.set()
            t.join(timeout=0.5)


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
        text_buf.append(event.content)
        output_chars[0] += len(event.content)
    elif isinstance(event, ToolStartEvent):
        _flush_text(text_buf)
        console.print(f"\n[bold]⏺[/bold] [dim]{event.name}[/dim]({_fmt_args(event.args)})")
    elif isinstance(event, ToolEndEvent):
        # Only surface errors and denials — successful tool calls stay quiet.
        if not event.permitted:
            console.print(f"  [dim]⎿[/dim]  [yellow](denied)[/yellow]")
        elif event.error:
            out = event.output[:120].replace("\n", " · ").rstrip(" · ")
            console.print(f"  [dim]⎿[/dim]  [red]{out}[/red]")
    elif isinstance(event, PermissionEvent):
        event.granted = ask_permission(event.name, event.args)
    elif isinstance(event, TurnDoneEvent):
        _flush_text(text_buf)
        print()
