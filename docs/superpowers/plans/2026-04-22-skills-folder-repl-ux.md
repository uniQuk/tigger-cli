# Skills Folder Loader, REPL UX & Gradient Logo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load skills from `.ai/skills/<name>/SKILL.md` folders, inject `references/` into context, add `prompt_toolkit` REPL with history + inline completion, and render a gradient logo.

**Architecture:** Four independent layers built bottom-up: (1) dep added to `pyproject.toml`, (2) `SkillDef` enriched + `load_skills_dir()` added to `skills.py`, (3) `NewcliCompleter` in new `completer.py`, (4) gradient logo in `ui.py`, (5) everything wired into `main.py`.

**Tech Stack:** Python 3.11+, `rich>=13.0`, `prompt_toolkit>=3.0`, `pytest`

---

## File Map

| File | Status | Responsibility |
|------|--------|----------------|
| `pyproject.toml` | modify | add `prompt_toolkit>=3.0` dep |
| `src/newcli/skills.py` | modify | `SkillDef` new fields, `load_skills_dir()`, updated `render()` |
| `src/newcli/completer.py` | **create** | `NewcliCompleter` — prompt_toolkit `Completer` subclass |
| `src/newcli/ui.py` | modify | `print_logo()` → amber→orange gradient, remove `_LOGO` constant |
| `src/newcli/main.py` | modify | `load_skills_dir()` in startup, `PromptSession` in repl, bottom toolbar |
| `tests/test_skills_dir.py` | **create** | folder loader + `render()` reference injection tests |
| `tests/test_completer.py` | **create** | `NewcliCompleter` unit tests |
| `tests/test_ui.py` | modify | add gradient logo tests |

---

## Task 1: Add `prompt_toolkit` Dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit `pyproject.toml` dependencies line**

In `pyproject.toml`, replace the `dependencies` line:
```toml
dependencies = ["openai>=1.0", "pyyaml>=6.0", "rich>=13.0", "tiktoken>=0.7", "prompt_toolkit>=3.0"]
```

- [ ] **Step 2: Install and verify**

```bash
pip install -e ".[dev]" --break-system-packages -q
python -c "import prompt_toolkit; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add prompt_toolkit>=3.0 dependency"
```

---

## Task 2: `SkillDef` Additions + `load_skills_dir()`

