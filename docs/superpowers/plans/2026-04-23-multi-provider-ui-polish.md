# Multi-Provider Support & UI Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-provider config with runtime model switching, first-run setup wizard, `/provider add` command, and UI polish (info box, context %, friendly times, spinner tokens, amber theme).

**Architecture:** Layered bottom-up: (1) new types, (2) config loading/writing, (3) code simplification extractions, (4) UI polish utilities, (5) commands, (6) setup wizard, (7) wiring. Each layer only depends on those below it. The existing `Config.base_url`/`model`/`api_key` fields are preserved so all downstream code works unchanged — they are computed from the active provider at construction time.

**Tech Stack:** Python 3.11+, `rich>=13.0`, `prompt_toolkit>=3.0`, `openai>=1.0`, `pytest`

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `src/newcli/types.py` | modify | Add `ProviderConfig`, add `providers`/`active_provider`/`active_model` to `Config` |
| `src/newcli/config.py` | modify | `derive_provider_name()`, `switch_model()`, backward-compat loading, new-format loading, `write_config()` |
| `src/newcli/_spinners.py` | **create** | `SPINNER_MESSAGES` list (extracted from `ui.py`) |
| `src/newcli/ui.py` | modify | Extract spinners, add `format_duration()`, `print_startup_info()`, `render_event()`, amber theme, spinner token counter |
| `src/newcli/main.py` | modify | Remove extracted rendering functions, wire info box, update toolbar to context %, pass token counter |
| `src/newcli/commands/misc.py` | modify | Replace `cmd_model` with interactive picker |
| `src/newcli/commands/provider.py` | **create** | `cmd_provider` with `add` subcommand |
| `src/newcli/commands/__init__.py` | modify | Register `/provider`, pass `config_path` through |
| `tests/test_types.py` | modify | Tests for `ProviderConfig`, new `Config` fields |
| `tests/test_config.py` | modify | Tests for `derive_provider_name`, `switch_model`, backward compat, new format, `write_config` |
| `tests/test_ui.py` | modify | Tests for `format_duration`, `print_startup_info`, `render_event` |
| `tests/test_model_cmd.py` | **create** | Tests for the new `/model` command |
| `tests/test_provider_cmd.py` | **create** | Tests for `/provider add` |

---

## Task 1: ProviderConfig Dataclass and Config Changes

**Files:**
- Modify: `src/newcli/types.py`
- Modify: `tests/test_types.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_types.py` (add `ProviderConfig` to the import line):

```python
from newcli.types import (
    Config, RunContext, Message, ToolCallRecord, ToolDef,
    TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent,
    TurnDoneEvent, AssistantMessage, TrustLevel, ProviderConfig,
)


def test_provider_config_fields():
    pc = ProviderConfig(name="local", base_url="http://localhost:1234/v1",
                        api_key="local", models=["qwen3"])
    assert pc.name == "local"
    assert pc.base_url == "http://localhost:1234/v1"
    assert pc.api_key == "local"
    assert pc.models == ["qwen3"]


def test_provider_config_is_frozen():
    pc = ProviderConfig(name="x", base_url="http://x", api_key="k", models=["m"])
    import pytest
    with pytest.raises(AttributeError):
        pc.name = "y"


def test_config_has_providers_field():
    pc = ProviderConfig(name="loc", base_url="http://x/v1", api_key="local", models=["m"])
    cfg = Config(base_url="http://x/v1", model="m", providers={"loc": pc},
                 active_provider="loc", active_model="m")
    assert cfg.providers["loc"].base_url == "http://x/v1"
    assert cfg.active_provider == "loc"
    assert cfg.active_model == "m"


def test_config_providers_default_empty():
    cfg = Config(base_url="http://x", model="m")
    assert cfg.providers == {}
    assert cfg.active_provider == ""
    assert cfg.active_model == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_types.py -v -k "provider_config or providers_field or providers_default"`
Expected: FAIL — `ImportError: cannot import name 'ProviderConfig'`

- [ ] **Step 3: Implement changes in types.py**

Add `ProviderConfig` dataclass after the `TrustLevel` enum and before `Config`:

```python
@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    models: list[str] = field(default_factory=list)
```

Add three new fields to `Config` (after `api_key`, before `context_limit`):

```python
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    active_provider: str = ""
    active_model: str = ""
```

The field ordering matters for positional construction — `providers` and `active_*` have defaults so they go after `api_key` (which also has a default). All existing positional construction patterns (`Config(base_url="...", model="...")`) continue to work.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_types.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/newcli/types.py tests/test_types.py
git commit -m "feat: add ProviderConfig dataclass and multi-provider fields to Config"
```

---

## Task 2: Config Loading, Backward Compat, switch_model, write_config

**Files:**
- Modify: `src/newcli/config.py`
- Modify: `tests/test_config.py`

This task adds four things to `config.py`:
1. `derive_provider_name(base_url)` — hostname extraction utility
2. `switch_model(config, provider, model)` — returns new Config with active provider/model switched
3. Updated `load_config` — handles both old flat format and new providers format
4. `write_config(path, config)` — serializes Config to JSON in the new providers format

- [ ] **Step 1: Write failing tests**

Add these imports at the top of `tests/test_config.py`:

```python
from newcli.types import ProviderConfig
from newcli.config import derive_provider_name, switch_model, write_config
```

Add these test functions:

```python
# --- derive_provider_name ---

