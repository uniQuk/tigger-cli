"""Tests for /mcp tier runtime command (Unit 6)."""
import json

from tigger.commands.mcp_cmd import cmd_mcp
from tigger.mcp import McpConnection, _connections, _DisabledTransport
from tigger.tools import ToolRegistry
from tigger.types import Config, RunContext, ToolDef


def _ctx() -> RunContext:
    return RunContext(
        config=Config(base_url="http://x", model="m"),
        messages=[],
        system_prompt="",
    )


def _stub(name: str, tier: str = "eager") -> ToolDef:
    return ToolDef(
        name=name, description="", parameters={},
        func=lambda _: "ok", read_only=False, tier=tier,
    )


class _FakeTransport:
    """Transport that records its lifecycle so tests can verify close()."""

    def __init__(self):
        self.closed = False

    def send(self, method, params):
        return {}

    def close(self):
        self.closed = True


def _make_conn(name: str, transport=None) -> McpConnection:
    return McpConnection(
        name=name,
        transport=transport or _FakeTransport(),
        server_info={"name": name, "version": "1.0"},
        capabilities={"tools": {}},
        protocol_version="2025-03-26",
    )


def setup_function():
    _connections.clear()
    # Reset the once-per-session warning flag so tests are order-independent.
    import tigger.commands.mcp_cmd as mcp_cmd_mod
    mcp_cmd_mod._disable_warning_shown = False


def teardown_function():
    _connections.clear()


# --- /mcp tier (no args): print current tiers ---


def test_tier_no_args_prints_per_server_tier(capsys):
    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="lazy"))
    registry.register(_stub("mcp__pw__click", tier="lazy"))
    registry.register(_stub("mcp__github__search", tier="eager"))
    conns = [_make_conn("pw"), _make_conn("github")]

    cmd_mcp("tier", _ctx(), connections=conns, registry=registry)
    out = capsys.readouterr().out
    assert "pw" in out
    assert "github" in out
    assert "lazy" in out
    assert "eager" in out


# --- /mcp tier <server> <tier>: mutate ---


def test_tier_set_to_lazy_mutates_tooldefs(capsys):
    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="eager"))
    registry.register(_stub("mcp__pw__click", tier="eager"))
    registry.register(_stub("mcp__other__x", tier="eager"))
    conns = [_make_conn("pw"), _make_conn("other")]

    cmd_mcp("tier pw lazy", _ctx(), connections=conns, registry=registry)
    assert registry.get("mcp__pw__navigate").tier == "lazy"
    assert registry.get("mcp__pw__click").tier == "lazy"
    assert registry.get("mcp__other__x").tier == "eager"  # untouched
    out = capsys.readouterr().out
    assert "lazy" in out


def test_tier_set_to_eager_re_promotes(capsys):
    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="lazy"))
    conns = [_make_conn("pw")]

    cmd_mcp("tier pw eager", _ctx(), connections=conns, registry=registry)
    assert registry.get("mcp__pw__navigate").tier == "eager"


def test_tier_set_to_disabled_closes_transport_and_keeps_connection(capsys):
    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="eager"))
    fake = _FakeTransport()
    conns = [_make_conn("pw", transport=fake)]

    cmd_mcp("tier pw disabled", _ctx(), connections=conns, registry=registry)
    assert fake.closed is True
    assert registry.get("mcp__pw__navigate").tier == "disabled"
    # Connection still in the list so /mcp can show it
    assert len(conns) == 1
    out = capsys.readouterr().out.lower()
    assert "restart required to re-enable" in out


def test_tier_disabled_warning_only_once_per_session(capsys):
    """The 'restart required to re-enable' warning fires once per session, not every call."""
    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="eager"))
    registry.register(_stub("mcp__github__search", tier="eager"))
    conns = [_make_conn("pw"), _make_conn("github")]

    cmd_mcp("tier pw disabled", _ctx(), connections=conns, registry=registry)
    capsys.readouterr()  # drain
    cmd_mcp("tier github disabled", _ctx(), connections=conns, registry=registry)
    second = capsys.readouterr().out.lower()
    assert "restart required to re-enable" not in second


# --- R10: disabled → eager/lazy is rejected ---


def test_tier_disabled_to_eager_is_rejected(capsys):
    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="disabled"))
    conns = [_make_conn("pw", transport=_DisabledTransport())]

    cmd_mcp("tier pw eager", _ctx(), connections=conns, registry=registry)
    assert registry.get("mcp__pw__navigate").tier == "disabled"  # unchanged
    out = capsys.readouterr().out.lower()
    assert "config" in out or "restart" in out
    assert "disabled" in out


def test_tier_disabled_to_disabled_is_noop_success(capsys):
    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="disabled"))
    conns = [_make_conn("pw", transport=_DisabledTransport())]

    cmd_mcp("tier pw disabled", _ctx(), connections=conns, registry=registry)
    # No error
    out = capsys.readouterr().out
    assert "error" not in out.lower()


