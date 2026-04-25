import json, os, pathlib, sys, tempfile
from tigger.mcp import (
    load_mcp_config, McpServerConfig, McpTransportError, McpConnection,
    StdioTransport,
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
