import pathlib

from tigger.repomap import build_repomap, repomap_tool


def _write(tmp_path: pathlib.Path, rel: str, body: str) -> pathlib.Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


# ── Python AST extraction ─────────────────────────────────────────────────

def test_python_signatures_with_args_and_return(tmp_path):
    _write(tmp_path, "pkg/mod.py",
           "import sys\n"
           "from os import path\n"
           "\n"
           "class Foo:\n"
           "    def method(self, x: int) -> bool:\n"
           "        return True\n"
           "\n"
           "def bar(a, b, *args, **kw) -> str:\n"
           "    return ''\n"
           "\n"
           "async def baz():\n"
           "    pass\n")
    out = build_repomap(tmp_path)
    # Header counts.
    assert "pkg/mod.py" in out
    assert "1F" not in out  # Foo.method + bar + baz = 3 funcs
    assert "3F" in out
    assert "1C" in out
    # Class.
    assert "C: Foo:4" in out
    # Function with args + return type.
    assert "bar(a, b, *args, **kw)->str:8" in out
    # Method namespacing.
    assert "Foo.method(self, x)->bool:5" in out
    # Imports flattened.
    assert "I: sys; os" in out


def test_python_signature_truncated_when_huge(tmp_path):
    huge_args = ", ".join(f"arg_{i}" for i in range(40))
    _write(tmp_path, "f.py", f"def big({huge_args}):\n    pass\n")
    out = build_repomap(tmp_path)
    # Goose convention: collapse to (N args) when signature exceeds 60 chars.
    assert "(40 args)" in out


def test_python_broken_syntax_does_not_crash(tmp_path):
    _write(tmp_path, "bad.py", "def oops(:\n")
    _write(tmp_path, "good.py", "def fine(): pass\n")
    out = build_repomap(tmp_path)
    # Broken file lists with line count but no symbols; good file still appears.
    assert "good.py" in out
    assert "fine" in out


# ── Multi-language regex fallback ─────────────────────────────────────────

def test_typescript_symbols_extracted(tmp_path):
    _write(tmp_path, "src/a.ts",
           "export interface User {}\n"
           "export type Id = string\n"
           "export class Svc {}\n"
           "export function go(x: number, y: number): boolean { return true }\n")
    out = build_repomap(tmp_path)
    assert "src/a.ts" in out
    assert "User:1" in out
    assert "Id:2" in out
    assert "Svc:3" in out
    assert "go(x: number, y: number)" in out


def test_rust_symbols_extracted(tmp_path):
    _write(tmp_path, "src/lib.rs",
           "pub struct Cfg {}\n"
           "pub trait Reader {}\n"
           "pub fn parse(input: &str) -> Result<Cfg, Error> { Ok(Cfg{}) }\n")
    out = build_repomap(tmp_path)
    assert "Cfg:1" in out
    assert "Reader:2" in out
    assert "parse(input: &str)" in out


# ── Walking & filtering ───────────────────────────────────────────────────

def test_excluded_dirs_skipped(tmp_path):
    _write(tmp_path, "node_modules/lib/x.js", "function noisy() {}\n")
    _write(tmp_path, ".venv/lib/y.py", "def hidden(): pass\n")
    _write(tmp_path, "src/real.py", "def real(): pass\n")
    out = build_repomap(tmp_path)
    assert "real" in out
    assert "noisy" not in out
    assert "hidden" not in out


def test_pattern_filters_paths(tmp_path):
    _write(tmp_path, "src/a.py", "def alpha(): pass\n")
    _write(tmp_path, "tests/b.py", "def beta(): pass\n")
    out = build_repomap(tmp_path, pattern=r"^src/")
    assert "alpha" in out
    assert "beta" not in out


def test_max_depth_caps_recursion(tmp_path):
    _write(tmp_path, "a.py", "def one(): pass\n")                         # depth 1
    _write(tmp_path, "x/b.py", "def two(): pass\n")                       # depth 2
    _write(tmp_path, "x/y/c.py", "def three(): pass\n")                   # depth 3
    _write(tmp_path, "x/y/z/d.py", "def four(): pass\n")                  # depth 4
    out = build_repomap(tmp_path, max_depth=2)
    assert "one" in out
    assert "two" in out
    assert "three" not in out
    assert "four" not in out


def test_max_depth_zero_means_unbounded(tmp_path):
    _write(tmp_path, "x/y/z/deep.py", "def deep(): pass\n")
    out = build_repomap(tmp_path, max_depth=0)
    assert "deep" in out
    assert "(depth=unbounded)" in out


# ── Aggregate header ──────────────────────────────────────────────────────

def test_header_counts_and_language_breakdown(tmp_path):
    _write(tmp_path, "a.py", "def f(): pass\nclass C: pass\n")
    _write(tmp_path, "b.py", "def g(): pass\n")
    _write(tmp_path, "c.ts", "function h() {}\n")
    out = build_repomap(tmp_path)
    # 3 files, 5 lines, 3 funcs, 1 class
    assert "3 files" in out
    assert "3F" in out
    assert "1C" in out
    # Language breakdown by file count, sorted by frequency.
    assert "python 67%" in out
    assert "typescript 33%" in out


def test_single_file_path_returns_file_summary(tmp_path):
    f = _write(tmp_path, "solo.py", "def lone(): pass\n")
    out = build_repomap(f)
    assert "solo.py" in out
    assert "lone" in out
    # No directory header in single-file mode.
    assert "files," not in out


# ── Tool wrapper ──────────────────────────────────────────────────────────

def test_repomap_tool_path_traversal_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = repomap_tool({"path": "/etc"})
    assert "access denied" in out.lower()


def test_repomap_tool_missing_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = repomap_tool({"path": "no-such-dir"})
    assert "does not exist" in out


def test_repomap_tool_bad_max_depth(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = repomap_tool({"max_depth": "lots"})
    assert "must be an integer" in out


def test_repomap_tool_negative_max_depth(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = repomap_tool({"max_depth": -1})
    assert "must be >= 0" in out


def test_repomap_tool_returns_no_matches_when_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = repomap_tool({})
    assert "no source files" in out.lower()
