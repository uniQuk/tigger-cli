from __future__ import annotations

import pathlib
import re
import sys

_FILE_REF = re.compile(r"@(\S+)")
_MAX_FILE_SIZE = 50 * 1024  # 50KB


def _warn(msg: str) -> None:
    """Route @file warnings to stderr so they don't pollute model input or REPL stdout."""
    print(f"Warning: {msg}", file=sys.stderr)


def _is_within_workspace(path: pathlib.Path) -> bool:
    """Return True if *path* resolves to a location within the current workspace."""
    cwd = pathlib.Path.cwd().resolve()
    try:
        path.resolve().relative_to(cwd)
        return True
    except ValueError:
        return False


def expand_file_refs(line: str) -> str:
    """Replace @path/to/file references with inlined file contents.

    Only files within the current workspace are expanded.  Absolute paths,
    home-relative paths (~), and paths that escape the workspace via ``..``
    are rejected to prevent reading sensitive files.
    """
    def _replace(match: re.Match) -> str:
        path_str = match.group(1)
        path = pathlib.Path(path_str)
        # Reject absolute paths and ~ expansion outside workspace
        if path_str.startswith("/") or path_str.startswith("~"):
            _warn(f"@file references must be relative to the workspace: {path_str}")
            return match.group(0)
        if not _is_within_workspace(path):
            _warn(f"access denied — path is outside the workspace: {path_str}")
            return match.group(0)
        if not path.exists():
            _warn(f"file not found: {path_str}")
            return match.group(0)  # leave as-is
        if path.is_dir():
            _warn(f"@file references must point to files, not directories: {path_str}")
            return match.group(0)
        if path.stat().st_size > _MAX_FILE_SIZE:
            _warn(f"{path_str} exceeds 50KB, truncating")
            content = path.read_text(errors="replace")[:_MAX_FILE_SIZE]
        else:
            content = path.read_text(errors="replace")
        return f"\n--- Contents of {path_str} ---\n{content}\n--- End of {path_str} ---\n"

    return _FILE_REF.sub(_replace, line)