**Files:**
- Modify: `src/newcli/skills.py`
- Create: `tests/test_skills_dir.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_skills_dir.py`:
```python
import pathlib
import textwrap
import pytest
from newcli.skills import load_skills_dir, SkillDef


def _make_skill(
    tmp_path: pathlib.Path,
    folder_name: str,
    skill_md: str,
    refs: dict[str, str] | None = None,
    assets: dict[str, str] | None = None,
) -> pathlib.Path:
    """Create a skill folder under tmp_path. Returns the folder path."""
    folder = tmp_path / folder_name
    folder.mkdir()
    (folder / "SKILL.md").write_text(skill_md)
    if refs:
        (folder / "references").mkdir()
        for fname, content in refs.items():
            (folder / "references" / fname).write_text(content)
    if assets:
        (folder / "assets").mkdir()
        for fname, content in assets.items():
            (folder / "assets" / fname).write_text(content)
    return folder


_BASIC = textwrap.dedent("""\
    ---
    name: my-skill
    ---
    Do the thing with $ARGUMENTS.
""")

_WITH_TRIGGER = textwrap.dedent("""\
    ---
    name: my-skill
    triggers: [/ms]
    ---
    Do the thing with $ARGUMENTS.
""")

_WITH_TOOLS = textwrap.dedent("""\
    ---
    name: my-skill
    tools: [read, grep]
    ---
    Body.
""")


def test_load_skills_dir_basic(tmp_path):
    _make_skill(tmp_path, "my-skill", _BASIC)
    skills = load_skills_dir(tmp_path)
    assert len(skills) == 1
    assert skills[0].name == "my-skill"
    assert "Do the thing" in skills[0].body


def test_load_skills_dir_default_trigger_is_folder_name(tmp_path):
    _make_skill(tmp_path, "my-skill", _BASIC)
    skills = load_skills_dir(tmp_path)
    assert skills[0].triggers == ["/my-skill"]


def test_load_skills_dir_explicit_trigger_overrides(tmp_path):
    _make_skill(tmp_path, "my-skill", _WITH_TRIGGER)
    skills = load_skills_dir(tmp_path)
    assert skills[0].triggers == ["/ms"]


def test_load_skills_dir_references_injected(tmp_path):
    _make_skill(
        tmp_path, "my-skill", _BASIC,
        refs={"a.md": "Reference A content", "b.md": "Reference B content"},
    )
    skills = load_skills_dir(tmp_path)
    assert len(skills[0].references) == 2
    assert "Reference A content" in skills[0].references
    assert "Reference B content" in skills[0].references


def test_load_skills_dir_references_sorted(tmp_path):
    _make_skill(
        tmp_path, "my-skill", _BASIC,
        refs={"z.md": "Z", "a.md": "A"},
    )
    skills = load_skills_dir(tmp_path)
    # sorted by filename: a.md first, z.md second
    assert skills[0].references[0] == "A"
    assert skills[0].references[1] == "Z"


def test_load_skills_dir_assets_path_set(tmp_path):
    _make_skill(
        tmp_path, "my-skill", _BASIC,
        assets={"template.html": "<html/>"},
    )
    skills = load_skills_dir(tmp_path)
    assert skills[0].assets is not None
    assert (skills[0].assets / "template.html").exists()


def test_load_skills_dir_no_assets_is_none(tmp_path):
    _make_skill(tmp_path, "my-skill", _BASIC)
    skills = load_skills_dir(tmp_path)
    assert skills[0].assets is None


def test_load_skills_dir_skips_folder_without_skill_md(tmp_path):
    (tmp_path / "not-a-skill").mkdir()
    (tmp_path / "not-a-skill" / "README.md").write_text("nothing")
    skills = load_skills_dir(tmp_path)
    assert skills == []


def test_load_skills_dir_skips_non_directories(tmp_path):
    _make_skill(tmp_path, "good-skill", _BASIC)
    (tmp_path / "stray_file.txt").write_text("ignored")
    skills = load_skills_dir(tmp_path)
    assert len(skills) == 1


def test_load_skills_dir_missing_name_skipped(tmp_path):
    bad_md = "---\ndescription: no name here\n---\nBody."
    _make_skill(tmp_path, "nameless", bad_md)
    skills = load_skills_dir(tmp_path)
    assert skills == []


def test_load_skills_dir_folder_field_set(tmp_path):
    _make_skill(tmp_path, "my-skill", _BASIC)
    skills = load_skills_dir(tmp_path)
    assert skills[0].folder == tmp_path / "my-skill"


def test_load_skills_dir_empty_dir(tmp_path):
    assert load_skills_dir(tmp_path) == []


def test_load_skills_dir_nonexistent(tmp_path):
    assert load_skills_dir(tmp_path / "no-such-dir") == []


def test_render_injects_references(tmp_path):
    _make_skill(
        tmp_path, "my-skill", _BASIC,
        refs={"ref.md": "Important reference context"},
    )
    skills = load_skills_dir(tmp_path)
    rendered = skills[0].render("/my-skill do this")
    assert "Important reference context" in rendered
    assert "Do the thing" in rendered
    assert "do this" in rendered
    assert "$ARGUMENTS" not in rendered


def test_render_no_references_unchanged(tmp_path):
    _make_skill(tmp_path, "my-skill", _BASIC)
    skills = load_skills_dir(tmp_path)
    rendered = skills[0].render("/my-skill hello")
    assert rendered == "Do the thing with hello."
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_skills_dir.py -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'load_skills_dir'`

- [ ] **Step 3: Implement changes in `skills.py`**

