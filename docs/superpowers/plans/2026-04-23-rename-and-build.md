# Rename to tigger-code + Build Improvements

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the package from `newcli` to `tigger`, the CLI command from `newcli` to `tigger-code`, centralise all hardcoded paths/names into a single constants module, rename the `.ai` config directory to `.tigger`, and add a `Makefile` for common dev tasks.

**Architecture:** Introduce `src/tigger/_constants.py` as the single source of truth for the app name, CLI command name, config directory name, and version. Rename the package directory `src/newcli/` → `src/tigger/`. Update `pyproject.toml` entry point so `pip install -e .` registers the `tigger-code` command. Add a `Makefile` with `install`, `dev`, `test`, `lint`, `clean` targets.

**Tech Stack:** Python, Hatchling (build), Make

**Naming decision:** Package = `tigger` (Python import name), CLI command = `tigger-code` (shell command), config dir = `.tigger` (project and home directory).

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/tigger/_constants.py` | Single source of truth for app name, CLI name, config dir, version |
| Create | `Makefile` | Dev workflow: install, test, lint, clean |
| Rename | `src/newcli/` → `src/tigger/` | Package directory rename |
| Modify | `pyproject.toml` | Package name, entry point, wheel packages |
| Modify | `src/tigger/config.py` | Use constants for `.tigger` config dir name |
| Modify | `src/tigger/main.py` | Use constants for argparse prog, history path, trusted path |
| Modify | `src/tigger/trust.py` | Use constants for default trusted file path |
| Modify | `src/tigger/ui.py` | Use constants for config dir in setup wizard |
| Modify | `src/tigger/completer.py` | Rename `NewcliCompleter` → `TiggerCompleter` |
| Modify | All `src/tigger/**/*.py` | Update `from newcli.` → `from tigger.` imports |
| Modify | All `tests/test_*.py` | Update `from newcli.` → `from tigger.` imports |
| Modify | `README.md` | Update package name, command name, config dir references |

---

### Task 1: Create constants module and Makefile

**Files:**
- Create: `src/tigger/_constants.py`
- Create: `Makefile`

- [ ] **Step 1: Create `src/tigger/_constants.py`**

First, rename the package directory:

```bash
mv src/newcli src/tigger
```

Then create the constants file:

```python
"""Single source of truth for app identity and paths."""
from __future__ import annotations
import pathlib

APP_NAME = "tigger"
CLI_COMMAND = "tigger-code"
CONFIG_DIR = ".tigger"
VERSION = "0.1.0"


def home_config_dir() -> pathlib.Path:
    """Return ~/.tigger/ path."""
    return pathlib.Path.home() / CONFIG_DIR


def project_config_dir(project_dir: pathlib.Path) -> pathlib.Path:
    """Return <project>/.tigger/ path."""
    return project_dir / CONFIG_DIR
```

- [ ] **Step 2: Create `Makefile`**

```makefile
.PHONY: install dev test lint clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -q

test-v:
	python -m pytest tests/ -v

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

format:
	ruff format src/ tests/

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
```

- [ ] **Step 3: Commit**

```bash
git add src/tigger/_constants.py Makefile
git commit -m "feat: add constants module and Makefile for tigger rename"
```

---

### Task 2: Update pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject.toml**

Change these three lines:

```toml
# Line 6: package name
name = "tigger-code"

# Line 12: entry point — CLI command name → Python module
tigger-code = "tigger.main:main"

# Line 18: wheel package location
packages = ["src/tigger"]
```

Remove the old `newcli = ...` entry point line.

- [ ] **Step 2: Verify the build config parses**

Run: `python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['name'])"`

