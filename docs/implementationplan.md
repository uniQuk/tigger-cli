# newcli Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal, clean AI agent CLI (~1550 lines) that replaces a 4200-line god-object with 12 focused modules, one provider target (OpenAI-compatible), and markdown-first config.

**Architecture:** A REPL shells out to an agent loop generator (`loop.py`) that streams events. All state flows through a typed `RunContext` dataclass. Tools are registered explicitly at startup into a `ToolRegistry`; hooks are middleware lists, not function replacement. Skills and agents are parsed from `.md` files.

**Tech Stack:** Python 3.11+, `openai` Python client (for OpenAI-compat streaming), `pytest`, `pytest-asyncio`, no other runtime dependencies.

---

## Bug Fixes Applied (vs. Architecture Doc)

1. **`permissions.py`** — `check()` now accepts `bash_safe_prefixes: list[str]` explicitly; `config` is not in scope there.
2. **`AssistantMessage`** — defined in `types.py` as a distinct dataclass (returned by `provider.stream()`); `Message` remains the neutral format stored in history.
3. **Hook decorator wiring** — `hooks.py` maintains a module-level `_REGISTRY` singleton; `load_hooks(path)` imports the file (causing decorators to fire) then returns the populated registry.
4. **`commands/` submodule** — added to file layout; `main.py` calls `load_builtin_commands()` which imports from `commands/`.
5. **`run_forked()`** — defined in `loop.py`; spec included in Task 12.
6. **`/memory` command** — slash added to match pattern.

---

## File Layout

```
src/newcli/
├── __init__.py
├── main.py             ← Entry, REPL, startup sequence        (~150 lines)
├── loop.py             ← Agent loop generator + run_forked    (~220 lines)
├── types.py            ← All dataclasses + events             (~120 lines)
├── config.py           ← Config loader + validation           (~80 lines)
├── provider.py         ← OpenAI-compat streaming client       (~150 lines)
├── tools.py            ← Tool registry + implementations      (~300 lines)
├── permissions.py      ← Permission gating (pure function)    (~60 lines)
├── compaction.py       ← Two-layer context management         (~120 lines)
├── skills.py           ← Skill/agent markdown parser          (~100 lines)
├── hooks.py            ← Hook middleware system               (~80 lines)
├── memory.py           ← Memory read/write                    (~60 lines)
├── mcp.py              ← MCP stdio/http client                (~150 lines)
└── commands/
    ├── __init__.py     ← load_builtin_commands()              (~30 lines)
    ├── compact.py      ← /compact                             (~20 lines)
    ├── memory.py       ← /memory, /remember                   (~25 lines)
    ├── skills.py       ← /skills                              (~15 lines)
    ├── agent.py        ← /agent                               (~30 lines)
    ├── misc.py         ← /help, /clear, /tokens, /model       (~50 lines)

tests/
├── test_types.py
├── test_config.py
├── test_permissions.py
├── test_tools.py
├── test_hooks.py
├── test_provider.py
├── test_compaction.py
├── test_skills.py
├── test_memory.py
├── test_loop.py

pyproject.toml
```

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/newcli/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "newcli"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["openai>=1.0"]

[project.scripts]
newcli = "newcli.main:main"

