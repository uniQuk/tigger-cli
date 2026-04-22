from __future__ import annotations
import datetime, pathlib

def read_memory(path: pathlib.Path) -> list[str]:
    """Return last 50 non-empty lines from *path*. Returns [] if file missing."""
    if not path.exists():
        return []
    lines = [l.rstrip() for l in path.read_text().splitlines() if l.strip()]
    return lines[-50:]

def append_memory(path: pathlib.Path, note: str) -> None:
    today = datetime.date.today().isoformat()
    entry = f"- [{today}] {note}\n"
    with path.open("a") as f:
        f.write(entry)

def format_for_prompt(lines: list[str]) -> str:
    if not lines:
        return ""
    body = "\n".join(lines)
    return f"## Memory\n\n{body}\n"