# --- Errors ---


def test_tier_unknown_server_errors_with_valid_names(capsys):
    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="eager"))
    conns = [_make_conn("pw"), _make_conn("github")]

    cmd_mcp("tier nonexistent lazy", _ctx(), connections=conns, registry=registry)
    out = capsys.readouterr().out
    assert "nonexistent" in out
    # State unchanged
    assert registry.get("mcp__pw__navigate").tier == "eager"


def test_tier_unknown_value_errors(capsys):
    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="eager"))
    conns = [_make_conn("pw")]

    cmd_mcp("tier pw turbo", _ctx(), connections=conns, registry=registry)
    out = capsys.readouterr().out.lower()
    assert "turbo" in out or "invalid" in out or "unknown" in out
    assert registry.get("mcp__pw__navigate").tier == "eager"


# --- --save ---


def test_tier_save_writes_user_mcp_json(tmp_path, monkeypatch):
    user_mcp = tmp_path / "mcp.json"
    user_mcp.write_text(json.dumps({"servers": {}}))

    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="eager"))
    conns = [_make_conn("pw")]

    monkeypatch.setattr(
        "tigger.commands.mcp_cmd._user_mcp_path",
        lambda: user_mcp,
    )
    cmd_mcp("tier pw lazy --save", _ctx(), connections=conns, registry=registry)

    written = json.loads(user_mcp.read_text())
    assert written["servers"]["pw"]["tier"] == "lazy"


def test_tier_save_preserves_unknown_keys(tmp_path, monkeypatch):
    """--save must not lose user fields not modeled in McpServerConfig."""
    user_mcp = tmp_path / "mcp.json"
    user_mcp.write_text(json.dumps({
        "servers": {
            "pw": {
                "command": ["npx", "@playwright/mcp"],
                "custom_user_field": "preserved",
                "env": {"FOO": "bar"},
            }
        }
    }))

    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="eager"))
    conns = [_make_conn("pw")]

    monkeypatch.setattr(
        "tigger.commands.mcp_cmd._user_mcp_path",
        lambda: user_mcp,
    )
    cmd_mcp("tier pw lazy --save", _ctx(), connections=conns, registry=registry)

    written = json.loads(user_mcp.read_text())
    assert written["servers"]["pw"]["tier"] == "lazy"
    assert written["servers"]["pw"]["custom_user_field"] == "preserved"
    assert written["servers"]["pw"]["env"] == {"FOO": "bar"}
    assert written["servers"]["pw"]["command"] == ["npx", "@playwright/mcp"]


def test_tier_save_adds_server_block_when_absent(tmp_path, monkeypatch):
    """--save on a server only present in project mcp.json adds it to the user mcp.json."""
    user_mcp = tmp_path / "mcp.json"
    user_mcp.write_text(json.dumps({"servers": {}}))

    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="eager"))
    conns = [_make_conn("pw")]

    monkeypatch.setattr(
        "tigger.commands.mcp_cmd._user_mcp_path",
        lambda: user_mcp,
    )
    cmd_mcp("tier pw lazy --save", _ctx(), connections=conns, registry=registry)

    written = json.loads(user_mcp.read_text())
    assert written["servers"]["pw"] == {"tier": "lazy"}


def test_tier_without_save_does_not_touch_disk(tmp_path, monkeypatch):
    user_mcp = tmp_path / "mcp.json"
    user_mcp.write_text(json.dumps({"servers": {"pw": {"tier": "eager"}}}))

    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="eager"))
    conns = [_make_conn("pw")]

    monkeypatch.setattr(
        "tigger.commands.mcp_cmd._user_mcp_path",
        lambda: user_mcp,
    )
    cmd_mcp("tier pw lazy", _ctx(), connections=conns, registry=registry)

    # In-memory mutated, on-disk unchanged
    assert registry.get("mcp__pw__navigate").tier == "lazy"
    on_disk = json.loads(user_mcp.read_text())
    assert on_disk["servers"]["pw"]["tier"] == "eager"


def test_tier_save_creates_parent_directory(tmp_path, monkeypatch):
    """--save works even when ~/.tigger/ doesn't yet exist."""
    user_mcp = tmp_path / "subdir" / "mcp.json"

    registry = ToolRegistry()
    registry.register(_stub("mcp__pw__navigate", tier="eager"))
    conns = [_make_conn("pw")]

    monkeypatch.setattr(
        "tigger.commands.mcp_cmd._user_mcp_path",
        lambda: user_mcp,
    )
    cmd_mcp("tier pw lazy --save", _ctx(), connections=conns, registry=registry)

    written = json.loads(user_mcp.read_text())
    assert written["servers"]["pw"]["tier"] == "lazy"
