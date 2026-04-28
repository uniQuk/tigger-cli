"""Compact code map for the workspace — tigger's analogue of Goose's Analyze.

Returns a dense, model-friendly summary of a directory tree (or single file):
file-level line/function/class counts, top-level signatures with arg counts,
imports, and a per-language file breakdown. Cheap to call, designed to be
invoked ONCE before any `read` so the model can target the few files it
actually needs to open.

Parsing strategy:
  - Python: stdlib `ast` (accurate signatures, return types, imports).
  - Everything else: language-specific regex catalogues. Less precise than
    tree-sitter but free of dependencies — the trade tigger explicitly
    accepts in exchange for staying minimal.

Output format mirrors Goose's Analyze conventions so models that have seen
either tool produce coherent reads:

  Directory:
    13 files, 1442L, 40F, 0C (depth=3)
    python 100%

    __init__.py [128L, 3F]
      F: load_builtin_commands(10 args)->dict:63 _switch_mode(args, ctx):103
      I: pathlib; sys; functools; tigger.commands; tigger.hooks

  Single file:
    mod.py [128L, 3F]
      C: Foo:6
      F: bar():12 baz():20
      I: pathlib; sys
"""
from __future__ import annotations

import ast
import pathlib
import re
from collections.abc import Iterable

# ── Language detection ────────────────────────────────────────────────────

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
}

_EXCLUDE_DIR_NAMES = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", "target",
    ".next", ".tigger",
}
_EXCLUDE_DIR_SUFFIXES = (".egg-info",)

# Hard caps. The model still benefits from a partial map even when the tree
# is huge — we truncate cleanly with a marker rather than refuse outright.
_DEFAULT_MAX_DEPTH = 3
_DEFAULT_MAX_FILES = 200
_DEFAULT_MAX_CHARS = 32 * 1024
# Per-signature truncation thresholds — match Goose so model output is uniform.
_SIG_MAX_CHARS = 60
_RETURN_MAX_CHARS = 30


# ── Regex catalogue (non-Python) ──────────────────────────────────────────

_FUNC_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "javascript": [
        re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"),
        re.compile(r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>"),
    ],
    "typescript": [
        re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"),
        re.compile(r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>"),
    ],
    "go": [
        re.compile(r"^func\s+(?:\([^)]*\)\s+)?([A-Za-z_]\w*)\s*\(([^)]*)\)"),
    ],
    "rust": [
        re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)\s*\(([^)]*)\)"),
    ],
    "ruby": [
        re.compile(r"^\s*def\s+(?:self\.)?([a-z_][\w?!=]*)\s*(?:\(([^)]*)\))?"),
    ],
    "java": [
        re.compile(
            r"^\s*(?:public|private|protected|static|final|abstract|synchronized|\s)*\s+"
            r"[\w<>\[\],\s]+\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*(?:throws[^{]+)?\{"
        ),
    ],
    "kotlin": [
        re.compile(r"^\s*(?:fun)\s+(?:<[^>]+>\s+)?([A-Za-z_]\w*)\s*\(([^)]*)\)"),
    ],
    "swift": [
        re.compile(r"^\s*(?:public|private|internal|fileprivate|open\s+)?func\s+([A-Za-z_]\w*)\s*\(([^)]*)\)"),
    ],
}

_CLASS_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "javascript": [re.compile(r"^(?:export\s+)?class\s+([A-Za-z_$][\w$]*)")],
    "typescript": [
        re.compile(r"^(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"),
        re.compile(r"^(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)"),
        re.compile(r"^(?:export\s+)?type\s+([A-Za-z_$][\w$]*)"),
    ],
    "go": [re.compile(r"^type\s+([A-Za-z_]\w*)")],
    "rust": [
        re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?struct\s+([A-Za-z_]\w*)"),
        re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?enum\s+([A-Za-z_]\w*)"),
        re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?trait\s+([A-Za-z_]\w*)"),
    ],
    "ruby": [
        re.compile(r"^\s*class\s+([A-Z][\w]*)"),
        re.compile(r"^\s*module\s+([A-Z][\w]*)"),
    ],
    "java": [re.compile(
        r"^\s*(?:public|abstract|final|\s)*\s*(?:class|interface|enum)\s+([A-Za-z_]\w*)"
    )],
    "kotlin": [re.compile(r"^\s*(?:open|abstract|sealed|data|\s)*\s*class\s+([A-Za-z_]\w*)")],
    "swift": [
        re.compile(r"^\s*(?:public|private|internal|fileprivate|open\s+)?class\s+([A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:public|private|internal|fileprivate|open\s+)?struct\s+([A-Za-z_]\w*)"),
        re.compile(r"^\s*(?:public|private|internal|fileprivate|open\s+)?protocol\s+([A-Za-z_]\w*)"),
    ],
}

