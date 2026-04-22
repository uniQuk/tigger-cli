from __future__ import annotations
import pathlib
import random
import threading
import time
from contextlib import contextmanager
from rich.console import Console

console = Console()

SPINNER_MESSAGES = [
    "Bouncing through the codebase...",
    "Consulting the whiskers...",
    "Chasing the laser pointer of insight...",
    "T-I-double-guh-er thinking...",
    "Sniffing out an answer...",
    "Padding softly through your files...",
    "I'm Feeling Lucky",
    'Shipping awesomeness...',
    'Painting the serifs back on...',
    'Navigating the slime mold...',
    'Consulting the digital spirits...',
    'Reticulating splines...',
    'Warming up the AI hamsters...',
    'Asking the magic conch shell...',
    'Generating witty retort...',
    'Polishing the algorithms...',
    "Don't rush perfection (or my code)...",
    'Brewing fresh bytes...',
    'Counting electrons...',
    'Engaging cognitive processors...',
    'Checking for syntax errors in the universe...',
    'One moment, optimizing humor...',
    'Shuffling punchlines...',
    'Untangling neural nets...',
    'Compiling brilliance...',
    'Loading wit.exe...',
    'Summoning the cloud of wisdom...',
    'Preparing a witty response...',
    "Just a sec, I'm debugging reality...",
    'Confuzzling the options...',
    'Tuning the cosmic frequencies...',
    'Crafting a response worthy of your patience...',
    'Compiling the 1s and 0s...',
    'Resolving dependencies... and existential crises...',
    'Defragmenting memories... both RAM and personal...',
    'Rebooting the humor module...',
    'Caching the essentials (mostly cat memes)...',
    'Optimizing for ludicrous speed',
    "Swapping bits... don't tell the bytes...",
    'Garbage collecting... be right back...',
    'Assembling the interwebs...',
    'Converting coffee into code...',
    'Updating the syntax for reality...',
    'Rewiring the synapses...',
    'Looking for a misplaced semicolon...',
    "Greasin' the cogs of the machine...",
    'Pre-heating the servers...',
    'Calibrating the flux capacitor...',
    'Engaging the improbability drive...',
    'Channeling the Force...',
    'Aligning the stars for optimal response...',
    'So say we all...',
    'Loading the next great idea...',
    "Just a moment, I'm in the zone...",
    'Preparing to dazzle you with brilliance...',
    "Just a tick, I'm polishing my wit...",
    "Hold tight, I'm crafting a masterpiece...",
    "Just a jiffy, I'm debugging the universe...",
    "Just a moment, I'm aligning the pixels...",
    "Just a sec, I'm optimizing the humor...",
    "Just a moment, I'm tuning the algorithms...",
    'Warp speed engaged...',
    'Mining for more Dilithium crystals...',
    "Don't panic...",
    'Following the white rabbit...',
    'The truth is in here... somewhere...',
    'Blowing on the cartridge...',
    'Loading... Do a barrel roll!',
    'Waiting for the respawn...',
    'Finishing the Kessel Run in less than 12 parsecs...',
    "The cake is not a lie, it's just still loading...",
    'Fiddling with the character creation screen...',
    "Just a moment, I'm finding the right meme...",
    "Pressing 'A' to continue...",
    'Herding digital cats...',
    'Polishing the pixels...',
    'Finding a suitable loading screen pun...',
    'Distracting you with this witty phrase...',
    'Almost there... probably...',
    'Our hamsters are working as fast as they can...',
    'Giving Cloudy a pat on the head...',
    'Petting the cat...',
    'Never gonna give you up, never gonna let you down...',
    'Slapping the bass...',
    'Tasting the snozberries...',
    "I'm going the distance, I'm going for speed...",
    'Is this the real life? Is this just fantasy?...',
    "I've got a good feeling about this...",
    'Poking the bear...',
    'Hmmm... let me think...',
    'What do you call a fish with no eyes? A fsh...',
    'Applying percussive maintenance...',
    'Searching for the correct USB orientation...',
    'Ensuring the magic smoke stays inside the wires...',
    'Trying to exit Vim...',
    'Spinning up the hamster wheel...',
    "That's not a bug, it's an undocumented feature...",
    'Engage.',
    "I'll be back... with an answer.",
    'My other process is a TARDIS...',
    'Communing with the machine spirit...',
    'Letting the thoughts marinate...',
    'Pondering the orb...',
    'Initiating thoughtful gaze...',
    'Making it go beep boop.',
    'Buffering... because even AIs need a moment.',
    'Entangling quantum particles for a faster response...',
    'Constructing additional pylons...',
]

_LOGO_LINES = [
    " ████████╗█╗  ██████╗  ██████╗ ███████╗██████╗ ",
    "    ██╔══╝█╗ ██╔════╝ ██╔════╝ ██╔════╝██╔══██╗",
    "    ██║   █╗ █╗ ██║  ███╗██║  ███╗█████╗  ██████╔╝",
    "    ██║   █╗ █╗ ██║   ██║██║   ██║██╔══╝  ██╔══██╗",
    "    ██║   █╗ █╗ ╚██████╔╝╚██████╔╝███████╗██║  ██║",
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


def print_turn_summary(tokens: int, elapsed: float) -> None:
    console.print(f"[dim]· {tokens} tokens · {elapsed:.1f}s[/dim]")


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