def test_derive_provider_name_ip():
    assert derive_provider_name("http://192.168.2.122:1234/v1") == "192.168.2.122"


def test_derive_provider_name_openai():
    assert derive_provider_name("https://api.openai.com/v1") == "openai"


def test_derive_provider_name_localhost():
    assert derive_provider_name("http://localhost:1234/v1") == "localhost"


def test_derive_provider_name_custom_domain():
    assert derive_provider_name("https://my-llm.example.org/v1") == "my-llm.example.org"


# --- switch_model ---

def test_switch_model_changes_active():
    pc1 = ProviderConfig(name="a", base_url="http://a/v1", api_key="ka", models=["m1"])
    pc2 = ProviderConfig(name="b", base_url="http://b/v1", api_key="kb", models=["m2", "m3"])
    cfg = Config(base_url="http://a/v1", model="m1", api_key="ka",
                 providers={"a": pc1, "b": pc2}, active_provider="a", active_model="m1")
    new = switch_model(cfg, "b", "m3")
    assert new.active_provider == "b"
    assert new.active_model == "m3"
    assert new.base_url == "http://b/v1"
    assert new.model == "m3"
    assert new.api_key == "kb"


def test_switch_model_preserves_other_fields():
    pc = ProviderConfig(name="a", base_url="http://a/v1", api_key="k", models=["m"])
    cfg = Config(base_url="http://a/v1", model="m", api_key="k",
                 providers={"a": pc}, active_provider="a", active_model="m",
                 context_limit=64000, temperature=0.5)
    new = switch_model(cfg, "a", "m")
    assert new.context_limit == 64000
    assert new.temperature == 0.5


# --- load_config backward compat (old flat format) ---

def test_load_old_format_creates_provider():
    p = _write({"base_url": "http://192.168.2.122:1234/v1", "model": "qwen3",
                "api_key": "sk-test"})
    cfg = load_config(p)
    assert len(cfg.providers) == 1
    assert cfg.active_provider == "192.168.2.122"
    assert cfg.active_model == "qwen3"
    assert cfg.base_url == "http://192.168.2.122:1234/v1"
    assert cfg.model == "qwen3"
    assert cfg.api_key == "sk-test"
    prov = cfg.providers["192.168.2.122"]
    assert prov.models == ["qwen3"]


# --- load_config new format ---

def test_load_new_format():
    data = {
        "default_provider": "local",
        "default_model": "qwen3",
        "providers": {
            "local": {
                "base_url": "http://localhost:1234/v1",
                "api_key": "local",
                "models": ["qwen3", "llama"]
            },
            "cloud": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-cloud",
                "models": ["gpt-4o"]
            }
        }
    }
    p = _write(data)
    cfg = load_config(p)
    assert len(cfg.providers) == 2
    assert cfg.active_provider == "local"
    assert cfg.active_model == "qwen3"
    assert cfg.base_url == "http://localhost:1234/v1"
    assert cfg.api_key == "local"
    assert cfg.providers["cloud"].models == ["gpt-4o"]


def test_load_new_format_defaults_to_first_provider():
    data = {
        "providers": {
            "only": {
                "base_url": "http://x/v1",
                "api_key": "k",
                "models": ["m1"]
            }
        }
    }
    p = _write(data)
    cfg = load_config(p)
    assert cfg.active_provider == "only"
    assert cfg.active_model == "m1"


# --- write_config ---

def test_write_config_round_trips(tmp_path):
    pc = ProviderConfig(name="loc", base_url="http://x/v1", api_key="k", models=["m1", "m2"])
    cfg = Config(base_url="http://x/v1", model="m1", api_key="k",
                 providers={"loc": pc}, active_provider="loc", active_model="m1")
    out = tmp_path / "config.json"
    write_config(out, cfg)
    reloaded = load_config(out)
    assert reloaded.active_provider == "loc"
    assert reloaded.active_model == "m1"
    assert reloaded.providers["loc"].models == ["m1", "m2"]


def test_write_config_creates_parent_dirs(tmp_path):
    pc = ProviderConfig(name="x", base_url="http://x/v1", api_key="k", models=["m"])
    cfg = Config(base_url="http://x/v1", model="m", api_key="k",
                 providers={"x": pc}, active_provider="x", active_model="m")
    out = tmp_path / "sub" / "dir" / "config.json"
    write_config(out, cfg)
    assert out.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v -k "derive_provider or switch_model or old_format_creates or new_format or write_config"`
Expected: FAIL — `ImportError: cannot import name 'derive_provider_name'`

- [ ] **Step 3: Implement derive_provider_name**

Add at the top of `src/newcli/config.py` (after existing imports):

```python
import urllib.parse
from newcli.types import Config, ProviderConfig
```

Remove the existing `from newcli.types import Config` line (now combined above).

Add the function before `load_config`:

```python
def derive_provider_name(base_url: str) -> str:
    """Derive a short provider name from a base URL's hostname."""
    hostname = urllib.parse.urlparse(base_url).hostname or base_url
    # Strip common prefixes/suffixes for readability
    if hostname.startswith("api."):
        hostname = hostname[4:]
    if hostname.endswith(".com"):
        hostname = hostname[:-4]
    if hostname.endswith(".org"):
        hostname = hostname[:-4]
    return hostname
```

- [ ] **Step 4: Implement switch_model**

Add after `derive_provider_name`:

```python
def switch_model(config: Config, provider_name: str, model_name: str) -> Config:
    """Return a new Config with the active provider and model switched."""
    import dataclasses
    provider = config.providers[provider_name]
    return dataclasses.replace(
        config,
        active_provider=provider_name,
        active_model=model_name,
        base_url=provider.base_url,
        model=model_name,
        api_key=provider.api_key,
    )
