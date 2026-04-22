# UI Overhaul, Workspace Trust, Modes & Permission Rename — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul newcli with a rich UI (Tigger brand), workspace trust gate, renamed permission modes (`ask`/`allow`/`bypass`), a new `plan` interaction mode, and three targeted bug fixes.

**Architecture:** Changes are layered — (1) type definitions, (2) new modules (`trust.py`, `ui.py`), (3) wiring into `main.py`, (4) behavioural updates to `loop.py` + `config.py` + `permissions.py`, (5) isolated bug fixes. Each layer only depends on those below it.

**Tech Stack:** Python 3.11+, `rich>=13.0`, `tiktoken>=0.7`, `openai>=1.0`, `pytest`

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `pyproject.toml` | modify | add deps, ruff/mypy config |
| `src/newcli/types.py` | modify | `TrustLevel` enum, `RunContext.trust_level`, `Config.mode`, permission default |
| `src/newcli/trust.py` | **create** | workspace trust gate logic |
| `src/newcli/ui.py` | **create** | all rich console output, spinner, prompts |
| `src/newcli/config.py` | modify | backward-compat permission rename, load `mode` field |
| `src/newcli/permissions.py` | modify | check new mode names (`ask`/`allow`/`bypass`) |
| `src/newcli/loop.py` | modify | plan mode injection, pass real `provider_fn` to compaction |
| `src/newcli/commands/misc.py` | modify | add `/mode`, `/permission` commands |
| `src/newcli/commands/__init__.py` | modify | register new commands |
| `src/newcli/main.py` | modify | trust gate, logo, argparse, use `ui.*` throughout |
| `src/newcli/compaction.py` | modify | tiktoken counting, fix `summarize_old` call signature |
| `src/newcli/provider.py` | modify | module-level client cache |
| `tests/test_types.py` | modify | assert new fields/enum |
| `tests/test_trust.py` | **create** | trust gate unit tests |
| `tests/test_ui.py` | **create** | ui helpers unit tests |
| `tests/test_config.py` | modify | backward-compat + new mode field tests |
| `tests/test_permissions.py` | modify | update mode name strings |
| `tests/test_loop.py` | modify | update mode string + add plan-mode test |
| `tests/test_compaction.py` | modify | tiktoken + `summarize_old` signature tests |
| `tests/test_provider.py` | modify | client cache tests |

---

## Task 1: Dependencies and Tooling Config

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `rich` and `tiktoken` to runtime dependencies**

Edit `pyproject.toml` — replace the `dependencies` line:
```toml
[project]
name = "newcli"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["openai>=1.0", "pyyaml>=6.0", "rich>=13.0", "tiktoken>=0.7"]

[project.optional-dependencies]
dev = ["ruff", "mypy", "pytest"]
```

- [ ] **Step 2: Add ruff and mypy config sections**

Append to `pyproject.toml`:
```toml
[tool.ruff]
line-length = 100
select = ["E", "F", "I", "UP"]
target-version = "py311"

[tool.mypy]
strict = false
ignore_missing_imports = true
```

- [ ] **Step 3: Install and verify**

```bash
pip install -e ".[dev]"
python -c "import rich; import tiktoken; print('OK')"
```
Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add rich, tiktoken deps and ruff/mypy tooling config"
```

---

## Task 2: Type System Additions

**Files:**
- Modify: `src/newcli/types.py`
- Modify: `tests/test_types.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_types.py` (after the existing imports, add `TrustLevel` to the import line):

```python
# Update existing import line to include TrustLevel:
from newcli.types import (
    Config, RunContext, Message, ToolCallRecord, ToolDef,
    TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent,
    TurnDoneEvent, AssistantMessage, TrustLevel,
)

def test_trust_level_enum():
    assert TrustLevel.SESSION == "session"
    assert TrustLevel.ALWAYS == "always"
    assert TrustLevel.READONLY == "readonly"

def test_run_context_has_trust_level():
    cfg = Config(base_url="http://x", model="m")
    ctx = RunContext(config=cfg, messages=[], system_prompt="s")
    assert ctx.trust_level == TrustLevel.SESSION

def test_config_mode_defaults_to_ask():
    cfg = Config(base_url="http://x", model="m")
    assert cfg.mode == "ask"

def test_config_permission_mode_default_is_allow():
    cfg = Config(base_url="http://x", model="m")
    assert cfg.permission_mode == "allow"
```

Also update the existing `test_config_defaults` to assert `"allow"` instead of `"auto"`:
```python
def test_config_defaults():
    cfg = Config(base_url="http://x", model="m")
    assert cfg.api_key == "local"
    assert cfg.context_limit == 8192
    assert cfg.permission_mode == "allow"   # was "auto"
    assert cfg.mode == "ask"
    assert cfg.max_depth == 4
    assert cfg.max_retries == 2
    assert cfg.bash_safe_prefixes == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_types.py -v -k "trust_level or mode_defaults or permission_mode_default"
```
Expected: FAIL — `ImportError: cannot import name 'TrustLevel'`

- [ ] **Step 3: Implement changes in types.py**

Replace `src/newcli/types.py` entirely:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class TrustLevel(str, Enum):
    SESSION = "session"
    ALWAYS = "always"
    READONLY = "readonly"


@dataclass(frozen=True)
class Config:
    base_url: str
    model: str
    api_key: str = "local"
    context_limit: int = 8192
    max_tokens: int = 2048
    temperature: float = 0.7
    permission_mode: str = "allow"   # ask | allow | bypass
    mode: str = "ask"                # ask | plan
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
    trust_level: TrustLevel = field(default_factory=lambda: TrustLevel.SESSION)


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

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_types.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/newcli/types.py tests/test_types.py
git commit -m "feat: add TrustLevel enum, Config.mode field, trust_level to RunContext"
```

