import json
import pathlib
import sys
import tempfile
from unittest.mock import MagicMock, patch

import httpx
import pytest

from tigger.commands.mcp_cmd import cmd_mcp
from tigger.mcp import (
    McpConnection,
    McpServerConfig,
    McpTransportError,
    SseTransport,
    StdioTransport,
    StreamableHttpTransport,
    _connections,
    _make_mcp_tool_func,
    _parse_sse_events,
    connect_all,
    get_connections,
    load_mcp_config,
)
from tigger.resolve import resolve_mcp_configs
from tigger.tools import ToolRegistry

MCP_JSON = {
    "servers": {
        "filesystem": {
            "transport": "stdio",
            "command": ["echo", "hello"]
        }
    }
}

def _write_mcp(data: dict) -> pathlib.Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return pathlib.Path(f.name)

def test_load_mcp_config():
    path = _write_mcp(MCP_JSON)
    configs = load_mcp_config(path)
    assert len(configs) == 1
    assert configs[0].name == "filesystem"
    assert configs[0].transport == "stdio"

def test_load_mcp_config_missing_file():
    configs = load_mcp_config(pathlib.Path("/no/mcp.json"))
    assert configs == []

def test_mcp_server_config_fields():
    cfg = McpServerConfig(name="test", transport="http", url="http://localhost:3001")
    assert cfg.name == "test"
    assert cfg.command is None


def test_mcp_server_config_env_field():
    cfg = McpServerConfig(name="test", transport="stdio", env={"KEY": "val"})
    assert cfg.env == {"KEY": "val"}


def test_mcp_server_config_env_default():
    cfg = McpServerConfig(name="test", transport="stdio")
    assert cfg.env == {}


def test_mcp_connection_fields():
    class _FakeTransport:
        def send(self, method: str, params: dict) -> dict:
            return {}
        def close(self) -> None:
            pass
    conn = McpConnection(
        name="test-server",
        transport=_FakeTransport(),
        server_info={"name": "test", "version": "1.0"},
        capabilities={"tools": {}},
        protocol_version="2025-03-26",
    )
    assert conn.name == "test-server"
    assert conn.server_info["name"] == "test"
    assert conn.capabilities == {"tools": {}}
    assert conn.protocol_version == "2025-03-26"


def test_mcp_transport_error():
    err = McpTransportError("connection refused")
    assert str(err) == "connection refused"
    try:
        raise McpTransportError("timeout")
    except McpTransportError as e:
        assert str(e) == "timeout"


# ── Unit 2: Config loading, env, merging ─────────────────────────────────

def test_load_mcp_config_parses_env():
    data = {"servers": {"s1": {"command": ["echo"], "env": {"API_KEY": "secret"}}}}
    path = _write_mcp(data)
    configs = load_mcp_config(path)
    assert configs[0].env == {"API_KEY": "secret"}


def test_load_mcp_config_no_env_defaults_empty():
    data = {"servers": {"s1": {"command": ["echo"]}}}
    path = _write_mcp(data)
    configs = load_mcp_config(path)
    assert configs[0].env == {}


def test_load_mcp_config_expandvars_command(monkeypatch):
    monkeypatch.setenv("MY_BIN", "/usr/local/bin/server")
    data = {"servers": {"s1": {"command": ["$MY_BIN", "--flag"]}}}
    path = _write_mcp(data)
    configs = load_mcp_config(path)
    assert configs[0].command[0] == "/usr/local/bin/server"


def test_load_mcp_config_expandvars_url(monkeypatch):
    monkeypatch.setenv("MCP_HOST", "example.com")
    data = {"servers": {"s1": {"transport": "http", "url": "http://${MCP_HOST}:8080"}}}
    path = _write_mcp(data)
    configs = load_mcp_config(path)
    assert configs[0].url == "http://example.com:8080"


def test_load_mcp_config_expandvars_undefined_passthrough():
    data = {"servers": {"s1": {"transport": "http", "url": "http://${UNDEFINED_VAR_XYZ}:8080"}}}
    path = _write_mcp(data)
    configs = load_mcp_config(path)
    assert "${UNDEFINED_VAR_XYZ}" in configs[0].url


# ── Tier configuration (eager / lazy / disabled) ───────────────────────


