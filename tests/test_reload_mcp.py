"""Tests for `connect_new` — the MCP-only path used by `/reload-plugins`."""
from __future__ import annotations

import pytest

from tigger import mcp
from tigger.mcp import McpConnection, McpServerConfig, connect_new


class _NullTransport:
    def send(self, method, params):
        return {}

    def close(self):
        return None


@pytest.fixture(autouse=True)
def _isolate_connections(monkeypatch):
    """Each test gets a clean `_connections` list."""
    monkeypatch.setattr(mcp, "_connections", [])
    yield


def _fake_existing(name: str) -> McpConnection:
    return McpConnection(
        name=name,
        transport=_NullTransport(),
        server_info={"name": name},
        capabilities=None,
        protocol_version=None,
    )


def test_connect_new_skips_when_no_new_servers(monkeypatch):
    mcp._connections.append(_fake_existing("alpha"))
    cfg = McpServerConfig(name="alpha", transport="stdio", command=["true"])

    called = {"connect_all": 0}
    def spy(*_a, **_kw):
        called["connect_all"] += 1
    monkeypatch.setattr(mcp, "connect_all", spy)

    started = connect_new(registry=None, configs=[cfg])
    assert started == []
    assert called["connect_all"] == 0


def test_connect_new_starts_only_added_servers(monkeypatch):
    mcp._connections.append(_fake_existing("alpha"))
    cfgs = [
        McpServerConfig(name="alpha", transport="stdio", command=["true"]),
        McpServerConfig(name="beta", transport="stdio", command=["true"]),
        McpServerConfig(name="gamma", transport="stdio", command=["true"]),
    ]

    captured: dict = {}
    def spy(registry, configs, *, require_consent=False):
        captured["names"] = [c.name for c in configs]
        captured["consent"] = require_consent
    monkeypatch.setattr(mcp, "connect_all", spy)

    started = connect_new(registry=None, configs=cfgs)
    assert sorted(started) == ["beta", "gamma"]
    assert sorted(captured["names"]) == ["beta", "gamma"]
    assert captured["consent"] is False


def test_connect_new_leaves_removed_servers_in_connections(monkeypatch):
    """A server present in `_connections` but absent from configs stays
    connected — there is no per-server disconnect today."""
    mcp._connections.append(_fake_existing("kept"))
    mcp._connections.append(_fake_existing("orphaned"))
    cfgs = [McpServerConfig(name="kept", transport="stdio", command=["true"])]

    monkeypatch.setattr(mcp, "connect_all", lambda *a, **k: None)
    connect_new(registry=None, configs=cfgs)

    names = {c.name for c in mcp._connections}
    assert names == {"kept", "orphaned"}  # orphaned still present