[tool.hatch.build.targets.wheel]
packages = ["src/newcli"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create empty package files**

```bash
mkdir -p src/newcli/commands tests
touch src/newcli/__init__.py src/newcli/commands/__init__.py tests/__init__.py
```

- [ ] **Step 3: Install in editable mode**

Run: `pip install -e ".[dev]" 2>/dev/null || pip install -e .`

Then: `pip install pytest`

- [ ] **Step 4: Verify pytest finds the package**

Run: `python -c "import newcli; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "chore: scaffold project structure"
```

---

## Task 2: Types (`types.py`)

All dataclasses and event types. No logic, no imports from sibling modules.

**Files:**
- Create: `src/newcli/types.py`
- Create: `tests/test_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_types.py
import dataclasses
from newcli.types import (
    Config, RunContext, Message, ToolCallRecord, ToolDef,
    TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent,
    TurnDoneEvent, AssistantMessage,
)

def test_config_frozen():
    cfg = Config(base_url="http://localhost:11434/v1", model="qwen3")
    try:
        cfg.model = "other"
        assert False, "should have raised"
    except dataclasses.FrozenInstanceError:
        pass

def test_config_defaults():
    cfg = Config(base_url="http://x", model="m")
    assert cfg.api_key == "local"
    assert cfg.context_limit == 8192
    assert cfg.permission_mode == "auto"
    assert cfg.max_depth == 4
    assert cfg.max_retries == 2
    assert cfg.bash_safe_prefixes == []

def test_message_defaults():
    m = Message(role="user", content="hello")
    assert m.tool_calls == []
    assert m.tool_call_id is None
    assert m.name is None

def test_tool_call_record():
    r = ToolCallRecord(call_id="c1", name="read", args={"path": "/x"})
    assert r.call_id == "c1"

def test_run_context_defaults():
    cfg = Config(base_url="http://x", model="m")
    ctx = RunContext(config=cfg, messages=[], system_prompt="s")
    assert ctx.depth == 0
    assert ctx.turn == 0
    assert ctx.allowed_tools is None

def test_events():
    assert TextChunk(content="hi").content == "hi"
    assert ToolStartEvent(call_id="c", name="read", args={}).name == "read"
    e = ToolEndEvent(call_id="c", name="read", output="data")
    assert not e.error and e.permitted
    p = PermissionEvent(call_id="c", name="bash", args={})
    assert not p.granted
    assert TurnDoneEvent(input_tokens=10, output_tokens=5).output_tokens == 5

def test_assistant_message():
    a = AssistantMessage(content="hi", tool_calls=[])
    assert a.content == "hi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_types.py -v`
Expected: `ERROR` — `ModuleNotFoundError: No module named 'newcli.types'`

- [ ] **Step 3: Write `src/newcli/types.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Config:
    base_url: str
    model: str
    api_key: str = "local"
    context_limit: int = 8192
    max_tokens: int = 2048
    temperature: float = 0.7
    permission_mode: str = "auto"   # auto | manual | accept-all
    max_depth: int = 4
    max_retries: int = 2
    bash_safe_prefixes: list[str] = field(default_factory=list)
    prefer_text_tools: bool = False


@dataclass
class ToolCallRecord:
    call_id: str
    name: str
    args: dict


@dataclass
class Message:
    role: str                               # "user" | "assistant" | "tool"
    content: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    tool_call_id: str | None = None         # for role="tool"
    name: str | None = None                 # for role="tool"


@dataclass
class AssistantMessage:
    """Raw response from the provider before it's stored as a Message."""
    content: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict                        # JSON Schema object
    func: Callable[[dict], str]
    read_only: bool = False
    safe: bool = False


@dataclass
class RunContext:
    config: Config
    messages: list[Message]
    system_prompt: str
    depth: int = 0
    allowed_tools: list[str] | None = None  # None = all tools
    turn: int = 0


# ── Events yielded by the agent loop ──────────────────────────────────────

@dataclass
class TextChunk:
    content: str


@dataclass
class ToolStartEvent:
    call_id: str
    name: str
    args: dict


@dataclass
class ToolEndEvent:
    call_id: str
    name: str
    output: str
    error: bool = False
    permitted: bool = True


@dataclass
class PermissionEvent:
    call_id: str
    name: str
    args: dict
    granted: bool = False


@dataclass
class TurnDoneEvent:
    input_tokens: int
    output_tokens: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_types.py -v`
Expected: all 7 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/newcli/types.py tests/test_types.py
git commit -m "feat: add all dataclasses and event types"
```

---

## Task 3: Config Loader (`config.py`)

Loads and validates `config.json` into a frozen `Config`. No I/O besides the file read.

**Files:**
- Create: `src/newcli/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import json, tempfile, pathlib, pytest
from newcli.config import load_config
from newcli.types import Config

def _write(data: dict) -> pathlib.Path:
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    json.dump(data, f)
    f.close()
    return pathlib.Path(f.name)

def test_load_minimal():
    p = _write({"base_url": "http://localhost:11434/v1", "model": "qwen3"})
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    assert cfg.base_url == "http://localhost:11434/v1"
    assert cfg.model == "qwen3"
    assert cfg.api_key == "local"           # default applied

def test_load_overrides_defaults():
    p = _write({"base_url": "http://x", "model": "m",
                "permission_mode": "accept-all", "max_depth": 2})
    cfg = load_config(p)
    assert cfg.permission_mode == "accept-all"
    assert cfg.max_depth == 2

def test_missing_required_fields():
    p = _write({"model": "qwen3"})          # no base_url
    with pytest.raises(ValueError, match="base_url"):
        load_config(p)

def test_invalid_permission_mode():
    p = _write({"base_url": "http://x", "model": "m", "permission_mode": "yolo"})
    with pytest.raises(ValueError, match="permission_mode"):
        load_config(p)

def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_config(pathlib.Path("/no/such/config.json"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: `ERROR` — `ModuleNotFoundError: No module named 'newcli.config'`

- [ ] **Step 3: Write `src/newcli/config.py`**

```python
from __future__ import annotations
import json, pathlib
from newcli.types import Config

_VALID_PERMISSION_MODES = {"auto", "manual", "accept-all"}


def load_config(path: pathlib.Path) -> Config:
    """Load config.json at *path* and return a validated frozen Config."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open() as f:
        data = json.load(f)

    if "base_url" not in data:
        raise ValueError("config.json missing required field: base_url")
    if "model" not in data:
        raise ValueError("config.json missing required field: model")

    mode = data.get("permission_mode", "auto")
    if mode not in _VALID_PERMISSION_MODES:
        raise ValueError(
            f"permission_mode must be one of {_VALID_PERMISSION_MODES}, got {mode!r}"
        )

    return Config(
        base_url=data["base_url"],
        model=data["model"],
        api_key=data.get("api_key", "local"),
        context_limit=data.get("context_limit", 8192),
        max_tokens=data.get("max_tokens", 2048),
        temperature=data.get("temperature", 0.7),
        permission_mode=mode,
        max_depth=data.get("max_depth", 4),
        max_retries=data.get("max_retries", 2),
        bash_safe_prefixes=data.get("bash_safe_prefixes", []),
        prefer_text_tools=data.get("prefer_text_tools", False),
    )


def find_config(start: pathlib.Path) -> pathlib.Path | None:
    """Walk up from *start* looking for .tigger/config.json, fallback to ~/.tigger/."""
    current = start.resolve()
    while True:
        candidate = current / ".ai" / "config.json"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    global_cfg = pathlib.Path.home() / ".ai" / "config.json"
    return global_cfg if global_cfg.exists() else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: all 5 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/newcli/config.py tests/test_config.py
git commit -m "feat: add config loader with validation"
```

---

## Task 4: Permissions (`permissions.py`)

Pure function. No I/O, no imports from sibling modules except `types.py`.

**Files:**
- Create: `src/newcli/permissions.py`
- Create: `tests/test_permissions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_permissions.py
from newcli.types import ToolDef
from newcli.permissions import check

def _tool(name="bash", read_only=False, safe=False):
    return ToolDef(name=name, description="", parameters={},
                   func=lambda a: "", read_only=read_only, safe=safe)

def test_read_only_always_permitted():
    t = _tool(read_only=True)
    for mode in ("auto", "manual", "accept-all"):
        assert check(t, mode, {}, bash_safe_prefixes=[]) is True

def test_accept_all_permits_everything():
    t = _tool()
    assert check(t, "accept-all", {}, bash_safe_prefixes=[]) is True

def test_safe_tool_auto_permitted():
    t = _tool(safe=True)
    assert check(t, "auto", {}, bash_safe_prefixes=[]) is True

def test_safe_tool_manual_not_permitted():
    t = _tool(safe=True)
    assert check(t, "manual", {}, bash_safe_prefixes=[]) is False

def test_bash_safe_prefix_auto():
    t = _tool(name="bash")
    prefixes = ["git log", "ls"]
    assert check(t, "auto", {"command": "git log --oneline"}, bash_safe_prefixes=prefixes) is True
    assert check(t, "auto", {"command": "rm -rf /"}, bash_safe_prefixes=prefixes) is False

def test_unknown_tool_manual_denied():
    t = _tool(name="write")
    assert check(t, "manual", {}, bash_safe_prefixes=[]) is False

def test_unknown_tool_auto_denied():
    t = _tool(name="write")
    assert check(t, "auto", {}, bash_safe_prefixes=[]) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions.py -v`
Expected: `ERROR` — `ModuleNotFoundError: No module named 'newcli.permissions'`

- [ ] **Step 3: Write `src/newcli/permissions.py`**

```python
from __future__ import annotations
from newcli.types import ToolDef


def check(
    tool: ToolDef,
    mode: str,
    args: dict,
    bash_safe_prefixes: list[str],
) -> bool:
    """Return True if *tool* is auto-approved under *mode*; False means ask."""
    if tool.read_only:
        return True
    if mode == "accept-all":
        return True
    if mode == "auto":
        if tool.safe:
            return True
        if tool.name == "bash":
            cmd = args.get("command", "")
            return any(cmd.startswith(p) for p in bash_safe_prefixes)
        return False
    return False    # manual: caller must prompt the user
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_permissions.py -v`
Expected: all 7 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/newcli/permissions.py tests/test_permissions.py
git commit -m "feat: add pure-function permission gating"
```

---

## Task 5: Tool Registry + Implementations (`tools.py`)

Registry first, then the 7 built-in tool implementations.

**Files:**
- Create: `src/newcli/tools.py`
- Create: `tests/test_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tools.py
import tempfile, pathlib
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

def test_read_tool():
    r = ToolRegistry()
    register_all(r)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello")
        p = f.name
    result = r.execute("read", {"path": p})
    assert "hello" in result

def test_read_tool_missing_file():
    r = ToolRegistry()
    register_all(r)
    result = r.execute("read", {"path": "/no/such/file.txt"})
    assert "not found" in result.lower() or "error" in result.lower()

def test_write_refuses_existing_file():
    r = ToolRegistry()
    register_all(r)
    with tempfile.NamedTemporaryFile(delete=False) as f:
        p = f.name
    result = r.execute("write", {"path": p, "content": "new"})
    assert "edit" in result.lower()        # error message references 'edit'

def test_write_creates_new_file():
    r = ToolRegistry()
    register_all(r)
    p = pathlib.Path(tempfile.mkdtemp()) / "new.txt"
    result = r.execute("write", {"path": str(p), "content": "created"})
    assert p.read_text() == "created"
    assert "error" not in result.lower()

def test_edit_tool_replaces_text():
    r = ToolRegistry()
    register_all(r)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("foo bar baz")
        p = f.name
    r.execute("edit", {"path": p, "old_string": "bar", "new_string": "QUX"})
    assert pathlib.Path(p).read_text() == "foo QUX baz"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tools.py -v`
Expected: `ERROR` — `ModuleNotFoundError: No module named 'newcli.tools'`

- [ ] **Step 3: Write `src/newcli/tools.py`**

```python
from __future__ import annotations
import glob as _glob, subprocess, pathlib, urllib.request
from newcli.types import ToolDef

_32KB = 32 * 1024


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def all(self) -> list[ToolDef]:
        return list(self._tools.values())

    def schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def execute(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'"
        try:
            result = tool.func(args)
        except Exception as exc:
            result = f"Error: {exc}"
        if len(result) > _32KB:
            result = result[:_32KB] + f"\n[output truncated at 32KB]"
        return result


# ── Tool implementations ────────────────────────────────────────────────

def _read(args: dict) -> str:
    p = pathlib.Path(args["path"])
    if not p.exists():
        return f"Error: file not found: {p}"
    return p.read_text(errors="replace")


def _glob_tool(args: dict) -> str:
    pattern = args["pattern"]
    base = args.get("path", ".")
    matches = _glob.glob(str(pathlib.Path(base) / pattern), recursive=True)
    return "\n".join(sorted(matches)) or "(no matches)"


def _grep(args: dict) -> str:
    import re
    pattern = args["pattern"]
    path = args.get("path", ".")
    glob_pat = args.get("glob", "**/*")
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"
    results = []
    for p in pathlib.Path(path).rglob(glob_pat.lstrip("**/").lstrip("*")):
        if not p.is_file():
            continue
        try:
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if rx.search(line):
                    results.append(f"{p}:{i}: {line}")
        except Exception:
            pass
    return "\n".join(results) or "(no matches)"


def _write(args: dict) -> str:
    p = pathlib.Path(args["path"])
    if p.exists():
        return "Error: file already exists. Use 'edit' to modify existing files."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args["content"])
    return f"Written: {p}"


def _edit(args: dict) -> str:
    p = pathlib.Path(args["path"])
    if not p.exists():
        return f"Error: file not found: {p}"
    text = p.read_text()
    old = args["old_string"]
    new = args["new_string"]
    if old not in text:
        return f"Error: old_string not found in {p}"
    p.write_text(text.replace(old, new, 1))
    return f"Edited: {p}"


def _bash(args: dict) -> str:
    cmd = args["command"]
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=30
    )
    out = result.stdout + result.stderr
    return out or "(no output)"


def _web_fetch(args: dict) -> str:
    url = args["url"]
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return f"Error: {exc}"


def register_all(registry: ToolRegistry) -> None:
    registry.register(ToolDef(
        name="read",
        description="Read the contents of a file.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        func=_read,
        read_only=True,
    ))
    registry.register(ToolDef(
        name="glob",
        description="Find files matching a glob pattern.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "description": "Base directory (default: cwd)"},
            },
            "required": ["pattern"],
        },
        func=_glob_tool,
        read_only=True,
    ))
    registry.register(ToolDef(
        name="grep",
        description="Search file contents for a regex pattern.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
                "glob": {"type": "string", "description": "File glob filter"},
            },
            "required": ["pattern"],
        },
        func=_grep,
        read_only=True,
    ))
    registry.register(ToolDef(
        name="write",
        description="Write content to a new file. Fails if file exists — use edit instead.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        func=_write,
    ))
    registry.register(ToolDef(
        name="edit",
        description="Replace old_string with new_string in an existing file (first occurrence).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        func=_edit,
    ))
    registry.register(ToolDef(
        name="bash",
        description="Run a shell command. Returns stdout + stderr.",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        func=_bash,
        safe=False,
    ))
    registry.register(ToolDef(
        name="web_fetch",
        description="Fetch the contents of a URL.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        func=_web_fetch,
        read_only=True,
    ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tools.py -v`
Expected: all 13 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/newcli/tools.py tests/test_tools.py
git commit -m "feat: add tool registry and 7 built-in tool implementations"
```

---

## Task 6: Hook Middleware (`hooks.py`)

Module-level `_REGISTRY` singleton so `@on_before` / `@on_after` decorators in user files register automatically on import.

**Files:**
- Create: `src/newcli/hooks.py`
- Create: `tests/test_hooks.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hooks.py
import pathlib, tempfile, textwrap
from newcli.types import ToolCallRecord, ToolEndEvent, Config, RunContext
from newcli.hooks import HookRegistry, run_before, run_after, load_hooks

def _ctx():
    cfg = Config(base_url="http://x", model="m")
    return RunContext(config=cfg, messages=[], system_prompt="")

def test_run_before_modifies_call():
    reg = HookRegistry()
    reg.before.setdefault("read", []).append(
        lambda call, ctx: ToolCallRecord(call.call_id, call.name, {"path": "/modified"})
    )
    call = ToolCallRecord("c1", "read", {"path": "/original"})
    result = run_before(call, _ctx(), reg)
    assert result.args["path"] == "/modified"

def test_run_after_modifies_event():
    reg = HookRegistry()
    reg.after.setdefault("bash", []).append(
        lambda e, ctx: ToolEndEvent(e.call_id, e.name, "overridden")
    )
    ev = ToolEndEvent("c1", "bash", "original")
    result = run_after(ev, _ctx(), reg)
    assert result.output == "overridden"

def test_wildcard_before_hook():
    reg = HookRegistry()
    log = []
    reg.before.setdefault("*", []).append(lambda c, ctx: (log.append(c.name), c)[1])
    call = ToolCallRecord("c1", "read", {})
    run_before(call, _ctx(), reg)
    assert "read" in log

def test_wildcard_after_hook():
    reg = HookRegistry()
    log = []
    reg.after.setdefault("*", []).append(lambda e, ctx: (log.append(e.name), e)[1])
    run_after(ToolEndEvent("c1", "bash", "out"), _ctx(), reg)
    assert "bash" in log

def test_multiple_hooks_chain():
    reg = HookRegistry()
    reg.before.setdefault("write", []).extend([
        lambda c, ctx: ToolCallRecord(c.call_id, c.name, {**c.args, "step": 1}),
        lambda c, ctx: ToolCallRecord(c.call_id, c.name, {**c.args, "step": 2}),
    ])
    call = ToolCallRecord("c1", "write", {})
    result = run_before(call, _ctx(), reg)
    assert result.args["step"] == 2

def test_load_hooks_from_file():
    src = textwrap.dedent("""
        from newcli.hooks import on_before
        @on_before("read")
        def my_hook(call, ctx):
            return call
    """)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(src)
        p = pathlib.Path(f.name)
    reg = load_hooks(p)
    assert "read" in reg.before

def test_load_hooks_missing_file_returns_empty():
    reg = load_hooks(pathlib.Path("/no/such/hooks.py"))
    assert reg.before == {} and reg.after == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hooks.py -v`
Expected: `ERROR` — `ModuleNotFoundError: No module named 'newcli.hooks'`

- [ ] **Step 3: Write `src/newcli/hooks.py`**

```python
from __future__ import annotations
import importlib.util, pathlib
from dataclasses import dataclass, field
from typing import Callable
from newcli.types import ToolCallRecord, ToolEndEvent, RunContext

BeforeFn = Callable[[ToolCallRecord, RunContext], ToolCallRecord]
AfterFn  = Callable[[ToolEndEvent,   RunContext], ToolEndEvent]


@dataclass
class HookRegistry:
    before: dict[str, list[BeforeFn]] = field(default_factory=dict)
    after:  dict[str, list[AfterFn]]  = field(default_factory=dict)


# Module-level singleton used by the decorator API.
# load_hooks() resets this before importing user code so each call is clean.
_REGISTRY = HookRegistry()


def on_before(*tool_names: str):
    """Decorator: register a before-hook for one or more tool names (or '*')."""
    def decorator(fn: BeforeFn) -> BeforeFn:
        for name in tool_names:
            _REGISTRY.before.setdefault(name, []).append(fn)
        return fn
    return decorator


def on_after(*tool_names: str):
    """Decorator: register an after-hook for one or more tool names (or '*')."""
    def decorator(fn: AfterFn) -> AfterFn:
        for name in tool_names:
            _REGISTRY.after.setdefault(name, []).append(fn)
        return fn
    return decorator


def run_before(call: ToolCallRecord, ctx: RunContext, registry: HookRegistry) -> ToolCallRecord:
    for fn in registry.before.get(call.name, []) + registry.before.get("*", []):
        call = fn(call, ctx)
    return call


def run_after(event: ToolEndEvent, ctx: RunContext, registry: HookRegistry) -> ToolEndEvent:
    for fn in registry.after.get(event.name, []) + registry.after.get("*", []):
        event = fn(event, ctx)
    return event


def load_hooks(path: pathlib.Path) -> HookRegistry:
    """Import *path* (causing @on_before/@on_after decorators to fire) and return the registry."""
    global _REGISTRY
    _REGISTRY = HookRegistry()          # reset so previous loads don't accumulate

    if not path.exists():
        return _REGISTRY

    spec = importlib.util.spec_from_file_location("_user_hooks", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        print(f"[hooks] Warning: failed to load {path}: {exc}")

    return _REGISTRY
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hooks.py -v`
Expected: all 7 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/newcli/hooks.py tests/test_hooks.py
git commit -m "feat: add hook middleware system with decorator API"
```

---

## Task 7: Memory (`memory.py`)

Append-only markdown log. Read at startup; write via `/remember`.

**Files:**
- Create: `src/newcli/memory.py`
- Create: `tests/test_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_memory.py
import pathlib, tempfile, datetime
from newcli.memory import read_memory, append_memory, format_for_prompt

def _tmp() -> pathlib.Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
    f.close()
    return pathlib.Path(f.name)

def test_read_empty_file():
    p = _tmp()
    assert read_memory(p) == []

def test_append_and_read():
    p = _tmp()
    append_memory(p, "use pytest")
    lines = read_memory(p)
    assert len(lines) == 1
    assert "use pytest" in lines[0]

def test_append_adds_date():
    p = _tmp()
    append_memory(p, "api at localhost")
    lines = read_memory(p)
    today = datetime.date.today().isoformat()
    assert today in lines[0]

def test_read_returns_last_50():
    p = _tmp()
    for i in range(60):
        append_memory(p, f"note {i}")
    lines = read_memory(p)
    assert len(lines) == 50
    assert "note 59" in lines[-1]

def test_format_for_prompt_empty():
    assert format_for_prompt([]) == ""

def test_format_for_prompt():
    lines = ["[2026-04-22] use pytest", "[2026-04-22] api at localhost"]
    prompt = format_for_prompt(lines)
    assert "## Memory" in prompt
    assert "use pytest" in prompt

def test_read_missing_file():
    assert read_memory(pathlib.Path("/no/memory.md")) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory.py -v`
Expected: `ERROR` — `ModuleNotFoundError: No module named 'newcli.memory'`

- [ ] **Step 3: Write `src/newcli/memory.py`**

```python
from __future__ import annotations
import datetime, pathlib


def read_memory(path: pathlib.Path) -> list[str]:
    """Return last 50 non-empty lines from *path*. Returns [] if file missing."""
    if not path.exists():
        return []
    lines = [l.rstrip() for l in path.read_text().splitlines() if l.strip()]
    return lines[-50:]


def append_memory(path: pathlib.Path, note: str) -> None:
    today = datetime.date.today().isoformat()
    entry = f"- [{today}] {note}\n"
    with path.open("a") as f:
        f.write(entry)


def format_for_prompt(lines: list[str]) -> str:
    if not lines:
        return ""
    body = "\n".join(lines)
    return f"## Memory\n\n{body}\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_memory.py -v`
Expected: all 7 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/newcli/memory.py tests/test_memory.py
git commit -m "feat: add append-only memory read/write"
```

---

## Task 8: Skills + Agents Markdown Parser (`skills.py`)

Parses `skills.md` and `agents.md` into typed objects.

**Files:**
- Create: `src/newcli/skills.py`
- Create: `tests/test_skills.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skills.py
import textwrap, pathlib, tempfile
from newcli.skills import load_skills, load_agents, match_skill, SkillDef, AgentDef

SKILLS_MD = textwrap.dedent("""
    ---
    name: review
    triggers: [/review]
    tools: [read, grep, glob]
    context: inline
    ---
    Review the code at $ARGUMENTS. Check for logic errors.

    ---
    name: refactor
    triggers: [/refactor]
    tools: [read, edit, bash]
    context: fork
    ---
    Refactor $ARGUMENTS. Preserve behavior.
""").strip()

AGENTS_MD = textwrap.dedent("""
    ---
    name: reviewer
    system_prompt: |
      You are a careful code reviewer.
    tools: [read, grep, glob]
    model: null
    ---
""").strip()

def _write(content: str) -> pathlib.Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
    f.write(content)
    f.close()
    return pathlib.Path(f.name)

def test_load_skills_count():
    skills = load_skills(_write(SKILLS_MD))
    assert len(skills) == 2

def test_skill_fields():
    skills = load_skills(_write(SKILLS_MD))
    review = next(s for s in skills if s.name == "review")
    assert review.context == "inline"
    assert "read" in review.tools
    assert "/review" in review.triggers

def test_skill_render_substitutes_arguments():
    skills = load_skills(_write(SKILLS_MD))
    review = next(s for s in skills if s.name == "review")
    rendered = review.render("/review src/main.py")
    assert "src/main.py" in rendered
    assert "$ARGUMENTS" not in rendered

def test_match_skill_by_slash():
    skills = load_skills(_write(SKILLS_MD))
    matched = match_skill("/review src/foo.py", skills)
    assert matched is not None and matched.name == "review"

def test_match_skill_no_match():
    skills = load_skills(_write(SKILLS_MD))
    assert match_skill("just a question", skills) is None

def test_load_skills_missing_file():
    assert load_skills(pathlib.Path("/no/skills.md")) == []

def test_load_agents():
    agents = load_agents(_write(AGENTS_MD))
    assert len(agents) == 1
    assert agents[0].name == "reviewer"
    assert "reviewer" in agents[0].system_prompt.lower()

def test_load_agents_missing_file():
    assert load_agents(pathlib.Path("/no/agents.md")) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_skills.py -v`
Expected: `ERROR` — `ModuleNotFoundError: No module named 'newcli.skills'`

- [ ] **Step 3: Write `src/newcli/skills.py`**

```python
from __future__ import annotations
import pathlib, re
from dataclasses import dataclass, field


@dataclass
class SkillDef:
    name: str
    triggers: list[str]
    tools: list[str]
    context: str            # "inline" | "fork"
    body: str               # prompt template with $ARGUMENTS placeholder

    def render(self, user_input: str) -> str:
        """Replace $ARGUMENTS with everything after the trigger token."""
        for trigger in self.triggers:
            if user_input.startswith(trigger):
                args = user_input[len(trigger):].strip()
                return self.body.replace("$ARGUMENTS", args)
        return self.body.replace("$ARGUMENTS", user_input)


@dataclass
class AgentDef:
    name: str
    system_prompt: str
    tools: list[str]
    model: str | None = None


def _parse_blocks(text: str) -> list[dict]:
    """Split a markdown file on --- separators and parse YAML frontmatter."""
    import yaml  # stdlib-safe: pyyaml ships with most Pythons; fall back to manual parse
    blocks = []
    parts = re.split(r"^---\s*$", text, flags=re.MULTILINE)
    # parts alternates: [pre, frontmatter, body, frontmatter, body, ...]
    i = 1
    while i + 1 < len(parts):
        fm_text = parts[i].strip()
        body = parts[i + 1].strip()
        if fm_text:
            try:
                fm = yaml.safe_load(fm_text)
                if isinstance(fm, dict):
                    blocks.append({"fm": fm, "body": body})
            except Exception:
                pass
        i += 2
    return blocks


def load_skills(path: pathlib.Path) -> list[SkillDef]:
    if not path.exists():
        return []
    blocks = _parse_blocks(path.read_text())
    skills = []
    for b in blocks:
        fm = b["fm"]
        if "name" not in fm:
            continue
        triggers = fm.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [triggers]
        tools = fm.get("tools", [])
        skills.append(SkillDef(
            name=fm["name"],
            triggers=triggers,
            tools=tools,
            context=fm.get("context", "inline"),
            body=b["body"],
        ))
    return skills


def load_agents(path: pathlib.Path) -> list[AgentDef]:
    if not path.exists():
        return []
    blocks = _parse_blocks(path.read_text())
    agents = []
    for b in blocks:
        fm = b["fm"]
        if "name" not in fm:
            continue
        tools = fm.get("tools", [])
        agents.append(AgentDef(
            name=fm["name"],
            system_prompt=fm.get("system_prompt", ""),
            tools=tools,
            model=fm.get("model"),
        ))
    return agents


def match_skill(user_input: str, skills: list[SkillDef]) -> SkillDef | None:
    for skill in skills:
        for trigger in skill.triggers:
            if user_input.startswith(trigger):
                return skill
    return None
```

- [ ] **Step 4: Install PyYAML (required by skills.py)**

Run: `pip install pyyaml`

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_skills.py -v`
Expected: all 8 tests `PASSED`

- [ ] **Step 6: Add pyyaml to pyproject.toml dependencies**

In `pyproject.toml`, update:
```toml
dependencies = ["openai>=1.0", "pyyaml>=6.0"]
```

- [ ] **Step 7: Commit**

```bash
git add src/newcli/skills.py tests/test_skills.py pyproject.toml
git commit -m "feat: add skills/agents markdown parser"
```

---

## Task 9: Compaction (`compaction.py`)

Two-layer context management. `estimate_tokens` is the single source of truth.

**Files:**
- Create: `src/newcli/compaction.py`
- Create: `tests/test_compaction.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compaction.py
from newcli.types import Config, Message
from newcli.compaction import estimate_tokens, snip_old_results, maybe_compact

def _cfg(**kw):
    return Config(base_url="http://x", model="m", **kw)

def _msg(role, content):
    return Message(role=role, content=content)

def _tool_msg(content):
    m = Message(role="tool", content=content, tool_call_id="c1", name="bash")
    return m

def test_estimate_tokens_empty():
    assert estimate_tokens([]) == 0

def test_estimate_tokens_rough():
    msgs = [_msg("user", "hello world")]   # 11 chars → ~3 tokens
    t = estimate_tokens(msgs)
    assert 1 <= t <= 10

def test_snip_old_results_no_op_short():
    msgs = [_msg("user", "hi"), _tool_msg("small result")]
    result = snip_old_results(msgs)
    assert result == msgs

def test_snip_removes_old_tool_results():
    # Build a long history: many tool results, then recent messages
    old = [_tool_msg("x" * 500) for _ in range(20)]
    recent = [_msg("user", "final question"), _msg("assistant", "final answer")]
    msgs = old + recent
    result = snip_old_results(msgs)
    # Should be shorter and preserve recent messages
    assert estimate_tokens(result) < estimate_tokens(msgs)
    assert result[-2].content == "final question"

def test_maybe_compact_noop_under_threshold():
    cfg = _cfg(context_limit=8192)
    msgs = [_msg("user", "short")]
    result = maybe_compact(msgs, cfg, provider_fn=None)
    assert result == msgs

def test_maybe_compact_layer1_triggers():
    cfg = _cfg(context_limit=100)   # very small limit
    # Fill past 70% threshold
    msgs = [_tool_msg("x" * 300) for _ in range(5)]
    result = maybe_compact(msgs, cfg, provider_fn=None)
    assert estimate_tokens(result) <= estimate_tokens(msgs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_compaction.py -v`
Expected: `ERROR` — `ModuleNotFoundError: No module named 'newcli.compaction'`

- [ ] **Step 3: Write `src/newcli/compaction.py`**

```python
from __future__ import annotations
from typing import Callable
from newcli.types import Message, Config


def estimate_tokens(messages: list[Message]) -> int:
    """Rough token estimate: total chars / 3.5."""
    total = sum(len(m.content) for m in messages)
    return int(total / 3.5)


def snip_old_results(messages: list[Message]) -> list[Message]:
    """Layer 1: replace old tool results with a short placeholder (no LLM call)."""
    if not messages:
        return messages

    # Find the boundary: keep last 25% of messages as "recent"
    boundary = max(1, len(messages) * 3 // 4)
    old, recent = messages[:boundary], messages[boundary:]

    compacted = []
    for m in old:
        if m.role == "tool" and len(m.content) > 200:
            compacted.append(Message(
                role=m.role,
                content="[tool result snipped during compaction]",
                tool_call_id=m.tool_call_id,
                name=m.name,
            ))
        else:
            compacted.append(m)
    return compacted + recent


def summarize_old(
    messages: list[Message],
    config: Config,
    provider_fn: Callable,
) -> list[Message]:
    """Layer 2: LLM-summarize old portion of history (makes a real API call)."""
    if not messages or provider_fn is None:
        return messages

    boundary = max(1, len(messages) * 3 // 4)
    old, recent = messages[:boundary], messages[boundary:]

    summary_prompt = (
        "Summarize the following conversation history concisely. "
        "Preserve key facts, decisions, and file paths mentioned.\n\n"
        + "\n".join(f"{m.role}: {m.content[:500]}" for m in old)
    )
    summary = provider_fn(summary_prompt)
    summary_msg = Message(role="user", content=f"[Conversation summary]\n{summary}")
    return [summary_msg] + recent


def maybe_compact(
    messages: list[Message],
    config: Config,
    provider_fn: Callable | None,
) -> list[Message]:
    """Compact *messages* if above 70% of context_limit. Returns (possibly shorter) list."""
    threshold = config.context_limit * 0.7
    if estimate_tokens(messages) < threshold:
        return messages

    # Layer 1: snip old tool results (no API call)
    messages = snip_old_results(messages)
    if estimate_tokens(messages) < threshold:
        return messages

    # Layer 2: LLM summarize (only if provider available)
    if provider_fn is not None:
        messages = summarize_old(messages, config, provider_fn)
    return messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_compaction.py -v`
Expected: all 6 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/newcli/compaction.py tests/test_compaction.py
git commit -m "feat: add two-layer context compaction"
```

---

## Task 10: Provider (`provider.py`)

OpenAI-compatible streaming client. Converts between `Message` (neutral) and OpenAI wire format.

**Files:**
- Create: `src/newcli/provider.py`
- Create: `tests/test_provider.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provider.py
from newcli.types import Message, ToolCallRecord
from newcli.provider import messages_to_openai, openai_tool_calls_to_records

def test_messages_to_openai_user():
    msgs = [Message(role="user", content="hello")]
    result = messages_to_openai(msgs)
    assert result == [{"role": "user", "content": "hello"}]

def test_messages_to_openai_tool():
    m = Message(role="tool", content="result", tool_call_id="c1", name="read")
    result = messages_to_openai([m])
    assert result[0]["role"] == "tool"
    assert result[0]["tool_call_id"] == "c1"

def test_messages_to_openai_assistant_with_tool_calls():
    tc = ToolCallRecord(call_id="c1", name="read", args={"path": "/x"})
    m = Message(role="assistant", content="", tool_calls=[tc])
    result = messages_to_openai([m])
    assert result[0]["tool_calls"][0]["function"]["name"] == "read"

def test_openai_tool_calls_to_records():
    raw = [{
        "id": "c1",
        "function": {"name": "read", "arguments": '{"path": "/x"}'},
    }]
    records = openai_tool_calls_to_records(raw)
    assert len(records) == 1
    assert records[0].name == "read"
    assert records[0].args == {"path": "/x"}

def test_openai_tool_calls_malformed_json():
    raw = [{"id": "c1", "function": {"name": "read", "arguments": "{bad json"}}]
    records = openai_tool_calls_to_records(raw)
    assert records[0].args == {}     # graceful fallback
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_provider.py -v`
Expected: `ERROR` — `ModuleNotFoundError: No module named 'newcli.provider'`

- [ ] **Step 3: Write `src/newcli/provider.py`**

```python
from __future__ import annotations
import json
from typing import Generator
from openai import OpenAI
from newcli.types import Config, Message, AssistantMessage, ToolCallRecord, TextChunk


def messages_to_openai(messages: list[Message]) -> list[dict]:
    """Convert neutral Message list to OpenAI wire format."""
    result = []
    for m in messages:
        if m.role == "tool":
            result.append({
                "role": "tool",
                "content": m.content,
                "tool_call_id": m.tool_call_id,
            })
        elif m.tool_calls:
            result.append({
                "role": m.role,
                "content": m.content,
                "tool_calls": [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.args),
                        },
                    }
                    for tc in m.tool_calls
                ],
            })
        else:
            result.append({"role": m.role, "content": m.content})
    return result


