from __future__ import annotations
import glob as _glob
import pathlib
import re as _re
import subprocess
import urllib.parse as _urlparse
import urllib.request
from tigger.types import ToolDef

_32KB = 32 * 1024

# Prefixes that indicate private / link-local addresses (SSRF protection).
_PRIVATE_PREFIXES = (
    "127.", "10.", "192.168.", "169.254.",
    "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.",
    "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
    "172.30.", "172.31.",
)


def _safe_path(p: pathlib.Path) -> pathlib.Path | None:
    """Resolve *p* and return it only if it lies within the current workspace."""
    cwd = pathlib.Path.cwd().resolve()
    try:
        resolved = p.resolve()
        resolved.relative_to(cwd)
        return resolved
    except ValueError:
        return None


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
            result = result[:_32KB] + "\n[output truncated at 32KB]"
        return result


# ── Tool implementations ────────────────────────────────────────────────

def _read(args: dict) -> str:
    p = pathlib.Path(args["path"])
    safe = _safe_path(p)
    if safe is None:
        return f"Error: access denied — path is outside the workspace: {args['path']}"
    if not safe.exists():
        return f"Error: file not found: {args['path']}"
    return safe.read_text(errors="replace")


def _glob_tool(args: dict) -> str:
    pattern = args["pattern"]
    base = args.get("path", ".")
    matches = _glob.glob(str(pathlib.Path(base) / pattern), recursive=True)
    return "\n".join(sorted(matches)) or "(no matches)"


def _grep(args: dict) -> str:
    pattern = args["pattern"]
    path = args.get("path", ".")
    glob_pat = args.get("glob", "**/*")
    try:
        rx = _re.compile(pattern)
    except _re.error as e:
        return f"Error: invalid regex: {e}"
    results = []
    base = pathlib.Path(path)
    # Use pathlib.glob() so patterns like src/**/*.py work correctly.
    for p in base.glob(glob_pat):
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
    safe = _safe_path(p)
    if safe is None:
        return f"Error: access denied — path is outside the workspace: {args['path']}"
    if safe.exists():
        return "Error: file already exists. Use 'edit' to modify existing files."
    safe.parent.mkdir(parents=True, exist_ok=True)
    safe.write_text(args["content"])
    return f"Written: {args['path']}"


def _edit(args: dict) -> str:
    p = pathlib.Path(args["path"])
    safe = _safe_path(p)
    if safe is None:
        return f"Error: access denied — path is outside the workspace: {args['path']}"
    if not safe.exists():
        return f"Error: file not found: {args['path']}"
    text = safe.read_text()
    old = args["old_string"]
    new = args["new_string"]
    if old not in text:
        return f"Error: old_string not found in {args['path']}"
    safe.write_text(text.replace(old, new, 1))
    return f"Edited: {args['path']}"


def _bash(args: dict) -> str:
    cmd = args["command"]
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=30
    )
    out = result.stdout + result.stderr
    return out or "(no output)"


def _strip_html(html: str) -> str:
    """Strip script/style blocks and HTML tags, decode common entities."""
    html = _re.sub(
        r"<(script|style)[^>]*>.*?</(script|style)>",
        "",
        html,
        flags=_re.DOTALL | _re.IGNORECASE,
    )
    html = _re.sub(r"<[^>]+>", "", html)
    html = (
        html.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
            .replace("&nbsp;", " ")
    )
    return _re.sub(r"\n{3,}", "\n\n", html).strip()


def _web_fetch(args: dict) -> str:
    url = args["url"]
    parsed = _urlparse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname in ("localhost", "::1") or any(hostname.startswith(p) for p in _PRIVATE_PREFIXES):
        return "Error: access to private/local network addresses is not permitted."
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Tigger/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read().decode("utf-8", errors="replace")
        if "text/html" in content_type:
            return _strip_html(raw)
        return raw
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
                "glob": {"type": "string", "description": "File glob filter (e.g. '**/*.py')"},
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
    ))
    registry.register(ToolDef(
        name="web_fetch",
        description="Fetch the text content of a URL. HTML is stripped to plain text.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        func=_web_fetch,
        read_only=True,
    ))
