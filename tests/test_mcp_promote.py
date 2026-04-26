"""Tests for the native mcp_promote tool (Unit 4)."""
from tigger.tools import ToolRegistry, register_all
from tigger.types import ToolDef


def _stub(name: str, tier: str = "eager") -> ToolDef:
    return ToolDef(
        name=name, description="", parameters={},
        func=lambda _: "ok", read_only=True, tier=tier,
    )


def test_mcp_promote_is_always_registered():
    r = ToolRegistry()
    register_all(r)
    assert r.get("mcp_promote") is not None


def test_mcp_promote_appears_in_schemas_as_eager():
    r = ToolRegistry()
    register_all(r)
    names = [s["function"]["name"] for s in r.schemas()]
    assert "mcp_promote" in names


def test_mcp_promote_promotes_lazy_server():
    r = ToolRegistry()
    register_all(r)
    r.register(_stub("mcp__pw__navigate", tier="lazy"))
    r.register(_stub("mcp__pw__click", tier="lazy"))
    result = r.execute("mcp_promote", {"server": "pw"})
    assert result.error is False
    # Lazy gate from Unit 1 no longer fires for these tools
    assert r.get("mcp__pw__navigate").tier == "eager"
    assert r.get("mcp__pw__click").tier == "eager"
    # Output names the now-available tools
    assert "navigate" in result.output
    assert "click" in result.output


def test_mcp_promote_already_eager_is_noop_success():
    r = ToolRegistry()
    register_all(r)
    r.register(_stub("mcp__pw__navigate", tier="eager"))
    result = r.execute("mcp_promote", {"server": "pw"})
    assert result.error is False
    assert "already" in result.output.lower() or "eager" in result.output.lower()


def test_mcp_promote_disabled_server_errors_with_restart_directive():
    r = ToolRegistry()
    register_all(r)
    r.register(_stub("mcp__exp__bork", tier="disabled"))
    result = r.execute("mcp_promote", {"server": "exp"})
    assert result.error is True
    assert "disabled" in result.output.lower()
    assert "restart" in result.output.lower() or "mcp.json" in result.output.lower()
    # State unchanged
    assert r.get("mcp__exp__bork").tier == "disabled"


def test_mcp_promote_unknown_server_errors():
    r = ToolRegistry()
    register_all(r)
    r.register(_stub("mcp__pw__navigate", tier="lazy"))
    result = r.execute("mcp_promote", {"server": "nonexistent"})
    assert result.error is True
    assert "no MCP server" in result.output or "nonexistent" in result.output


def test_mcp_promote_after_promotion_lazy_gate_no_longer_fires():
    """Integration: model-style call promotes, then a follow-up call to the
    real tool succeeds (no longer hits the lazy gate from Unit 1)."""
    r = ToolRegistry()
    register_all(r)
    r.register(ToolDef(
        name="mcp__pw__navigate", description="", parameters={},
        func=lambda args: f"navigated to {args.get('url')}",
        read_only=False, tier="lazy",
    ))

    # Before promotion: lazy gate fires
    pre = r.execute("mcp__pw__navigate", {"url": "https://example.com"})
    assert pre.error is True
    assert "mcp_promote" in pre.output

    # Promote
    promote_result = r.execute("mcp_promote", {"server": "pw"})
    assert promote_result.error is False

    # After promotion: real tool runs
    post = r.execute("mcp__pw__navigate", {"url": "https://example.com"})
    assert post.error is False
    assert "navigated to https://example.com" in post.output


def test_mcp_promote_only_promotes_lazy_not_disabled_in_mixed_state():
    """If a server has some lazy and some disabled tools, only lazy get promoted."""
    r = ToolRegistry()
    register_all(r)
    r.register(_stub("mcp__pw__navigate", tier="lazy"))
    r.register(_stub("mcp__pw__broken", tier="disabled"))
    result = r.execute("mcp_promote", {"server": "pw"})
    # Disabled tools stay disabled — disabled is set explicitly per-tool and is intentional
    assert r.get("mcp__pw__navigate").tier == "eager"
    assert r.get("mcp__pw__broken").tier == "disabled"
    assert result.error is False