---

## Task 3: Workspace Trust Logic (`trust.py`)

**Files:**
- Create: `src/newcli/trust.py`
- Create: `tests/test_trust.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_trust.py`:
```python
import json
import pathlib
import pytest
from newcli.types import TrustLevel
from newcli.trust import is_trusted, write_trusted, check_trust


def test_is_trusted_returns_false_when_file_missing(tmp_path):
    result = is_trusted(tmp_path, tmp_path / "trusted_paths.json")
    assert result is False


def test_is_trusted_exact_match(tmp_path):
    tf = tmp_path / "trusted_paths.json"
    tf.write_text(json.dumps([str(tmp_path)]))
    assert is_trusted(tmp_path, tf) is True


def test_is_trusted_parent_match(tmp_path):
    sub = tmp_path / "project" / "subdir"
    sub.mkdir(parents=True)
    tf = tmp_path / "trusted_paths.json"
    tf.write_text(json.dumps([str(tmp_path)]))
    assert is_trusted(sub, tf) is True


def test_is_trusted_sibling_not_matched(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    target = tmp_path / "project"
    target.mkdir()
    tf = tmp_path / "trusted_paths.json"
    tf.write_text(json.dumps([str(other)]))
    assert is_trusted(target, tf) is False


def test_write_trusted_creates_file(tmp_path):
    tf = tmp_path / "trusted_paths.json"
    write_trusted(tmp_path / "proj", tf)
    data = json.loads(tf.read_text())
    assert str((tmp_path / "proj").resolve()) in data


def test_write_trusted_no_duplicates(tmp_path):
    tf = tmp_path / "trusted_paths.json"
    write_trusted(tmp_path, tf)
    write_trusted(tmp_path, tf)
    data = json.loads(tf.read_text())
    assert data.count(str(tmp_path.resolve())) == 1


def test_write_trusted_appends_to_existing(tmp_path):
    tf = tmp_path / "trusted_paths.json"
    tf.write_text(json.dumps(["/existing"]))
    write_trusted(tmp_path / "new", tf)
    data = json.loads(tf.read_text())
    assert "/existing" in data
    assert str((tmp_path / "new").resolve()) in data


def test_check_trust_returns_always_when_trusted(tmp_path):
    tf = tmp_path / "trusted_paths.json"
    tf.write_text(json.dumps([str(tmp_path)]))
    result = check_trust(tmp_path, trusted_file=tf)
    assert result == TrustLevel.ALWAYS


def test_check_trust_returns_none_when_not_trusted(tmp_path):
    tf = tmp_path / "trusted_paths.json"
    result = check_trust(tmp_path / "unknown", trusted_file=tf)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_trust.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'newcli.trust'`

- [ ] **Step 3: Implement trust.py**

Create `src/newcli/trust.py`:
```python
from __future__ import annotations
import json
import pathlib
from newcli.types import TrustLevel

_DEFAULT_TRUSTED_FILE = pathlib.Path.home() / ".ai" / "trusted_paths.json"


def is_trusted(cwd: pathlib.Path, trusted_file: pathlib.Path) -> bool:
    """Return True if *cwd* or any parent is listed in *trusted_file*."""
    if not trusted_file.exists():
        return False
    trusted = json.loads(trusted_file.read_text())
    cwd = cwd.resolve()
    for t in trusted:
        try:
            cwd.relative_to(pathlib.Path(t).resolve())
            return True
        except ValueError:
            continue
    return False


def write_trusted(path: pathlib.Path, trusted_file: pathlib.Path) -> None:
    """Add *path* to *trusted_file* (no-op if already present)."""
    trusted_file.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = json.loads(trusted_file.read_text()) if trusted_file.exists() else []
    entry = str(path.resolve())
    if entry not in existing:
        existing.append(entry)
    trusted_file.write_text(json.dumps(existing))


def check_trust(
    cwd: pathlib.Path,
    trusted_file: pathlib.Path | None = None,
) -> TrustLevel | None:
    """Return TrustLevel.ALWAYS if *cwd* is already trusted, else None (prompt required)."""
    if trusted_file is None:
        trusted_file = _DEFAULT_TRUSTED_FILE
    if is_trusted(cwd, trusted_file):
        return TrustLevel.ALWAYS
    return None
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_trust.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/newcli/trust.py tests/test_trust.py
git commit -m "feat: add workspace trust gate (trust.py)"
```

---

## Task 4: Permission Rename (`config.py` + `permissions.py`)

**Files:**
- Modify: `src/newcli/config.py`
- Modify: `src/newcli/permissions.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_permissions.py`
- Modify: `tests/test_loop.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_config.py` (also needs `import warnings` at the top):
```python
import warnings

def test_old_permission_names_map_to_new():
    mapping = {"manual": "ask", "auto": "allow", "accept-all": "bypass"}
    for old, new in mapping.items():
        p = _write({"base_url": "http://x", "model": "m", "permission_mode": old})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(p)
        assert cfg.permission_mode == new, f"{old} should map to {new}"
        assert any("deprecated" in str(x.message).lower() for x in w)

def test_new_permission_names_accepted():
    for name in ("ask", "allow", "bypass"):
        p = _write({"base_url": "http://x", "model": "m", "permission_mode": name})
        cfg = load_config(p)
        assert cfg.permission_mode == name

def test_config_loads_mode_field():
    p = _write({"base_url": "http://x", "model": "m", "mode": "plan"})
    cfg = load_config(p)
    assert cfg.mode == "plan"

def test_config_mode_defaults_to_ask():
    p = _write({"base_url": "http://x", "model": "m"})
    cfg = load_config(p)
    assert cfg.mode == "ask"

def test_invalid_mode_raises():
    p = _write({"base_url": "http://x", "model": "m", "mode": "yolo"})
    with pytest.raises(ValueError, match="mode"):
        load_config(p)
```