_IMPORT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "javascript": [
        re.compile(r"""^import\s+.*?from\s+['"]([^'"]+)['"]"""),
        re.compile(r"""^(?:const|let|var)\s+\w+\s*=\s*require\(['"]([^'"]+)['"]\)"""),
    ],
    "typescript": [
        re.compile(r"""^import\s+.*?from\s+['"]([^'"]+)['"]"""),
        re.compile(r"""^import\s+['"]([^'"]+)['"]"""),
    ],
    "go": [re.compile(r'^\s*"([^"]+)"\s*$')],  # inside import block; rough.
    "rust": [re.compile(r"^use\s+([\w:{}*,\s]+);")],
    "ruby": [re.compile(r"^require(?:_relative)?\s+['\"]([^'\"]+)['\"]")],
    "java": [re.compile(r"^import\s+(?:static\s+)?([\w.]+)(?:\.\*)?;")],
    "kotlin": [re.compile(r"^import\s+([\w.]+)(?:\.\*)?")],
    "swift": [re.compile(r"^import\s+(\w+)")],
}


# ── Per-file analysis ─────────────────────────────────────────────────────

class FileSummary:
    """Mutable bundle of facts about one source file."""

    __slots__ = ("path", "lang", "lines", "funcs", "classes", "imports")

    def __init__(self, path: pathlib.Path, lang: str) -> None:
        self.path = path
        self.lang = lang
        self.lines = 0
        # Each func entry: (name, signature_str, return_type_or_None, lineno)
        self.funcs: list[tuple[str, str, str | None, int]] = []
        # Each class entry: (kind, name, lineno) — kind = "class"|"interface"|...
        self.classes: list[tuple[str, str, int]] = []
        self.imports: list[str] = []


def _analyze_python(text: str, summary: FileSummary) -> None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return  # leave summary empty rather than crash on broken sources.
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            summary.funcs.append(_python_func(node))
        elif isinstance(node, ast.ClassDef):
            summary.classes.append(("class", node.name, node.lineno))
            # Surface methods as nested funcs so the model sees the surface area.
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name, sig, ret, lineno = _python_func(sub)
                    summary.funcs.append((f"{node.name}.{name}", sig, ret, lineno))
        elif isinstance(node, ast.Import):
            summary.imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            summary.imports.append(mod or ".")


def _python_func(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, str, str | None, int]:
    args = node.args
    parts: list[str] = []
    parts.extend(a.arg for a in args.posonlyargs)
    parts.extend(a.arg for a in args.args)
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    parts.extend(a.arg for a in args.kwonlyargs)
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    sig = ", ".join(parts)
    ret = ast.unparse(node.returns) if node.returns is not None else None
    return (node.name, sig, ret, node.lineno)


def _analyze_regex(text: str, summary: FileSummary) -> None:
    fpats = _FUNC_PATTERNS.get(summary.lang, [])
    cpats = _CLASS_PATTERNS.get(summary.lang, [])
    ipats = _IMPORT_PATTERNS.get(summary.lang, [])
    for i, line in enumerate(text.splitlines(), 1):
        for rx in fpats:
            m = rx.match(line)
            if m:
                name = m.group(1)
                sig = m.group(2).strip() if m.lastindex and m.lastindex >= 2 else ""
                summary.funcs.append((name, sig, None, i))
                break
        for rx in cpats:
            m = rx.match(line)
            if m:
                summary.classes.append(("class", m.group(1), i))
                break
        for rx in ipats:
            m = rx.match(line)
            if m:
                summary.imports.append(m.group(1).strip())
                break


def analyze_file(path: pathlib.Path, root: pathlib.Path) -> FileSummary | None:
    lang = _EXT_TO_LANG.get(path.suffix)
    if lang is None:
        return None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    summary = FileSummary(path.relative_to(root), lang)
    summary.lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    if lang == "python":
        _analyze_python(text, summary)
    else:
        _analyze_regex(text, summary)
    return summary


# ── Format helpers ────────────────────────────────────────────────────────

def _fmt_sig(name: str, sig: str, ret: str | None) -> str:
    """Render `name(args)->Ret`, applying Goose's truncation rules."""
    arg_count = 0 if not sig else len([a for a in sig.split(",") if a.strip()])
    if len(sig) > _SIG_MAX_CHARS:
        sig_str = f"({arg_count} args)"
    else:
        sig_str = f"({sig})"
    if ret:
        ret_clean = ret.strip()
        if len(ret_clean) > _RETURN_MAX_CHARS:
            ret_clean = ret_clean[: _RETURN_MAX_CHARS - 3] + "..."
        return f"{name}{sig_str}->{ret_clean}"
    return f"{name}{sig_str}"


