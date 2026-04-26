from __future__ import annotations

import glob as _glob
import ipaddress as _ipaddress
import os
import pathlib
import re as _re
import signal
import socket as _socket
import subprocess
import urllib.parse as _urlparse
import urllib.request

from tigger.types import ToolDef, ToolResult

_32KB = 32 * 1024

# Exact directory names to exclude.
_DEFAULT_EXCLUDES = {".git", "node_modules", ".venv", "__pycache__"}
# Suffix patterns — any path part ending with one of these is excluded.
# `.egg-info` directories are typically named `<pkg>.egg-info`, so an exact
# match never fires. The suffix check catches them.
_DEFAULT_EXCLUDE_SUFFIXES = (".egg-info",)


def _part_is_excluded(part: str) -> bool:
    return part in _DEFAULT_EXCLUDES or any(
        part.endswith(suffix) for suffix in _DEFAULT_EXCLUDE_SUFFIXES
    )


def _is_excluded(path: pathlib.Path) -> bool:
    """Return True if any parent directory of *path* is in the default exclude set."""
    return any(_part_is_excluded(p) for p in path.parent.parts)


def _is_excluded_dir(path: pathlib.Path) -> bool:
    """Return True if *path* itself or any ancestor is in the default exclude set."""
    return any(_part_is_excluded(p) for p in path.parts)


def _safe_path(p: pathlib.Path) -> pathlib.Path | None:
    """Resolve *p* and return it only if it lies within the current workspace."""
    cwd = pathlib.Path.cwd().resolve()
    try:
        resolved = p.resolve()
        resolved.relative_to(cwd)
        return resolved
    except ValueError:
        return None