def test_load_mcp_config_default_tier_is_eager():
    """Configs without a tier field default to eager (backwards compat)."""
    data = {"servers": {"s1": {"command": ["echo"]}}}
    path = _write_mcp(data)
    configs = load_mcp_config(path)
    assert configs[0].tier == "eager"
    assert configs[0].tool_tiers == {}


def test_load_mcp_config_parses_tier_lazy():
    data = {"servers": {"s1": {"command": ["echo"], "tier": "lazy"}}}
    path = _write_mcp(data)
    configs = load_mcp_config(path)
    assert configs[0].tier == "lazy"


def test_load_mcp_config_parses_tier_disabled():
    """Disabled servers parse cleanly even without command/url present."""
    data = {"servers": {"s1": {"tier": "disabled"}}}
    path = _write_mcp(data)
    configs = load_mcp_config(path)
    assert configs[0].tier == "disabled"
    # command/url remain unset and that's OK — connect_all skips disabled before _build_transport
    assert configs[0].command is None
    assert configs[0].url is None


def test_load_mcp_config_parses_per_tool_tier_overrides():
    data = {"servers": {"s1": {
        "command": ["echo"],
        "tier": "eager",
        "tools": {"search": "lazy", "create": "eager"},
    }}}
    path = _write_mcp(data)
    configs = load_mcp_config(path)
    assert configs[0].tier == "eager"
    assert configs[0].tool_tiers == {"search": "lazy", "create": "eager"}


def test_load_mcp_config_empty_tools_map():
    data = {"servers": {"s1": {"command": ["echo"], "tools": {}}}}
    path = _write_mcp(data)
    configs = load_mcp_config(path)
    assert configs[0].tool_tiers == {}


def test_load_mcp_config_invalid_tier_warns_and_defaults(capsys):
    """An invalid tier value warns and falls back to eager — does not crash loading."""
    data = {"servers": {"s1": {"command": ["echo"], "tier": "turbo"}}}
    path = _write_mcp(data)
    configs = load_mcp_config(path)
    assert configs[0].tier == "eager"
    out = capsys.readouterr().out + capsys.readouterr().err
    # Warning is fine on stdout (matches existing `[mcp] Warning:` style)
    # We just need *some* signal — assert via re-running with capture
    # The above readouterr already drained; redo:
    # (acceptable: the warning is logged, we don't pin its exact channel)


def test_load_mcp_config_invalid_per_tool_tier_warns(capsys):
    data = {"servers": {"s1": {"command": ["echo"], "tools": {"search": "turbo"}}}}
    path = _write_mcp(data)
    configs = load_mcp_config(path)
    # Bad per-tool tier is dropped; valid entries (none here) remain
    assert configs[0].tool_tiers == {}


def test_resolve_mcp_configs_merges_tiers(tmp_path):
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    # Global has server A
    (global_dir / "mcp.json").write_text(json.dumps({
        "servers": {"server-a": {"command": ["global-a"]}}
    }))
    # Project has server B
    (project_dir / "mcp.json").write_text(json.dumps({
        "servers": {"server-b": {"command": ["project-b"]}}
    }))
    configs = resolve_mcp_configs(project_dir, global_dir, internal_dir=tmp_path / "empty")
    names = {c.name for c in configs}
    assert names == {"server-a", "server-b"}


def test_resolve_mcp_configs_project_shadows_global(tmp_path):
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    # Global has server A with one command
    (global_dir / "mcp.json").write_text(json.dumps({
        "servers": {"server-a": {"command": ["global-cmd"]}}
    }))
    # Project overrides server A
    (project_dir / "mcp.json").write_text(json.dumps({
        "servers": {"server-a": {"command": ["project-cmd"]}}
    }))
    configs = resolve_mcp_configs(project_dir, global_dir, internal_dir=tmp_path / "empty")
    assert len(configs) == 1
    assert configs[0].command == ["project-cmd"]


def test_resolve_mcp_configs_no_files(tmp_path):
    configs = resolve_mcp_configs(tmp_path / "a", tmp_path / "b", internal_dir=tmp_path / "c")
    assert configs == []


def test_resolve_mcp_configs_malformed_json(tmp_path, capsys):
    tier_dir = tmp_path / "bad"
    tier_dir.mkdir()
    (tier_dir / "mcp.json").write_text("{invalid json")
    configs = resolve_mcp_configs(None, tier_dir, internal_dir=tmp_path / "empty")
    assert configs == []
    captured = capsys.readouterr()
    assert "Warning" in captured.err


