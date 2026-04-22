import pathlib
import pytest
from newcli.tools import ToolRegistry, register_all
from newcli.types import ToolDef


def _stub(name="ping", read_only=True):
    return ToolDef(name=name, description="", parameters={},
                   func=lambda _: "pong", read_only=read_only)


# ── Registry ────────────────────────────────────────────────────────────

def test_register_and_get():
    r = ToolRegistry()
    r.register(_stub())
    assert r.get("ping") is not None
    assert r.get("nope") is None


def test_schemas_returns_list():
    r = ToolRegistry()
    r.register(_stub())
    schemas = r.schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "ping"


def test_execute_calls_func():
    r = ToolRegistry()
    r.register(_stub())
    assert r.execute("ping", {}) == "pong"


def test_execute_unknown_tool():
    r = ToolRegistry()
    result = r.execute("nope", {})
    assert "unknown tool" in result.lower()


def test_output_truncated_at_32kb():
    big = "x" * (33 * 1024)
    r = ToolRegistry()
    r.register(ToolDef("big", "", {}, func=lambda _: big))
    out = r.execute("big", {})
    assert len(out) <= 32 * 1024 + 100   # allow for truncation message overhead


def test_execute_catches_exceptions():
    def boom(_): raise RuntimeError("exploded")
    r = ToolRegistry()
    r.register(ToolDef("boom", "", {}, func=boom))
    result = r.execute("boom", {})
    assert "exploded" in result


# ── Built-in tools ───────────────────────────────────────────────────────

def test_register_all_registers_expected_tools():
    r = ToolRegistry()
    register_all(r)
    for name in ("read", "glob", "grep", "write", "edit", "bash", "web_fetch"):
        assert r.get(name) is not None, f"missing tool: {name}"


def test_read_tool(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "hello.txt"
    p.write_text("hello")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("read", {"path": str(p)})
    assert "hello" in result


def test_read_tool_missing_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    r = ToolRegistry()
    register_all(r)
    result = r.execute("read", {"path": str(tmp_path / "no_such_file.txt")})
    assert "not found" in result.lower() or "error" in result.lower()


def test_read_tool_blocks_path_traversal(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    r = ToolRegistry()
    register_all(r)
    result = r.execute("read", {"path": "/etc/passwd"})
    assert "access denied" in result.lower() or "error" in result.lower()


def test_write_refuses_existing_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "existing.txt"
    p.write_text("existing")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("write", {"path": str(p), "content": "new"})
    assert "edit" in result.lower()


def test_write_creates_new_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "new.txt"
    r = ToolRegistry()
    register_all(r)
    result = r.execute("write", {"path": str(p), "content": "created"})
    assert p.read_text() == "created"
    assert "error" not in result.lower()


def test_write_blocks_path_traversal(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    r = ToolRegistry()
    register_all(r)
    result = r.execute("write", {"path": "/tmp/evil.txt", "content": "bad"})
    assert "access denied" in result.lower() or "error" in result.lower()


def test_edit_tool_replaces_text(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "edit_me.txt"
    p.write_text("foo bar baz")
    r = ToolRegistry()
    register_all(r)
    r.execute("edit", {"path": str(p), "old_string": "bar", "new_string": "QUX"})
    assert p.read_text() == "foo QUX baz"
