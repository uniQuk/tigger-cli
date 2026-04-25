import pathlib
import pytest
from tigger.tools import ToolRegistry, register_all
from tigger.types import ToolDef


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


# ── Remember tool ───────────────────────────────────────────────────────

def test_remember_tool_appends_to_memory(tmp_path):
    memory_path = tmp_path / "memory.md"
    registry = ToolRegistry()
    register_all(registry, memory_path=memory_path)

    tool = registry.get("remember")
    assert tool is not None

    result = tool.func({"note": "user prefers tabs"})
    assert "Remembered" in result
    assert memory_path.exists()
    assert "user prefers tabs" in memory_path.read_text()


def test_remember_tool_empty_note():
    registry = ToolRegistry()
    register_all(registry, memory_path=pathlib.Path("/tmp/test_mem.md"))

    tool = registry.get("remember")
    result = tool.func({"note": ""})
    assert "Error" in result


def test_remember_tool_not_registered_without_path():
    registry = ToolRegistry()
    register_all(registry)

    assert registry.get("remember") is None


# ── SSRF defense ──────────────────────────────────────────────────────

from tigger.tools import _is_private_or_local


def test_ssrf_localhost():
    assert _is_private_or_local("localhost") is True


def test_ssrf_127():
    assert _is_private_or_local("127.0.0.1") is True


def test_ssrf_0000():
    assert _is_private_or_local("0.0.0.0") is True


def test_ssrf_private_192():
    assert _is_private_or_local("192.168.1.1") is True


def test_ssrf_private_10():
    assert _is_private_or_local("10.0.0.1") is True


def test_ssrf_ipv6_loopback():
    assert _is_private_or_local("::1") is True


def test_ssrf_public_allowed():
    assert _is_private_or_local("example.com") is False


def test_ssrf_empty_blocked():
    assert _is_private_or_local("") is True


# ── grep/glob execution ──────────────────────────────────────────────

def test_grep_finds_pattern(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hello.py").write_text("def greet(): pass")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("grep", {"pattern": "greet"})
    assert "greet" in result


def test_grep_no_match(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hello.py").write_text("def greet(): pass")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("grep", {"pattern": "nonexistent_xyz"})
    assert result == "(no matches)"


def test_grep_invalid_regex(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    r = ToolRegistry()
    register_all(r)
    result = r.execute("grep", {"pattern": "[invalid"})
    assert "error" in result.lower()


def test_glob_finds_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.txt").write_text("")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("glob", {"pattern": "*.py"})
    assert "a.py" in result
    assert "b.txt" not in result


def test_glob_no_match(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    r = ToolRegistry()
    register_all(r)
    result = r.execute("glob", {"pattern": "*.xyz"})
    assert result == "(no matches)"


def test_glob_respects_workspace(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    r = ToolRegistry()
    register_all(r)
    result = r.execute("glob", {"pattern": "*.py", "path": "/etc"})
    assert "access denied" in result.lower() or "error" in result.lower()


# ── grep/glob default excludes ────────────────────────────────────────

def test_grep_skips_node_modules(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("export const needle = 1")
    (tmp_path / "src.js").write_text("const needle = 2")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("grep", {"pattern": "needle"})
    assert "src.js" in result
    # Check that no result line comes from inside node_modules/
    for line in result.splitlines():
        assert "/node_modules/" not in line


def test_glob_skips_venv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "mod.py").write_text("")
    (tmp_path / "app.py").write_text("")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("glob", {"pattern": "**/*.py"})
    assert "app.py" in result
    for line in result.splitlines():
        assert "/.venv/" not in line


def test_grep_explicit_path_into_excluded(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "mod.py").write_text("needle_here")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("grep", {"pattern": "needle_here", "path": ".venv"})
    assert "needle_here" in result


def test_glob_explicit_path_into_excluded(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "pkg.js").write_text("")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("glob", {"pattern": "*.js", "path": "node_modules"})
    assert "pkg.js" in result


def test_glob_does_not_exclude_similarly_named_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "node_modules.txt").write_text("")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("glob", {"pattern": "*.txt"})
    assert "node_modules.txt" in result