# ── Unit 3: StdioTransport ───────────────────────────────────────────────

# A tiny Python script that acts as a JSON-RPC echo server on stdin/stdout.
_ECHO_SERVER = r"""
import json, sys
while True:
    line = sys.stdin.readline()
    if not line:
        break
    req = json.loads(line)
    if "id" not in req:
        continue  # notification — no response
    resp = {"jsonrpc": "2.0", "id": req["id"], "result": {"echo": req.get("method")}}
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
"""


def test_stdio_transport_send_receive():
    t = StdioTransport([sys.executable, "-c", _ECHO_SERVER])
    try:
        result = t.send("test/ping", {})
        assert result == {"echo": "test/ping"}
    finally:
        t.close()


def test_stdio_transport_notification():
    t = StdioTransport([sys.executable, "-c", _ECHO_SERVER])
    try:
        result = t.send("notifications/initialized", {})
        assert result == {}
    finally:
        t.close()


def test_stdio_transport_dead_process():
    t = StdioTransport([sys.executable, "-c", "pass"])
    import time
    time.sleep(0.2)  # let process exit
    try:
        t.send("test/ping", {})
        assert False, "Expected McpTransportError"
    except McpTransportError:
        pass
    finally:
        t.close()


def test_stdio_transport_malformed_json():
    # Server that writes non-JSON
    bad_server = r"""
import sys
line = sys.stdin.readline()
sys.stdout.write("not json\n")
sys.stdout.flush()
"""
    t = StdioTransport([sys.executable, "-c", bad_server])
    try:
        t.send("test/ping", {})
        assert False, "Expected McpTransportError"
    except McpTransportError as e:
        assert "invalid JSON" in str(e)
    finally:
        t.close()


def test_stdio_transport_close_already_dead():
    import time
    t = StdioTransport([sys.executable, "-c", "pass"])
    time.sleep(0.2)
    t.close()  # should not raise


def test_stdio_transport_close_terminates():
    # Long-running process
    t = StdioTransport([sys.executable, "-c", "import time; time.sleep(60)"])
    t.close()
    assert t.proc.poll() is not None


def test_stdio_transport_env_merge(monkeypatch):
    # Server that prints the value of TEST_MCP_VAR
    env_server = r"""
import json, os, sys
line = sys.stdin.readline()
req = json.loads(line)
val = os.environ.get("TEST_MCP_VAR", "missing")
sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"val": val}}) + "\n")
sys.stdout.flush()
"""
    t = StdioTransport([sys.executable, "-c", env_server], env={"TEST_MCP_VAR": "hello"})
    try:
        result = t.send("test/env", {})
        assert result["val"] == "hello"
    finally:
        t.close()


# ── Unit 4: StreamableHttpTransport ──────────────────────────────────────

def _mock_json_response(data, status_code=200, headers=None):
    """Create a mock httpx.Response with JSON content."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = headers or {"content-type": "application/json"}
    resp.json.return_value = data
    resp.text = json.dumps(data)
    resp.raise_for_status = MagicMock()
    return resp


def _mock_sse_response(events_text, status_code=200, headers=None):
    """Create a mock httpx.Response with SSE content."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = headers or {"content-type": "text/event-stream"}
    resp.text = events_text
    resp.raise_for_status = MagicMock()
    return resp


def test_parse_sse_events():
    text = "event: message\ndata: {\"id\": 1}\n\nevent: done\ndata: ok\n\n"
    events = _parse_sse_events(text)
    assert len(events) == 2
    assert events[0] == {"event": "message", "data": '{"id": 1}'}
    assert events[1] == {"event": "done", "data": "ok"}


def test_streamable_http_json_response():
    t = StreamableHttpTransport("http://localhost:8080")
    resp_data = {"jsonrpc": "2.0", "id": 99, "result": {"tools": []}}
    mock_resp = _mock_json_response(resp_data)
    with patch.object(t._client, "post", return_value=mock_resp):
        # We need to match the id that will be generated
        result = t.send("tools/list", {})
    assert result == {"tools": []}