Replace `src/newcli/skills.py` entirely:
```python
from __future__ import annotations
import pathlib
import re
import sys
from dataclasses import dataclass, field


@dataclass
class SkillDef:
    name: str
    triggers: list[str]
    tools: list[str]
    context: str                                    # "inline" | "fork"
    body: str                                       # prompt template
    folder: pathlib.Path | None = None              # source folder
    references: list[str] = field(default_factory=list)  # injected at render time
    assets: pathlib.Path | None = None              # assets/ subdir path

    def render(self, user_input: str) -> str:
        ref_block = "\n\n".join(self.references)
        base = f"{ref_block}\n\n{self.body}" if ref_block else self.body
        for trigger in self.triggers:
            if user_input.startswith(trigger):
                args = user_input[len(trigger):].strip()
                return base.replace("$ARGUMENTS", args)
        return base.replace("$ARGUMENTS", user_input)


@dataclass
class AgentDef:
    name: str
    system_prompt: str
    tools: list[str]
    model: str | None = None


def _parse_blocks(text: str) -> list[dict]:
    import yaml
    blocks = []
    parts = re.split(r"^---\s*$", text, flags=re.MULTILINE)
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
    """Load skills from a flat skills.md file (legacy/fallback)."""
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


def load_skills_dir(skills_dir: pathlib.Path) -> list[SkillDef]:
    """Load skills from a directory. Each subdirectory with SKILL.md is one skill."""
    if not skills_dir.exists() or not skills_dir.is_dir():
        return []
    skills = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            continue
        blocks = _parse_blocks(skill_md.read_text())
        if not blocks:
            continue
        b = blocks[0]
        fm = b["fm"]
        if "name" not in fm:
            continue

        # Triggers: explicit frontmatter wins; default is /<folder-name>
        triggers = fm.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [triggers]
        if not triggers:
            triggers = [f"/{entry.name}"]

        # References: glob references/*.md sorted by name
        refs: list[str] = []
        refs_dir = entry / "references"
        if refs_dir.exists():
            for ref_file in sorted(refs_dir.glob("*.md")):
                try:
                    refs.append(ref_file.read_text())
                except OSError as exc:
                    print(f"Warning: could not read {ref_file}: {exc}", file=sys.stderr)

        # Assets: store path if directory exists
        assets_dir = entry / "assets"
        assets = assets_dir if assets_dir.exists() else None

        tools = fm.get("tools", [])
        skills.append(SkillDef(
            name=fm["name"],
            triggers=triggers,
            tools=tools,
            context=fm.get("context", "inline"),
            body=b["body"],
            folder=entry,
            references=refs,
            assets=assets,
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

- [ ] **Step 4: Run all skills tests**

```bash
pytest tests/test_skills_dir.py tests/test_skills.py -v
```
Expected: all PASS

- [ ] **Step 5: Run full test suite**

```bash
pytest -v --tb=short -q 2>&1 | tail -5
```
Expected: all PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/newcli/skills.py tests/test_skills_dir.py
git commit -m "feat: add load_skills_dir(), SkillDef folder/references/assets fields, inject refs into render()"
```

---

## Task 3: Gradient Logo

**Files:**
- Modify: `src/newcli/ui.py`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_ui.py` (append after existing tests):
```python
from newcli.ui import _gradient_line, _LOGO_LINES


def test_gradient_line_spaces_pass_through():
    result = _gradient_line("  ABC", 5)
    assert result.startswith("  ")


def test_gradient_line_non_spaces_get_color_markup():
    result = _gradient_line("ABC", 3)
    assert "[#" in result


def test_gradient_line_leftmost_is_amber():
    # t=0 → g=179=0xb3, so color is #ffb300
    result = _gradient_line("X", 1)
    assert "[#ffb300]" in result


def test_gradient_line_rightmost_is_orange_red():
    # t=1 → g=69=0x45, so color is #ff4500
    # With max_width=2 and col=1: t = 1/(2-1) = 1.0
    result = _gradient_line("AB", 2)
    assert "[#ff4500]" in result


def test_logo_lines_constant_non_empty():
    assert len(_LOGO_LINES) == 6
    assert all(isinstance(line, str) and len(line) > 0 for line in _LOGO_LINES)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_ui.py -v -k "gradient or logo_lines"
```
Expected: `ImportError: cannot import name '_gradient_line'`

- [ ] **Step 3: Update `ui.py`**

In `src/newcli/ui.py`, replace the `_LOGO` constant and `print_logo()` function:

Find and remove:
```python
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
```

Replace with:
```python
_LOGO_LINES = [
    " ████████╗██╗  ██████╗  ██████╗ ███████╗██████╗ ",
    "    ██╔══╝██║ ██╔════╝ ██╔════╝ ██╔════╝██╔══██╗",
    "    ██║   ██║ ██║  ███╗██║  ███╗█████╗  ██████╔╝",
    "    ██║   ██║ ██║   ██║██║   ██║██╔══╝  ██╔══██╗",
    "    ██║   ██║ ╚██████╔╝╚██████╔╝███████╗██║  ██║",
    "    ╚═╝   ╚═╝  ╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝",
]

_LOGO_FOOTER = """\

      /\\_/\\      Tigger — AI Agent
     ( o.o )
      > ^ <      [dim]a minimal, clean CLI[/dim]
"""


