from __future__ import annotations

import json
import pathlib

from tigger._constants import home_config_dir
from tigger.mcp import McpConnection
from tigger.tools import ToolRegistry
from tigger.types import RunContext

_VALID_TIERS = {"eager", "lazy", "disabled"}

# Module-level: track whether we've shown the "restart required to re-enable"
# warning yet this session, so it fires once not on every disable.
_disable_warning_shown = False


def _user_mcp_path() -> pathlib.Path:
    """User-level mcp.json path. Indirected so tests can monkeypatch."""
    return home_config_dir() / "mcp.json"


def cmd_mcp(
    args: str,
    ctx: RunContext,
    *,
    connections: list[McpConnection],
    registry: ToolRegistry,
) -> None:
    """Dispatch /mcp sub-commands.

    `/mcp`            → status
    `/mcp tier ...`   → tier inspection / mutation
    """
    parts = args.split() if args else []
    if not parts:
        _cmd_mcp_status(connections, registry)
        return
    sub = parts[0]
    rest = parts[1:]
    if sub == "tier":
        _cmd_mcp_tier(rest, connections=connections, registry=registry)
        return
    if sub == "tokens":
        _cmd_mcp_tokens(connections=connections, registry=registry)
        return
    print(f"\n  Unknown /mcp sub-command: {sub}\n")


# ── Status (no-arg /mcp) ─────────────────────────────────────────────────


def _cmd_mcp_status(
    connections: list[McpConnection],
    registry: ToolRegistry,
) -> None:
    from tigger.ui import console

    if not connections:
        console.print("\n  [dim]No MCP servers connected.[/dim]\n")
        return

    console.print()
    console.print(f"[bold]MCP Servers[/bold] [dim]({len(connections)})[/dim]")
    for conn in connections:
        # Disabled servers carry a sentinel transport; surface that distinctly.
        is_disabled = bool(conn.server_info and conn.server_info.get("disabled"))
        if is_disabled:
            transport_type = "disabled"
        else:
            transport_type = type(conn.transport).__name__.replace("Transport", "").lower()

        prefix = f"mcp__{conn.name}__"
        tool_count = sum(1 for t in registry.all() if t.name.startswith(prefix))

        version = "unknown"
        if conn.server_info and conn.server_info.get("version"):
            version = conn.server_info["version"]

        if transport_type == "disabled":
            target = "(skipped)"
        elif transport_type == "stdio":
            target = f"pid={conn.transport.proc.pid}" if hasattr(conn.transport, "proc") else ""
        elif hasattr(conn.transport, "_url"):
            target = conn.transport._url
        elif hasattr(conn.transport, "_endpoint_url"):
            target = conn.transport._endpoint_url
        else:
            target = ""

        transport_colour = "yellow" if is_disabled else "cyan"
        console.print(
            f"  [magenta]{conn.name:<20}[/magenta] "
            f"[{transport_colour}]{transport_type:<8}[/{transport_colour}] "
            f"[dim]{tool_count} tools[/dim]  "
            f"{target}  [dim]v{version}[/dim]"
        )

    console.print()


# ── Tier sub-command ─────────────────────────────────────────────────────