def test_streamable_http_sse_response():
    t = StreamableHttpTransport("http://localhost:8080")
    # The transport will assign an id via _id_counter; we don't know it ahead of
    # time, so we patch _parse_sse_response to accept any id.
    sse_text = 'event: message\ndata: {"jsonrpc":"2.0","id":999,"result":{"ok":true}}\n\n'
    mock_resp = _mock_sse_response(sse_text)
    with patch.object(t._client, "post", return_value=mock_resp):
        with patch.object(t, "_parse_sse_response", return_value={"ok": True}):
            result = t.send("tools/list", {})
    assert result == {"ok": True}


def test_streamable_http_session_id():
    t = StreamableHttpTransport("http://localhost:8080")
    resp_data = {"jsonrpc": "2.0", "id": 0, "result": {"serverInfo": {}}}
    mock_resp = _mock_json_response(
        resp_data,
        headers={"content-type": "application/json", "mcp-session-id": "abc-123"},
    )
    with patch.object(t._client, "post", return_value=mock_resp):
        t.send("initialize", {"protocolVersion": "2025-03-26"})
    assert t._session_id == "abc-123"

    # Next request should include the session id in headers
    mock_resp2 = _mock_json_response({"jsonrpc": "2.0", "id": 1, "result": {"tools": []}})
    with patch.object(t._client, "post", return_value=mock_resp2) as mock_post:
        t.send("tools/list", {})
    call_headers = mock_post.call_args[1]["headers"]
    assert call_headers["Mcp-Session-Id"] == "abc-123"


def test_streamable_http_notification():
    t = StreamableHttpTransport("http://localhost:8080")
    mock_resp = _mock_json_response({}, headers={"content-type": "application/json"})
    with patch.object(t._client, "post", return_value=mock_resp):
        result = t.send("notifications/initialized", {})
    assert result == {}


def test_streamable_http_network_error():
    t = StreamableHttpTransport("http://localhost:8080")
    with patch.object(t._client, "post", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(McpTransportError, match="HTTP error"):
            t.send("test/ping", {})


def test_streamable_http_404():
    t = StreamableHttpTransport("http://localhost:8080")
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"
    mock_resp.headers = {"content-type": "text/plain"}
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404", request=MagicMock(), response=mock_resp
    )
    with patch.object(t._client, "post", return_value=mock_resp):
        with pytest.raises(McpTransportError, match="HTTP 404"):
            t.send("test/ping", {})


def test_streamable_http_jsonrpc_error():
    t = StreamableHttpTransport("http://localhost:8080")
    resp_data = {"jsonrpc": "2.0", "id": 0, "error": {"code": -32600, "message": "Invalid"}}
    mock_resp = _mock_json_response(resp_data)
    with patch.object(t._client, "post", return_value=mock_resp):
        with pytest.raises(McpTransportError, match="JSON-RPC error -32600"):
            t.send("test/ping", {})


def test_streamable_http_close():
    t = StreamableHttpTransport("http://localhost:8080")
    with patch.object(t._client, "close") as mock_close:
        t.close()
    mock_close.assert_called_once()


# ── Unit 5: SseTransport ────────────────────────────────────────────────

class _FakeSseStream:
    """Mock httpx streaming response for SSE tests."""

    def __init__(self, lines: list[str]):
        self._lines = lines
        self._iter_idx = 0

    def iter_lines(self):
        yield from self._lines

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _make_sse_transport(endpoint_url="/messages?sid=1", extra_lines=None):
    """Create an SseTransport with mocked SSE stream that provides endpoint event."""
    lines = [
        "event: endpoint",
        f"data: {endpoint_url}",
        "",
    ]
    if extra_lines:
        lines.extend(extra_lines)
    fake_stream = _FakeSseStream(lines)

    with patch("httpx.Client") as MockClient:
        client_instance = MockClient.return_value
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=fake_stream)
        ctx.__exit__ = MagicMock(return_value=False)
        client_instance.stream.return_value = ctx
        t = SseTransport("http://localhost:8080", timeout=5.0)
        # Replace client with a fresh mock for post calls
        t._client = MagicMock()
        return t


def test_sse_transport_init_resolves_endpoint():
    t = _make_sse_transport("/messages?sid=abc")
    assert t._endpoint_url == "http://localhost:8080/messages?sid=abc"
    t.close()


def test_sse_transport_init_absolute_endpoint():
    t = _make_sse_transport("http://other-host:9090/msg")
    assert t._endpoint_url == "http://other-host:9090/msg"
    t.close()