def _gradient_line(line: str, max_width: int) -> str:
    """Render one logo line with an amber→orange-red left-to-right gradient."""
    out = []
    for col, ch in enumerate(line):
        if ch == " ":
            out.append(" ")
        else:
            t = col / max(max_width - 1, 1)
            r = 255
            g = int(179 + (69 - 179) * t)   # 179 (#b3) → 69 (#45)
            b = 0
            out.append(f"[#{r:02x}{g:02x}{b:02x}]{ch}[/]")
    return "".join(out)


def print_logo() -> None:
    max_width = max(len(line) for line in _LOGO_LINES)
    for line in _LOGO_LINES:
        console.print(_gradient_line(line, max_width), highlight=False)
    console.print(_LOGO_FOOTER)
```

- [ ] **Step 4: Run UI tests**

```bash
pytest tests/test_ui.py -v
```
Expected: all PASS

- [ ] **Step 5: Run full test suite**

```bash
pytest -v --tb=short -q 2>&1 | tail -5
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/newcli/ui.py tests/test_ui.py
git commit -m "feat: amber→orange-red gradient logo"
```

---

## Task 4: `NewcliCompleter`

**Files:**
- Create: `src/newcli/completer.py`
- Create: `tests/test_completer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_completer.py`:
```python
from newcli.completer import NewcliCompleter
from newcli.skills import SkillDef
from newcli.hooks import HookRegistry
from prompt_toolkit.document import Document


def _completer(extra_skills: list[SkillDef] | None = None) -> NewcliCompleter:
    commands = {"clear": None, "tokens": None, "help": None, "mode": None, "permission": None}
    skills = [
        SkillDef(name="how", triggers=["/how"], tools=[], context="inline", body=""),
    ]
    if extra_skills:
        skills.extend(extra_skills)
    return NewcliCompleter(commands, skills, HookRegistry())


def _completions(completer: NewcliCompleter, text: str) -> list[str]:
    doc = Document(text, cursor_position=len(text))
    return [c.text for c in completer.get_completions(doc, None)]


def test_completer_no_activation_without_slash():
    results = _completions(_completer(), "how")
    assert results == []


def test_completer_no_activation_empty():
    results = _completions(_completer(), "")
    assert results == []


def test_completer_matches_command_prefix():
    results = _completions(_completer(), "/cl")
    assert "/clear" in results


def test_completer_matches_skill_prefix():
    results = _completions(_completer(), "/ho")
    assert "/how" in results


def test_completer_substring_match():
    c = _completer(extra_skills=[
        SkillDef(
            name="architecture-diagram",
            triggers=["/architecture-diagram"],
            tools=[],
            context="inline",
            body="",
        ),
    ])
    results = _completions(c, "/rchi")
    assert "/architecture-diagram" in results


def test_completer_slash_alone_shows_all():
    results = _completions(_completer(), "/")
    assert "/clear" in results
    assert "/how" in results


def test_completer_case_insensitive():
    results = _completions(_completer(), "/CL")
    assert "/clear" in results


def test_completer_no_duplicates():
    results = _completions(_completer(), "/")
    assert len(results) == len(set(results))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_completer.py -v 2>&1 | head -15
```
Expected: `ModuleNotFoundError: No module named 'newcli.completer'`

- [ ] **Step 3: Create `src/newcli/completer.py`**

```python
from __future__ import annotations
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from newcli.skills import SkillDef
from newcli.hooks import HookRegistry


class NewcliCompleter(Completer):
    """Inline completion for newcli REPL. Only activates when input starts with '/'."""

    def __init__(
        self,
        commands: dict,
        skills: list[SkillDef],
        hooks: HookRegistry,
    ) -> None:
        self._candidates: list[str] = []
        # Built-in command names (without leading /)
        self._candidates.extend(commands.keys())
        # Skill triggers (strip leading / for matching, re-add on completion)
        for skill in skills:
            for trigger in skill.triggers:
                stripped = trigger.lstrip("/")
                if stripped not in self._candidates:
                    self._candidates.append(stripped)

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        fragment = text[1:].lower()  # strip leading /
        seen: set[str] = set()
        for candidate in self._candidates:
            if fragment in candidate.lower() and candidate not in seen:
                seen.add(candidate)
                yield Completion(
                    "/" + candidate,
                    start_position=-len(text),
                )
