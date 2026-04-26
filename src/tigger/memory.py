from __future__ import annotations

import datetime
import pathlib


def read_memory(path: pathlib.Path) -> list[str]:
    """Return last 50 non-empty lines from *path*. Returns [] if file missing."""
    if not path.exists():
        return []
    lines = [line.rstrip() for line in path.read_text().splitlines() if line.strip()]
    return lines[-50:]

def append_memory(path: pathlib.Path, note: str) -> None:
    today = datetime.date.today().isoformat()
    entry = f"- [{today}] {note}\n"
    with path.open("a") as f:
        f.write(entry)

def search_memory(path: pathlib.Path, query: str) -> list[tuple[int, str]]:
    """Return (1-based index, line) tuples for lines containing *query* (case-insensitive)."""
    lines = read_memory(path)
    q = query.lower()
    return [(i + 1, line) for i, line in enumerate(lines) if q in line.lower()]

def delete_memory(path: pathlib.Path, index: int) -> bool:
    """Remove the 1-based *index* entry and rewrite the file. Returns True if successful."""
    lines = read_memory(path)
    if index < 1 or index > len(lines):
        return False
    lines.pop(index - 1)
    path.write_text("\n".join(lines) + "\n" if lines else "")
    return True

def clear_memory(path: pathlib.Path) -> None:
    """Truncate the memory file."""
    path.write_text("")

def format_for_prompt(lines: list[str]) -> str:
    if not lines:
        return ""
    body = "\n".join(lines)
    return f"## Memory\n\n{body}\n"
