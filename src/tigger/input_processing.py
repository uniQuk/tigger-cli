from __future__ import annotations
import pathlib
import re

_FILE_REF = re.compile(r"@(\S+)")
_MAX_FILE_SIZE = 50 * 1024  # 50KB


def expand_file_refs(line: str) -> str:
    """Replace @path/to/file references with inlined file contents."""
    def _replace(match: re.Match) -> str:
        path_str = match.group(1)
        path = pathlib.Path(path_str).expanduser()
        if not path.exists():
            print(f"Warning: file not found: {path_str}")
            return match.group(0)  # leave as-is
        if path.stat().st_size > _MAX_FILE_SIZE:
            print(f"Warning: {path_str} exceeds 50KB, truncating")
            content = path.read_text(errors="replace")[:_MAX_FILE_SIZE]
        else:
            content = path.read_text(errors="replace")
        return f"\n--- Contents of {path_str} ---\n{content}\n--- End of {path_str} ---\n"

    return _FILE_REF.sub(_replace, line)