```

- [ ] **Step 5: Update load_config for both formats**

Replace the body of `load_config` (keep the signature and the file-reading/permission-mode/mode validation logic). The key change is the construction of the `Config` return value. After the existing `perm` and `mode` validation blocks, replace the `return Config(...)` block:

```python
    # --- Provider loading ---
    if "providers" in data:
        # New multi-provider format
        providers = {}
        for name, prov_data in data["providers"].items():
            providers[name] = ProviderConfig(
                name=name,
                base_url=prov_data["base_url"],
                api_key=prov_data.get("api_key", "local"),
                models=prov_data.get("models", []),
            )
        if not providers:
            raise ValueError("config.json 'providers' is empty")
        active_provider = data.get("default_provider", next(iter(providers)))
        if active_provider not in providers:
            raise ValueError(f"default_provider {active_provider!r} not found in providers")
        active_model = data.get("default_model", providers[active_provider].models[0])
        active_prov = providers[active_provider]
    else:
        # Old flat format — backward compat migration
        if "base_url" not in data:
            raise ValueError("config.json missing required field: base_url")
        if "model" not in data:
            raise ValueError("config.json missing required field: model")
        prov_name = derive_provider_name(data["base_url"])
        api_key = data.get("api_key", "local")
        active_prov = ProviderConfig(
            name=prov_name,
            base_url=data["base_url"],
            api_key=api_key,
            models=[data["model"]],
        )
        providers = {prov_name: active_prov}
        active_provider = prov_name
        active_model = data["model"]

    return Config(
        base_url=active_prov.base_url,
        model=active_model,
        api_key=active_prov.api_key,
        providers=providers,
        active_provider=active_provider,
        active_model=active_model,
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
```

Move the `base_url`/`model` required field checks into the `else` (old format) branch — for the new format, those fields are inside providers and validated there.

- [ ] **Step 6: Implement write_config**

Add at the end of `config.py`:

```python
def write_config(path: pathlib.Path, config: Config) -> None:
    """Serialize *config* to JSON at *path* in the new providers format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    providers_data = {}
    for name, prov in config.providers.items():
        providers_data[name] = {
            "base_url": prov.base_url,
            "api_key": prov.api_key,
            "models": list(prov.models),
        }
    data = {
        "default_provider": config.active_provider,
        "default_model": config.active_model,
        "providers": providers_data,
        "context_limit": config.context_limit,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "permission_mode": config.permission_mode,
        "mode": config.mode,
        "max_depth": config.max_depth,
        "max_retries": config.max_retries,
        "bash_safe_prefixes": config.bash_safe_prefixes,
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
```

- [ ] **Step 7: Run all config tests**

Run: `pytest tests/test_config.py -v`
Expected: all PASS

- [ ] **Step 8: Run full test suite**

Run: `pytest -v`
Expected: all PASS (existing tests still work because `Config` still has `base_url`, `model`, `api_key` fields with the same defaults)

- [ ] **Step 9: Commit**

```bash
git add src/newcli/types.py src/newcli/config.py tests/test_types.py tests/test_config.py
git commit -m "feat: multi-provider config format with backward compat, switch_model, write_config"
```

---

## Task 3: Code Simplification — Extract Spinners and Rendering

**Files:**
- Create: `src/newcli/_spinners.py`
- Modify: `src/newcli/ui.py`
- Modify: `src/newcli/main.py`

This task moves code, not adds features. No new tests needed — existing tests must continue to pass.

- [ ] **Step 1: Create _spinners.py**

Create `src/newcli/_spinners.py` containing the `SPINNER_MESSAGES` list. Copy the entire list from `ui.py` lines 11-120:

```python
SPINNER_MESSAGES = [
    "Bouncing through the codebase...",
    "Consulting the whiskers...",
    "Chasing the laser pointer of insight...",
    "T-I-double-guh-er thinking...",
    "Sniffing out an answer...",
    "Padding softly through your files...",
    "I'm Feeling Lucky",
    'Shipping awesomeness...',
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
    'Never gonna give you up, never gonna let you down...',
    'Slapping the bass...',
    'Tasting the snozberries...',
    "I'm going the distance, I'm going for speed...",
    'Is this the real life? Is this just fantasy?...',
    "I've got a good feeling about this...",
    'Poking the bear...',
    'Hmmm... let me think...',
    'What do you call a fish with no eyes? A fsh...',
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
    'Pondering the orb...',
    'Initiating thoughtful gaze...',
    'Making it go beep boop.',
    'Buffering... because even AIs need a moment.',
    'Entangling quantum particles for a faster response...',
    'Constructing additional pylons...',
]
```

- [ ] **Step 2: Update ui.py — replace inline list with import**

In `src/newcli/ui.py`, delete the `SPINNER_MESSAGES = [...]` block (lines 11-120). Replace with:

```python
from newcli._spinners import SPINNER_MESSAGES
```

Add this import after the existing imports at the top of the file.

- [ ] **Step 3: Move render_event, _flush_text, _fmt_args from main.py to ui.py**

Cut `_fmt_args`, `_flush_text`, and `render_event` from `src/newcli/main.py` (lines 38-81). Paste them into `src/newcli/ui.py` at the end of the file.

In `ui.py`, add the necessary imports at the top (these are already available in main.py but not yet in ui.py):

```python
from rich.markdown import Markdown
from newcli.types import TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent, TurnDoneEvent
```

The `render_event` function references `ui.console` and `ui.ask_permission` — since it's now inside `ui.py`, change these to just `console` and `ask_permission`.

- [ ] **Step 4: Update main.py to call ui.render_event**

In `src/newcli/main.py`, remove the `from rich.markdown import Markdown` import (no longer needed). Replace all calls to `render_event(...)` with `ui.render_event(...)`. The calls are in the `repl()` function:

```python
        if first_event is not None:
            ui.render_event(first_event, ctx, output_chars, text_buf)
            for event in event_gen:
                ui.render_event(event, ctx, output_chars, text_buf)
```

Remove the now-deleted function's imports from main.py: `TextChunk, ToolStartEvent, ToolEndEvent, PermissionEvent, TurnDoneEvent` — unless they're used elsewhere in main.py (check: they are not, they were only used by render_event).

- [ ] **Step 5: Run full test suite**

Run: `pytest -v`
Expected: all PASS — this is a pure code move, no behavior change.

- [ ] **Step 6: Commit**

```bash
git add src/newcli/_spinners.py src/newcli/ui.py src/newcli/main.py
git commit -m "refactor: extract spinner messages to _spinners.py, move render_event to ui.py"
```

---

## Task 4: UI Polish — format_duration, Context %, Amber Theme

**Files:**
- Modify: `src/newcli/ui.py`
- Modify: `src/newcli/main.py`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write failing tests for format_duration**

Add to `tests/test_ui.py`:

```python
from newcli.ui import format_duration


def test_format_duration_short():
    assert format_duration(2.3) == "2.3s"


def test_format_duration_under_minute():
    assert format_duration(45.1) == "45.1s"


def test_format_duration_minutes():
    assert format_duration(696.2) == "11m 36s"


def test_format_duration_exact_minute():
    assert format_duration(60.0) == "1m 0s"


def test_format_duration_hour():
    assert format_duration(3720.0) == "1h 2m"


def test_format_duration_zero():
    assert format_duration(0.0) == "0.0s"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui.py -v -k "format_duration"`
Expected: FAIL — `ImportError: cannot import name 'format_duration'`

- [ ] **Step 3: Implement format_duration**

Add to `src/newcli/ui.py`:

```python
def format_duration(seconds: float) -> str:
    """Format seconds into human-friendly duration: 2.3s, 11m 36s, 1h 2m."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m = int(seconds) // 60
        s = int(seconds) % 60
        return f"{m}m {s}s"
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    return f"{h}h {m}m"
```

- [ ] **Step 4: Run format_duration tests**

Run: `pytest tests/test_ui.py -v -k "format_duration"`
Expected: all PASS

- [ ] **Step 5: Update toolbar to show context percentage**

In `src/newcli/main.py`, update the `_toolbar` function:

```python
def _toolbar(ctx: RunContext) -> str:
    used = estimate_tokens(ctx.messages)
    limit = ctx.config.context_limit
    pct = (used / limit * 100) if limit else 0
    return (
        f" {ctx.config.model}"
        f"  mode:{ctx.config.mode}"
        f"  perm:{ctx.config.permission_mode}"
        f"  {pct:.1f}% context"
    )
```

- [ ] **Step 6: Update turn summary to use format_duration**

In `src/newcli/main.py`, in the `repl()` function, find the line:

```python
        ui.print_turn_summary(output_chars[0] // 4, elapsed)
```

In `src/newcli/ui.py`, update `print_turn_summary`:

```python
def print_turn_summary(tokens: int, elapsed: float) -> None:
    console.print(f"[dim]· {tokens} tokens · {format_duration(elapsed)}[/dim]")
```

- [ ] **Step 7: Add amber/orange theme to console**

In `src/newcli/ui.py`, update the `console` construction at the top of the file. Replace:

```python
console = Console()
```

with:

```python
from rich.theme import Theme

_THEME = Theme({
    "markdown.code": "bold #ffb300",
    "markdown.code_block": "#ff8c00",
    "markdown.h1": "bold #ffb300",
    "markdown.h2": "bold #ff8c00",
    "markdown.h3": "bold #ff6600",
    "markdown.strong": "bold #ffb300",
    "markdown.emph": "italic #ff8c00",
})

console = Console(theme=_THEME)
```

- [ ] **Step 8: Run full test suite**

Run: `pytest -v`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add src/newcli/ui.py src/newcli/main.py tests/test_ui.py
git commit -m "feat: format_duration, context % in toolbar, amber theme for markdown"
```

---

## Task 5: UI Polish — Startup Info Box and Spinner Token Counter

**Files:**
- Modify: `src/newcli/ui.py`
- Modify: `src/newcli/main.py`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write failing tests for print_startup_info**

Add to `tests/test_ui.py`:

```python
from io import StringIO
from rich.console import Console


def test_print_startup_info_contains_model(monkeypatch):
    import newcli.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    ui_mod.print_startup_info(provider="lmstudio", model="qwen3", cwd="/home/user/project")
    out = buf.getvalue()
    assert "qwen3" in out
    assert "lmstudio" in out
    assert "/home/user/project" in out


def test_print_startup_info_contains_model_hint(monkeypatch):
    import newcli.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    ui_mod.print_startup_info(provider="x", model="m", cwd="/tmp")
    out = buf.getvalue()
    assert "/model" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui.py -v -k "startup_info"`
Expected: FAIL — `AttributeError: module 'newcli.ui' has no attribute 'print_startup_info'`

- [ ] **Step 3: Implement print_startup_info**

Add to `src/newcli/ui.py`:

```python
def print_startup_info(provider: str, model: str, cwd: str) -> None:
    """Print provider/model info and cwd below the logo."""
    console.print(f"      [bold]{provider}[/bold] | [bold cyan]{model}[/bold cyan] [dim](/model to change)[/dim]")
    console.print(f"      [dim]{cwd}[/dim]")
    console.print()
```

Also update `_LOGO_FOOTER` to remove `[dim]a minimal, clean CLI[/dim]` — the startup info box replaces it:

```python
_LOGO_FOOTER = """\

      /\\_/\\      Tigger — AI Agent
     ( o.o )
      > ^ <
"""
```

- [ ] **Step 4: Update Spinner to accept token_counter**

In `src/newcli/ui.py`, update the `Spinner` context manager:

```python
@contextmanager
def Spinner(start: float, token_counter: list[int] | None = None):
    """
    Show an animated spinner with a live elapsed-time counter while the model
    is thinking. Optionally shows streaming token count.

    ``start`` should be ``time.time()`` captured at the top of the turn.
    ``token_counter`` is an optional 1-element mutable list updated by the streaming loop.
    """
    msg = random.choice(SPINNER_MESSAGES)
    stop_event = threading.Event()

    with console.status("", spinner="dots") as status:
        def _tick() -> None:
            while not stop_event.is_set():
                elapsed = time.time() - start
                parts = [msg, f"{elapsed:.0f}s"]
                if token_counter and token_counter[0] > 0:
                    parts.append(f"↓ {token_counter[0]} tokens")
                status.update(f"[dim]{' · '.join(parts)}[/dim]")
                stop_event.wait(0.1)

        t = threading.Thread(target=_tick, daemon=True)
        t.start()
        try:
            yield
        finally:
            stop_event.set()
            t.join(timeout=0.5)
```

- [ ] **Step 5: Update main.py — call print_startup_info and pass token_counter to Spinner**

In `src/newcli/main.py`, in the `startup()` function, after `ui.print_logo()`, add:

```python
    ui.print_startup_info(
        provider=config.active_provider or derive_provider_name(config.base_url),
        model=config.model,
        cwd=str(cwd),
    )
```

Add the import at the top of main.py:

```python
from newcli.config import load_config, find_config, derive_provider_name
```

(Replace the existing `from newcli.config import load_config, find_config` line.)

In the `repl()` function, update the Spinner call to pass the token counter:

```python
        with ui.Spinner(turn_start, token_counter=output_chars):
```

This works because `output_chars` is already a `list[int]` tracking character count. The spinner will show the current count as it accumulates. (The token count shown is approximate — characters divided by 4 gives rough tokens. The same `output_chars[0]` is already used for the turn summary as `output_chars[0] // 4`. For the spinner, showing the raw character count labeled as "tokens" is close enough; or divide by 4 in the spinner display.)

Actually, to keep it accurate, let's update the Spinner `_tick` to divide by 4:

In the Spinner's `_tick`, change the token display line:

```python
                if token_counter and token_counter[0] > 0:
                    tok = token_counter[0] // 4
                    parts.append(f"↓ {tok} tokens")
```

- [ ] **Step 6: Run full test suite**

Run: `pytest -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/newcli/ui.py src/newcli/main.py tests/test_ui.py
git commit -m "feat: startup info box with provider/model/cwd, spinner shows token count"
```

---

## Task 6: /model Command — Interactive Picker

**Files:**
- Modify: `src/newcli/commands/misc.py`
- Create: `tests/test_model_cmd.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_model_cmd.py`:

```python
import dataclasses
import pytest
from newcli.types import Config, RunContext, ProviderConfig
from newcli.commands.misc import cmd_model


def _cfg():
    pc1 = ProviderConfig(name="local", base_url="http://localhost/v1",
                         api_key="local", models=["qwen3", "llama"])
    pc2 = ProviderConfig(name="cloud", base_url="https://api.openai.com/v1",
                         api_key="sk-cloud", models=["gpt-4o", "gpt-4o-mini"])
    return Config(
        base_url="http://localhost/v1", model="qwen3", api_key="local",
        providers={"local": pc1, "cloud": pc2},
        active_provider="local", active_model="qwen3",
    )


def _ctx():
    return RunContext(config=_cfg(), messages=[], system_prompt="s")


def test_model_no_args_shows_list(capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "1")
    ctx = _ctx()
    cmd_model("", ctx)
    out = capsys.readouterr().out
    assert "local:" in out or "local" in out
    assert "qwen3" in out
    assert "gpt-4o" in out


def test_model_direct_switch_unambiguous(capsys):
    ctx = _ctx()
    cmd_model("gpt-4o", ctx)
    assert ctx.config.model == "gpt-4o"
    assert ctx.config.active_provider == "cloud"
    assert ctx.config.base_url == "https://api.openai.com/v1"


def test_model_direct_switch_with_provider_prefix(capsys):
    ctx = _ctx()
    cmd_model("cloud/gpt-4o-mini", ctx)
    assert ctx.config.model == "gpt-4o-mini"
    assert ctx.config.active_provider == "cloud"


def test_model_not_found(capsys):
    ctx = _ctx()
    cmd_model("nonexistent", ctx)
    out = capsys.readouterr().out
    assert "not found" in out.lower() or "unknown" in out.lower()
    # Model should not have changed
    assert ctx.config.model == "qwen3"


def test_model_picker_by_number(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "3")
    ctx = _ctx()
    cmd_model("", ctx)
    # Number 3 should be gpt-4o (local: 1=qwen3, 2=llama; cloud: 3=gpt-4o, 4=gpt-4o-mini)
    assert ctx.config.model == "gpt-4o"
    assert ctx.config.active_provider == "cloud"


def test_model_no_providers_shows_current(capsys):
    cfg = Config(base_url="http://x", model="m")
    ctx = RunContext(config=cfg, messages=[], system_prompt="s")
    cmd_model("", ctx)
    out = capsys.readouterr().out
    assert "m" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_model_cmd.py -v`
Expected: FAIL — the current `cmd_model` doesn't have picker logic.

- [ ] **Step 3: Replace cmd_model in misc.py**

Replace the existing `cmd_model` function in `src/newcli/commands/misc.py`:

```python
def cmd_model(args: str, ctx: RunContext) -> None:
    from newcli.config import switch_model

    providers = ctx.config.providers

    # No providers configured — fall back to simple name-only switch
    if not providers:
        if not args.strip():
            print(f"Current model: {ctx.config.model}")
            return
        ctx.config = dataclasses.replace(ctx.config, model=args.strip())
        print(f"Model set to: {args.strip()}")
        return

    # Direct switch: /model provider/model
    if "/" in args.strip():
        prov_name, model_name = args.strip().split("/", 1)
        if prov_name not in providers:
            print(f"Unknown provider: {prov_name}. Available: {', '.join(providers)}")
            return
        if model_name not in providers[prov_name].models:
            print(f"Model {model_name!r} not found in provider {prov_name!r}. "
                  f"Available: {', '.join(providers[prov_name].models)}")
            return
        ctx.config = switch_model(ctx.config, prov_name, model_name)
        print(f"Switched to {prov_name}/{model_name}")
        return

    # Direct switch: /model <name> — search all providers
    if args.strip():
        target = args.strip()
        matches = []
        for pname, prov in providers.items():
            if target in prov.models:
                matches.append((pname, target))
        if len(matches) == 1:
            pname, mname = matches[0]
            ctx.config = switch_model(ctx.config, pname, mname)
            print(f"Switched to {pname}/{mname}")
            return
        if len(matches) > 1:
            print(f"Model {target!r} found in multiple providers:")
            for pname, _ in matches:
                print(f"  {pname}/{target}")
            print("Use provider/model syntax to disambiguate.")
            return
        print(f"Model {target!r} not found. Available models:")
        for pname, prov in providers.items():
            print(f"  {pname}: {', '.join(prov.models)}")
        return

    # No args — interactive picker
    numbered: list[tuple[str, str]] = []  # (provider_name, model_name)
    for pname, prov in providers.items():
        print(f"\n  {pname}:")
        for mname in prov.models:
            numbered.append((pname, mname))
            idx = len(numbered)
            active = " (active)" if (pname == ctx.config.active_provider
                                     and mname == ctx.config.active_model) else ""
            print(f"    {idx}. {mname}{active}")

    try:
        choice = input(f"\nPick [1-{len(numbered)}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(numbered):
        print("Cancelled.")
        return
    pname, mname = numbered[int(choice) - 1]
    ctx.config = switch_model(ctx.config, pname, mname)
    print(f"Switched to {pname}/{mname}")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_model_cmd.py -v`
Expected: all PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/newcli/commands/misc.py tests/test_model_cmd.py
git commit -m "feat: /model interactive picker with provider grouping and direct switch"
```

---

## Task 7: First-Run Setup Wizard

**Files:**
- Modify: `src/newcli/ui.py`
- Modify: `src/newcli/main.py`
- Create: `tests/test_setup_wizard.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_setup_wizard.py`:

```python
import json
import pathlib
import pytest


def test_run_setup_wizard_creates_config(monkeypatch, tmp_path):
    import newcli.ui as ui_mod
    from io import StringIO
    from rich.console import Console

    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))

    inputs = iter([
        "http://localhost:1234/v1",   # base_url
        "",                            # api_key (defaults to "local")
        "qwen3",                       # model
        "p",                           # save to project
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    config_path, config_data = ui_mod.run_setup_wizard(project_dir=tmp_path)

    assert config_path == tmp_path / ".ai" / "config.json"
    assert config_path.exists()

    data = json.loads(config_path.read_text())
    assert "providers" in data
    assert data["default_model"] == "qwen3"
    provider_name = data["default_provider"]
    assert data["providers"][provider_name]["base_url"] == "http://localhost:1234/v1"
    assert data["providers"][provider_name]["models"] == ["qwen3"]


def test_run_setup_wizard_user_location(monkeypatch, tmp_path):
    import newcli.ui as ui_mod
    from io import StringIO
    from rich.console import Console

    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))

    inputs = iter([
        "https://api.openai.com/v1",
        "sk-test",
        "gpt-4o",
        "u",                          # save to user
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "fakehome")

    config_path, _ = ui_mod.run_setup_wizard(project_dir=tmp_path)

    assert config_path == tmp_path / "fakehome" / ".ai" / "config.json"
    assert config_path.exists()


def test_run_setup_wizard_empty_api_key_defaults_to_local(monkeypatch, tmp_path):
    import newcli.ui as ui_mod
    from io import StringIO
    from rich.console import Console

    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))

    inputs = iter(["http://x/v1", "", "m", "p"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    config_path, _ = ui_mod.run_setup_wizard(project_dir=tmp_path)
    data = json.loads(config_path.read_text())
    prov = list(data["providers"].values())[0]
    assert prov["api_key"] == "local"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_setup_wizard.py -v`
Expected: FAIL — `AttributeError: module 'newcli.ui' has no attribute 'run_setup_wizard'`

- [ ] **Step 3: Implement run_setup_wizard**

Add to `src/newcli/ui.py`:

```python
def run_setup_wizard(project_dir: pathlib.Path) -> tuple[pathlib.Path, dict]:
    """Interactive first-run setup. Returns (config_path, config_data)."""
    from newcli.config import derive_provider_name, write_config
    from newcli.types import Config, ProviderConfig

    console.print("\n[bold]No config found.[/bold] Let's set up your first provider.\n")

    base_url = input("  Base URL (e.g. http://localhost:1234/v1): ").strip()
    api_key = input("  API key (Enter for 'local'): ").strip() or "local"
    model = input("  Model name (e.g. qwen3, gpt-4o): ").strip()
    location = input("  Save to [P]roject or [u]ser (~/.ai/)? [P/u]: ").strip().lower()

    provider_name = derive_provider_name(base_url)
    prov = ProviderConfig(name=provider_name, base_url=base_url,
                          api_key=api_key, models=[model])

    if location == "u":
        ai_dir = pathlib.Path.home() / ".ai"
    else:
        ai_dir = project_dir / ".ai"

    config = Config(
        base_url=base_url,
        model=model,
        api_key=api_key,
        providers={provider_name: prov},
        active_provider=provider_name,
        active_model=model,
    )
    config_path = ai_dir / "config.json"
    write_config(config_path, config)

    console.print(f"\n  [green]Config saved to {config_path}[/green]\n")
    return config_path, {}
```

- [ ] **Step 4: Wire wizard into startup()**

In `src/newcli/main.py`, in the `startup()` function, replace the block:

```python
    if config_path is None:
        ui.print_error("no .ai/config.json found. Create one in your project or ~/.ai/")
        sys.exit(1)
```

with:

```python
    if config_path is None:
        config_path, _ = ui.run_setup_wizard(project_dir=pathlib.Path.cwd())
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_setup_wizard.py -v`
Expected: all PASS

- [ ] **Step 6: Run full test suite**

Run: `pytest -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/newcli/ui.py src/newcli/main.py tests/test_setup_wizard.py
git commit -m "feat: first-run setup wizard creates config interactively"
```

---

## Task 8: /provider add Command and Final Wiring

**Files:**
- Create: `src/newcli/commands/provider.py`
- Modify: `src/newcli/commands/__init__.py`
- Modify: `src/newcli/main.py`
- Create: `tests/test_provider_cmd.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_provider_cmd.py`:

```python
import json
import pathlib
import pytest
from newcli.types import Config, RunContext, ProviderConfig
from newcli.commands.provider import cmd_provider


def _cfg():
    pc = ProviderConfig(name="local", base_url="http://localhost/v1",
                        api_key="local", models=["qwen3"])
    return Config(
        base_url="http://localhost/v1", model="qwen3", api_key="local",
        providers={"local": pc}, active_provider="local", active_model="qwen3",
    )


def _ctx():
    return RunContext(config=_cfg(), messages=[], system_prompt="s")


def test_provider_no_args_shows_usage(capsys):
    ctx = _ctx()
    cmd_provider("", ctx, pathlib.Path("/tmp/fake.json"))
    out = capsys.readouterr().out
    assert "usage" in out.lower() or "add" in out.lower()


def test_provider_add_new(monkeypatch, tmp_path, capsys):
    from newcli.config import write_config
    config_path = tmp_path / "config.json"
    ctx = _ctx()
    write_config(config_path, ctx.config)

    inputs = iter([
        "cloud",                          # provider name
        "https://api.openai.com/v1",      # base_url
        "sk-test",                        # api_key
        "gpt-4o",                         # model
        "n",                              # don't switch
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    cmd_provider("add", ctx, config_path)

    data = json.loads(config_path.read_text())
    assert "cloud" in data["providers"]
    assert data["providers"]["cloud"]["models"] == ["gpt-4o"]
    assert data["providers"]["cloud"]["base_url"] == "https://api.openai.com/v1"
    # Also check in-memory config was updated
    assert "cloud" in ctx.config.providers


def test_provider_add_model_to_existing(monkeypatch, tmp_path, capsys):
    from newcli.config import write_config
    config_path = tmp_path / "config.json"
    ctx = _ctx()
    write_config(config_path, ctx.config)

    inputs = iter([
        "local",                          # existing provider
        "llama",                          # new model
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    cmd_provider("add", ctx, config_path)

    data = json.loads(config_path.read_text())
    assert "llama" in data["providers"]["local"]["models"]
    assert "qwen3" in data["providers"]["local"]["models"]


def test_provider_add_switch_yes(monkeypatch, tmp_path, capsys):
    from newcli.config import write_config
    config_path = tmp_path / "config.json"
    ctx = _ctx()
    write_config(config_path, ctx.config)

    inputs = iter(["newprov", "http://new/v1", "k", "newmodel", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    cmd_provider("add", ctx, config_path)

    assert ctx.config.active_provider == "newprov"
    assert ctx.config.model == "newmodel"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_provider_cmd.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'newcli.commands.provider'`

- [ ] **Step 3: Implement cmd_provider**

Create `src/newcli/commands/provider.py`:

```python
from __future__ import annotations
import dataclasses
import pathlib
import re
from newcli.types import RunContext, ProviderConfig
from newcli.config import switch_model, write_config


def cmd_provider(args: str, ctx: RunContext, config_path: pathlib.Path) -> None:
    subcmd = args.strip().lower()
    if subcmd != "add":
        print("Usage: /provider add")
        return
    _provider_add(ctx, config_path)


def _provider_add(ctx: RunContext, config_path: pathlib.Path) -> None:
    existing = list(ctx.config.providers.keys())
    hint = f" (or existing: {', '.join(existing)})" if existing else ""
    name = input(f"  Provider name{hint}: ").strip()

    if not name or not re.match(r'^[a-zA-Z0-9._-]+$', name):
        print("Invalid provider name. Use alphanumeric characters, hyphens, dots.")
        return

    if name in ctx.config.providers:
        # Add model to existing provider
        model = input("  Model name: ").strip()
        if not model:
            print("Cancelled — no model name given.")
            return
        prov = ctx.config.providers[name]
        if model in prov.models:
            print(f"Model {model!r} already exists in provider {name!r}.")
            return
        new_models = list(prov.models) + [model]
        new_prov = dataclasses.replace(prov, models=new_models)
        new_providers = dict(ctx.config.providers)
        new_providers[name] = new_prov
        ctx.config = dataclasses.replace(ctx.config, providers=new_providers)
        write_config(config_path, ctx.config)
        print(f"Added model {model!r} to provider {name!r}.")
    else:
        # New provider
        base_url = input("  Base URL: ").strip()
        if not base_url.startswith(("http://", "https://")):
            print("Base URL must start with http:// or https://")
            return
        api_key = input("  API key (Enter for 'local'): ").strip() or "local"
        model = input("  Model name: ").strip()
        if not model:
            print("Cancelled — no model name given.")
            return

        new_prov = ProviderConfig(name=name, base_url=base_url,
                                  api_key=api_key, models=[model])
        new_providers = dict(ctx.config.providers)
        new_providers[name] = new_prov
        ctx.config = dataclasses.replace(ctx.config, providers=new_providers)
        write_config(config_path, ctx.config)
        print(f"Added provider {name!r} with model {model!r}.")

        try:
            switch = input("  Switch to it now? [Y/n]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return
        if switch in ("y", ""):
            ctx.config = switch_model(ctx.config, name, model)
            print(f"Switched to {name}/{model}")
```

- [ ] **Step 4: Register /provider in commands/__init__.py**

In `src/newcli/commands/__init__.py`, add the import:

```python
from newcli.commands import provider as provider_cmd
```

Add `config_path` parameter to `load_builtin_commands`:

```python
def load_builtin_commands(
    memory_path: pathlib.Path,
    config_path: pathlib.Path,
    skills: list[SkillDef],
    agents: list[AgentDef],
    registry: ToolRegistry,
    hooks: HookRegistry,
    provider_fn,
) -> dict:
```

Add the `/provider` entry to the dict:

```python
        "provider": lambda args, ctx: provider_cmd.cmd_provider(args, ctx, config_path),
```

- [ ] **Step 5: Update main.py to pass config_path**

In `src/newcli/main.py`, in the `startup()` function, update the `load_builtin_commands` call to include `config_path`:

```python
    commands = load_builtin_commands(
        memory_path=ai_dir / "memory.md",
        config_path=config_path,
        skills=skills,
        agents=agents,
        registry=registry,
        hooks=hooks,
        provider_fn=_provider.stream,
    )
```

Also store `config_path` in `StartupResult` for potential future use. Add the field:

```python
@dataclasses.dataclass
class StartupResult:
    ctx: RunContext
    commands: dict
    skills: list
    registry: object
    hooks: object
    provider_fn: object
    config_path: pathlib.Path
```

And set it in the return:

```python
    return StartupResult(
        ctx=ctx,
        commands=commands,
        skills=skills,
        registry=registry,
        hooks=hooks,
        provider_fn=_provider.stream,
        config_path=config_path,
    )
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_provider_cmd.py -v`
Expected: all PASS

- [ ] **Step 7: Run full test suite**

Run: `pytest -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add src/newcli/commands/provider.py src/newcli/commands/__init__.py \
        src/newcli/main.py tests/test_provider_cmd.py
git commit -m "feat: /provider add command with persistence, wire config_path through startup"
```

---

## Final Verification

```bash
# 1. All tests pass
pytest -v

# 2. Ruff clean
ruff check src/

# 3. Manual: existing old-format config still loads
# The .ai/config.json in the project uses the old flat format — it should load
# and auto-migrate to a single-provider config in memory.

# 4. Manual: /model shows grouped picker
# Run newcli, type /model — should show the provider name and model list

# 5. Manual: /provider add creates new provider
# Run /provider add, enter a new provider, verify config.json is updated

# 6. Manual: startup info box shows below logo
# Logo should be followed by provider | model (/model to change) and cwd

# 7. Manual: toolbar shows context % instead of raw tokens
# Bottom bar should show "0.1% context" instead of "123/128000 tok"

# 8. Manual: long response shows friendly time
# After a response taking >60s, turn summary should show "Xm Ys" not "X.Xs"
```
