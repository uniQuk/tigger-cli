from __future__ import annotations

import pathlib

from tigger import memory as _mem
from tigger.types import RunContext


def cmd_memory(args: str, ctx: RunContext, memory_path: pathlib.Path) -> None:
    from tigger.ui import console

    parts = args.strip().split(None, 1)
    sub = parts[0] if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    if sub == "search":
        if not rest:
            console.print("[dim]Usage:[/dim] /memory search <query>")
            return
        results = _mem.search_memory(memory_path, rest)
        if not results:
            console.print("[dim]No matches.[/dim]")
            return
        for idx, line in results:
            console.print(f"  [dim]{idx}.[/dim] {line}")
        return

    if sub == "delete":
        if not rest.isdigit():
            console.print("[dim]Usage:[/dim] /memory delete <number>")
            return
        ok = _mem.delete_memory(memory_path, int(rest))
        if ok:
            console.print(f"[dim]✓ Deleted entry[/dim] {rest}")
        else:
            console.print(f"[red]Invalid index:[/red] {rest}")
        return

    if sub == "clear":
        _mem.clear_memory(memory_path)
        console.print("[dim]✓ Memory cleared.[/dim]")
        return

    # Default: list all
    lines = _mem.read_memory(memory_path)
    if not lines:
        console.print("[dim](memory is empty)[/dim]")
        return
    console.print()
    console.print("[bold]Memory[/bold]")
    for idx, line in enumerate(lines, start=1):
        console.print(f"  [dim]{idx}.[/dim] {line}")
    console.print()


def cmd_remember(args: str, ctx: RunContext, memory_path: pathlib.Path) -> None:
    from tigger.ui import console

    if not args.strip():
        console.print("[dim]Usage:[/dim] /remember <note>")
        return
    note = args.strip()
    _mem.append_memory(memory_path, note)
    # Truncate the echo so a long note doesn't take over the screen.
    echo = note if len(note) <= 80 else note[:77] + "..."
    console.print(f"[dim]✓ Remembered:[/dim] {echo}")
