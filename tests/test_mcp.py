import json, os, pathlib, sys, tempfile
from unittest.mock import patch, MagicMock
import httpx
import pytest
from tigger.mcp import (
    load_mcp_config, McpServerConfig, McpTransportError, McpConnection,
    StdioTransport, StreamableHttpTransport, _parse_sse_events,
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
    import time; time.sleep(0.2)  # let process exit
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
    t = StdioTransport([sys.executable, "-c", "pass"])
    import time; time.sleep(0.2)
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
