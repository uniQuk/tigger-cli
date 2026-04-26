from __future__ import annotations

import pathlib

from tigger import memory as _mem
from tigger.types import RunContext


def cmd_memory(args: str, ctx: RunContext, memory_path: pathlib.Path) -> None:
    parts = args.strip().split(None, 1)
    sub = parts[0] if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    if sub == "search":
        if not rest:
            print("Usage: /memory search <query>")
            return
        results = _mem.search_memory(memory_path, rest)
        if not results:
            print("No matches.")
            return
        for idx, line in results:
            print(f"[{idx}] {line}")
        return

    if sub == "delete":
        if not rest.isdigit():
            print("Usage: /memory delete <number>")
            return
        ok = _mem.delete_memory(memory_path, int(rest))
        if ok:
            print(f"Deleted entry {rest}.")
        else:
            print(f"Invalid index: {rest}")
        return

    if sub == "clear":
        _mem.clear_memory(memory_path)
        print("Memory cleared.")
        return

    # Default: list all
    lines = _mem.read_memory(memory_path)
    if not lines:
        print("(memory is empty)")
        return
    for line in lines:
        print(line)


def cmd_remember(args: str, ctx: RunContext, memory_path: pathlib.Path) -> None:
    if not args.strip():
        print("Usage: /remember <note>")
        return
    _mem.append_memory(memory_path, args.strip())
    print(f"Remembered: {args.strip()}")
