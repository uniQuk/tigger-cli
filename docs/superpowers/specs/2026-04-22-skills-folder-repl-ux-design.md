# Skills Folder Loader, REPL UX & Gradient Logo — Design Spec

**Date:** 2026-04-22  
**Status:** Approved  

---

## Overview

Four cohesive improvements to `newcli`:

1. **Skills folder loader** — load skills from `.ai/skills/<name>/SKILL.md` instead of a flat `skills.md`, with reference injection and asset path tracking.
2. **Nested command routing** — skill folder names become command namespaces (`/how explain auth`).
3. **`prompt_toolkit` REPL** — replaces `input()` with history, arrow-key navigation, and real-time inline command/skill completion.
4. **Gradient logo** — amber → orange-red left-to-right gradient on the ASCII art block.

---

## Architecture

Five files change; loop logic is untouched.

```
skills/                          prompt_toolkit
loader (skills.py)               session (main.py)
    │                                │
    ▼                                ▼
SkillDef                         PromptSession
  + folder: Path                   + NewcliCompleter
  + references: list[str]              /commands
  + assets: Path | None              + skill folder names
  + render() injects refs            + hooks
        │
        ▼
    ui.py  (gradient logo)
```

**Files modified:**
- `src/newcli/skills.py` — `SkillDef` additions, `load_skills_dir()`
- `src/newcli/main.py` — `PromptSession` replaces `input()`, loads from `skills/` dir, nested command routing
- `src/newcli/ui.py` — gradient logo
- `pyproject.toml` — add `prompt_toolkit>=3.0`

**Files added:**
- `tests/test_skills_dir.py` — loader tests
- `tests/test_completer.py` — completer unit tests

**Unchanged:** `loop.py`, `config.py`, `permissions.py`, `trust.py`, `types.py`, all other commands.

---

## Section 1: Skills Loader & Data Model

### `SkillDef` changes

```python
@dataclass
class SkillDef:
    name: str
    triggers: list[str]
    tools: list[str]
    context: str                              # "inline" | "fork"
    body: str                                 # prompt template
    folder: pathlib.Path | None = None        # source folder on disk
    references: list[str] = field(default_factory=list)  # content of references/*.md
    assets: pathlib.Path | None = None        # path to assets/ subdir
```

### `load_skills_dir(skills_dir: Path) -> list[SkillDef]`

Walk `skills_dir`. For each immediate subdirectory containing a `SKILL.md`:

1. Parse `SKILL.md` frontmatter + body (reuse existing `_parse_blocks` logic, adapted for a single file).
2. **Trigger convention:** if frontmatter has no `triggers:` key, use the folder name as the sole trigger (prefixed with `/`).
3. **References:** glob `references/*.md` (sorted), read each file's content into `references: list[str]`.
4. **Assets:** if an `assets/` subdirectory exists, store its path in `assets`; otherwise `None`.
5. Skip `.DS_Store`, non-directory entries, and directories without `SKILL.md`.

The existing `load_skills(path: Path)` (flat file loader) is **kept unchanged** for backward compatibility. `main.py` calls `load_skills_dir()` first if the directory exists, falls back to `load_skills()` for the flat file.

### `render()` changes

```python
def render(self, user_input: str) -> str:
    ref_block = "\n\n---\n\n".join(self.references)
    base = f"{ref_block}\n\n{self.body}" if ref_block else self.body
    for trigger in self.triggers:
        if user_input.startswith(trigger):
            args = user_input[len(trigger):].strip()
            return base.replace("$ARGUMENTS", args)
    return base.replace("$ARGUMENTS", user_input)
```

### Nested command routing

In the REPL, before checking built-in slash commands, check if the first token after `/` matches a skill's folder name (or any of its triggers stripped of `/`):

```
/how explain auth
 ^^^             → matches skill with folder "how"
     ^^^^^^^^^^^  → passed as $ARGUMENTS to render()
```

`/how` alone (no arguments) renders with `$ARGUMENTS = ""`. The skill body should handle this gracefully (the `how` skill already does via its mode description).

---

## Section 2: `prompt_toolkit` REPL

### `NewcliCompleter`

A `prompt_toolkit.completion.Completer` subclass. Only activates when the current buffer starts with `/`. Builds the candidate list from:

1. Built-in command names (static list)
2. Skill trigger strings (from loaded `SkillDef.triggers`)
3. Hook names (if any)