Expected: `tigger-code`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: update pyproject.toml for tigger-code package"
```

---

### Task 3: Bulk-rename all imports (source)

**Files:**
- Modify: All `src/tigger/**/*.py` (24 files)

This is a mechanical find-and-replace. Every occurrence of `from newcli.` becomes `from tigger.` and `import newcli` becomes `import tigger`.

- [ ] **Step 1: Run bulk rename on source files**

```bash
find src/tigger -name '*.py' -exec sed -i '' 's/from newcli\./from tigger./g; s/import newcli/import tigger/g' {} +
```

- [ ] **Step 2: Rename `NewcliCompleter` class**

In `src/tigger/completer.py`:
- `class NewcliCompleter` → `class TiggerCompleter`
- Docstring: `newcli REPL` → `tigger REPL`

In `src/tigger/main.py`:
- `from tigger.completer import NewcliCompleter` → `from tigger.completer import TiggerCompleter`
- `NewcliCompleter(` → `TiggerCompleter(`

- [ ] **Step 3: Update argparse prog name**

In `src/tigger/main.py`, find `argparse.ArgumentParser(prog="newcli")` and change to:

```python
from tigger._constants import CLI_COMMAND
# ...
parser = argparse.ArgumentParser(prog=CLI_COMMAND)
```

- [ ] **Step 4: Update the comment on line 1 of main.py**

`# src/newcli/main.py` → `# src/tigger/main.py`

- [ ] **Step 5: Verify all imports resolve**

Run: `python -c "from tigger.main import main; print('OK')"`

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/tigger/
git commit -m "refactor: rename all newcli imports to tigger in source"
```

---

### Task 4: Bulk-rename all imports (tests)

**Files:**
- Modify: All `tests/test_*.py` (15+ files)

- [ ] **Step 1: Run bulk rename on test files**

```bash
find tests -name '*.py' -exec sed -i '' 's/from newcli\./from tigger./g; s/import newcli/import tigger/g' {} +
```

- [ ] **Step 2: Update `NewcliCompleter` references in tests**

In `tests/test_completer.py`:
- `from tigger.completer import NewcliCompleter` → `from tigger.completer import TiggerCompleter`
- All usages of `NewcliCompleter` → `TiggerCompleter`

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest tests/ -q`

Expected: `167 passed`

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "refactor: rename all newcli imports to tigger in tests"
```

---

### Task 5: Centralise config directory paths using constants

**Files:**
- Modify: `src/tigger/config.py`
- Modify: `src/tigger/main.py`
- Modify: `src/tigger/trust.py`
- Modify: `src/tigger/ui.py`

This task replaces every hardcoded `".ai"` path with the constants from `_constants.py`.

- [ ] **Step 1: Update `config.py` — `find_config()`**

Replace the two hardcoded `.ai` references:

```python
from tigger._constants import CONFIG_DIR, home_config_dir

# In find_config():
# Line: candidate = current / ".ai" / "config.json"
# becomes:
candidate = current / CONFIG_DIR / "config.json"

# Line: global_cfg = pathlib.Path.home() / ".ai" / "config.json"
# becomes:
global_cfg = home_config_dir() / "config.json"
```

- [ ] **Step 2: Update `main.py` — trusted paths and history**

```python
from tigger._constants import home_config_dir

# Line: _trust.write_trusted(cwd, pathlib.Path.home() / ".ai" / "trusted_paths.json")
# becomes:
_trust.write_trusted(cwd, home_config_dir() / "trusted_paths.json")

# Line: history_path = pathlib.Path.home() / ".ai" / "history"
# becomes:
history_path = home_config_dir() / "history"
```

- [ ] **Step 3: Update `trust.py` — default trusted file**

```python
from tigger._constants import home_config_dir

# Line: _DEFAULT_TRUSTED_FILE = pathlib.Path.home() / ".ai" / "trusted_paths.json"
# becomes:
_DEFAULT_TRUSTED_FILE = home_config_dir() / "trusted_paths.json"
```

- [ ] **Step 4: Update `ui.py` — setup wizard**

```python
from tigger._constants import CONFIG_DIR, home_config_dir

# In run_setup_wizard():
# Line: console.print("  Save to [P]roject or [u]ser (~/.ai/)? [P/u]: ")
# becomes (use the constant in the prompt text):
location = input(f"  Save to [P]roject or [u]ser (~/{CONFIG_DIR}/)? [P/u]: ").strip().lower()

# Line: ai_dir = pathlib.Path.home() / ".ai"
# becomes:
ai_dir = home_config_dir()

# Line: ai_dir = project_dir / ".ai"
# becomes:
ai_dir = project_dir / CONFIG_DIR
```

- [ ] **Step 5: Verify no hardcoded `.ai` paths remain in source**

Run: `grep -rn '\.ai"' src/tigger/ --include='*.py'`

Expected: No output (or only references in comments/docs that don't construct paths)

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/ -q`

Expected: All pass. Some test fixtures construct `.ai` paths directly — those are fine since they test the behaviour, not the constant.

- [ ] **Step 7: Commit**

```bash
git add src/tigger/config.py src/tigger/main.py src/tigger/trust.py src/tigger/ui.py
git commit -m "refactor: centralise config dir paths via _constants module"
```

---

### Task 6: Update tests for `.tigger` config directory

**Files:**
- Modify: `tests/test_setup_wizard.py`
- Modify: `tests/test_config.py` (if any `.ai` path assertions)

- [ ] **Step 1: Check which tests assert `.ai` paths**

Run: `grep -rn '\.ai' tests/ --include='*.py'`

Review the output. Tests that assert specific directory names like `".ai"` need updating to `".tigger"`.

- [ ] **Step 2: Update `tests/test_setup_wizard.py`**

Find assertions like:
```python
assert config_path == tmp_path / ".ai" / "config.json"
```

Replace with:
```python
assert config_path == tmp_path / ".tigger" / "config.json"
```

And for home directory references:
```python
# ".ai" → ".tigger" in all path assertions
```

- [ ] **Step 3: Update any config discovery tests**

If `tests/test_config.py` has tests that create `.ai/config.json` fixtures, update those to `.tigger/config.json`.

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`

Expected: All 167 tests pass

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: update config dir assertions from .ai to .tigger"
```

---

### Task 7: Update README and do final install verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README.md**

Replace throughout:
- `newcli` (command name) → `tigger-code`
- `newcli` (package references) → `tigger`
- `.ai/` (config dir) → `.tigger/`
- `src/newcli/` (source layout) → `src/tigger/`

- [ ] **Step 2: Clean install and verify the CLI command works**

```bash
pip install -e .
tigger-code --help
```

Expected: The argparse help message shows `usage: tigger-code ...`

- [ ] **Step 3: Verify `make test` works**

```bash
make test
```

Expected: `167 passed`

- [ ] **Step 4: Verify `make lint` works**

```bash
make lint
```

Expected: Clean output (or known warnings only)

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: update README for tigger-code rename"
```

---

### Task 8: Clean up old package artifacts

- [ ] **Step 1: Uninstall the old `newcli` package**

```bash
pip uninstall newcli -y 2>/dev/null || true
```

- [ ] **Step 2: Clean build artifacts**

```bash
make clean
```

- [ ] **Step 3: Reinstall fresh**

```bash
make install
```

- [ ] **Step 4: Final verification — run the app**

```bash
tigger-code --help
```

Expected: Shows the Tigger CLI help with proper program name.

- [ ] **Step 5: Run full test suite one last time**

```bash
make test
```

Expected: All tests pass.

- [ ] **Step 6: Commit any remaining cleanup**

```bash
git add -A
git commit -m "chore: clean up old newcli artifacts after rename"
```

---

## Notes

- **Documentation in `docs/`**: The old plan files (`plan.md`, `planv2.md`, `implementationplan.md`, etc.) reference `newcli` extensively. These are historical records — **do not update them**. They document what the project was called when those plans were written.
- **The `.ai` → `.tigger` rename** is a breaking change for any existing config directories. Users would need to `mv .ai .tigger` in their projects. This is acceptable at v0.1.0.
- **Logo in `ui.py`** already says "Tigger" — no change needed there.
- **`_constants.py` as single source of truth** means future renames only require changing 4 strings in one file + `pyproject.toml`.
