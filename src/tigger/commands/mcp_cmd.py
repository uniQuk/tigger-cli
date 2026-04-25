from __future__ import annotations
from tigger.mcp import McpConnection
from tigger.tools import ToolRegistry
from tigger.types import RunContext


def cmd_mcp(
    args: str,
    ctx: RunContext,
    *,
    connections: list[McpConnection],
    registry: ToolRegistry,
) -> None:
    """Display connected MCP servers and their tools."""
    if not connections:
        print("\n  No MCP servers connected.\n")
        return

    print(f"\n  MCP Servers ({len(connections)})")
    for conn in connections:
        # Derive transport type from class name
        transport_type = type(conn.transport).__name__.replace("Transport", "").lower()

        # Count tools with this server's prefix
        prefix = f"mcp__{conn.name}__"
        tool_count = sum(1 for t in registry.all() if t.name.startswith(prefix))

        # Server version
        version = "unknown"
        if conn.server_info and conn.server_info.get("version"):
            version = conn.server_info["version"]

        # Target info
        if transport_type == "stdio":
            target = f"pid={conn.transport.proc.pid}" if hasattr(conn.transport, "proc") else ""
        elif hasattr(conn.transport, "_url"):
            target = conn.transport._url
        elif hasattr(conn.transport, "_endpoint_url"):
            target = conn.transport._endpoint_url
        else:
            target = ""

        print(f"    {conn.name:<20} {transport_type:<8} {tool_count} tools  {target}  v{version}")

    print()