Update `test_load_overrides_defaults` to use `"bypass"` instead of `"accept-all"`:
```python
def test_load_overrides_defaults():
    p = _write({"base_url": "http://x", "model": "m",
                "permission_mode": "bypass", "max_depth": 2})
    cfg = load_config(p)
    assert cfg.permission_mode == "bypass"
    assert cfg.max_depth == 2
```

Replace all tests in `tests/test_permissions.py` with updated mode names:
```python
from newcli.types import ToolDef
from newcli.permissions import check


def _tool(name="bash", read_only=False, safe=False):
    return ToolDef(name=name, description="", parameters={},
                   func=lambda a: "", read_only=read_only, safe=safe)


def test_read_only_always_permitted():
    t = _tool(read_only=True)
    for mode in ("allow", "ask", "bypass"):
        assert check(t, mode, {}, bash_safe_prefixes=[]) is True


def test_bypass_permits_everything():
    t = _tool()
    assert check(t, "bypass", {}, bash_safe_prefixes=[]) is True


def test_safe_tool_allow_permitted():
    t = _tool(safe=True)
    assert check(t, "allow", {}, bash_safe_prefixes=[]) is True


def test_safe_tool_ask_not_permitted():
    t = _tool(safe=True)
    assert check(t, "ask", {}, bash_safe_prefixes=[]) is False


def test_bash_safe_prefix_allow():
    t = _tool(name="bash")
    prefixes = ["git log", "ls"]
    assert check(t, "allow", {"command": "git log --oneline"}, bash_safe_prefixes=prefixes) is True
    assert check(t, "allow", {"command": "rm -rf /"}, bash_safe_prefixes=prefixes) is False


def test_unknown_tool_ask_denied():
    t = _tool(name="write")
    assert check(t, "ask", {}, bash_safe_prefixes=[]) is False


def test_unknown_tool_allow_denied():
    t = _tool(name="write")
    assert check(t, "allow", {}, bash_safe_prefixes=[]) is False
```

In `tests/test_loop.py`, update the `_ctx` helper (line 10) to use `"bypass"` instead of `"accept-all"`:
```python
def _ctx(permission_mode="bypass"):
    cfg = Config(base_url="http://x", model="m", permission_mode=permission_mode)
    return RunContext(config=cfg, messages=[], system_prompt="You are helpful.")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py tests/test_permissions.py tests/test_loop.py -v
```
Expected: several FAIL — new mode name assertions, backward-compat mapping

- [ ] **Step 3: Update config.py**

Replace `src/newcli/config.py` entirely:
```python
from __future__ import annotations
import json
import pathlib
import warnings
from newcli.types import Config

_PERM_RENAME: dict[str, str] = {"manual": "ask", "auto": "allow", "accept-all": "bypass"}
_VALID_PERMISSION_MODES = {"ask", "allow", "bypass"}
_VALID_MODES = {"ask", "plan"}


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

    perm = data.get("permission_mode", "allow")
    if perm in _PERM_RENAME:
        new_perm = _PERM_RENAME[perm]
        warnings.warn(
            f"permission_mode {perm!r} is deprecated; use {new_perm!r} instead",
            DeprecationWarning,
            stacklevel=2,
        )
        perm = new_perm
    if perm not in _VALID_PERMISSION_MODES:
        raise ValueError(
            f"permission_mode must be one of {_VALID_PERMISSION_MODES}, got {perm!r}"
        )

    mode = data.get("mode", "ask")
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {_VALID_MODES}, got {mode!r}")

    return Config(
        base_url=data["base_url"],
        model=data["model"],
        api_key=data.get("api_key", "local"),
        context_limit=data.get("context_limit", 8192),
        max_tokens=data.get("max_tokens", 2048),
        temperature=data.get("temperature", 0.7),
        permission_mode=perm,
        mode=mode,
        max_depth=data.get("max_depth", 4),
        max_retries=data.get("max_retries", 2),
        bash_safe_prefixes=data.get("bash_safe_prefixes", []),
        prefer_text_tools=data.get("prefer_text_tools", False),
    )


def find_config(start: pathlib.Path) -> pathlib.Path | None:
    """Walk up from *start* looking for .ai/config.json, fallback to ~/.ai/."""
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

- [ ] **Step 4: Update permissions.py**

Replace `src/newcli/permissions.py` entirely:
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
    if mode == "bypass":
        return True
    if mode == "allow":
        if tool.safe:
            return True
        if tool.name == "bash":
            cmd = args.get("command", "")
            return any(cmd.startswith(p) for p in bash_safe_prefixes)
        return False
    return False    # ask: caller must prompt the user
```

- [ ] **Step 5: Run all tests**

```bash
pytest tests/test_config.py tests/test_permissions.py tests/test_types.py tests/test_loop.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/newcli/config.py src/newcli/permissions.py \
        tests/test_config.py tests/test_permissions.py tests/test_loop.py
git commit -m "feat: rename permission modes (manual→ask, auto→allow, accept-all→bypass) with backward compat"
```

---

## Task 5: Rich UI Module (`ui.py`)

