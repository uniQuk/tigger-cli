from __future__ import annotations

import itertools
import json
import os
import pathlib
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

from tigger.tools import ToolDef, ToolRegistry

_CONNECT_TIMEOUT = 3.0
_PROTOCOL_VERSION = "2025-03-26"
_VALID_TIERS = {"eager", "lazy", "disabled"}


class McpTransportError(Exception):
    """Raised by transports on network, protocol, or parse failures."""


@runtime_checkable
class McpTransport(Protocol):
    def send(self, method: str, params: dict) -> dict: ...
    def close(self) -> None: ...


@dataclass
class McpConnection:
    name: str
    transport: McpTransport
    server_info: dict | None = None
    capabilities: dict | None = None
    protocol_version: str | None = None


@dataclass
class McpServerConfig:
    name: str
    transport: str              # "stdio" | "sse" | "http"
    command: list[str] | None = None
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    tier: str = "eager"                                     # "eager" | "lazy" | "disabled"
    tool_tiers: dict[str, str] = field(default_factory=dict)  # bare tool name -> tier


def _coerce_tier(value: str | None, *, where: str) -> str:
    """Validate a tier value, falling back to 'eager' with a warning if unknown."""
    if value is None:
        return "eager"
    if value in _VALID_TIERS:
        return value
    from tigger.ui import console as _console
    _console.print(
        f"      [yellow]\\[mcp] Warning:[/yellow] unknown tier {value!r} for "
        f"{where}, [dim]defaulting to 'eager'[/dim]"
    )
    return "eager"


def load_mcp_config(path: pathlib.Path) -> list[McpServerConfig]:
    if not path.exists():
        return []
    with path.open() as f:
        data = json.load(f)
    configs = []
    for name, srv in data.get("servers", {}).items():
        command = srv.get("command")
        if command:
            command = [os.path.expandvars(c) for c in command]
        url = srv.get("url")
        if url:
            url = os.path.expandvars(url)
        tier = _coerce_tier(srv.get("tier"), where=f"server {name!r}")
        raw_tool_tiers = srv.get("tools", {}) or {}
        tool_tiers: dict[str, str] = {}
        for tool_name, raw_t in raw_tool_tiers.items():
            if raw_t in _VALID_TIERS:
                tool_tiers[tool_name] = raw_t
            else:
                from tigger.ui import console as _console
                _console.print(
                    f"      [yellow]\\[mcp] Warning:[/yellow] unknown tier {raw_t!r} for "
                    f"{name!r}.tools.{tool_name!r}, [dim]ignoring[/dim]"
                )
        # Stdio default only applies when transport not specified AND we're connecting.
        # Disabled servers may omit transport/command entirely; tolerate that.
        configs.append(McpServerConfig(
            name=name,
            transport=srv.get("transport", "stdio"),
            command=command,
            url=url,
            env=srv.get("env", {}),
            tier=tier,
            tool_tiers=tool_tiers,
        ))
    return configs


_id_counter = itertools.count(2)  # 0 = initialize, 1 = tools/list