```

- [ ] **Step 4: Run completer tests**

```bash
pytest tests/test_completer.py -v
```
Expected: all PASS

- [ ] **Step 5: Run full test suite**

```bash
pytest -v --tb=short -q 2>&1 | tail -5
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/newcli/completer.py tests/test_completer.py
git commit -m "feat: add NewcliCompleter with substring skill/command matching"
```

---

## Task 5: Wire Everything into `main.py`

**Files:**
- Modify: `src/newcli/main.py`

- [ ] **Step 1: Run full test suite as baseline**

```bash
pytest -v --tb=short -q 2>&1 | tail -5
```
Expected: all PASS before touching `main.py`

- [ ] **Step 2: Update imports in `main.py`**

Replace the existing skills import line:
```python
from newcli.skills import load_skills, load_agents, match_skill
```
with:
```python
from newcli.skills import load_skills, load_skills_dir, load_agents, match_skill
```

Add after the `from newcli import ui` line:
```python
from newcli.completer import NewcliCompleter
```

- [ ] **Step 3: Update `startup()` to load from `skills/` directory**

In `startup()`, find:
```python
    # 7-8. Skills + agents
    skills = load_skills(ai_dir / "skills.md")
    agents = load_agents(ai_dir / "agents.md")
```

Replace with:
```python
    # 7-8. Skills + agents — prefer skills/ directory, fall back to skills.md
    skills_dir = ai_dir / "skills"
    if skills_dir.exists() and skills_dir.is_dir():
        skills = load_skills_dir(skills_dir)
    else:
        skills = load_skills(ai_dir / "skills.md")
    agents = load_agents(ai_dir / "agents.md")
```

- [ ] **Step 4: Add `_toolbar()` helper above `repl()`**

Add this function immediately before the `repl()` function definition:
```python
def _toolbar(ctx: RunContext) -> str:
    used = estimate_tokens(ctx.messages)
    return (
        f" mode:{ctx.config.mode}"
        f"  perm:{ctx.config.permission_mode}"
        f"  tokens:{used}/{ctx.config.context_limit}"
    )
```

- [ ] **Step 5: Replace `input()` with `PromptSession` in `repl()`**

In `repl()`, replace the entire `while True:` block's input section:

Find:
```python
    while True:
        try:
            line = input(_prompt(ctx)).strip()
        except (KeyboardInterrupt, EOFError):
            ui.print_info("\nBye.")
            break
```

Replace with:
```python
    # Set up prompt_toolkit session with history and tab completion.
    # Falls back to plain input() if prompt_toolkit is unavailable.
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory, InMemoryHistory

        history_path = pathlib.Path.home() / ".ai" / "history"
        try:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            _history = FileHistory(str(history_path))
        except OSError:
            _history = InMemoryHistory()

        _session: PromptSession = PromptSession(
            history=_history,
            completer=NewcliCompleter(commands, skills, hooks),
            complete_while_typing=True,
        )

        def _get_input() -> str:
            return _session.prompt(_prompt(ctx), bottom_toolbar=lambda: _toolbar(ctx))

    except ImportError:
        ui.print_info("prompt_toolkit not installed — history and completion unavailable.")

        def _get_input() -> str:  # type: ignore[misc]
            return input(_prompt(ctx))

    while True:
        try:
            line = _get_input().strip()
        except (KeyboardInterrupt, EOFError):
            ui.print_info("\nBye.")
            break
```

- [ ] **Step 6: Run full test suite**

```bash
pytest -v --tb=short -q 2>&1 | tail -5
```
Expected: all PASS

- [ ] **Step 7: Manual smoke test**

```bash
newcli
```
- Trust prompt → choose session or always
- Logo should appear with amber → orange-red gradient
- Prompt appears; press Up/Down → history navigates
- Type `/` → dropdown shows commands + skills
- Type `/ho` → dropdown filters to `/how` and others containing "ho"
- Type `/skills` → should show loaded skills (from `.ai/skills/` directory)
- `Ctrl-C` → clean exit

- [ ] **Step 8: Commit**

```bash
git add src/newcli/main.py
git commit -m "feat: prompt_toolkit REPL with history, inline completion, bottom toolbar; load skills from directory"
```

---

## Final Verification

```bash
# All tests pass
pytest -v

# Confirm skills load from folder
newcli
# At prompt: /skills
# Expected: lists how, karpathy-guidelines, architecture-diagram (not "No skills loaded")

# Confirm nested command routing
# At prompt: /how explain the loop module
# Expected: renders how skill with "explain the loop module" as $ARGUMENTS

# Confirm gradient: logo lines should shift amber→orange left-to-right
```