**Files:**
- Create: `src/newcli/ui.py`
- Create: `tests/test_ui.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ui.py`:
```python
from io import StringIO
from rich.console import Console
from newcli.ui import SPINNER_MESSAGES, print_status, ask_permission


def test_spinner_messages_non_empty():
    assert len(SPINNER_MESSAGES) >= 6
    assert all(isinstance(m, str) for m in SPINNER_MESSAGES)


def test_print_status_contains_model_and_tokens(monkeypatch):
    import newcli.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    print_status(model="qwen3", used=100, limit=8192, mode="ask", permission="allow")
    out = buf.getvalue()
    assert "qwen3" in out
    assert "100" in out
    assert "8192" in out


def test_ask_permission_returns_true_on_y(monkeypatch):
    import newcli.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert ask_permission("bash", {"command": "ls"}) is True


def test_ask_permission_returns_false_on_n(monkeypatch):
    import newcli.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert ask_permission("bash", {"command": "rm -rf /"}) is False


def test_ask_permission_returns_false_on_empty(monkeypatch):
    import newcli.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert ask_permission("write", {}) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_ui.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'newcli.ui'`

- [ ] **Step 3: Implement ui.py**

Create `src/newcli/ui.py`:
```python
from __future__ import annotations
import pathlib
from contextlib import contextmanager
from rich.console import Console

console = Console()

SPINNER_MESSAGES = [
    "Bouncing through the codebase...",
    "Consulting the whiskers...",
    "Chasing the laser pointer of insight...",
    "T-I-double-guh-er thinking...",
    "Sniffing out an answer...",
    "Padding softly through your files...",
    "I'm Feeling Lucky",
    'Shipping awesomeness... ',
    'Painting the serifs back on...',
    'Navigating the slime mold...',
    'Consulting the digital spirits...',
    'Reticulating splines...',
    'Warming up the AI hamsters...',
    'Asking the magic conch shell...',
    'Generating witty retort...',
    'Polishing the algorithms...',
    "Don't rush perfection (or my code)...",
    'Brewing fresh bytes...',
    'Counting electrons...',
    'Engaging cognitive processors...',
    'Checking for syntax errors in the universe...',
    'One moment, optimizing humor...',
    'Shuffling punchlines...',
    'Untangling neural nets...',
    'Compiling brilliance...',
    'Loading wit.exe...',
    'Summoning the cloud of wisdom...',
    'Preparing a witty response...',
    "Just a sec, I'm debugging reality...",
    'Confuzzling the options...',
    'Tuning the cosmic frequencies...',
    'Crafting a response worthy of your patience...',
    'Compiling the 1s and 0s...',
    'Resolving dependencies... and existential crises...',
    'Defragmenting memories... both RAM and personal...',
    'Rebooting the humor module...',
    'Caching the essentials (mostly cat memes)...',
    'Optimizing for ludicrous speed',
    "Swapping bits... don't tell the bytes...",
    'Garbage collecting... be right back...',
    'Assembling the interwebs...',
    'Converting coffee into code...',
    'Updating the syntax for reality...',
    'Rewiring the synapses...',
    'Looking for a misplaced semicolon...',
    "Greasin' the cogs of the machine...",
    'Pre-heating the servers...',
    'Calibrating the flux capacitor...',
    'Engaging the improbability drive...',
    'Channeling the Force...',
    'Aligning the stars for optimal response...',
    'So say we all...',
    'Loading the next great idea...',
    "Just a moment, I'm in the zone...",
    'Preparing to dazzle you with brilliance...',
    "Just a tick, I'm polishing my wit...",
    "Hold tight, I'm crafting a masterpiece...",
    "Just a jiffy, I'm debugging the universe...",
    "Just a moment, I'm aligning the pixels...",
    "Just a sec, I'm optimizing the humor...",
    "Just a moment, I'm tuning the algorithms...",
    'Warp speed engaged...',
    'Mining for more Dilithium crystals...',
    "Don't panic...",
    'Following the white rabbit...',
    'The truth is in here... somewhere...',
    'Blowing on the cartridge...',
    'Loading... Do a barrel roll!',
    'Waiting for the respawn...',
    'Finishing the Kessel Run in less than 12 parsecs...',
    "The cake is not a lie, it's just still loading...",
    'Fiddling with the character creation screen...',
    "Just a moment, I'm finding the right meme...",
    "Pressing 'A' to continue...",
    'Herding digital cats...',
    'Polishing the pixels...',
    'Finding a suitable loading screen pun...',
    'Distracting you with this witty phrase...',
    'Almost there... probably...',
    'Our hamsters are working as fast as they can...',
    'Giving Cloudy a pat on the head...',
    'Petting the cat...',
    'Rickrolling my boss...',
    'Never gonna give you up, never gonna let you down...',
    'Slapping the bass...',
    'Tasting the snozberries...',
    "I'm going the distance, I'm going for speed...",
    'Is this the real life? Is this just fantasy?...',
    "I've got a good feeling about this...",
    'Poking the bear...',
    'Doing research on the latest memes...',
    'Figuring out how to make this more witty...',
    'Hmmm... let me think...',
    'What do you call a fish with no eyes? A fsh...',
    'Why did the computer go to therapy? It had too many bytes...',
    "Why don't programmers like nature? It has too many bugs...",
    'Why do programmers prefer dark mode? Because light attracts bugs...',
    'Why did the developer go broke? Because they used up all their cache...',
    "What can you do with a broken pencil? Nothing, it's pointless...",
    'Applying percussive maintenance...',
    'Searching for the correct USB orientation...',
    'Ensuring the magic smoke stays inside the wires...',
    'Trying to exit Vim...',
    'Spinning up the hamster wheel...',
    "That's not a bug, it's an undocumented feature...",
    'Engage.',
    "I'll be back... with an answer.",
    'My other process is a TARDIS...',
    'Communing with the machine spirit...',
    'Letting the thoughts marinate...',
    'Just remembered where I put my keys...',
    'Pondering the orb...',
    "I've seen things you people wouldn't believe... like a user who reads loading messages.",
    'Initiating thoughtful gaze...',
    "What's a computer's favorite snack? Microchips.",
    "Why do Java developers wear glasses? Because they don't C#.",
    'Charging the laser... pew pew!',
    'Dividing by zero... just kidding!',
    'Looking for an adult superviso... I mean, processing.',
    'Making it go beep boop.',
    'Buffering... because even AIs need a moment.',
    'Entangling quantum particles for a faster response...',
    'Polishing the chrome... on the algorithms.',
    'Are you not entertained? (Working on it!)',
    'Summoning the code gremlins... to help, of course.',
    'Just waiting for the dial-up tone to finish...',
    'Recalibrating the humor-o-meter.',
    'My other loading screen is even funnier.',
    "Pretty sure there's a cat walking on the keyboard somewhere...",
    'Enhancing... Enhancing... Still loading.',
    "It's not a bug, it's a feature... of this loading screen.",
    'Have you tried turning it off and on again? (The loading screen, not me.)',
    'Constructing additional pylons...',
]

_LOGO = """\
[bold yellow] ████████╗██╗  ██████╗  ██████╗ ███████╗██████╗ [/bold yellow]
[bold yellow]    ██╔══╝██║ ██╔════╝ ██╔════╝ ██╔════╝██╔══██╗[/bold yellow]
[bold yellow]    ██║   ██║ ██║  ███╗██║  ███╗█████╗  ██████╔╝[/bold yellow]
[bold yellow]    ██║   ██║ ██║   ██║██║   ██║██╔══╝  ██╔══██╗[/bold yellow]
[bold yellow]    ██║   ██║ ╚██████╔╝╚██████╔╝███████╗██║  ██║[/bold yellow]
[bold yellow]    ╚═╝   ╚═╝  ╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝[/bold yellow]

      /\_/\      Tigger — AI Agent
     ( o.o )     
      > ^ <      [dim]a minimal, clean CLI[/dim]
"""


def print_logo() -> None:
    console.print(_LOGO)


def print_status(model: str, used: int, limit: int, mode: str, permission: str) -> None:
    console.print(
        f"[dim][[/dim][bold cyan]{model}[/bold cyan][dim]] "
        f"{used}/{limit} tokens · mode=[/dim][bold]{mode}[/bold]"
        f"[dim] · perm=[/dim][bold]{permission}[/bold]",
        end="",
    )


def print_tool_start(name: str, args: dict) -> None:
    console.print(f"\n[dim]▶ tool[/dim] [bold]{name}[/bold] {args}")


def print_tool_end(name: str, status: str, output: str) -> None:
    color = "red" if status == "error" else ("dim" if status == "denied" else "green")
    console.print(f"[{color}]◀ {name} → {status}:[/{color}] {output[:120]}")


def print_error(msg: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {msg}")


def print_info(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")


def print_success(msg: str) -> None:
    console.print(f"[green]{msg}[/green]")


def ask_permission(name: str, args: dict) -> bool:
    """Prompt user to allow/deny a tool call. Returns True only if user types 'y'."""
    console.print(f"\n[yellow]Allow[/yellow] [bold]{name}[/bold]({args})?", end=" ")
    answer = input("[y/N] ").strip().lower()
    return answer == "y"


def ask_trust_prompt(cwd: pathlib.Path) -> str:
    """Interactive trust prompt. Returns 'session', 'always', or 'deny'."""
    console.print(f"\n[yellow bold]Workspace trust required:[/yellow bold] {cwd}")
    console.print("  [bold][T][/bold] Trust this session")
    console.print("  [bold][A][/bold] Always trust this directory")
    console.print("  [bold][D][/bold] Deny (read-only mode)")
    while True:
        choice = input("Choice [T/A/D]: ").strip().lower()
        if choice in ("t", ""):
            return "session"
        if choice == "a":
            return "always"
        if choice == "d":
            return "deny"


@contextmanager
def Spinner():
    """Context manager that shows a Tigger-themed spinner while waiting for first response."""
    with console.status(SPINNER_MESSAGES[0], spinner="dots"):
        yield
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_ui.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/newcli/ui.py tests/test_ui.py
git commit -m "feat: add rich UI module with logo, spinner, status line, permission + trust prompts"
```

