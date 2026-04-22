from __future__ import annotations
import json, pathlib, subprocess, threading
from dataclasses import dataclass
from newcli.tools import ToolRegistry, ToolDef

_CONNECT_TIMEOUT = 3.0


@dataclass
class McpServerConfig:
    name: str
    transport: str              # "stdio" | "http"
    command: list[str] | None = None
    url: str | None = None


def load_mcp_config(path: pathlib.Path) -> list[McpServerConfig]:
    if not path.exists():
        return []
    with path.open() as f:
        data = json.load(f)
    configs = []
    for name, srv in data.get("servers", {}).items():
        configs.append(McpServerConfig(
            name=name,
            transport=srv.get("transport", "stdio"),
            command=srv.get("command"),
            url=srv.get("url"),
        ))
    return configs


def _make_mcp_tool_func(server_name: str, tool_name: str, proc: subprocess.Popen):
    _lock = threading.Lock()
    def call(args: dict) -> str:
        request = json.dumps({
            "jsonrpc": "2.0", "id": 1,
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


def connect_all(registry: ToolRegistry, path: pathlib.Path) -> None:
    """Connect to all MCP servers in *path* and register their tools. Blocking, 3s timeout."""
    for cfg in load_mcp_config(path):
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