def _server_segment(name: str) -> str:
    """Extract the server segment from an `mcp__<server>__<tool>` name.

    Returns the literal name when the prefix is absent (native tools should
    never reach the lazy/disabled gate, but we want a sensible fallback).
    """
    if name.startswith("mcp__"):
        rest = name[len("mcp__"):]
        if "__" in rest:
            return rest.split("__", 1)[0]
    return name


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def all(self) -> list[ToolDef]:
        return list(self._tools.values())

    def lazy_tools(self) -> list[ToolDef]:
        """Return tools whose tier is 'lazy' (registered but not shipped to the LLM)."""
        return [t for t in self._tools.values() if t.tier == "lazy"]

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
            if t.tier == "eager"
        ]

    def execute(self, name: str, args: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(output=f"Error: unknown tool '{name}'", error=True)
        if tool.tier == "lazy":
            server = _server_segment(name)
            return ToolResult(
                output=(
                    f"Error: tool '{name}' is lazy. "
                    f"Call mcp_promote(server='{server}') first to load its schema."
                ),
                error=True,
            )
        if tool.tier == "disabled":
            server = _server_segment(name)
            return ToolResult(
                output=f"Error: tool '{name}' belongs to a disabled server '{server}'. Re-enable in mcp.json and restart.",
                error=True,
            )
        try:
            output = tool.func(args)
            # Tool implementations signal in-band failures by prefixing "Error:".
            # Centralize that detection here so callers don't parse strings.
            error = output.startswith("Error:")
        except Exception as exc:
            output = f"Error: {exc}"
            error = True
        if len(output) > _32KB:
            output = output[:_32KB] + "\n[output truncated at 32KB]"
        return ToolResult(output=output, error=error)


# ── Tool implementations ────────────────────────────────────────────────

def _read(args: dict) -> str:
    p = pathlib.Path(args["path"])
    safe = _safe_path(p)
    if safe is None:
        return f"Error: access denied — path is outside the workspace: {args['path']}"
    if not safe.exists():
        return f"Error: file not found: {args['path']}"
    return safe.read_text(errors="replace")


_GLOB_MAX_RESULTS = 200


def _glob_tool(args: dict) -> str:
    pattern = args["pattern"]
    base = args.get("path", ".")
    base_path = pathlib.Path(base)
    # Validate base path is within workspace
    safe_base = _safe_path(base_path)
    if safe_base is None:
        return f"Error: access denied — path is outside the workspace: {base}"
    matches = _glob.glob(str(safe_base / pattern), recursive=True)
    # Filter results to workspace-contained paths only, skip default excludes
    # unless user provided an explicit path into an excluded directory.
    cwd = pathlib.Path.cwd().resolve()
    skip_excludes = not _is_excluded_dir(base_path)
    safe_matches = []
    for m in sorted(matches):
        mp = pathlib.Path(m)
        try:
            mp.resolve().relative_to(cwd)
        except ValueError:
            continue
        if skip_excludes and _is_excluded(mp):
            continue
        safe_matches.append(m)
    total = len(safe_matches)
    if total > _GLOB_MAX_RESULTS:
        safe_matches = safe_matches[:_GLOB_MAX_RESULTS]
        return "\n".join(safe_matches) + f"\n\n(truncated — showing {_GLOB_MAX_RESULTS} of {total} results. Use a more specific pattern to narrow results.)"
    return "\n".join(safe_matches) or "(no matches)"


def _grep(args: dict) -> str:
    pattern = args["pattern"]
    path = args.get("path", ".")
    glob_pat = args.get("glob", "**/*")
    try:
        rx = _re.compile(pattern)
    except _re.error as e:
        return f"Error: invalid regex: {e}"
    # Validate base path is within workspace
    base = pathlib.Path(path)
    safe_base = _safe_path(base)
    if safe_base is None:
        return f"Error: access denied — path is outside the workspace: {path}"
    cwd = pathlib.Path.cwd().resolve()
    skip_excludes = not _is_excluded_dir(pathlib.Path(path))
    results = []
    # Use pathlib.glob() so patterns like src/**/*.py work correctly.
    for p in safe_base.glob(glob_pat):
        if not p.is_file():
            continue
        # Skip files outside workspace (e.g. from symlinks)
        try:
            p.resolve().relative_to(cwd)
        except ValueError:
            continue
        if skip_excludes and _is_excluded(p):
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


_BASH_TIMEOUT = 30
_BASH_KILL_GRACE = 5


def _bash(args: dict) -> str:
    cmd = args["command"]
    # start_new_session puts the shell (and its grandchildren) in their own
    # process group so a single killpg can reach the whole tree. Without it,
    # a SIGTERM-ignoring child can keep the agent's communicate() blocked
    # on an open pipe.
    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=_BASH_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass  # Already exited between the timeout and the kill.
        try:
            out, _ = proc.communicate(timeout=_BASH_KILL_GRACE)
        except subprocess.TimeoutExpired:
            return f"Error: command did not exit after SIGKILL ({_BASH_TIMEOUT}s + {_BASH_KILL_GRACE}s)"
        return f"Error: command timed out after {_BASH_TIMEOUT}s (killed)\n{out or ''}"
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


def _is_private_or_local(hostname: str) -> bool:
    """Return True if *hostname* resolves to a private, loopback, or link-local address.

    Note: TOCTOU risk — hostname is resolved again by urlopen, so DNS rebinding
    can bypass this check.  Full mitigation requires a custom opener.
    """
    if not hostname:
        return True
    # Check well-known local hostnames first.
    if hostname in ("localhost", "localhost.localdomain"):
        return True
    # Try parsing as IP directly (handles 0.0.0.0, ::1, 127.1, etc.)
    try:
        addr = _ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        pass
    # Resolve hostname and check all addresses.
    try:
        infos = _socket.getaddrinfo(hostname, None, type=_socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in infos:
            ip_str = sockaddr[0]
            addr = _ipaddress.ip_address(ip_str)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return True
    except (_socket.gaierror, ValueError):
        pass
    return False


def _web_fetch(args: dict) -> str:
    url = args["url"]
    parsed = _urlparse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if _is_private_or_local(hostname):
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


def _make_mcp_promote(registry: ToolRegistry):
    """Build the mcp_promote tool function bound to a specific registry.

    Closure pattern mirrors `_remember` below — the tool needs registry access
    to mutate ToolDef.tier in place.
    """
    def promote(args: dict) -> str:
        server = (args.get("server") or "").strip()
        if not server:
            return "Error: missing 'server' argument"
        prefix = f"mcp__{server}__"
        matching = [t for t in registry.all() if t.name.startswith(prefix)]
        if not matching:
            return f"Error: no MCP server named {server!r}"
        # Server-level disabled (R10): every tool is disabled → server itself is off.
        # Per-tool disabled (R2 override) is intentional and left alone — only lazy gets promoted.
        if all(t.tier == "disabled" for t in matching):
            return (
                f"Error: server {server!r} is disabled. Edit mcp.json and "
                f"restart to re-enable."
            )
        promoted_names: list[str] = []
        already_eager: list[str] = []
        for t in matching:
            if t.tier == "lazy":
                t.tier = "eager"
                promoted_names.append(t.name[len(prefix):])
            elif t.tier == "eager":
                already_eager.append(t.name[len(prefix):])
        if promoted_names:
            return (
                f"Promoted {server!r}. {len(promoted_names)} tools now available: "
                f"{', '.join(promoted_names)}"
            )
        return f"Server {server!r} is already eager ({len(already_eager)} tools)"

    return promote


def register_all(registry: ToolRegistry, *, memory_path: pathlib.Path | None = None) -> None:
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
        name="mcp_promote",
        description=(
            "Promote a lazy MCP server so its tool schemas become available "
            "next turn. Use when you see an MCP tool name in the system prompt "
            "but its schema isn't loaded yet."
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "MCP server name (e.g. 'playwright', 'github')",
                },
            },
            "required": ["server"],
        },
        func=_make_mcp_promote(registry),
        read_only=True,
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

    if memory_path is not None:
        def _remember(args: dict) -> str:
            note = args.get("note", "").strip()
            if not note:
                return "Error: note cannot be empty"
            from tigger.memory import append_memory
            append_memory(memory_path, note)
            return f"Remembered: {note}"

        registry.register(ToolDef(
            name="remember",
            description="Save a fact or decision to persistent memory. Use this to remember important context for future conversations.",
            parameters={
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "The fact or decision to remember"},
                },
                "required": ["note"],
            },
            func=_remember,
        ))