---

## Task 6: Wire Trust and UI into `main.py`

**Files:**
- Modify: `src/newcli/main.py`

`main.py` is I/O-heavy; the existing test suite covers all the modules it calls. This task wires them together. The manual verification steps below substitute for unit tests here.

- [ ] **Step 1: Run full test suite as baseline**

```bash
pytest -v
```
Expected: all PASS before touching main.py

- [ ] **Step 2: Replace main.py**

Replace `src/newcli/main.py` entirely:
```python
# src/newcli/main.py
from __future__ import annotations
import dataclasses
import pathlib
import sys
from newcli.config import load_config, find_config
from newcli.types import RunContext, TrustLevel
from newcli.tools import ToolRegistry, register_all
from newcli.hooks import load_hooks
from newcli.skills import load_skills, load_agents, match_skill
from newcli.memory import read_memory, format_for_prompt
from newcli.mcp import connect_all
from newcli.compaction import estimate_tokens
from newcli.loop import run, run_forked
from newcli.commands import load_builtin_commands
from newcli import provider as _provider
from newcli import trust as _trust
from newcli import ui
from newcli.types import TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent, TurnDoneEvent


def _prompt(ctx: RunContext) -> str:
    used = estimate_tokens(ctx.messages)
    return (
        f"[{ctx.config.model} · {used}/{ctx.config.context_limit} tokens"
        f" · {ctx.config.mode}/{ctx.config.permission_mode}] > "
    )


def render_event(event, ctx: RunContext) -> None:
    if isinstance(event, TextChunk):
        print(event.content, end="", flush=True)
    elif isinstance(event, ToolStartEvent):
        ui.print_tool_start(event.name, event.args)
    elif isinstance(event, ToolEndEvent):
        status = "denied" if not event.permitted else ("error" if event.error else "ok")
        ui.print_tool_end(event.name, status, event.output)
    elif isinstance(event, PermissionEvent):
        event.granted = ui.ask_permission(event.name, event.args)
    elif isinstance(event, TurnDoneEvent):
        print()


def _make_provider_fn(config):
    def provider_fn(system, messages, tools, cfg):
        return _provider.stream(system, messages, tools, cfg)
    return provider_fn


def startup(config_path: pathlib.Path | None = None):
    # 1. Find and load config
    if config_path is None:
        config_path = find_config(pathlib.Path.cwd())
    if config_path is None:
        ui.print_error("no .ai/config.json found. Create one in your project or ~/.ai/")
        sys.exit(1)

    ai_dir = config_path.parent
    config = load_config(config_path)

    # 2. Workspace trust check
    cwd = pathlib.Path.cwd()
    trust_level = _trust.check_trust(cwd)
    if trust_level is None:
        choice = ui.ask_trust_prompt(cwd)
        if choice == "always":
            _trust.write_trusted(cwd, pathlib.Path.home() / ".ai" / "trusted_paths.json")
            trust_level = TrustLevel.ALWAYS
        elif choice == "session":
            trust_level = TrustLevel.SESSION
        else:
            trust_level = TrustLevel.READONLY

    # 3. Logo
    ui.print_logo()

    # 4. Tool registry
    registry = ToolRegistry()
    register_all(registry)

    # 5. MCP
    connect_all(registry, ai_dir / "mcp.json")

    # 6. Hooks
    hooks = load_hooks(ai_dir / "hooks.py")

    # 7-8. Skills + agents
    skills = load_skills(ai_dir / "skills.md")
    agents = load_agents(ai_dir / "agents.md")

    # 9. System prompt + memory
    memory_lines = read_memory(ai_dir / "memory.md")
    memory_section = format_for_prompt(memory_lines)
    system = f"You are a helpful AI agent.\n\n{memory_section}".strip()

    # 10. Context
    ctx = RunContext(config=config, messages=[], system_prompt=system, trust_level=trust_level)

    # 11. Restrict tools for read-only trust level
    if trust_level == TrustLevel.READONLY:
        ctx.allowed_tools = [t.name for t in registry.all() if t.read_only]

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
            line = input(_prompt(ctx)).strip()
        except (KeyboardInterrupt, EOFError):
            ui.print_info("\nBye.")
            break

        if not line:
            continue

        skill = match_skill(line, skills)
        if skill:
            if skill.context == "fork":
                query = skill.render(line)
                result = run_forked(query, skill, ctx, registry, hooks, provider_fn)
                print(result)
                continue
            else:
                line = skill.render(line)

        if line.startswith("/"):
            name, _, args = line[1:].partition(" ")
            handler = commands.get(name)
            if handler:
                handler(args, ctx)
            else:
                ui.print_error(f"Unknown command: /{name}. Type /help for list.")
            continue

        # Spinner wraps the wait for first event; stops as soon as first event arrives
        event_gen = run(line, ctx, registry, hooks, provider_fn=provider_fn)
        with ui.Spinner():
            first_event = next(event_gen, None)
        if first_event is not None:
            render_event(first_event, ctx)
        for event in event_gen:
            render_event(event, ctx)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="newcli")
    parser.add_argument("--mode", choices=["ask", "plan"], default=None)
    parser.add_argument("--permission", choices=["ask", "allow", "bypass"], dest="permission", default=None)
    parsed = parser.parse_args()

    ctx, commands, skills, registry, hooks, provider_fn = startup()

    if parsed.mode is not None:
        ctx.config = dataclasses.replace(ctx.config, mode=parsed.mode)
    if parsed.permission is not None:
        ctx.config = dataclasses.replace(ctx.config, permission_mode=parsed.permission)

    repl(ctx, commands, skills, registry, hooks, provider_fn)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run full test suite**

```bash
pytest -v
```
Expected: all PASS

- [ ] **Step 4: Manual smoke test — trust gate**

```bash
cd /tmp && mkdir test-newcli && cd test-newcli
newcli
```
Expected: trust prompt with T/A/D; entering `T` → logo renders → REPL prompt with model/tokens/mode/perm.

- [ ] **Step 5: Manual smoke test — deny (read-only mode)**

At trust prompt, enter `D`. Then at the REPL, attempt a destructive tool call. It should be blocked (only read-only tools are in `ctx.allowed_tools`).

- [ ] **Step 6: Commit**

```bash
git add src/newcli/main.py
git commit -m "feat: wire trust gate, rich UI, spinner, and argparse into main.py"
```

---

## Task 7: Plan Mode Injection + `/mode` and `/permission` Commands

**Files:**
- Modify: `src/newcli/loop.py`
- Modify: `src/newcli/commands/misc.py`
- Modify: `src/newcli/commands/__init__.py`
- Modify: `tests/test_loop.py`

- [ ] **Step 1: Write failing tests for plan mode**

Add to `tests/test_loop.py`:
```python
def test_plan_mode_injects_into_system_prompt():
    """In plan mode, the provider receives a system prompt containing 'numbered plan'."""
    calls: list[str] = []

    def recording_provider(system, messages, tools, cfg):
        calls.append(system)
        yield TextChunk(content="1. Plan")
        yield AssistantMessage(content="1. Plan", tool_calls=[])

    cfg = Config(base_url="http://x", model="m", permission_mode="bypass", mode="plan")
    ctx = RunContext(config=cfg, messages=[], system_prompt="You are helpful.")
    list(run("do something", ctx, _registry(), _hooks(), provider_fn=recording_provider))

    assert len(calls) == 1
    assert "numbered plan" in calls[0]
    assert "You are helpful." in calls[0]