Filtering: candidates that contain the typed fragment (case-insensitive substring match, not just prefix) are shown. Up to 10 candidates displayed at once in the dropdown.

```python
class NewcliCompleter(Completer):
    def __init__(self, commands: dict, skills: list[SkillDef], hooks: HookRegistry): ...

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        fragment = text[1:]  # strip leading /
        for candidate in self._all_candidates():
            if fragment.lower() in candidate.lower():
                yield Completion("/" + candidate, start_position=-len(text))
```

### `PromptSession` setup

```python
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

session = PromptSession(
    history=FileHistory(pathlib.Path.home() / ".ai" / "history"),
    completer=NewcliCompleter(commands, skills, hooks),
    complete_while_typing=True,
)
```

`session.prompt(_prompt(ctx))` replaces `input(_prompt(ctx))`. `KeyboardInterrupt` and `EOFError` are caught identically to before.

### Bottom toolbar

A passive one-liner showing current state — no interactivity:

```python
def _toolbar(ctx):
    return f" mode:{ctx.config.mode}  perm:{ctx.config.permission_mode}  tokens:{estimate_tokens(ctx.messages)}/{ctx.config.context_limit}"
```

Passed as `bottom_toolbar=lambda: _toolbar(ctx)` to `session.prompt()`.

---

## Section 3: Gradient Logo

`print_logo()` in `ui.py` renders the 6-line ASCII art block with a left-to-right amber→orange-red gradient.

**Colour endpoints:**
- Left: `rgb(255, 179, 0)` — amber `#FFB300`
- Right: `rgb(255, 69, 0)` — orange-red `#FF4500`

**Algorithm:**
```python
def _gradient_line(line: str, max_width: int) -> str:
    out = []
    for col, ch in enumerate(line):
        if ch == " ":
            out.append(" ")
        else:
            t = col / max(max_width - 1, 1)
            r = 255
            g = int(179 + (69 - 179) * t)   # 179 → 69
            b = int(0   + (0  -   0) * t)   # 0   → 0
            out.append(f"[rgb({r},{g},{b})]{ch}[/rgb({r},{g},{b})]")
    return "".join(out)
```

The cat art and tagline below the ASCII block remain white/dim (no gradient applied).

Rich markup is used directly — no external colour library needed.

---

## Dependencies

Add to `pyproject.toml`:
```toml
dependencies = ["openai>=1.0", "pyyaml>=6.0", "rich>=13.0", "tiktoken>=0.7", "prompt_toolkit>=3.0"]
```

---

## Testing

### `tests/test_skills_dir.py`
- `test_load_skills_dir_basic` — tmp dir with one skill folder, asserts name/trigger/body loaded
- `test_load_skills_dir_references_injected` — skill with `references/a.md` + `references/b.md`, asserts both contents in `SkillDef.references`
- `test_load_skills_dir_assets_path` — skill with `assets/` dir, asserts `SkillDef.assets` is set
- `test_load_skills_dir_default_trigger` — no `triggers:` in frontmatter, folder name becomes trigger
- `test_load_skills_dir_explicit_trigger_overrides` — explicit trigger in frontmatter is used
- `test_load_skills_dir_skips_no_skill_md` — folder without SKILL.md is ignored
- `test_render_injects_references` — `render()` prepends reference content before body

### `tests/test_completer.py`
- `test_completer_only_activates_on_slash` — no slash → no completions
- `test_completer_matches_commands` — `/cl` → `/clear` in results
- `test_completer_matches_skills` — `/ho` → `/how` in results
- `test_completer_substring_match` — `/rchi` → `/architecture-diagram` in results (contains match)

---

## Error Handling

- `SKILL.md` missing required `name:` frontmatter field → silently skipped (matches existing flat-file behaviour).
- `references/` file unreadable → skip that file, log warning to stderr, continue loading.
- `prompt_toolkit` import failure → fall back to `input()` with a warning printed once at startup. This preserves headless/pipe use.
- History file unwritable → `InMemoryHistory` used as fallback (no crash).

---

## Out of Scope

- Skills written as Python scripts (not `.md`) — future work.
- Hot-reload of skills while REPL is running.
- Multi-level nesting (`/how/explain/auth`) — folder names are one level deep.
- `agents.md` equivalent as folder — not requested.
