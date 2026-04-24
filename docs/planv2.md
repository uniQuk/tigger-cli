## Plan: UI Overhaul, Workspace Trust, Modes & Permission Rename

TL;DR: Four implementation streams — workspace trust gate, `rich`-powered UI with Tigger logo + cat mascot + spinner, renamed permission modes (`ask`/`allow`/`bypass`) + new `ask`/`plan` interaction modes, and targeted bug fixes. MCP SDK + CI/CD go to backlog.

---

### Phase 1 — Dependencies + Tooling Config

1. Add `rich>=13.0` and `tiktoken>=0.7` to pyproject.toml dependencies
2. Add `[tool.ruff]` (line-length 100, select E/F/I/UP, py311 target) and `[tool.mypy]` (strict=false, ignore_missing_imports) sections to pyproject.toml
3. Add `[project.optional-dependencies] dev = ["ruff", "mypy", "pytest"]`

**Relevant files**
- pyproject.toml

---

### Phase 2 — Workspace Trust (`trust.py`)

4. Create `src/newcli/trust.py` — on startup, check if `cwd` (or any parent) is in `~/.tigger/trusted_paths.json`. If not, show a styled prompt with three choices:
   - **[T] Trust this session** — no-op, continues normally
   - **[A] Always trust** — writes path to `~/.tigger/trusted_paths.json`
   - **[D] Deny** — starts in read-only mode (only `ToolDef.read_only=True` tools available)
5. Add `TrustLevel` enum and `trust_level: TrustLevel` field to `RunContext` in types.py
6. Call `check_trust()` in `main.py::startup()` immediately after config load; if `READONLY`, restrict `ctx.allowed_tools` to read-only tool names only

**Relevant files**
- `src/newcli/trust.py` — new
- types.py — `TrustLevel` enum + field on `RunContext`
- main.py — call in `startup()`

---

### Phase 3 — Rich UI (`ui.py`)

7. Create `src/newcli/ui.py` owning all console output. Replace all `print()` calls in main.py. Exports:
   - `print_logo()` — Tigger block-letter logo + cat mascot on startup
   - `print_status(model, used, limit, mode, permission)` — styled prompt line (replaces current `status_line()`)
   - `Spinner` context manager — wraps `rich.status.Status` with rotating Tigger-themed messages (see below); starts before first provider token, stops on first `TextChunk`
   - `print_tool_start/end`, `print_error/success/info` — semantic colored helpers
   - `ask_permission(name, args) -> bool` — `rich.Confirm` replaces raw `input()` in `render_event`
   - `print_trust_prompt(cwd) -> str` — for trust.py

8. **Logo**: "TIGGER" with tiger color gradient in block ASCII + cat to the right:
   ```
   ████████╗██╗ ██████╗  ██████╗ ███████╗██████╗
      ██╔══╝...
   
    /\_____/\
   ( ^o^ ^o^ )   Tigger — AI Agent
    =( Y )=       a minimal, clean CLI
   ```

9. **Spinner messages** (rotate): `"Bouncing through the codebase..."`, `"Consulting the whiskers..."`, `"Chasing the laser pointer of insight..."`, `"T-I-double-guh-er thinking..."`, `"Sniffing out an answer..."`, `"Padding softly through your files..."`

**Relevant files**
- `src/newcli/ui.py` — new
- main.py — swap all print to ui.*, wrap spinner around provider stream

---

### Phase 4 — Permission Rename + Interaction Modes

10. Rename permission modes (config.py maps old names → new on load with a warning; permissions.py updated internally):

    | Old | New (Copilot-style) |
    |---|---|
    | `manual` | `ask` |
    | `auto` | `allow` |
    | `accept-all` | `bypass` |

11. Add `mode: str = "ask"` field to `Config` in types.py (values: `"ask"` / `"plan"`)
12. In `loop.py::run()` — when `ctx.config.mode == "plan"`, prepend `"Before taking any action, write a numbered plan of the steps you will take, then execute it."` into the system prompt for that call only (not permanently to `ctx.messages`)
13. Add `argparse` flags to `main.py::main()`: `--mode ask|plan`, `--permission ask|allow|bypass` — both override config after load
14. Add `/mode [ask|plan]` and `/permission [ask|allow|bypass]` commands to misc.py (same `dataclasses.replace` pattern as existing `/model`); register in `commands/__init__.py`

**Relevant files**
- types.py — `mode` field, permission literal
- config.py — backward compat rename, load `mode`
- permissions.py — new name checks
- loop.py — plan mode injection
- main.py — argparse
- misc.py + `commands/__init__.py` — new commands

---

### Phase 5 — Bug Fixes

15. **tiktoken counting** — `compaction.py::estimate_tokens()` uses `tiktoken.get_encoding("cl100k_base")`, with a `try/except ImportError` fallback to char/3.5
16. **Cache OpenAI client** — provider.py: module-level `dict` keyed by `(base_url, api_key)`; new `_get_client()` helper replaces inline `OpenAI(...)` in `stream()`
17. **Fix dead layer-2 compaction** — loop.py currently passes `provider_fn=None` to `maybe_compact`, preventing summarisation. Pass the real fn; fix `summarize_old` in compaction.py to call `provider_fn(system, [msg], [], config)` and collect `TextChunk` events (*parallel with step 16*)

**Relevant files**
- compaction.py — tiktoken + fix `summarize_old`
- provider.py — client cache
- loop.py — pass real provider_fn

---

### Backlog

- **Replace MCP JSON-RPC with official MCP SDK** — MCP SDK is still evolving; current stdio impl works. Revisit once SDK stabilises.
- **CI/CD pipeline** — needs ruff/mypy baseline clean (Phase 1) merged first; add in a follow-up PR.

---

### Verification

1. Cold-start in untrusted dir → trust prompt shows T/A/D choices; `D` restricts to read-only tools
2. `newcli --mode plan --permission bypass` flags reflect in `ctx.config`
3. `/mode plan` then ask a multi-step task → agent outputs numbered plan before acting
4. `/permission ask` → next bash/write call prompts even if session started as bypass
5. Tigger logo + cat render on startup; spinner fires before first streamed token
6. Token count in status bar is accurate (tiktoken)
7. `pytest` passes — no regressions
8. `ruff check src/` clean with new config

---

### Decisions

- `rich` chosen over `colorama` — handles spinners, panels, Confirm prompts, and markdown in one dep
- Permission rename is backward-compatible via config.py mapping, not a migration script
- Plan mode uses system prompt injection (not a second API call) — no latency cost
- MCP SDK and CI/CD deferred — no blocking reason now, lower ROI vs. the UI + correctness work