class StdioTransport:
    """MCP transport over subprocess stdin/stdout."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None) -> None:
        merged_env = {**os.environ, **(env or {})}
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=merged_env,
        )
        self._lock = threading.Lock()

    def send(self, method: str, params: dict) -> dict:
        is_notification = method.startswith("notifications/")
        msg: dict = {"jsonrpc": "2.0", "method": method, "params": params}
        if not is_notification:
            msg["id"] = next(_id_counter)
        line = json.dumps(msg) + "\n"

        with self._lock:
            try:
                if self.proc.poll() is not None:
                    raise McpTransportError(f"stdio process exited (code {self.proc.returncode})")
                self.proc.stdin.write(line.encode())
                self.proc.stdin.flush()
                if is_notification:
                    return {}
                # Use a timer thread for portable timeout instead of select.select
                timed_out = threading.Event()
                def _timeout():
                    timed_out.set()
                timer = threading.Timer(_CONNECT_TIMEOUT, _timeout)
                timer.daemon = True
                timer.start()
                resp_line = self.proc.stdout.readline()
                timer.cancel()
                if timed_out.is_set() or not resp_line:
                    raise McpTransportError("stdio read timed out")
                resp = json.loads(resp_line)
            except McpTransportError:
                raise
            except (BrokenPipeError, OSError) as exc:
                raise McpTransportError(f"stdio I/O error: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise McpTransportError(f"stdio invalid JSON response: {exc}") from exc

        if "error" in resp:
            err = resp["error"]
            raise McpTransportError(f"JSON-RPC error {err.get('code')}: {err.get('message')}")
        return resp.get("result", {})

    def close(self) -> None:
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def _parse_sse_events(text: str) -> list[dict[str, str]]:
    """Parse SSE text into a list of dicts with 'event' and 'data' keys."""
    events = []
    current: dict[str, str] = {}
    for line in text.split("\n"):
        if line == "":
            if current:
                events.append(current)
                current = {}
        elif line.startswith("event:"):
            current["event"] = line[6:].strip()
        elif line.startswith("data:"):
            prev = current.get("data", "")
            current["data"] = (prev + "\n" + line[5:].strip()) if prev else line[5:].strip()
    if current:
        events.append(current)
    return events


class StreamableHttpTransport:
    """MCP transport over Streamable HTTP (2025-03-26 standard)."""

    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")
        self._client = httpx.Client(timeout=30.0)
        self._session_id: str | None = None

    def send(self, method: str, params: dict) -> dict:
        is_notification = method.startswith("notifications/")
        msg: dict = {"jsonrpc": "2.0", "method": method, "params": params}
        if not is_notification:
            msg["id"] = next(_id_counter)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        try:
            resp = self._client.post(self._url, json=msg, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            raise McpTransportError(f"HTTP {code}: {exc.response.text}") from exc
        except httpx.HTTPError as exc:
            raise McpTransportError(f"HTTP error: {exc}") from exc

        # Capture session ID from initialize response
        session_id = resp.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id

        if is_notification:
            return {}

        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return self._parse_sse_response(resp.text, msg["id"])
        else:
            # application/json
            try:
                data = resp.json()
            except Exception as exc:
                raise McpTransportError(f"HTTP invalid JSON response: {exc}") from exc
            if "error" in data:
                err = data["error"]
                raise McpTransportError(f"JSON-RPC error {err.get('code')}: {err.get('message')}")
            return data.get("result", {})

    def _parse_sse_response(self, text: str, request_id: int) -> dict:
        """Extract JSON-RPC result from an SSE response body."""
        for event in _parse_sse_events(text):
            data = event.get("data", "")
            if not data:
                continue
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                continue
            if parsed.get("id") == request_id:
                if "error" in parsed:
                    err = parsed["error"]
                    raise McpTransportError(
                        f"JSON-RPC error {err.get('code')}: {err.get('message')}"
                    )
                return parsed.get("result", {})
        raise McpTransportError("No matching JSON-RPC response in SSE stream")

    def close(self) -> None:
        self._client.close()


class SseTransport:
    """MCP transport over legacy SSE (2024-11-05 spec)."""

    def __init__(self, url: str, *, timeout: float = 10.0) -> None:
        self._client = httpx.Client(timeout=timeout)
        self._endpoint_url: str | None = None
        self._pending: dict[int, queue.Queue] = {}
        self._stop_event = threading.Event()
        self._reader_thread: threading.Thread | None = None

        # Open GET /sse and wait for the endpoint event
        try:
            self._sse_response = self._client.stream("GET", f"{url.rstrip('/')}/sse")
            self._sse_stream = self._sse_response.__enter__()
        except httpx.HTTPError as exc:
            raise McpTransportError(f"SSE connection failed: {exc}") from exc

        # Read lines until we get event: endpoint
        self._line_iter = self._sse_stream.iter_lines()
        event_type = None
        deadline = threading.Event()
        timer = threading.Timer(timeout, deadline.set)
        timer.daemon = True
        timer.start()
        for raw_line in self._line_iter:
            if deadline.is_set():
                timer.cancel()
                raise McpTransportError("SSE endpoint event not received within timeout")
            if raw_line.startswith("event:"):
                event_type = raw_line[6:].strip()
            elif raw_line.startswith("data:") and event_type == "endpoint":
                endpoint = raw_line[5:].strip()
                if not endpoint:
                    raise McpTransportError("SSE endpoint URL is empty")
                # Resolve relative URL against the SSE origin
                if endpoint.startswith("/"):
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    self._endpoint_url = f"{parsed.scheme}://{parsed.netloc}{endpoint}"
                else:
                    self._endpoint_url = endpoint
                break
        timer.cancel()

        if not self._endpoint_url:
            raise McpTransportError("SSE endpoint event not received")

        # Start background reader thread
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="mcp-sse-reader"
        )
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        """Read SSE events and dispatch JSON-RPC responses to pending queues."""
        event_type = None
        try:
            for raw_line in self._line_iter:
                if self._stop_event.is_set():
                    return
                if raw_line.startswith("event:"):
                    event_type = raw_line[6:].strip()
                elif raw_line.startswith("data:") and event_type == "message":
                    data = raw_line[5:].strip()
                    try:
                        parsed = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    msg_id = parsed.get("id")
                    if msg_id is not None and msg_id in self._pending:
                        self._pending[msg_id].put(parsed)
                    event_type = None
                elif raw_line == "":
                    event_type = None
        except Exception:
            pass  # stream closed or errored — daemon thread will die

    def send(self, method: str, params: dict) -> dict:
        is_notification = method.startswith("notifications/")
        msg: dict = {"jsonrpc": "2.0", "method": method, "params": params}
        if not is_notification:
            msg["id"] = next(_id_counter)

        if not is_notification:
            q: queue.Queue = queue.Queue(maxsize=1)
            self._pending[msg["id"]] = q

        try:
            resp = self._client.post(self._endpoint_url, json=msg)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            if not is_notification:
                self._pending.pop(msg["id"], None)
            raise McpTransportError(f"SSE POST failed: {exc}") from exc

        if is_notification:
            return {}

        try:
            response = q.get(timeout=30.0)
        except queue.Empty:
            raise McpTransportError("SSE response timed out")
        finally:
            self._pending.pop(msg["id"], None)

        if "error" in response:
            err = response["error"]
            raise McpTransportError(f"JSON-RPC error {err.get('code')}: {err.get('message')}")
        return response.get("result", {})

    def close(self) -> None:
        self._stop_event.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2)
        try:
            self._sse_response.__exit__(None, None, None)
        except Exception:
            pass
        self._client.close()


def _make_mcp_tool_func(server_name: str, tool_name: str, transport: McpTransport):
    def call(args: dict) -> str:
        # Let McpTransportError propagate. ToolRegistry.execute catches it
        # and produces ToolResult(error=True). Returning the error string
        # in-band here would make the registry mark the call as success
        # because the message did not start with "Error:".
        result = transport.send("tools/call", {"name": tool_name, "arguments": args})
        content = result.get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
    return call


# ── Module-level connection registry ─────────────────────────────────────

_connections: list[McpConnection] = []
_cleanup_registered = False


def get_connections() -> list[McpConnection]:
    """Return the list of active MCP connections (read-only access for /mcp command)."""
    return _connections


def _cleanup() -> None:
    """Close all MCP transports. Registered via atexit on first connect_all call."""
    for conn in _connections:
        try:
            conn.transport.close()
        except Exception:
            pass


class _DisabledTransport:
    """Sentinel transport for servers configured as `tier: disabled`.

    The connection is recorded so `/mcp` can still display the server, but no
    subprocess is spawned and no network call is made.
    """

    def send(self, method: str, params: dict) -> dict:
        raise McpTransportError("server is disabled")

    def close(self) -> None:
        return None


def _build_transport(cfg: McpServerConfig) -> McpTransport:
    """Construct the appropriate transport for a server config."""
    if cfg.transport == "stdio":
        if not cfg.command:
            raise McpTransportError(f"stdio transport requires 'command' for server {cfg.name!r}")
        return StdioTransport(cfg.command, env=cfg.env or None)
    elif cfg.transport == "http":
        if not cfg.url:
            raise McpTransportError(f"http transport requires 'url' for server {cfg.name!r}")
        return StreamableHttpTransport(cfg.url)
    elif cfg.transport == "sse":
        if not cfg.url:
            raise McpTransportError(f"sse transport requires 'url' for server {cfg.name!r}")
        return SseTransport(cfg.url)
    else:
        raise McpTransportError(f"Unknown transport {cfg.transport!r} for server {cfg.name!r}")


def connect_all(
    registry: ToolRegistry,
    configs: list[McpServerConfig],
    *,
    require_consent: bool = False,
) -> None:
    """Connect to all MCP servers and register their tools.

    When *require_consent* is True, the user is prompted before launching
    MCP servers.  Set to False for trusted workspaces or tests.
    """
    global _cleanup_registered
    if not configs:
        return

    from tigger.ui import console

    if require_consent:
        names = [c.name for c in configs]
        console.print(
            f"      [dim]\\[mcp][/dim] Found MCP servers: "
            f"[magenta]{', '.join(names)}[/magenta]"
        )
        try:
            answer = input("  Launch MCP servers? [y/N] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            answer = "n"
        if answer != "y":
            console.print("      [dim]\\[mcp] Skipped — MCP servers not launched.[/dim]")
            return

    import atexit
    if not _cleanup_registered:
        atexit.register(_cleanup)
        _cleanup_registered = True

    for cfg in configs:
        # Disabled servers: record a marker connection so /mcp can show them,
        # but skip subprocess spawn / network connect / handshake entirely.
        if cfg.tier == "disabled":
            console.print(
                f"      [dim]\\[mcp] Skipped disabled server:[/dim] "
                f"[magenta]{cfg.name}[/magenta]"
            )
            _connections.append(McpConnection(
                name=cfg.name,
                transport=_DisabledTransport(),
                server_info={"disabled": True},
                capabilities=None,
                protocol_version=None,
            ))
            continue

        try:
            transport = _build_transport(cfg)

            # Handshake: initialize
            init_result = transport.send("initialize", {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "tigger-code", "version": "0.1.0"},
            })

            server_info = init_result.get("serverInfo")
            capabilities = init_result.get("capabilities")
            server_protocol = init_result.get("protocolVersion")

            if server_protocol and server_protocol != _PROTOCOL_VERSION:
                console.print(
                    f"      [yellow]\\[mcp] Warning:[/yellow] [magenta]{cfg.name}[/magenta] "
                    f"uses protocol [cyan]{server_protocol}[/cyan] "
                    f"[dim](client: {_PROTOCOL_VERSION})[/dim]"
                )

            # Send required initialized notification
            transport.send("notifications/initialized", {})

            # Register tools if server advertises tool capability
            if capabilities and "tools" in capabilities:
                try:
                    tools_result = transport.send("tools/list", {})
                    listed_tools = tools_result.get("tools", [])
                    listed_names = {t["name"] for t in listed_tools}

                    # Warn for per-tool override keys that don't match any real tool.
                    for override_name in cfg.tool_tiers:
                        if override_name not in listed_names:
                            console.print(
                                f"      [yellow]\\[mcp] Warning:[/yellow] "
                                f"[magenta]{cfg.name}[/magenta] per-tool override "
                                f"references unknown tool {override_name!r}; "
                                "[dim]ignoring.[/dim]"
                            )

                    for tool in listed_tools:
                        full_name = f"mcp__{cfg.name}__{tool['name']}"
                        default_schema = {"type": "object", "properties": {}}
                        effective_tier = cfg.tool_tiers.get(tool["name"], cfg.tier)
                        registry.register(ToolDef(
                            name=full_name,
                            description=tool.get("description", ""),
                            parameters=tool.get("inputSchema", default_schema),
                            func=_make_mcp_tool_func(cfg.name, tool["name"], transport),
                            read_only=False,
                            tier=effective_tier,
                        ))
                except McpTransportError as exc:
                    console.print(
                        f"      [yellow]\\[mcp] Warning:[/yellow] "
                        f"[magenta]{cfg.name}[/magenta] tools/list failed: "
                        f"[red]{exc}[/red]"
                    )

            conn = McpConnection(
                name=cfg.name,
                transport=transport,
                server_info=server_info,
                capabilities=capabilities,
                protocol_version=server_protocol,
            )
            _connections.append(conn)

        except Exception as exc:
            # McpTransportError is a subclass of Exception; both branches
            # had identical bodies, so a single handler covers them.
            console.print(
                f"      [yellow]\\[mcp] Warning:[/yellow] failed to connect to "
                f"[magenta]{cfg.name}[/magenta]: [red]{exc}[/red]"
            )

    # Summary line so users know their MCP setup loaded without /mcp.
    live = [c for c in _connections
            if not (c.server_info and c.server_info.get("disabled"))]
    if live:
        n_tools = sum(1 for t in registry.all() if t.name.startswith("mcp__"))
        names = ", ".join(c.name for c in live)
        console.print(
            f"      [dim]\\[mcp] connected:[/dim] [magenta]{names}[/magenta] "
            f"[dim]({n_tools} tool{'s' if n_tools != 1 else ''})[/dim]"
        )


def connect_new(registry: ToolRegistry, configs: list[McpServerConfig]) -> list[str]:
    """Connect any servers in *configs* whose name isn't already in `_connections`.

    Used by `/reload-plugins` to pick up newly added MCP entries without
    touching servers already running. Returns the list of names actually
    started. Removed-from-config servers are deliberately left connected for
    the rest of the session — there is no per-server disconnect path today,
    and killing live transports could orphan in-flight tool calls.
    """
    existing = {c.name for c in _connections}
    new_configs = [c for c in configs if c.name not in existing]
    if not new_configs:
        return []
    connect_all(registry, new_configs, require_consent=False)
    return [c.name for c in new_configs]
