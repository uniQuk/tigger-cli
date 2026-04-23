from __future__ import annotations
import pathlib
from newcli.types import RunContext
from newcli import memory as _mem


def cmd_memory(args: str, ctx: RunContext, memory_path: pathlib.Path) -> None:
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
