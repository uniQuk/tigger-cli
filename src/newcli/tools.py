from __future__ import annotations
import glob as _glob, subprocess, pathlib, urllib.request
from newcli.types import ToolDef

_32KB = 32 * 1024


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def all(self) -> list[ToolDef]:
        return list(self._tools.values())

    def schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def execute(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'"
        try:
            result = tool.func(args)
        except Exception as exc:
            result = f"Error: {exc}"
        if len(result) > _32KB:
            result = result[:_32KB] + f"\n[output truncated at 32KB]"
        return result


# ── Tool implementations ────────────────────────────────────────────────

def _read(args: dict) -> str:
    p = pathlib.Path(args["path"])
    if not p.exists():
        return f"Error: file not found: {p}"
    return p.read_text(errors="replace")


def _glob_tool(args: dict) -> str:
    pattern = args["pattern"]
    base = args.get("path", ".")
    matches = _glob.glob(str(pathlib.Path(base) / pattern), recursive=True)
    return "\n".join(sorted(matches)) or "(no matches)"


def _grep(args: dict) -> str:
    import re
    pattern = args["pattern"]
    path = args.get("path", ".")
    glob_pat = args.get("glob", "**/*")
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"
    results = []
    # Extract the filename pattern (everything after last /)
    pattern_part = glob_pat.rsplit("/", 1)[-1] if "/" in glob_pat else glob_pat
    for p in pathlib.Path(path).rglob(pattern_part):
        if not p.is_file():
            continue
        try:
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if rx.search(line):
                    results.append(f"{p}:{i}: {line}")
        except Exception:
            pass
    return "\n".join(results) or "(no matches)"


def _write(args: dict) -> str:
    p = pathlib.Path(args["path"])
    if p.exists():
        return "Error: file already exists. Use 'edit' to modify existing files."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args["content"])
    return f"Written: {p}"


def _edit(args: dict) -> str:
    p = pathlib.Path(args["path"])
    if not p.exists():
        return f"Error: file not found: {p}"
    text = p.read_text()
    old = args["old_string"]
    new = args["new_string"]
    if old not in text:
        return f"Error: old_string not found in {p}"
    p.write_text(text.replace(old, new, 1))
    return f"Edited: {p}"


def _bash(args: dict) -> str:
    cmd = args["command"]
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=30
    )
    out = result.stdout + result.stderr
    return out or "(no output)"


def _web_fetch(args: dict) -> str:
    url = args["url"]
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return f"Error: {exc}"


def register_all(registry: ToolRegistry) -> None:
    registry.register(ToolDef(
        name="read",
        description="Read the contents of a file.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        func=_read,
        read_only=True,
    ))
    registry.register(ToolDef(
        name="glob",
        description="Find files matching a glob pattern.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "description": "Base directory (default: cwd)"},
            },
            "required": ["pattern"],
        },
        func=_glob_tool,
        read_only=True,
    ))
    registry.register(ToolDef(
        name="grep",
        description="Search file contents for a regex pattern.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
                "glob": {"type": "string", "description": "File glob filter"},
            },
            "required": ["pattern"],
        },
        func=_grep,
        read_only=True,
    ))
    registry.register(ToolDef(
        name="write",
        description="Write content to a new file. Fails if file exists — use edit instead.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        func=_write,
    ))
    registry.register(ToolDef(
        name="edit",
        description="Replace old_string with new_string in an existing file (first occurrence).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        func=_edit,
    ))
    registry.register(ToolDef(
        name="bash",
        description="Run a shell command. Returns stdout + stderr.",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        func=_bash,
        safe=False,
    ))
    registry.register(ToolDef(
        name="web_fetch",
        description="Fetch the contents of a URL.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        func=_web_fetch,
        read_only=True,
    ))