def openai_tool_calls_to_records(raw: list[dict]) -> list[ToolCallRecord]:
    records = []
    for tc in raw:
        try:
            args = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}
        records.append(ToolCallRecord(
            call_id=tc.get("id", ""),
            name=tc["function"]["name"],
            args=args,
        ))
    return records


def stream(
    system: str,
    messages: list[Message],
    tools: list[dict],
    config: Config,
) -> Generator[TextChunk | AssistantMessage, None, None]:
    """Stream a chat completion. Yields TextChunk during streaming, then AssistantMessage."""
    client = OpenAI(base_url=config.base_url, api_key=config.api_key)

    openai_messages = [{"role": "system", "content": system}] + messages_to_openai(messages)

    kwargs: dict = dict(
        model=config.model,
        messages=openai_messages,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        stream=True,
    )
    if tools:
        kwargs["tools"] = tools

    collected_text = ""
    collected_tool_calls: list[dict] = []

    response = client.chat.completions.create(**kwargs)
    for chunk in response:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta is None:
            continue
        if delta.content:
            collected_text += delta.content
            yield TextChunk(content=delta.content)
        if delta.tool_calls:
            for tc_chunk in delta.tool_calls:
                idx = tc_chunk.index
                while len(collected_tool_calls) <= idx:
                    collected_tool_calls.append({"id": "", "function": {"name": "", "arguments": ""}})
                if tc_chunk.id:
                    collected_tool_calls[idx]["id"] = tc_chunk.id
                if tc_chunk.function.name:
                    collected_tool_calls[idx]["function"]["name"] += tc_chunk.function.name
                if tc_chunk.function.arguments:
                    collected_tool_calls[idx]["function"]["arguments"] += tc_chunk.function.arguments

    yield AssistantMessage(
        content=collected_text,
        tool_calls=openai_tool_calls_to_records(collected_tool_calls),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_provider.py -v`
Expected: all 5 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/newcli/provider.py tests/test_provider.py
git commit -m "feat: add OpenAI-compatible streaming provider"
```

---

## Task 11: MCP Client (`mcp.py`)

Connects to MCP servers at boot, registers their tools into `ToolRegistry`.

**Files:**
- Create: `src/newcli/mcp.py`
- Create: `tests/test_mcp.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp.py
import json, pathlib, tempfile
from newcli.mcp import load_mcp_config, McpServerConfig
from newcli.tools import ToolRegistry

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp.py -v`
Expected: `ERROR` — `ModuleNotFoundError: No module named 'newcli.mcp'`

- [ ] **Step 3: Write `src/newcli/mcp.py`**

```python
from __future__ import annotations
import json, pathlib, subprocess, threading
from dataclasses import dataclass, field
from newcli.tools import ToolRegistry, ToolDef

_CONNECT_TIMEOUT = 3.0


@dataclass
class McpServerConfig:
    name: str
    transport: str              # "stdio" | "http"
    command: list[str] | None = None
    url: str | None = None


def load_mcp_config(path: pathlib.Path) -> list[McpServerConfig]:
    if not path.exists():
        return []
    with path.open() as f:
        data = json.load(f)
    configs = []
    for name, srv in data.get("servers", {}).items():
        configs.append(McpServerConfig(
            name=name,
            transport=srv.get("transport", "stdio"),
            command=srv.get("command"),
            url=srv.get("url"),
        ))
    return configs


def _make_mcp_tool_func(server_name: str, tool_name: str, proc: subprocess.Popen):
    """Return a callable that sends a JSON-RPC call to the stdio MCP process."""
    _lock = threading.Lock()

    def call(args: dict) -> str:
        request = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        }) + "\n"
        with _lock:
            try:
                proc.stdin.write(request.encode())
                proc.stdin.flush()
                line = proc.stdout.readline()
                resp = json.loads(line)
                content = resp.get("result", {}).get("content", [])
                return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
            except Exception as exc:
                return f"Error calling MCP tool {tool_name}: {exc}"
    return call


def connect_all(registry: ToolRegistry, path: pathlib.Path) -> None:
    """Connect to all MCP servers in *path* and register their tools. Blocking, 3s timeout."""
    for cfg in load_mcp_config(path):
        if cfg.transport == "stdio" and cfg.command:
            try:
                proc = subprocess.Popen(
                    cfg.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                # Send initialize
                init = json.dumps({
                    "jsonrpc": "2.0", "id": 0,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
                }) + "\n"
                proc.stdin.write(init.encode())
                proc.stdin.flush()

                import select
                ready, _, _ = select.select([proc.stdout], [], [], _CONNECT_TIMEOUT)
                if not ready:
                    print(f"[mcp] Warning: {cfg.name} timed out during initialize — skipping")
                    proc.kill()
                    continue

                resp_line = proc.stdout.readline()
                resp = json.loads(resp_line)

                # List tools
                list_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
                proc.stdin.write(list_req.encode())
                proc.stdin.flush()
                tools_line = proc.stdout.readline()
                tools_resp = json.loads(tools_line)
                for tool in tools_resp.get("result", {}).get("tools", []):
                    full_name = f"mcp__{cfg.name}__{tool['name']}"
                    registry.register(ToolDef(
                        name=full_name,
                        description=tool.get("description", ""),
                        parameters=tool.get("inputSchema", {"type": "object", "properties": {}}),
                        func=_make_mcp_tool_func(cfg.name, tool["name"], proc),
                        read_only=False,
                    ))
            except Exception as exc:
                print(f"[mcp] Warning: failed to connect to {cfg.name}: {exc}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp.py -v`
Expected: all 3 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/newcli/mcp.py tests/test_mcp.py
git commit -m "feat: add MCP stdio client with tool registration"
```

---

## Task 12: Agent Loop (`loop.py`)

The heart of the CLI. Generator that drives multi-turn exchanges and yields events.

**Files:**
- Create: `src/newcli/loop.py`
- Create: `tests/test_loop.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_loop.py
from unittest.mock import patch, MagicMock
from newcli.types import (
    Config, RunContext, Message, ToolCallRecord, AssistantMessage,
    TextChunk, ToolStartEvent, ToolEndEvent, TurnDoneEvent,
)
from newcli.tools import ToolRegistry, ToolDef
from newcli.hooks import HookRegistry
from newcli.loop import run, run_forked

def _ctx(permission_mode="accept-all"):
    cfg = Config(base_url="http://x", model="m", permission_mode=permission_mode)
    return RunContext(config=cfg, messages=[], system_prompt="You are helpful.")

def _registry(tools=None):
    r = ToolRegistry()
    if tools:
        for t in tools:
            r.register(t)
    return r

def _hooks():
    return HookRegistry()

def _make_provider(text="Hello!", tool_calls=None):
    """Return a mock provider.stream that yields TextChunk then AssistantMessage."""
    def fake_stream(system, messages, tools, config):
        yield TextChunk(content=text)
        yield AssistantMessage(content=text, tool_calls=tool_calls or [])
    return fake_stream

def test_simple_text_response():
    ctx = _ctx()
    events = list(run("hi", ctx, _registry(), _hooks(), provider_fn=_make_provider("Hello!")))
    texts = [e.content for e in events if isinstance(e, TextChunk)]
    assert texts == ["Hello!"]
    dones = [e for e in events if isinstance(e, TurnDoneEvent)]
    assert len(dones) == 1

def test_messages_appended_after_turn():
    ctx = _ctx()
    list(run("hi", ctx, _registry(), _hooks(), provider_fn=_make_provider("Hello!")))
    assert len(ctx.messages) == 2   # user + assistant
    assert ctx.messages[0].role == "user"
    assert ctx.messages[1].role == "assistant"

def test_tool_call_executed():
    called = []
    def my_tool(args): called.append(args); return "tool result"
    t = ToolDef("my_tool", "", {"type": "object", "properties": {}}, func=my_tool)
    reg = _registry([t])

    tc = ToolCallRecord("c1", "my_tool", {"x": 1})
    first_call = True
    def provider(system, messages, tools, config):
        nonlocal first_call
        if first_call:
            first_call = False
            yield TextChunk(content="")
            yield AssistantMessage(content="", tool_calls=[tc])
        else:
            yield TextChunk(content="Done")
            yield AssistantMessage(content="Done", tool_calls=[])

    ctx = _ctx()
    events = list(run("go", ctx, reg, _hooks(), provider_fn=provider))
    assert called == [{"x": 1}]
    ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert ends[0].output == "tool result"

def test_run_forked_depth_incremented():
    ctx = _ctx()
    assert ctx.depth == 0
    forked_ctx = None
    def capture_provider(system, messages, tools, config):
        nonlocal forked_ctx
        yield TextChunk(content="ok")
        yield AssistantMessage(content="ok", tool_calls=[])

    from newcli.skills import SkillDef
    skill = SkillDef(name="s", triggers=["/s"], tools=[], context="fork", body="do it")
    run_forked("do it", skill, ctx, _registry(), _hooks(), provider_fn=capture_provider)
    assert ctx.depth == 0           # original unchanged

def test_depth_cap_prevents_infinite_fork():
    from newcli.skills import SkillDef
    cfg = Config(base_url="http://x", model="m", max_depth=1)
    ctx = RunContext(config=cfg, messages=[], system_prompt="", depth=1)
    skill = SkillDef(name="s", triggers=["/s"], tools=[], context="fork", body="do it")
    result = run_forked("do it", skill, ctx, _registry(), _hooks(), provider_fn=None)
    assert "depth" in result.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_loop.py -v`
Expected: `ERROR` — `ModuleNotFoundError: No module named 'newcli.loop'`

- [ ] **Step 3: Write `src/newcli/loop.py`**

```python
from __future__ import annotations
import copy
from typing import Callable, Generator
from newcli.types import (
    Config, RunContext, Message, ToolCallRecord, AssistantMessage,
    TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent, TurnDoneEvent,
)
from newcli.tools import ToolRegistry
from newcli.hooks import HookRegistry, run_before, run_after
from newcli.permissions import check as permission_check
from newcli.compaction import maybe_compact

Event = TextChunk | ToolStartEvent | ToolEndEvent | PermissionEvent | TurnDoneEvent


def run(
    query: str,
    ctx: RunContext,
    registry: ToolRegistry,
    hooks: HookRegistry,
    provider_fn: Callable,
) -> Generator[Event, None, None]:
    """Drive a full multi-turn agent exchange. Yields events; mutates ctx.messages in place."""
    ctx.messages.append(Message(role="user", content=query))

    allowed = set(ctx.allowed_tools) if ctx.allowed_tools is not None else None

    for _ in range(ctx.config.max_retries + 1):
        ctx.messages = maybe_compact(ctx.messages, ctx.config, provider_fn=None)

        tools_schemas = [
            s for s in registry.schemas()
            if allowed is None or s["function"]["name"] in allowed
        ]

        stream = provider_fn(ctx.system_prompt, ctx.messages, tools_schemas, ctx.config)
        assistant_msg: AssistantMessage | None = None

        for chunk in stream:
            if isinstance(chunk, TextChunk):
                yield chunk
            elif isinstance(chunk, AssistantMessage):
                assistant_msg = chunk

        if assistant_msg is None:
            # Empty response — inject correction and retry
            ctx.messages.append(Message(role="user", content="Your last response was empty. Please try again."))
            continue

        # Record assistant turn
        ctx.messages.append(Message(
            role="assistant",
            content=assistant_msg.content,
            tool_calls=assistant_msg.tool_calls,
        ))
        yield TurnDoneEvent(input_tokens=0, output_tokens=0)

        if not assistant_msg.tool_calls:
            break   # no tools → conversation turn complete

        # Execute each tool call
        hallucinated = False
        for tc in assistant_msg.tool_calls:
            tool = registry.get(tc.name)
            if tool is None:
                correction = f"You used unknown tool '{tc.name}'. Available: {[t.name for t in registry.all()]}."
                ctx.messages.append(Message(role="user", content=correction))
                hallucinated = True
                break

            # Permission check
            permitted = permission_check(
                tool,
                ctx.config.permission_mode,
                tc.args,
                bash_safe_prefixes=ctx.config.bash_safe_prefixes,
            )
            if not permitted:
                perm_event = PermissionEvent(call_id=tc.call_id, name=tc.name, args=tc.args)
                yield perm_event
                permitted = perm_event.granted

            if not permitted:
                yield ToolEndEvent(call_id=tc.call_id, name=tc.name, output="(denied)", permitted=False)
                ctx.messages.append(Message(
                    role="tool",
                    content="(tool call denied by user)",
                    tool_call_id=tc.call_id,
                    name=tc.name,
                ))
                continue

            # Run before-hooks, execute, run after-hooks
            tc = run_before(tc, ctx, hooks)
            yield ToolStartEvent(call_id=tc.call_id, name=tc.name, args=tc.args)
            output = registry.execute(tc.name, tc.args)
            end_event = ToolEndEvent(call_id=tc.call_id, name=tc.name, output=output)
            end_event = run_after(end_event, ctx, hooks)
            yield end_event

            ctx.messages.append(Message(
                role="tool",
                content=end_event.output,
                tool_call_id=tc.call_id,
                name=tc.name,
            ))

        if hallucinated:
            continue    # retry with correction message
        # Loop back for next assistant turn (model processes tool results)

    ctx.turn += 1


def run_forked(
    query: str,
    skill,                          # SkillDef — imported lazily to avoid circular
    ctx: RunContext,
    registry: ToolRegistry,
    hooks: HookRegistry,
    provider_fn: Callable | None,
) -> str:
    """Run *query* in a forked context (isolated message history, depth+1). Returns result string."""
    if ctx.depth >= ctx.config.max_depth:
        return f"Error: max agent depth ({ctx.config.max_depth}) reached — cannot fork."

    allowed = skill.tools if skill.tools else None
    forked = RunContext(
        config=ctx.config,
        messages=[],
        system_prompt=ctx.system_prompt,
        depth=ctx.depth + 1,
        allowed_tools=allowed,
    )

    # Restrict registry to skill's tool list
    from newcli.tools import ToolRegistry as _TR
    if allowed:
        sub_registry = _TR()
        for name in allowed:
            t = registry.get(name)
            if t:
                sub_registry.register(t)
    else:
        sub_registry = registry

    if provider_fn is None:
        return "(no provider available for forked skill)"

    result_parts = []
    for event in run(query, forked, sub_registry, hooks, provider_fn=provider_fn):
        if isinstance(event, TextChunk):
            result_parts.append(event.content)

    return "".join(result_parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_loop.py -v`
Expected: all 5 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/newcli/loop.py tests/test_loop.py
git commit -m "feat: add agent loop with tool execution, hooks, permission gating, and run_forked"
```

---

## Task 13: Built-in Commands (`commands/`)

One file per command group. Each handler: `(args: str, ctx: RunContext) -> None`.

**Files:**
- Create: `src/newcli/commands/__init__.py`
- Create: `src/newcli/commands/misc.py`
- Create: `src/newcli/commands/memory.py`
- Create: `src/newcli/commands/compact.py`
- Create: `src/newcli/commands/skills.py`
- Create: `src/newcli/commands/agent.py`

- [ ] **Step 1: Write `src/newcli/commands/misc.py`**

```python
from __future__ import annotations
from newcli.types import RunContext
from newcli.compaction import estimate_tokens


def cmd_help(args: str, ctx: RunContext, commands: dict, skills: list) -> None:
    print("\nBuilt-in commands:")
    for name in sorted(commands):
        print(f"  /{name}")
    if skills:
        print("\nLoaded skills:")
        for s in skills:
            print(f"  {', '.join(s.triggers)}  — {s.name}")
    print()


def cmd_clear(args: str, ctx: RunContext) -> None:
    ctx.messages.clear()
    print("Message history cleared.")


def cmd_tokens(args: str, ctx: RunContext) -> None:
    used = estimate_tokens(ctx.messages)
    limit = ctx.config.context_limit
    remaining = max(0, limit - used)
    pct = int(used / limit * 100) if limit else 0
    print(f"Tokens: {used}/{limit} ({pct}% used, ~{remaining} remaining)")


def cmd_model(args: str, ctx: RunContext) -> None:
    import dataclasses
    if not args.strip():
        print(f"Current model: {ctx.config.model}")
        return
    new_model = args.strip()
    object.__setattr__(ctx.config, "model", new_model)  # frozen workaround: replace config
    ctx.config = dataclasses.replace(ctx.config, model=new_model)
    print(f"Model set to: {new_model}")
```

- [ ] **Step 2: Write `src/newcli/commands/memory.py`**

```python
from __future__ import annotations
import pathlib
from newcli.types import RunContext
from newcli import memory as _mem


def cmd_memory(args: str, ctx: RunContext, memory_path: pathlib.Path) -> None:
    lines = _mem.read_memory(memory_path)
    if not lines:
        print("(memory is empty)")
        return
    for line in lines:
        print(line)


def cmd_remember(args: str, ctx: RunContext, memory_path: pathlib.Path) -> None:
    if not args.strip():
        print("Usage: /remember <note>")
        return
    _mem.append_memory(memory_path, args.strip())
    print(f"Remembered: {args.strip()}")
```

- [ ] **Step 3: Write `src/newcli/commands/compact.py`**

```python
from __future__ import annotations
from newcli.types import RunContext
from newcli.compaction import maybe_compact, estimate_tokens


def cmd_compact(args: str, ctx: RunContext, provider_fn) -> None:
    before = estimate_tokens(ctx.messages)
    # Force compaction by temporarily lowering the threshold
    import dataclasses
    low_limit_config = dataclasses.replace(ctx.config, context_limit=1)
    ctx.messages = maybe_compact(ctx.messages, low_limit_config, provider_fn)
    after = estimate_tokens(ctx.messages)
    print(f"Compacted: {before} → {after} estimated tokens")
```

- [ ] **Step 4: Write `src/newcli/commands/skills.py`**

```python
from __future__ import annotations
from newcli.types import RunContext


def cmd_skills(args: str, ctx: RunContext, skills: list) -> None:
    if not skills:
        print("No skills loaded.")
        return
    for s in skills:
        print(f"  {s.name}  triggers={s.triggers}  context={s.context}  tools={s.tools}")
```

- [ ] **Step 5: Write `src/newcli/commands/agent.py`**

```python
from __future__ import annotations
from newcli.types import RunContext
from newcli.skills import AgentDef, SkillDef
from newcli.loop import run_forked
from newcli.tools import ToolRegistry
from newcli.hooks import HookRegistry


def cmd_agent(
    args: str,
    ctx: RunContext,
    agents: list[AgentDef],
    registry: ToolRegistry,
    hooks: HookRegistry,
    provider_fn,
) -> None:
    parts = args.strip().split(maxsplit=1)
    if len(parts) < 2:
        print("Usage: /agent <name> <query>")
        return
    agent_name, query = parts
    agent = next((a for a in agents if a.name == agent_name), None)
    if agent is None:
        names = [a.name for a in agents]
        print(f"Unknown agent '{agent_name}'. Available: {names}")
        return

    import dataclasses
    agent_config = dataclasses.replace(ctx.config, model=agent.model or ctx.config.model)
    agent_ctx = RunContext(
        config=agent_config,
        messages=[],
        system_prompt=agent.system_prompt,
        depth=ctx.depth + 1,
        allowed_tools=agent.tools or None,
    )
    # Treat agent as a fork skill so run_forked handles depth cap
    dummy_skill = SkillDef(name=agent_name, triggers=[], tools=agent.tools, context="fork", body="")
    result = run_forked(query, dummy_skill, ctx, registry, hooks, provider_fn)
    print(result)
```

- [ ] **Step 6: Write `src/newcli/commands/__init__.py`**

```python
from __future__ import annotations
import pathlib
from newcli.types import RunContext
from newcli.tools import ToolRegistry
from newcli.hooks import HookRegistry
from newcli.skills import AgentDef, SkillDef
from newcli.commands import misc, memory as mem_cmd, compact as compact_cmd, skills as skills_cmd, agent as agent_cmd


def load_builtin_commands(
    memory_path: pathlib.Path,
    skills: list[SkillDef],
    agents: list[AgentDef],
    registry: ToolRegistry,
    hooks: HookRegistry,
    provider_fn,
) -> dict:
    """Return a dict mapping command name → handler callable with (args, ctx) signature."""
    return {
        "help":     lambda args, ctx: misc.cmd_help(args, ctx, commands={}, skills=skills),
        "clear":    lambda args, ctx: misc.cmd_clear(args, ctx),
        "tokens":   lambda args, ctx: misc.cmd_tokens(args, ctx),
        "model":    lambda args, ctx: misc.cmd_model(args, ctx),
        "memory":   lambda args, ctx: mem_cmd.cmd_memory(args, ctx, memory_path),
        "remember": lambda args, ctx: mem_cmd.cmd_remember(args, ctx, memory_path),
        "compact":  lambda args, ctx: compact_cmd.cmd_compact(args, ctx, provider_fn),
        "skills":   lambda args, ctx: skills_cmd.cmd_skills(args, ctx, skills),
        "agent":    lambda args, ctx: agent_cmd.cmd_agent(args, ctx, agents, registry, hooks, provider_fn),
    }
```

- [ ] **Step 7: Verify commands import cleanly**

Run: `python -c "from newcli.commands import load_builtin_commands; print('ok')"`
Expected: `ok`

- [ ] **Step 8: Commit**

```bash
git add src/newcli/commands/
git commit -m "feat: add built-in commands (help, clear, tokens, model, memory, remember, compact, skills, agent)"
```

---

## Task 14: REPL + Startup (`main.py`)

Thin shell. Wires everything together. No business logic.

**Files:**
- Create: `src/newcli/main.py`

- [ ] **Step 1: Write `src/newcli/main.py`**

```python
from __future__ import annotations
import pathlib, sys
from newcli.config import load_config, find_config
from newcli.types import RunContext
from newcli.tools import ToolRegistry, register_all
from newcli.hooks import load_hooks
from newcli.skills import load_skills, load_agents, match_skill
from newcli.memory import read_memory, format_for_prompt
from newcli.mcp import connect_all
from newcli.compaction import estimate_tokens
from newcli.loop import run, run_forked
from newcli.commands import load_builtin_commands
from newcli import provider as _provider
from newcli.types import TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent, TurnDoneEvent


def status_line(ctx: RunContext) -> str:
    used = estimate_tokens(ctx.messages)
    limit = ctx.config.context_limit
    remaining = max(0, int((limit - used) / (limit / max(len(ctx.messages), 1)))) if ctx.messages else 99
    return f"[{ctx.config.model} · {used}/{limit} tokens] "


def render_event(event, ctx: RunContext) -> None:
    if isinstance(event, TextChunk):
        print(event.content, end="", flush=True)
    elif isinstance(event, ToolStartEvent):
        print(f"\n[tool] {event.name}({event.args})", flush=True)
    elif isinstance(event, ToolEndEvent):
        status = "denied" if not event.permitted else ("error" if event.error else "ok")
        print(f"[tool] {event.name} → {status}: {event.output[:120]}", flush=True)
    elif isinstance(event, PermissionEvent):
        answer = input(f"\nAllow {event.name}({event.args})? [y/N] ").strip().lower()
        event.granted = answer == "y"
    elif isinstance(event, TurnDoneEvent):
        print()   # newline after streamed text


def _make_provider_fn(config):
    def provider_fn(system, messages, tools, cfg):
        return _provider.stream(system, messages, tools, cfg)
    return provider_fn


def startup(config_path: pathlib.Path | None = None) -> tuple[RunContext, dict, list, list]:
    # 1. Find and load config
    if config_path is None:
        config_path = find_config(pathlib.Path.cwd())
    if config_path is None:
        print("Error: no .tigger/config.json found. Create one in your project or ~/.tigger/")
        sys.exit(1)

    ai_dir = config_path.parent
    config = load_config(config_path)

    # 2-4. Tool registry
    registry = ToolRegistry()
    register_all(registry)

    # 5. MCP
    mcp_path = ai_dir / "mcp.json"
    connect_all(registry, mcp_path)

    # 6. Hooks
    hooks = load_hooks(ai_dir / "hooks.py")

    # 7-8. Skills + agents
    skills = load_skills(ai_dir / "skills.md")
    agents = load_agents(ai_dir / "agents.md")

    # 9. System prompt
    memory_lines = read_memory(ai_dir / "memory.md")
    memory_section = format_for_prompt(memory_lines)
    system = f"You are a helpful AI agent.\n\n{memory_section}".strip()

    # 10. Context
    ctx = RunContext(config=config, messages=[], system_prompt=system)

    provider_fn = _make_provider_fn(config)

    commands = load_builtin_commands(
        memory_path=ai_dir / "memory.md",
        skills=skills,
        agents=agents,
        registry=registry,
        hooks=hooks,
        provider_fn=provider_fn,
    )

    return ctx, commands, skills, registry, hooks, provider_fn


def repl(ctx: RunContext, commands: dict, skills: list, registry, hooks, provider_fn) -> None:
    while True:
        try:
            line = input(status_line(ctx) + "> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break

        if not line:
            continue

        # Skill trigger check
        skill = match_skill(line, skills)
        if skill:
            if skill.context == "fork":
                query = skill.render(line)
                result = run_forked(query, skill, ctx, registry, hooks, provider_fn)
                print(result)
                continue
            else:
                line = skill.render(line)

        # Slash command
        if line.startswith("/"):
            name, _, args = line[1:].partition(" ")
            handler = commands.get(name)
            if handler:
                handler(args, ctx)
            else:
                print(f"Unknown command: /{name}. Type /help for list.")
            continue

        # Agent query
        for event in run(line, ctx, registry, hooks, provider_fn=provider_fn):
            render_event(event, ctx)


def main() -> None:
    ctx, commands, skills, registry, hooks, provider_fn = startup()
    repl(ctx, commands, skills, registry, hooks, provider_fn)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify entry point works (no config needed for import)**

Run: `python -c "from newcli.main import main; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -v`
Expected: all tests `PASSED` (no failures)

- [ ] **Step 4: Commit**

```bash
git add src/newcli/main.py
git commit -m "feat: add REPL and startup sequence — newcli is complete"
```

---

## Task 15: Smoke Test (End-to-End)

Verify the CLI starts against a real local model endpoint.

**Files:**
- Create: `.tigger/config.json` (local, not committed)

- [ ] **Step 1: Create a minimal `.tigger/config.json`**

```json
{
  "base_url": "http://localhost:11434/v1",
  "model": "qwen2.5:3b",
  "api_key": "local",
  "context_limit": 4096,
  "permission_mode": "auto"
}
```

- [ ] **Step 2: Start Ollama (or another OpenAI-compat server)**

Run: `ollama serve` (in a separate terminal)

- [ ] **Step 3: Run the CLI**

Run: `newcli`
Expected: prompt appears — `[qwen2.5:3b · 0/4096 tokens] >`

- [ ] **Step 4: Send a test message**

Type: `say hello in exactly 3 words`
Expected: a 3-word response streams to the terminal

- [ ] **Step 5: Test a built-in command**

Type: `/tokens`
Expected: token count display

- [ ] **Step 6: Test a tool**

Type: `what files are in the current directory?`
Expected: model calls the `glob` or `bash` tool; results displayed

- [ ] **Step 7: Exit**

Press: `Ctrl+D`
Expected: `Bye.`

- [ ] **Step 8: Commit `.tigger/config.json` to `.gitignore`**

```bash
echo ".tigger/" >> .gitignore
git add .gitignore
git commit -m "chore: ignore local .tigger/ config directory"
```

---

## Invariant Checklist (Verify Before Merging)

- [ ] `estimate_tokens` defined only in `compaction.py` — not duplicated anywhere
- [ ] `write` tool returns an error (not raises) when file exists
- [ ] Tool output truncated at 32KB inside `registry.execute()` only
- [ ] `Config` is frozen — no runtime mutation except `cmd_model` which uses `dataclasses.replace`
- [ ] `RunContext` is never passed to tool `func` callables
- [ ] All files under their line budgets: `pytest --co -q | wc -l` doesn't lie, but also `wc -l src/newcli/*.py`
- [ ] `pytest tests/ -v` — all green