def test_ask_mode_does_not_inject_plan_text():
    calls: list[str] = []

    def recording_provider(system, messages, tools, cfg):
        calls.append(system)
        yield TextChunk(content="done")
        yield AssistantMessage(content="done", tool_calls=[])

    cfg = Config(base_url="http://x", model="m", permission_mode="bypass", mode="ask")
    ctx = RunContext(config=cfg, messages=[], system_prompt="You are helpful.")
    list(run("do something", ctx, _registry(), _hooks(), provider_fn=recording_provider))

    assert "numbered plan" not in calls[0]
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_loop.py -v -k "plan_mode"
```
Expected: FAIL — `AssertionError: "numbered plan" not in calls[0]`

- [ ] **Step 3: Add plan mode injection to loop.py**

In `src/newcli/loop.py`, inside `run()`, find the line:
```python
stream = provider_fn(ctx.system_prompt, ctx.messages, tools_schemas, ctx.config)
```
Replace it with:
```python
system = ctx.system_prompt
if ctx.config.mode == "plan":
    system += (
        "\n\nBefore taking any action, write a numbered plan of the steps "
        "you will take, then execute it."
    )
stream = provider_fn(system, ctx.messages, tools_schemas, ctx.config)
```

- [ ] **Step 4: Run loop tests**

```bash
pytest tests/test_loop.py -v
```
Expected: all PASS

- [ ] **Step 5: Add `/mode` and `/permission` to misc.py**

Add to `src/newcli/commands/misc.py`:
```python
def cmd_mode(args: str, ctx: RunContext) -> None:
    valid = {"ask", "plan"}
    if not args.strip():
        print(f"Current mode: {ctx.config.mode}")
        return
    new_mode = args.strip()
    if new_mode not in valid:
        print(f"Invalid mode {new_mode!r}. Must be one of {sorted(valid)}")
        return
    ctx.config = dataclasses.replace(ctx.config, mode=new_mode)
    print(f"Mode set to: {new_mode}")


