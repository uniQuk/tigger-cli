from __future__ import annotations
import pathlib
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
    'Shipping awesomeness... ',
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
    'Rickrolling my boss...',
    'Never gonna give you up, never gonna let you down...',
    'Slapping the bass...',
    'Tasting the snozberries...',
    "I'm going the distance, I'm going for speed...",
    'Is this the real life? Is this just fantasy?...',
    "I've got a good feeling about this...",
    'Poking the bear...',
    'Doing research on the latest memes...',
    'Figuring out how to make this more witty...',
    'Hmmm... let me think...',
    'What do you call a fish with no eyes? A fsh...',
    'Why did the computer go to therapy? It had too many bytes...',
    "Why don't programmers like nature? It has too many bugs...",
    'Why do programmers prefer dark mode? Because light attracts bugs...',
    'Why did the developer go broke? Because they used up all their cache...',
    "What can you do with a broken pencil? Nothing, it's pointless...",
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
    'Just remembered where I put my keys...',
    'Pondering the orb...',
    "I've seen things you people wouldn't believe... like a user who reads loading messages.",
    'Initiating thoughtful gaze...',
    "What's a computer's favorite snack? Microchips.",
    "Why do Java developers wear glasses? Because they don't C#.",
    'Charging the laser... pew pew!',
    'Dividing by zero... just kidding!',
    'Looking for an adult superviso... I mean, processing.',
    'Making it go beep boop.',
    'Buffering... because even AIs need a moment.',
    'Entangling quantum particles for a faster response...',
    'Polishing the chrome... on the algorithms.',
    'Are you not entertained? (Working on it!)',
    'Summoning the code gremlins... to help, of course.',
    'Just waiting for the dial-up tone to finish...',
    'Recalibrating the humor-o-meter.',
    'My other loading screen is even funnier.',
    "Pretty sure there's a cat walking on the keyboard somewhere...",
    'Enhancing... Enhancing... Still loading.',
    "It's not a bug, it's a feature... of this loading screen.",
    'Have you tried turning it off and on again? (The loading screen, not me.)',
    'Constructing additional pylons...',
]

_LOGO = """\
[bold yellow] ████████╗██╗  ██████╗  ██████╗ ███████╗██████╗ [/bold yellow]
[bold yellow]    ██╔══╝██║ ██╔════╝ ██╔════╝ ██╔════╝██╔══██╗[/bold yellow]
[bold yellow]    ██║   ██║ ██║  ███╗██║  ███╗█████╗  ██████╔╝[/bold yellow]
[bold yellow]    ██║   ██║ ██║   ██║██║   ██║██╔══╝  ██╔══██╗[/bold yellow]
[bold yellow]    ██║   ██║ ╚██████╔╝╚██████╔╝███████╗██║  ██║[/bold yellow]
[bold yellow]    ╚═╝   ╚═╝  ╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝[/bold yellow]

      /\\_/\\      Tigger — AI Agent
     ( o.o )
      > ^ <      [dim]a minimal, clean CLI[/dim]
"""


def print_logo() -> None:
    console.print(_LOGO)


def print_status(model: str, used: int, limit: int, mode: str, permission: str) -> None:
    console.print(
        f"[dim][[/dim][bold cyan]{model}[/bold cyan][dim]] "
        f"{used}/{limit} tokens · mode=[/dim][bold]{mode}[/bold]"
        f"[dim] · perm=[/dim][bold]{permission}[/bold]",
        end="",
    )


def print_tool_start(name: str, args: dict) -> None:
    console.print(f"\n[dim]▶ tool[/dim] [bold]{name}[/bold] {args}")


def print_tool_end(name: str, status: str, output: str) -> None:
    color = "red" if status == "error" else ("dim" if status == "denied" else "green")
    console.print(f"[{color}]◀ {name} → {status}:[/{color}] {output[:120]}")


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
    """Interactive trust prompt. Returns 'session', 'always', or 'deny'."""
    console.print(f"\n[yellow bold]Workspace trust required:[/yellow bold] {cwd}")
    console.print("  [bold][T][/bold] Trust this session")
    console.print("  [bold][A][/bold] Always trust this directory")
    console.print("  [bold][D][/bold] Deny (read-only mode)")
    while True:
        choice = input("Choice [T/A/D]: ").strip().lower()
        if choice in ("t", ""):
            return "session"
        if choice == "a":
            return "always"
        if choice == "d":
            return "deny"


@contextmanager
def Spinner():
    """Context manager that shows a Tigger-themed spinner while waiting for first response."""
    with console.status(SPINNER_MESSAGES[0], spinner="dots"):
        yield
