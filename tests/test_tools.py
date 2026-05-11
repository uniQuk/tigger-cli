import pathlib
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
    assert r.execute("ping", {}).output == "pong"


def test_execute_unknown_tool():
    r = ToolRegistry()
    result = r.execute("nope", {}).output
    assert "unknown tool" in result.lower()


def test_output_truncated_at_32kb():
    big = "x" * (33 * 1024)
    r = ToolRegistry()
    r.register(ToolDef("big", "", {}, func=lambda _: big))
    out = r.execute("big", {}).output
    assert len(out) <= 32 * 1024 + 100   # allow for truncation message overhead


def test_execute_catches_exceptions():
    def boom(_): raise RuntimeError("exploded")
    r = ToolRegistry()
    r.register(ToolDef("boom", "", {}, func=boom))
    result = r.execute("boom", {}).output
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
    result = r.execute("read", {"path": str(p)}).output
    assert "hello" in result


def test_read_tool_missing_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    r = ToolRegistry()
    register_all(r)
    result = r.execute("read", {"path": str(tmp_path / "no_such_file.txt")}).output
    assert "not found" in result.lower() or "error" in result.lower()


def test_read_tool_blocks_path_traversal(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    r = ToolRegistry()
    register_all(r)
    result = r.execute("read", {"path": "/etc/passwd"}).output
    assert "access denied" in result.lower() or "error" in result.lower()


def _read_setup(monkeypatch, tmp_path, n_lines=10):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "lines.txt"
    p.write_text("".join(f"line{i}\n" for i in range(1, n_lines + 1)))
    r = ToolRegistry()
    register_all(r)
    return r, p


def test_read_offset_limit_returns_slice(monkeypatch, tmp_path):
    r, p = _read_setup(monkeypatch, tmp_path)
    out = r.execute("read", {"path": str(p), "offset": 3, "limit": 2}).output
    # Slice marker + only the requested lines.
    assert out.startswith("[lines 3-4 of 10")
    assert "line3" in out and "line4" in out
    assert "line2" not in out and "line5" not in out


def test_read_offset_only_reads_to_end(monkeypatch, tmp_path):
    r, p = _read_setup(monkeypatch, tmp_path)
    out = r.execute("read", {"path": str(p), "offset": 8}).output
    assert out.startswith("[lines 8-10 of 10")
    assert "line8" in out and "line10" in out
    assert "line7" not in out


def test_read_limit_only_starts_at_one(monkeypatch, tmp_path):
    r, p = _read_setup(monkeypatch, tmp_path)
    out = r.execute("read", {"path": str(p), "limit": 2}).output
    assert out.startswith("[lines 1-2 of 10")
    assert "line1" in out and "line2" in out
    assert "line3" not in out


def test_read_offset_past_end(monkeypatch, tmp_path):
    r, p = _read_setup(monkeypatch, tmp_path, n_lines=5)
    out = r.execute("read", {"path": str(p), "offset": 99}).output
    assert "past end" in out and "5 lines" in out


def test_read_limit_clamps_to_eof(monkeypatch, tmp_path):
    r, p = _read_setup(monkeypatch, tmp_path, n_lines=5)
    out = r.execute("read", {"path": str(p), "offset": 4, "limit": 100}).output
    assert out.startswith("[lines 4-5 of 5")


def test_read_invalid_offset_returns_error(monkeypatch, tmp_path):
    r, p = _read_setup(monkeypatch, tmp_path)
    out = r.execute("read", {"path": str(p), "offset": 0}).output
    assert "must be >= 1" in out


def test_read_no_offset_no_marker_back_compat(monkeypatch, tmp_path):
    r, p = _read_setup(monkeypatch, tmp_path)
    out = r.execute("read", {"path": str(p)}).output
    # Plain read on a small file still returns raw content with no marker
    # prefix. Auto-pagination only kicks in for files above the default
    # page size.
    assert not out.startswith("[lines ")
    assert out.startswith("line1\n")


def test_read_auto_pages_large_file(monkeypatch, tmp_path):
    r, p = _read_setup(monkeypatch, tmp_path, n_lines=2500)
    out = r.execute("read", {"path": str(p)}).output
    # Plain read on a >2000-line file auto-pages: returns a header with the
    # total line count and a continuation hint pointing at the next offset.
    assert out.startswith("[lines 1-2000 of 2500 ")
    assert "auto-paged" in out
    assert "offset=2001" in out
    assert "500 lines remaining" in out
    # First and last line of the page are present; line 2001 is not.
    assert "line1\n" in out
    assert "line2000\n" in out
    assert "line2001\n" not in out


def test_read_explicit_offset_signals_partial(monkeypatch, tmp_path):
    r, p = _read_setup(monkeypatch, tmp_path, n_lines=20)
    out = r.execute("read", {"path": str(p), "offset": 1, "limit": 5}).output
    # Explicit slice that doesn't reach EOF gets a partial marker so the
    # model knows to continue. Auto-paged wording is reserved for the
    # implicit-default path.
    assert out.startswith("[lines 1-5 of 20 ")
    assert "partial" in out
    assert "offset=6" in out
    assert "auto-paged" not in out


def test_per_tool_max_output_bytes_override(monkeypatch, tmp_path):
    # Tools can opt into a larger byte cap than the global default. `read`
    # uses this so the user's "summarize a 200KB file" workflow doesn't
    # require 6-8 round-trips at 32KB-per-page.
    from tigger.types import ToolDef, ToolResult

    big_output = "x" * (40 * 1024)
    big_tool = ToolDef(
        name="big",
        description="",
        parameters={"type": "object", "properties": {}},
        func=lambda args: big_output,
        max_output_bytes=64 * 1024,
    )
    small_tool = ToolDef(
        name="small",
        description="",
        parameters={"type": "object", "properties": {}},
        func=lambda args: big_output,
        # No override → falls back to global 32KB.
    )
    r = ToolRegistry()
    r.register(big_tool)
    r.register(small_tool)
    big_out = r.execute("big", {}).output
    small_out = r.execute("small", {}).output
    # The 64KB-cap tool returns the full 40KB output untouched.
    assert "truncated" not in big_out
    assert len(big_out) == 40 * 1024
    # The default-cap tool gets chopped at 32KB with the matching marker.
    assert "[output truncated at 32KB]" in small_out


def test_read_byte_budget_trims_long_lines(monkeypatch, tmp_path):
    # 100 lines × 1KB each = 100KB; soft budget is 28KB so the page should
    # trim to roughly 28 lines and emit a partial marker with the next offset.
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "wide.txt"
    p.write_text("".join("x" * 1023 + "\n" for _ in range(100)))
    r = ToolRegistry()
    register_all(r)
    out = r.execute("read", {"path": str(p), "offset": 1, "limit": 100}).output
    assert out.startswith("[lines 1-")
    # The page must stay under the 32KB tool-output cap so the trailing
    # marker stays attached.
    assert "[output truncated at 32KB]" not in out
    assert "partial" in out or "auto-paged" in out


def test_write_refuses_existing_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "existing.txt"
    p.write_text("existing")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("write", {"path": str(p), "content": "new"}).output
    assert "edit" in result.lower()


def test_write_creates_new_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "new.txt"
    r = ToolRegistry()
    register_all(r)
    result = r.execute("write", {"path": str(p), "content": "created"}).output
    assert p.read_text() == "created"
    assert "error" not in result.lower()


def test_write_blocks_path_traversal(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    r = ToolRegistry()
    register_all(r)
    result = r.execute("write", {"path": "/tmp/evil.txt", "content": "bad"}).output
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
    result = r.execute("grep", {"pattern": "greet"}).output
    assert "greet" in result


def test_grep_no_match(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hello.py").write_text("def greet(): pass")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("grep", {"pattern": "nonexistent_xyz"}).output
    assert result == "(no matches)"


def test_grep_invalid_regex(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    r = ToolRegistry()
    register_all(r)
    result = r.execute("grep", {"pattern": "[invalid"}).output
    assert "error" in result.lower()


def test_glob_finds_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.txt").write_text("")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("glob", {"pattern": "*.py"}).output
    assert "a.py" in result
    assert "b.txt" not in result


def test_glob_no_match(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    r = ToolRegistry()
    register_all(r)
    result = r.execute("glob", {"pattern": "*.xyz"}).output
    assert result == "(no matches)"


def test_glob_respects_workspace(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    r = ToolRegistry()
    register_all(r)
    result = r.execute("glob", {"pattern": "*.py", "path": "/etc"}).output
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
    result = r.execute("grep", {"pattern": "needle"}).output
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
    result = r.execute("glob", {"pattern": "**/*.py"}).output
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
    result = r.execute("grep", {"pattern": "needle_here", "path": ".venv"}).output
    assert "needle_here" in result


def test_glob_explicit_path_into_excluded(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "pkg.js").write_text("")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("glob", {"pattern": "*.js", "path": "node_modules"}).output
    assert "pkg.js" in result


def test_glob_does_not_exclude_similarly_named_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "node_modules.txt").write_text("")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("glob", {"pattern": "*.txt"}).output
    assert "node_modules.txt" in result


def test_glob_does_not_exclude_file_named_like_excluded_dir(monkeypatch, tmp_path):
    """A file literally named '.git' or '__pycache__' should not be excluded."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "__pycache__").write_text("I am a file, not a dir")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("glob", {"pattern": "__pycache__"}).output
    assert "__pycache__" in result


def test_grep_does_not_exclude_file_named_like_excluded_dir(monkeypatch, tmp_path):
    """A file literally named '.git' should still be searchable."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").write_text("not a real git dir, just a file")
    r = ToolRegistry()
    register_all(r)
    result = r.execute("grep", {"pattern": "not a real git"}).output
    assert "not a real git" in result


# ── Tool tier (eager / lazy / disabled) ───────────────────────────────


def _tiered_stub(name="ping", tier="eager"):
    return ToolDef(
        name=name, description="", parameters={},
        func=lambda _: "pong", read_only=True, tier=tier,
    )


def test_tooldef_default_tier_is_eager():
    t = ToolDef(name="x", description="", parameters={}, func=lambda _: "")
    assert t.tier == "eager"


def test_schemas_excludes_lazy_tools():
    r = ToolRegistry()
    r.register(_tiered_stub("eager_one", tier="eager"))
    r.register(_tiered_stub("lazy_one", tier="lazy"))
    names = [s["function"]["name"] for s in r.schemas()]
    assert "eager_one" in names
    assert "lazy_one" not in names


def test_schemas_excludes_disabled_tools():
    r = ToolRegistry()
    r.register(_tiered_stub("eager_one", tier="eager"))
    r.register(_tiered_stub("disabled_one", tier="disabled"))
    names = [s["function"]["name"] for s in r.schemas()]
    assert "eager_one" in names
    assert "disabled_one" not in names


def test_lazy_tools_returns_only_lazy():
    r = ToolRegistry()
    r.register(_tiered_stub("eager_one", tier="eager"))
    r.register(_tiered_stub("lazy_one", tier="lazy"))
    r.register(_tiered_stub("disabled_one", tier="disabled"))
    lazy = r.lazy_tools()
    names = [t.name for t in lazy]
    assert names == ["lazy_one"]


def test_lazy_tools_empty_when_none_registered():
    r = ToolRegistry()
    r.register(_tiered_stub("eager_one", tier="eager"))
    assert r.lazy_tools() == []


def test_execute_rejects_lazy_tool_with_promote_directive():
    r = ToolRegistry()
    r.register(_tiered_stub("mcp__playwright__navigate", tier="lazy"))
    result = r.execute("mcp__playwright__navigate", {})
    assert result.error is True
    assert "mcp_promote" in result.output
    assert "playwright" in result.output


def test_execute_rejects_disabled_tool_with_disabled_message():
    r = ToolRegistry()
    r.register(_tiered_stub("mcp__experimental__bork", tier="disabled"))
    result = r.execute("mcp__experimental__bork", {})
    assert result.error is True
    assert "disabled" in result.output.lower()


def test_native_tools_default_to_eager():
    r = ToolRegistry()
    register_all(r)
    for name in ("read", "glob", "grep", "write", "edit", "bash", "web_fetch"):
        t = r.get(name)
        assert t is not None
        assert t.tier == "eager", f"{name} should default to eager"


# ── _bash timeout escalation (F006) ─────────────────────────────────────

# ── ToolRegistry.execute defensive coercion ─────────────────────────────

def test_execute_coerces_none_return_to_empty_string():
    """A buggy tool returning None must not crash output.startswith()."""
    r = ToolRegistry()
    r.register(ToolDef(name="bad", description="", parameters={},
                       func=lambda _: None, read_only=True))
    result = r.execute("bad", {})
    assert result.error is False
    assert result.output == ""


def test_execute_coerces_non_string_return():
    r = ToolRegistry()
    r.register(ToolDef(name="num", description="", parameters={},
                       func=lambda _: 42, read_only=True))
    result = r.execute("num", {})
    assert result.output == "42"


# ── _DEFAULT_EXCLUDES suffix matching (F017) ────────────────────────────

def test_egg_info_dir_is_excluded():
    """F017 regression: pkgname.egg-info dirs were not being excluded
    because the previous implementation used set-intersection on exact
    directory names."""
    from tigger.tools import _is_excluded_dir
    assert _is_excluded_dir(pathlib.Path("tigger.egg-info")) is True
    assert _is_excluded_dir(pathlib.Path("src/tigger.egg-info/PKG-INFO")) is True


def test_bare_egg_info_dir_still_excluded():
    from tigger.tools import _is_excluded_dir
    assert _is_excluded_dir(pathlib.Path(".egg-info")) is True


def test_egg_info_substring_in_filename_not_excluded():
    """A regular file named foo.egg-info.txt is not a build artifact."""
    from tigger.tools import _is_excluded_dir
    assert _is_excluded_dir(pathlib.Path("foo.egg-info.txt")) is False


def test_other_excludes_still_work():
    from tigger.tools import _is_excluded_dir
    assert _is_excluded_dir(pathlib.Path(".git/HEAD")) is True
    assert _is_excluded_dir(pathlib.Path("node_modules/foo")) is True
    assert _is_excluded_dir(pathlib.Path("src/main.py")) is False


def test_bash_happy_path():
    from tigger.tools import _bash
    out = _bash({"command": "echo hi"})
    assert out.strip() == "hi"


def test_bash_empty_command_returns_no_output_marker():
    from tigger.tools import _bash
    out = _bash({"command": "true"})
    assert out == "(no output)"


def test_bash_nonzero_exit_appends_exit_marker():
    from tigger.tools import _bash
    # `false` exits 1 with no output; marker must surface the code.
    out = _bash({"command": "false"})
    assert out == "(no output)\n[exit 1]"
    # Custom exit code with stdout: marker appended on a new line.
    out = _bash({"command": "echo nope; exit 42"})
    assert out.rstrip("\n").endswith("[exit 42]")
    assert "nope" in out


def test_bash_exit_zero_no_marker():
    from tigger.tools import _bash
    # Successful command with output: no exit marker.
    out = _bash({"command": "echo ok"})
    assert "[exit" not in out
    assert out.strip() == "ok"


def test_bash_sigterm_ignoring_child_is_killed(monkeypatch):
    """F006 regression: a child that ignores SIGTERM must be SIGKILL'd within
    the grace window. Without process-group escalation this would hang."""
    import time
    from tigger.tools import _bash

    # Shrink the timeout to keep the test fast. The escalation logic is
    # what we're verifying, not the 30s default.
    monkeypatch.setattr("tigger.tools._BASH_TIMEOUT", 1)
    monkeypatch.setattr("tigger.tools._BASH_KILL_GRACE", 3)

    start = time.monotonic()
    out = _bash({"command": "trap '' TERM; sleep 60"})
    elapsed = time.monotonic() - start

    # Generous CI margin — the timeout+grace are 1+3=4s; allow 4x for
    # scheduling delay on overloaded runners. The point of the test is
    # that escalation HAPPENED, not the exact timing.
    assert elapsed < 16, f"bash hung for {elapsed:.1f}s; SIGKILL escalation failed"
    assert out.startswith("Error: command timed out")
    assert "killed" in out