def cmd_permission(args: str, ctx: RunContext) -> None:
    valid = {"ask", "allow", "bypass"}
    if not args.strip():
        print(f"Current permission: {ctx.config.permission_mode}")
        return
    new_perm = args.strip()
    if new_perm not in valid:
        print(f"Invalid permission {new_perm!r}. Must be one of {sorted(valid)}")
        return
    ctx.config = dataclasses.replace(ctx.config, permission_mode=new_perm)
    print(f"Permission set to: {new_perm}")
```

Note: `dataclasses` is already imported at the top of `misc.py` (used by `cmd_model`).

- [ ] **Step 6: Register commands in commands/__init__.py**

In `src/newcli/commands/__init__.py`, update the dict inside `load_builtin_commands`:
```python
d.update({
    "clear":      lambda args, ctx: misc.cmd_clear(args, ctx),
    "tokens":     lambda args, ctx: misc.cmd_tokens(args, ctx),
    "model":      lambda args, ctx: misc.cmd_model(args, ctx),
    "mode":       lambda args, ctx: misc.cmd_mode(args, ctx),
    "permission": lambda args, ctx: misc.cmd_permission(args, ctx),
    "memory":     lambda args, ctx: mem_cmd.cmd_memory(args, ctx, memory_path),
    "remember":   lambda args, ctx: mem_cmd.cmd_remember(args, ctx, memory_path),
    "compact":    lambda args, ctx: compact_cmd.cmd_compact(args, ctx, provider_fn),
    "skills":     lambda args, ctx: skills_cmd.cmd_skills(args, ctx, skills),
    "agent":      lambda args, ctx: agent_cmd.cmd_agent(args, ctx, agents, registry, hooks, provider_fn),
})
```

- [ ] **Step 7: Run full test suite**

```bash
pytest -v
```
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add src/newcli/loop.py src/newcli/commands/misc.py src/newcli/commands/__init__.py \
        tests/test_loop.py
git commit -m "feat: plan mode injection into system prompt, /mode and /permission commands"
```

---

## Task 8: Bug Fixes

**Files:**
- Modify: `src/newcli/compaction.py`
- Modify: `src/newcli/provider.py`
- Modify: `src/newcli/loop.py`
- Modify: `tests/test_compaction.py`
- Modify: `tests/test_provider.py`

### Bug 1: tiktoken token counting

- [ ] **Step 1: Write tiktoken tests**

Add to `tests/test_compaction.py`:
```python
def test_estimate_tokens_uses_tiktoken_when_available():
    pytest.importorskip("tiktoken")
    msgs = [_msg("user", "hello world this is a test message")]
    t = estimate_tokens(msgs)
    assert isinstance(t, int) and t > 0


def test_estimate_tokens_fallback_when_tiktoken_missing(monkeypatch):
    import builtins
    real_import = builtins.__import__
    def patched_import(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", patched_import)
    msgs = [_msg("user", "hello")]
    t = estimate_tokens(msgs)
    assert t == int(len("hello") / 3.5)
```

- [ ] **Step 2: Verify current behaviour**

```bash
pytest tests/test_compaction.py::test_estimate_tokens_uses_tiktoken_when_available -v
```
Expected: FAIL — current impl uses `chars / 3.5`, not tiktoken

- [ ] **Step 3: Update estimate_tokens in compaction.py**

Replace the existing `estimate_tokens` function:
```python
def estimate_tokens(messages: list[Message]) -> int:
    """Token count via tiktoken (cl100k_base) if available, else chars/3.5."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return sum(len(enc.encode(m.content)) for m in messages)
    except ImportError:
        total = sum(len(m.content) for m in messages)
        return int(total / 3.5)
```

- [ ] **Step 4: Run compaction tests**