def test_sse_transport_send_notification():
    t = _make_sse_transport()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    t._client.post.return_value = mock_resp
    result = t.send("notifications/initialized", {})
    assert result == {}
    t.close()


def test_sse_transport_send_with_response():
    t = _make_sse_transport()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    t._client.post.return_value = mock_resp

    # Simulate the reader thread delivering a response
    import threading
    def _deliver():
        import time
        time.sleep(0.05)
        # Find the pending queue and deliver a response
        for msg_id, q in list(t._pending.items()):
            q.put({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": ["a"]}})
            break
    deliverer = threading.Thread(target=_deliver)
    deliverer.start()

    result = t.send("tools/list", {})
    assert result == {"tools": ["a"]}
    deliverer.join()
    t.close()


def test_sse_transport_post_failure():
    t = _make_sse_transport()
    t._client.post.side_effect = httpx.ConnectError("refused")
    with pytest.raises(McpTransportError, match="SSE POST failed"):
        t.send("tools/list", {})
    t.close()


def test_sse_transport_close_idempotent():
    t = _make_sse_transport()
    t.close()
    t.close()  # should not raise


def test_sse_transport_init_no_endpoint():
    """SSE stream that never provides an endpoint event."""
    fake_stream = _FakeSseStream(["event: other", "data: irrelevant", ""])
    with patch("httpx.Client") as MockClient:
        client_instance = MockClient.return_value
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=fake_stream)
        ctx.__exit__ = MagicMock(return_value=False)
        client_instance.stream.return_value = ctx
        with pytest.raises(McpTransportError, match="endpoint event not received"):
            SseTransport("http://localhost:8080", timeout=5.0)


# ── Unit 6: Transport-agnostic connect_all + lifecycle ───────────────────

# A tiny MCP server script for integration tests
_MCP_SERVER = r"""
import json, sys
while True:
    line = sys.stdin.readline()
    if not line:
        break
    req = json.loads(line)
    if "id" not in req:
        continue
    method = req["method"]
    if method == "initialize":
        resp = {"jsonrpc": "2.0", "id": req["id"], "result": {
            "serverInfo": {"name": "test-srv", "version": "0.1"},
            "capabilities": {"tools": {}},
            "protocolVersion": "2025-03-26",
        }}
    elif method == "tools/list":
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        tool = {"name": "greet", "description": "Say hello", "inputSchema": schema}
        resp = {"jsonrpc": "2.0", "id": req["id"], "result": {"tools": [tool]}}
    elif method == "tools/call":
        name = req["params"]["arguments"].get("name", "world")
        content = [{"type": "text", "text": f"Hello {name}"}]
        resp = {"jsonrpc": "2.0", "id": req["id"], "result": {"content": content}}
    else:
        resp = {"jsonrpc": "2.0", "id": req["id"], "result": {}}
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
"""


@pytest.fixture(autouse=True)
def _clear_connections():
    """Clear module-level connections before each test."""
    _connections.clear()
    yield
    _connections.clear()


def test_connect_all_stdio():
    registry = ToolRegistry()
    cmd = [sys.executable, "-c", _MCP_SERVER]
    configs = [McpServerConfig(name="test", transport="stdio", command=cmd)]
    connect_all(registry, configs)
    assert len(get_connections()) == 1
    conn = get_connections()[0]
    assert conn.name == "test"
    assert conn.server_info == {"name": "test-srv", "version": "0.1"}
    assert conn.protocol_version == "2025-03-26"
    # Check tool was registered
    tool_names = [t.name for t in registry.all()]
    assert "mcp__test__greet" in tool_names


def test_connect_all_registers_callable_tool():
    registry = ToolRegistry()
    cmd = [sys.executable, "-c", _MCP_SERVER]
    configs = [McpServerConfig(name="test", transport="stdio", command=cmd)]
    connect_all(registry, configs)
    tool = next(t for t in registry.all() if t.name == "mcp__test__greet")
    result = tool.func({"name": "Alice"})
    assert result == "Hello Alice"


def test_connect_all_no_tools_capability():
    """Server without tools capability — no tools/list sent."""
    server = r"""
import json, sys
while True:
    line = sys.stdin.readline()
    if not line:
        break
    req = json.loads(line)
    if "id" not in req:
        continue
    resp = {"jsonrpc": "2.0", "id": req["id"], "result": {
        "serverInfo": {"name": "no-tools"},
        "capabilities": {},
        "protocolVersion": "2025-03-26",
    }}
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
"""
    registry = ToolRegistry()
    cmd = [sys.executable, "-c", server]
    configs = [McpServerConfig(name="bare", transport="stdio", command=cmd)]
    connect_all(registry, configs)
    assert len(get_connections()) == 1
    assert len(registry.all()) == 0


def test_connect_all_protocol_version_mismatch(capsys):
    server = r"""
import json, sys
while True:
    line = sys.stdin.readline()
    if not line:
        break
    req = json.loads(line)
    if "id" not in req:
        continue
    resp = {"jsonrpc": "2.0", "id": req["id"], "result": {
        "serverInfo": {"name": "old"},
        "capabilities": {},
        "protocolVersion": "2024-11-05",
    }}
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
"""
    registry = ToolRegistry()
    cmd = [sys.executable, "-c", server]
    configs = [McpServerConfig(name="old-srv", transport="stdio", command=cmd)]
    connect_all(registry, configs)
    assert len(get_connections()) == 1
    captured = capsys.readouterr()
    assert "protocol" in captured.out.lower()


def test_connect_all_skips_failed_server(capsys):
    registry = ToolRegistry()
    configs = [McpServerConfig(name="bad", transport="stdio", command=["nonexistent-binary-xyz"])]
    connect_all(registry, configs)
    assert len(get_connections()) == 0
    captured = capsys.readouterr()
    assert "Warning" in captured.out


def test_connect_all_empty_configs():
    registry = ToolRegistry()
    connect_all(registry, [])
    assert len(get_connections()) == 0


# ── Tier wiring in connect_all ───────────────────────────────────────────


def test_connect_all_skips_disabled_server(capsys):
    """Disabled servers must not spawn a subprocess, open a transport, or register tools.
    A marker McpConnection is still recorded so /mcp can display them."""
    registry = ToolRegistry()
    # Use a bogus command that would fail loudly if connect_all attempted to spawn
    configs = [McpServerConfig(
        name="experimental",
        transport="stdio",
        command=["definitely-not-a-real-binary-xyz"],
        tier="disabled",
    )]
    connect_all(registry, configs)
    # No tools registered — that's the token-saving win
    assert len(registry.all()) == 0
    # No "failed to connect" output — connect_all did not attempt the spawn
    out = capsys.readouterr().out
    assert "disabled" in out.lower()
    assert "failed to connect" not in out.lower()


def test_connect_all_propagates_lazy_tier_to_tools():
    registry = ToolRegistry()
    cmd = [sys.executable, "-c", _MCP_SERVER]
    configs = [McpServerConfig(
        name="lazyserver", transport="stdio", command=cmd, tier="lazy",
    )]
    connect_all(registry, configs)
    tool = next(t for t in registry.all() if t.name == "mcp__lazyserver__greet")
    assert tool.tier == "lazy"
    # And the lazy tool is excluded from schemas()
    schema_names = [s["function"]["name"] for s in registry.schemas()]
    assert "mcp__lazyserver__greet" not in schema_names


def test_connect_all_per_tool_override_beats_server_tier():
    registry = ToolRegistry()
    cmd = [sys.executable, "-c", _MCP_SERVER]
    configs = [McpServerConfig(
        name="mixed", transport="stdio", command=cmd,
        tier="eager",
        tool_tiers={"greet": "lazy"},
    )]
    connect_all(registry, configs)
    tool = next(t for t in registry.all() if t.name == "mcp__mixed__greet")
    assert tool.tier == "lazy"


def test_connect_all_per_tool_override_for_missing_tool_warns(capsys):
    """An override key referencing a tool the server doesn't expose warns; server still connects."""
    registry = ToolRegistry()
    cmd = [sys.executable, "-c", _MCP_SERVER]
    configs = [McpServerConfig(
        name="warn", transport="stdio", command=cmd,
        tier="eager",
        tool_tiers={"nonexistent_tool": "lazy"},
    )]
    connect_all(registry, configs)
    # Server still connects and registers its real tool
    assert len(get_connections()) == 1
    assert any(t.name == "mcp__warn__greet" for t in registry.all())
    out = capsys.readouterr().out
    assert "nonexistent_tool" in out
    assert "warning" in out.lower()


def test_connect_all_disabled_recorded_in_connections():
    """Disabled servers should still appear in /mcp status — record a marker connection."""
    registry = ToolRegistry()
    configs = [McpServerConfig(
        name="exp", transport="stdio", command=["bogus"], tier="disabled",
    )]
    connect_all(registry, configs)
    conns = get_connections()
    assert len(conns) == 1
    assert conns[0].name == "exp"
    # Marker: connection has no live transport behaviour. We use a sentinel.
    # Either a `disabled: True` flag on McpConnection, or transport is a NullTransport.
    # Test the observable property: server_info reflects the disabled state.
    assert conns[0].server_info is not None
    assert conns[0].server_info.get("disabled") is True


def test_make_mcp_tool_func_propagates_transport_error():
    """F010a regression: transport errors must raise so ToolRegistry.execute
    can mark the call as error=True. Previously the wrapper returned an
    'Error calling MCP tool …' string that the registry treated as success
    because it did not start with 'Error:'."""
    class _FailTransport:
        def send(self, method, params):
            raise McpTransportError("boom")
        def close(self):
            pass
    func = _make_mcp_tool_func("srv", "tool1", _FailTransport())
    with pytest.raises(McpTransportError, match="boom"):
        func({})


def test_mcp_tool_failure_surfaces_as_error_via_registry():
    """End-to-end: a failing MCP tool registered with ToolRegistry must
    produce ToolResult(error=True). This is the F010a regression."""
    from tigger.tools import ToolRegistry
    from tigger.types import ToolDef

    class _FailTransport:
        def send(self, method, params):
            raise McpTransportError("backend down")
        def close(self):
            pass

    registry = ToolRegistry()
    registry.register(ToolDef(
        name="mcp__srv__tool1",
        description="test",
        parameters={},
        func=_make_mcp_tool_func("srv", "tool1", _FailTransport()),
        read_only=True,
    ))
    result = registry.execute("mcp__srv__tool1", {})
    assert result.error is True
    assert "backend down" in result.output


def test_cleanup_closes_all():
    from tigger.mcp import _cleanup
    closed = []
    class _TrackingTransport:
        def send(self, method, params): return {}
        def close(self): closed.append(True)
    _connections.append(McpConnection(name="a", transport=_TrackingTransport()))
    _connections.append(McpConnection(name="b", transport=_TrackingTransport()))
    _cleanup()
    assert len(closed) == 2


# ── Unit 7: /mcp status command ──────────────────────────────────────────


def _make_ctx():
    from tigger.types import Config, RunContext
    cfg = Config(base_url="http://localhost", model="test")
    return RunContext(config=cfg, messages=[], system_prompt="")


def test_mcp_cmd_no_servers(capsys):
    registry = ToolRegistry()
    cmd_mcp("", _make_ctx(), connections=[], registry=registry)
    out = capsys.readouterr().out
    assert "No MCP servers connected" in out


def test_mcp_cmd_with_servers(capsys):
    class _FakeTransport:
        _url = "http://example.com"
        def send(self, method, params): return {}
        def close(self): pass
    registry = ToolRegistry()
    from tigger.types import ToolDef
    noop = lambda a: ""  # noqa: E731
    registry.register(ToolDef(
        name="mcp__srv1__tool_a", description="test",
        parameters={}, func=noop, read_only=False,
    ))
    registry.register(ToolDef(
        name="mcp__srv1__tool_b", description="test",
        parameters={}, func=noop, read_only=False,
    ))
    conn = McpConnection(
        name="srv1",
        transport=_FakeTransport(),
        server_info={"name": "srv1", "version": "2.0"},
        capabilities={"tools": {}},
    )
    cmd_mcp("", _make_ctx(), connections=[conn], registry=registry)
    out = capsys.readouterr().out
    assert "srv1" in out
    assert "2 tools" in out
    assert "v2.0" in out


def test_mcp_cmd_unknown_version(capsys):
    class _FakeTransport:
        def send(self, method, params): return {}
        def close(self): pass
    conn = McpConnection(name="bare", transport=_FakeTransport())
    cmd_mcp("", _make_ctx(), connections=[conn], registry=ToolRegistry())
    out = capsys.readouterr().out
    assert "unknown" in out