def _cmd_mcp_tier(
    args: list[str],
    *,
    connections: list[McpConnection],
    registry: ToolRegistry,
) -> None:
    """Inspect or mutate per-server tier at runtime.

    Forms:
      /mcp tier                           → list current tiers
      /mcp tier <server> <tier>           → mutate session-only
      /mcp tier <server> <tier> --save    → also persist to user mcp.json
    """
    save = False
    if "--save" in args:
        save = True
        args = [a for a in args if a != "--save"]

    if not args:
        _print_current_tiers(connections, registry)
        return

    if len(args) == 1:
        # Single server name → show its tier
        _print_server_tier(args[0], connections, registry)
        return

    server, tier = args[0], args[1]

    if tier not in _VALID_TIERS:
        from tigger.ui import console
        console.print(
            f"\n  [red]Invalid tier[/red] {tier!r}. "
            "[dim]Valid:[/dim] eager | lazy | disabled\n"
        )
        return

    matching_tools = [t for t in registry.all() if t.name.startswith(f"mcp__{server}__")]
    matching_conn = next((c for c in connections if c.name == server), None)

    if not matching_tools and matching_conn is None:
        from tigger.ui import console
        valid_names = sorted({c.name for c in connections})
        names_str = ", ".join(valid_names) or "(none)"
        console.print(
            f"\n  [red]Unknown server[/red] {server!r}. "
            f"[dim]Connected servers:[/dim] {names_str}\n"
        )
        return

    # R10: disabled cannot be promoted at runtime. A server is "currently disabled"
    # if either the connection carries the disabled marker OR every registered tool
    # is at tier="disabled" (matches both connect-time disable and runtime disable).
    conn_marked = bool(
        matching_conn is not None
        and matching_conn.server_info
        and matching_conn.server_info.get("disabled")
    )
    all_tools_disabled = bool(matching_tools) and all(t.tier == "disabled" for t in matching_tools)
    is_currently_disabled = conn_marked or all_tools_disabled
    if is_currently_disabled and tier != "disabled":
        from tigger.ui import console
        console.print(
            f"\n  [yellow]'{server}' is currently disabled.[/yellow] "
            "[dim]Edit mcp.json and restart to re-enable.[/dim]\n"
        )
        return

    # Mutate ToolDef.tier in place.
    for t in matching_tools:
        t.tier = tier

    # If transitioning to disabled, close the live transport (if any) and mark the connection.
    if tier == "disabled" and matching_conn is not None and not is_currently_disabled:
        try:
            matching_conn.transport.close()
        except Exception:
            pass
        # Mark the connection as disabled so /mcp status reflects it.
        matching_conn.server_info = {"disabled": True, **(matching_conn.server_info or {})}

    # First-time disabled-at-runtime warning, once per session.
    global _disable_warning_shown
    if tier == "disabled" and not is_currently_disabled and not _disable_warning_shown:
        _disable_warning_shown = True
        from tigger.ui import console
        console.print(
            f"\n  [dim]✓[/dim] [magenta]{server}[/magenta] "
            "[dim]tier set to[/dim] [yellow]disabled[/yellow]. "
            "[dim](Restart required to re-enable; --save to persist.)[/dim]\n"
        )
    else:
        from tigger.ui import console
        console.print(
            f"\n  [dim]✓[/dim] [magenta]{server}[/magenta] "
            f"[dim]tier set to[/dim] [cyan]{tier}[/cyan].\n"
        )

    if save:
        _persist_tier_to_user_config(server, tier)


def _print_current_tiers(
    connections: list[McpConnection],
    registry: ToolRegistry,
) -> None:
    """Print one row per server: name and the most common tier among its tools.

    For uniform-tier servers (the common case), the row is unambiguous. For
    mixed-tier servers (per-tool overrides in play), prefix with '~' so the
    user knows tools differ.
    """
    from tigger.ui import console
    if not connections:
        console.print("\n  [dim]No MCP servers connected.[/dim]\n")
        return
    console.print()
    for conn in connections:
        prefix = f"mcp__{conn.name}__"
        tools = [t for t in registry.all() if t.name.startswith(prefix)]
        is_disabled = bool(conn.server_info and conn.server_info.get("disabled"))
        if is_disabled:
            tier = "disabled"
        elif not tools:
            tier = "(no tools)"
        else:
            tiers = {t.tier for t in tools}
            if len(tiers) == 1:
                tier = next(iter(tiers))
            else:
                tier = "~mixed"
        # Colour by tier: eager green, lazy cyan, disabled yellow, mixed magenta.
        if tier == "eager":
            tcol = "green"
        elif tier == "lazy":
            tcol = "cyan"
        elif tier == "disabled":
            tcol = "yellow"
        else:
            tcol = "magenta"
        console.print(
            f"  [magenta]{conn.name:<20}[/magenta] [{tcol}]{tier}[/{tcol}]"
        )
    console.print()