def _fmt_file_block(summary: FileSummary, indent: str = "") -> list[str]:
    counts = [f"{summary.lines}L"]
    if summary.funcs:
        counts.append(f"{len(summary.funcs)}F")
    if summary.classes:
        counts.append(f"{len(summary.classes)}C")
    header = f"{indent}{summary.path} [{', '.join(counts)}]"
    out = [header]
    if summary.classes:
        cls_str = " ".join(f"{n}:{ln}" for _, n, ln in summary.classes)
        out.append(f"{indent}  C: {cls_str}")
    if summary.funcs:
        sigs = " ".join(
            f"{_fmt_sig(n, s, r)}:{ln}" for n, s, r, ln in summary.funcs
        )
        out.append(f"{indent}  F: {sigs}")
    if summary.imports:
        # Dedupe preserving order, cap at 12 entries to keep imports terse.
        seen: dict[str, None] = {}
        for imp in summary.imports:
            seen[imp] = None
        items = list(seen)
        suffix = ""
        if len(items) > 12:
            suffix = f"; +{len(items) - 12} more"
            items = items[:12]
        out.append(f"{indent}  I: {'; '.join(items)}{suffix}")
    return out


# ── Walking ───────────────────────────────────────────────────────────────

def _excluded(path: pathlib.Path) -> bool:
    for part in path.parts:
        if part in _EXCLUDE_DIR_NAMES:
            return True
        if any(part.endswith(suffix) for suffix in _EXCLUDE_DIR_SUFFIXES):
            return True
    return False


def _iter_source_files(
    root: pathlib.Path, max_depth: int
) -> Iterable[pathlib.Path]:
    root_depth = len(root.parts)
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in _EXT_TO_LANG:
            continue
        rel = p.relative_to(root)
        if _excluded(rel):
            continue
        if max_depth > 0:
            depth = len(p.parts) - root_depth
            if depth > max_depth:
                continue
        yield p


# ── Public entry points ───────────────────────────────────────────────────

def build_repomap(
    root: pathlib.Path,
    *,
    pattern: str | None = None,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    max_files: int = _DEFAULT_MAX_FILES,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """Return a markdown-ish symbol map under *max_chars* characters.

    Kept under the original name for back-compat with existing tests.
    """
    root = root.resolve()
    if root.is_file():
        s = analyze_file(root, root.parent)
        if s is None:
            return f"(unsupported file type: {root.suffix})"
        return "\n".join(_fmt_file_block(s))

    files = sorted(_iter_source_files(root, max_depth))
    if pattern:
        rx = re.compile(pattern)
        files = [f for f in files if rx.search(str(f.relative_to(root)))]
    if not files:
        return "(no source files matched)"

    truncated = len(files) > max_files
    files = files[:max_files]

    summaries: list[FileSummary] = []
    for f in files:
        s = analyze_file(f, root)
        if s is not None:
            summaries.append(s)

    total_lines = sum(s.lines for s in summaries)
    total_funcs = sum(len(s.funcs) for s in summaries)
    total_classes = sum(len(s.classes) for s in summaries)
    lang_counts: dict[str, int] = {}
    for s in summaries:
        lang_counts[s.lang] = lang_counts.get(s.lang, 0) + 1

    header_parts = [
        f"{len(summaries)} files",
        f"{total_lines}L",
    ]
    if total_funcs:
        header_parts.append(f"{total_funcs}F")
    if total_classes:
        header_parts.append(f"{total_classes}C")
    depth_str = "unbounded" if max_depth == 0 else str(max_depth)
    lines: list[str] = [
        f"# Analyze {root.name} (depth={depth_str})",
        ", ".join(header_parts),
    ]
    if lang_counts:
        total = sum(lang_counts.values())
        breakdown = " | ".join(
            f"{lang} {round(100 * n / total)}%"
            for lang, n in sorted(lang_counts.items(), key=lambda kv: -kv[1])
        )
        lines.append(breakdown)
    if truncated:
        lines.append(f"(truncated to first {max_files} files; narrow with `pattern`)")
    lines.append("")

    for s in summaries:
        lines.extend(_fmt_file_block(s))
        # Bail out cleanly once we cross the budget.
        if sum(len(line) + 1 for line in lines) > max_chars:
            lines.append(
                f"\n[output truncated at {max_chars} chars — narrow with "
                "`pattern` or `path`]"
            )
            break

    return "\n".join(lines)


# ── Tool wiring ────────────────────────────────────────────────────────────

def repomap_tool(args: dict) -> str:
    pattern = args.get("pattern")
    base = args.get("path", ".")
    max_depth_raw = args.get("max_depth", _DEFAULT_MAX_DEPTH)
    try:
        max_depth = int(max_depth_raw)
    except (TypeError, ValueError):
        return f"Error: 'max_depth' must be an integer, got {max_depth_raw!r}"
    if max_depth < 0:
        return f"Error: 'max_depth' must be >= 0 (0 = unbounded), got {max_depth}"

    base_path = pathlib.Path(base)
    cwd = pathlib.Path.cwd().resolve()
    try:
        resolved = base_path.resolve()
        resolved.relative_to(cwd)
    except ValueError:
        return f"Error: access denied — path is outside the workspace: {base}"
    if not resolved.exists():
        return f"Error: path does not exist: {base}"
    return build_repomap(resolved, pattern=pattern, max_depth=max_depth)