```bash
pytest tests/test_compaction.py -v
```
Expected: all PASS

### Bug 2: Cache OpenAI client

- [ ] **Step 5: Write client cache tests**

Add to `tests/test_provider.py`:
```python
def test_get_client_returns_same_instance_for_same_key():
    from newcli.provider import _get_client
    c1 = _get_client("http://localhost", "key1")
    c2 = _get_client("http://localhost", "key1")
    assert c1 is c2


def test_get_client_different_keys_different_instances():
    from newcli.provider import _get_client
    c1 = _get_client("http://localhost", "key1")
    c2 = _get_client("http://localhost", "key2")
    assert c1 is not c2
```

- [ ] **Step 6: Verify failure**

```bash
pytest tests/test_provider.py -v -k "get_client"
```
Expected: FAIL — `ImportError: cannot import name '_get_client'`

- [ ] **Step 7: Add client cache to provider.py**

Add after the imports in `src/newcli/provider.py`:
```python
_client_cache: dict[tuple[str, str], OpenAI] = {}


def _get_client(base_url: str, api_key: str) -> OpenAI:
    key = (base_url, api_key)
    if key not in _client_cache:
        _client_cache[key] = OpenAI(base_url=base_url, api_key=api_key)
    return _client_cache[key]
```

In `stream()`, replace:
```python
client = OpenAI(base_url=config.base_url, api_key=config.api_key)
```
with:
```python
client = _get_client(config.base_url, config.api_key)
```

- [ ] **Step 8: Run provider tests**

```bash
pytest tests/test_provider.py -v
```
Expected: all PASS

### Bug 3: Fix dead layer-2 compaction

The bug: `summarize_old` calls `provider_fn(summary_prompt)` (one string arg), but the real `provider_fn` signature is `(system, messages, tools, config)` — a generator returning `TextChunk | AssistantMessage`. Also, `loop.py` hard-codes `provider_fn=None`, preventing layer-2 from ever running.

- [ ] **Step 9: Write failing test for summarize_old**

Add to `tests/test_compaction.py`:
```python
def test_summarize_old_calls_provider_with_correct_signature():
    from newcli.compaction import summarize_old
    call_args: list = []

    def fake_provider(system, messages, tools, cfg):
        call_args.extend([system, messages, tools, cfg])
        from newcli.types import TextChunk
        yield TextChunk(content="summary text")

    cfg = _cfg()
    msgs = [_msg("user", f"msg{i}") for i in range(8)]
    result = summarize_old(msgs, cfg, fake_provider)

    assert len(call_args) == 4           # system, messages, tools, cfg
    assert isinstance(call_args[0], str)
    assert isinstance(call_args[1], list)
    assert call_args[2] == []            # no tools passed
    assert result[0].content.startswith("[Conversation summary]")
    assert "summary text" in result[0].content
```

- [ ] **Step 10: Verify failure**

```bash
pytest tests/test_compaction.py::test_summarize_old_calls_provider_with_correct_signature -v
```
Expected: FAIL — `TypeError: fake_provider() takes 4 positional arguments but 1 was given`

- [ ] **Step 11: Fix summarize_old in compaction.py**

Replace the `summarize_old` function:
```python
def summarize_old(
    messages: list[Message],
    config: Config,
    provider_fn: Callable,
) -> list[Message]:
    """Layer 2: LLM-summarize old portion of history (real API call)."""
    if not messages or provider_fn is None:
        return messages
    boundary = max(1, len(messages) * 3 // 4)
    old, recent = messages[:boundary], messages[boundary:]
    prompt = (
        "Summarize the following conversation history concisely. "
        "Preserve key facts, decisions, and file paths mentioned.\n\n"
        + "\n".join(f"{m.role}: {m.content[:500]}" for m in old)
    )
    parts: list[str] = []
    for chunk in provider_fn(
        "You are a concise summarizer.",
        [Message(role="user", content=prompt)],
        [],
        config,
    ):
        if isinstance(chunk, TextChunk):
            parts.append(chunk.content)
    summary = "".join(parts)
    return [Message(role="user", content=f"[Conversation summary]\n{summary}")] + recent
```

Note: `TextChunk` must be imported at the top of `compaction.py`. Add it to the existing import:
```python
from newcli.types import Message, Config, TextChunk
```

- [ ] **Step 12: Fix loop.py — pass real provider_fn to maybe_compact**

In `src/newcli/loop.py`, inside `run()`, change:
```python
ctx.messages = maybe_compact(ctx.messages, ctx.config, provider_fn=None)
```
to:
```python
ctx.messages = maybe_compact(ctx.messages, ctx.config, provider_fn)
```

- [ ] **Step 13: Run full test suite**

```bash
pytest -v
```
Expected: all PASS, no regressions

- [ ] **Step 14: Commit**

```bash
git add src/newcli/compaction.py src/newcli/provider.py src/newcli/loop.py \
        tests/test_compaction.py tests/test_provider.py
git commit -m "fix: tiktoken token counting, cache OpenAI client, fix summarize_old provider signature"
```

---

## Final Verification

```bash
# 1. All tests pass
pytest -v

# 2. Ruff clean (after Phase 1 deps are installed)
ruff check src/

# 3. Manual: argparse flags reach ctx.config
newcli --mode plan --permission bypass
# At REPL prompt: type /mode  → should print "Current mode: plan"
# Type /permission            → should print "Current permission: bypass"

# 4. Manual: /mode plan → numbered plan output
# At REPL: /mode plan
# Then ask: "list all .py files and count them"
# Expected: agent prints numbered plan before executing tools

# 5. Manual: trust gate D (read-only) blocks write tools
# Cold-start in untrusted dir, enter D
# Try: "write hello to /tmp/test.txt"
# Expected: tool call denied or not offered
```
