from __future__ import annotations
import itertools
import json, os, pathlib, queue, subprocess, threading

import httpx
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from tigger.tools import ToolRegistry, ToolDef

_CONNECT_TIMEOUT = 3.0
_PROTOCOL_VERSION = "2025-03-26"


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
        configs.append(McpServerConfig(
            name=name,
            transport=srv.get("transport", "stdio"),
            command=command,
            url=url,
            env=srv.get("env", {}),
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
            resp = self._client.post(f"{self._url}/mcp", json=msg, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise McpTransportError(f"HTTP {exc.response.status_code}: {exc.response.text}") from exc
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


def _make_mcp_tool_func(server_name: str, tool_name: str, proc: subprocess.Popen):
    _lock = threading.Lock()
    def call(args: dict) -> str:
        request = json.dumps({
            "jsonrpc": "2.0", "id": next(_id_counter),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        }) + "\n"
        with _lock:
            try:
                proc.stdin.write(request.encode())
                proc.stdin.flush()
                line = proc.stdout.readline()
                resp = json.loads(line)
                content = resp.get("result", {}).get("content", [])
                return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
            except Exception as exc:
                return f"Error calling MCP tool {tool_name}: {exc}"
    return call


def connect_all(registry: ToolRegistry, path: pathlib.Path, *, require_consent: bool = False) -> None:
    """Connect to all MCP servers in *path* and register their tools. Blocking, 3s timeout.

    When *require_consent* is True, the user is prompted before launching each
    MCP server subprocess.  Set to False for trusted workspaces or tests.
    """
    configs = load_mcp_config(path)
    if not configs:
        return

    if require_consent and configs:
        names = [c.name for c in configs]
        print(f"[mcp] Found MCP servers: {', '.join(names)}")
        try:
            answer = input("  Launch MCP servers? [y/N] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            answer = "n"
        if answer != "y":
            print("[mcp] Skipped — MCP servers not launched.")
            return

    for cfg in configs:
        if cfg.transport == "stdio" and cfg.command:
            try:
                proc = subprocess.Popen(
                    cfg.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                init = json.dumps({
                    "jsonrpc": "2.0", "id": 0,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
                }) + "\n"
                proc.stdin.write(init.encode())
                proc.stdin.flush()

                import select
                ready, _, _ = select.select([proc.stdout], [], [], _CONNECT_TIMEOUT)
                if not ready:
                    print(f"[mcp] Warning: {cfg.name} timed out — skipping")
                    proc.kill()
                    continue

                proc.stdout.readline()  # consume initialize response

                # Send required `initialized` notification before any further requests.
                notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
                proc.stdin.write(notif.encode())
                proc.stdin.flush()

                list_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
                proc.stdin.write(list_req.encode())
                proc.stdin.flush()
                tools_line = proc.stdout.readline()
                tools_resp = json.loads(tools_line)
                for tool in tools_resp.get("result", {}).get("tools", []):
                    full_name = f"mcp__{cfg.name}__{tool['name']}"
                    registry.register(ToolDef(
                        name=full_name,
                        description=tool.get("description", ""),
                        parameters=tool.get("inputSchema", {"type": "object", "properties": {}}),
                        func=_make_mcp_tool_func(cfg.name, tool["name"], proc),
                        read_only=False,
                    ))
            except Exception as exc:
                print(f"[mcp] Warning: failed to connect to {cfg.name}: {exc}")
