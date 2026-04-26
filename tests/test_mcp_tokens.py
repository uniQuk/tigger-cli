"""Tests for /mcp tokens analytics command (Unit 7)."""
from tigger.commands.mcp_cmd import cmd_mcp
from tigger.mcp import McpConnection, _connections
from tigger.tools import ToolRegistry
from tigger.types import Config, RunContext, ToolDef


def _ctx() -> RunContext:
    return RunContext(
        config=Config(base_url="http://x", model="m"),
        messages=[],
        system_prompt="",
    )


class _FakeTransport:
    def __init__(self):
        self.calls = []

    def send(self, method, params):
        self.calls.append(method)
        return {}

    def close(self):
        pass


def _conn(name: str) -> McpConnection:
    return McpConnection(
        name=name,
        transport=_FakeTransport(),
        server_info={"name": name},
        capabilities={"tools": {}},
        protocol_version="2025-03-26",
    )


def _tool(name: str, tier: str = "eager", description: str = "x", schema: dict | None = None) -> ToolDef:
    return ToolDef(
        name=name, description=description,
        parameters=schema or {"type": "object", "properties": {"x": {"type": "string"}}},
        func=lambda _: "", read_only=False, tier=tier,
    )


def setup_function():
    _connections.clear()


def teardown_function():
    _connections.clear()


def test_tokens_no_servers(capsys):
    registry = ToolRegistry()
    cmd_mcp("tokens", _ctx(), connections=[], registry=registry)
    out = capsys.readouterr().out
    assert "No MCP servers" in out


def test_tokens_lists_per_server_with_tiers_and_totals(capsys):
    registry = ToolRegistry()
    registry.register(_tool("mcp__pw__navigate", tier="eager"))
    registry.register(_tool("mcp__pw__click", tier="eager"))
    registry.register(_tool("mcp__github__search", tier="lazy"))
    conns = [_conn("pw"), _conn("github")]

    cmd_mcp("tokens", _ctx(), connections=conns, registry=registry)
    out = capsys.readouterr().out
    assert "pw" in out
    assert "github" in out
    assert "eager" in out
    assert "lazy" in out


def test_tokens_per_row_carries_cl100k_caveat(capsys):
    """Adversarial review point: caveat on every row, not only the header."""
    registry = ToolRegistry()
    registry.register(_tool("mcp__pw__navigate", tier="eager"))
    conns = [_conn("pw")]

    cmd_mcp("tokens", _ctx(), connections=conns, registry=registry)
    out = capsys.readouterr().out
    # The literal tag appears multiple times — one per row that displays a number
    assert out.count("cl100k") >= 2


def test_tokens_summary_rows(capsys):
    registry = ToolRegistry()
    registry.register(_tool("mcp__pw__navigate", tier="eager"))
    registry.register(_tool("mcp__pw__click", tier="eager"))
    registry.register(_tool("mcp__github__search", tier="lazy"))
    conns = [_conn("pw"), _conn("github")]

    cmd_mcp("tokens", _ctx(), connections=conns, registry=registry)
    out = capsys.readouterr().out.lower()
    # Eager total per turn + lazy potential
    assert "total eager" in out or "eager total" in out or "eager:" in out
    assert "lazy" in out


def test_tokens_disabled_count_in_summary(capsys):
    registry = ToolRegistry()
    registry.register(_tool("mcp__pw__navigate", tier="eager"))
    # Disabled connection has the marker; no tools registered for it
    disabled_conn = _conn("experimental")
    disabled_conn.server_info = {"disabled": True}
    conns = [_conn("pw"), disabled_conn]

    cmd_mcp("tokens", _ctx(), connections=conns, registry=registry)
    out = capsys.readouterr().out.lower()
    assert "disabled" in out
    assert "1" in out  # one disabled server


def test_tokens_emits_tip_when_one_server_dominates_eager(capsys):
    """One server > 50% of eager budget → actionable tip."""
    registry = ToolRegistry()
    # Heavy server: 5 verbose tools
    big_schema = {
        "type": "object",
        "properties": {f"prop_{i}": {"type": "string", "description": "x" * 200} for i in range(20)},
    }
    for i in range(5):
        registry.register(_tool(f"mcp__playwright__tool_{i}", tier="eager", schema=big_schema))
    # Tiny server: one trivial tool
    registry.register(_tool("mcp__tiny__ping", tier="eager"))
    conns = [_conn("playwright"), _conn("tiny")]

    cmd_mcp("tokens", _ctx(), connections=conns, registry=registry)
    out = capsys.readouterr().out
    assert "Tip" in out or "tip" in out
    assert "playwright" in out


def test_tokens_no_tip_when_balanced(capsys):
    registry = ToolRegistry()
    registry.register(_tool("mcp__a__one", tier="eager"))
    registry.register(_tool("mcp__b__one", tier="eager"))
    conns = [_conn("a"), _conn("b")]

    cmd_mcp("tokens", _ctx(), connections=conns, registry=registry)
    out = capsys.readouterr().out
    # Two equal servers — neither >50%
    assert "Tip:" not in out


def test_tokens_handles_zero_eager_budget(capsys):
    """All tools lazy/disabled — should not crash on division by zero in tip logic."""
    registry = ToolRegistry()
    registry.register(_tool("mcp__pw__navigate", tier="lazy"))
    conns = [_conn("pw")]

    cmd_mcp("tokens", _ctx(), connections=conns, registry=registry)
    out = capsys.readouterr().out
    # No crash; lazy total surfaces
    assert "lazy" in out.lower()


def test_tokens_is_read_only_no_network_calls(capsys):
    registry = ToolRegistry()
    registry.register(_tool("mcp__pw__navigate", tier="eager"))
    fake = _FakeTransport()
    conn = McpConnection(
        name="pw", transport=fake,
        server_info={"name": "pw"}, capabilities={"tools": {}},
        protocol_version="2025-03-26",
    )

    cmd_mcp("tokens", _ctx(), connections=[conn], registry=registry)
    # No tools/list, no network — pure registry inspection
    assert fake.calls == []
    # And registry is unmutated
    assert registry.get("mcp__pw__navigate").tier == "eager"


def test_tokens_breakdown_sorts_per_tool_descending(capsys):
    """Within a server, tools sort by token cost descending."""
    registry = ToolRegistry()
    big_schema = {
        "type": "object",
        "properties": {f"prop_{i}": {"type": "string", "description": "x" * 50} for i in range(15)},
    }
    small_schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    registry.register(_tool("mcp__pw__big_tool", tier="eager", schema=big_schema))
    registry.register(_tool("mcp__pw__tiny_tool", tier="eager", schema=small_schema))
    conns = [_conn("pw")]

    cmd_mcp("tokens", _ctx(), connections=conns, registry=registry)
    out = capsys.readouterr().out
    big_idx = out.index("big_tool")
    tiny_idx = out.index("tiny_tool")
    assert big_idx < tiny_idx  # bigger tool listed first