def _print_server_tier(
    server: str,
    connections: list[McpConnection],
    registry: ToolRegistry,
) -> None:
    matching_tools = [t for t in registry.all() if t.name.startswith(f"mcp__{server}__")]
    matching_conn = next((c for c in connections if c.name == server), None)
    if not matching_tools and matching_conn is None:
        valid_names = sorted({c.name for c in connections})
        names_str = ", ".join(valid_names) or "(none)"
        print(f"\n  Unknown server {server!r}. Connected: {names_str}\n")
        return
    is_disabled = bool(
        matching_conn
        and matching_conn.server_info
        and matching_conn.server_info.get("disabled")
    )
    if is_disabled:
        print(f"\n  {server}: disabled\n")
        return
    tiers = {t.tier for t in matching_tools}
    if len(tiers) == 1:
        print(f"\n  {server}: {next(iter(tiers))}\n")
    else:
        prefix = f"mcp__{server}__"
        breakdown = ", ".join(f"{t.name[len(prefix):]}={t.tier}" for t in matching_tools)
        print(f"\n  {server}: mixed ({breakdown})\n")


def _cmd_mcp_tokens(
    *,
    connections: list[McpConnection],
    registry: ToolRegistry,
) -> None:
    """Read-only display of per-server schema token cost.

    Token counts use cl100k_base, which is OpenAI-specific. Per-row tags
    surface this caveat at every reading rather than only in the header
    so the limitation is visible at the point of decision.
    """
    from tigger.ui import console

    if not connections:
        console.print("\n  [dim]No MCP servers to analyze.[/dim]\n")
        return

    enc, fallback = _load_encoder()
    encoding_note = "(approximate, tiktoken unavailable)" if enc is None else ""

    # Build per-server breakdown
    server_data: dict[str, dict] = {}
    for conn in connections:
        prefix = f"mcp__{conn.name}__"
        tools = [t for t in registry.all() if t.name.startswith(prefix)]
        is_disabled = bool(conn.server_info and conn.server_info.get("disabled"))
        per_tool: list[tuple[str, int, str]] = []  # (short_name, tokens, tier)
        for t in tools:
            cost = _count_schema_tokens(t, enc, fallback)
            per_tool.append((t.name[len(prefix):], cost, t.tier))
        per_tool.sort(key=lambda x: x[1], reverse=True)
        if is_disabled:
            tier_label = "disabled"
        elif not tools:
            tier_label = "(none)"
        else:
            tiers = {t.tier for t in tools}
            tier_label = next(iter(tiers)) if len(tiers) == 1 else "~mixed"
        total = sum(c for _, c, _ in per_tool)
        server_data[conn.name] = {
            "tier_label": tier_label,
            "tools": per_tool,
            "total": total,
            "disabled": is_disabled,
        }

    # Sort servers by total descending
    sorted_servers = sorted(server_data.items(), key=lambda kv: kv[1]["total"], reverse=True)

    note_suffix = f" [dim]{encoding_note}[/dim]" if encoding_note else ""
    console.print(f"\n[bold]MCP Schema Token Cost[/bold]{note_suffix}")
    console.print()
    # Header row
    console.print(
        f"  [dim]{'Server':<20} {'Tier':<10} {'Tools':<6} {'Tokens':<10}[/dim]"
    )

    def _tier_colour(tier: str) -> str:
        if tier == "eager":
            return "green"
        if tier == "lazy":
            return "cyan"
        if tier == "disabled":
            return "yellow"
        return "magenta"

    eager_total = 0
    lazy_total = 0
    disabled_count = 0
    eager_per_server: dict[str, int] = {}

    for name, data in sorted_servers:
        if data["disabled"]:
            disabled_count += 1
            console.print(
                f"  [magenta]{name:<20}[/magenta] [yellow]{'disabled':<10}[/yellow] "
                f"[dim]{0:<6} {'—':<10}[/dim]"
            )
            continue
        # Per-server total counts what would actually ship: only eager tools.
        server_eager = sum(c for _, c, t in data["tools"] if t == "eager")
        server_lazy = sum(c for _, c, t in data["tools"] if t == "lazy")
        eager_total += server_eager
        lazy_total += server_lazy
        if server_eager > 0:
            eager_per_server[name] = server_eager
        # Display the eager portion as the "per-turn" cost; lazy is potential.
        display_total = server_eager
        tcol = _tier_colour(data["tier_label"])
        console.print(
            f"  [magenta]{name:<20}[/magenta] "
            f"[{tcol}]{data['tier_label']:<10}[/{tcol}] "
            f"[bold]{len(data['tools']):<6}[/bold] "
            f"[bold]{display_total}[/bold] [dim](cl100k est.)[/dim]"
        )
        # Per-tool breakdown for top N tools
        top_n = 5
        for short_name, cost, tier in data["tools"][:top_n]:
            tcol2 = _tier_colour(tier)
            tier_marker = "" if tier == "eager" else f" [{tcol2}][{tier}][/{tcol2}]"
            console.print(
                f"      [dim]{short_name:<24}[/dim] {cost} [dim](cl100k est.){tier_marker}[/dim]"
            )
        remaining = len(data["tools"]) - top_n
        if remaining > 0:
            console.print(f"      [dim]... ({remaining} more)[/dim]")

    console.print()
    console.print(
        f"  [dim]Total eager (per turn):[/dim]      "
        f"[bold green]{eager_total}[/bold green] [dim](cl100k est.)[/dim]"
    )
    console.print(
        f"  [dim]Lazy potential (not sent):[/dim]   "
        f"[cyan]{lazy_total}[/cyan] [dim](cl100k est.)[/dim]"
    )
    console.print(
        f"  [dim]Disabled servers:[/dim]            "
        f"[yellow]{disabled_count}[/yellow]"
    )

    # Tip when one server dominates the eager budget
    if eager_total > 0 and eager_per_server:
        biggest_name, biggest_cost = max(eager_per_server.items(), key=lambda kv: kv[1])
        share = biggest_cost / eager_total
        if share > 0.5:
            pct = round(share * 100)
            console.print(
                f"\n  [yellow]Tip:[/yellow] [magenta]{biggest_name}[/magenta] "
                f"is [bold]{pct}%[/bold] of eager budget. "
                f"[dim]Try[/dim] [cyan]/mcp tier {biggest_name} lazy[/cyan]."
            )
    console.print()


def _load_encoder():
    """Return (enc, fallback_fn). enc is None when tiktoken is unavailable."""
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base"), None
    except Exception:
        # Fallback matches compaction.py: ~3.5 chars per token
        return None, lambda s: int(len(s) / 3.5)


def _count_schema_tokens(tool, enc, fallback) -> int:
    """Count tokens for a single tool's schema in the wire format."""
    schema = {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
    serialized = json.dumps(schema, separators=(",", ":"))
    if enc is not None:
        try:
            return len(enc.encode(serialized))
        except Exception:
            pass
    return fallback(serialized) if fallback else int(len(serialized) / 3.5)


def _persist_tier_to_user_config(server: str, tier: str) -> None:
    """Read-modify-write the user mcp.json, preserving unknown keys."""
    path = _user_mcp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            print(f"\n  Error: could not parse {path}: {exc}\n")
            return
    else:
        data = {}
    servers = data.setdefault("servers", {})
    server_block = servers.setdefault(server, {})
    server_block["tier"] = tier
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  Saved tier={tier} for '{server}' to {path}")
