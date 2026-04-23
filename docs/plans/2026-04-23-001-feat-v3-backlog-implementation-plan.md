---
title: "feat: Implement Tigger CLI v3 backlog"
type: feat
status: completed
date: 2026-04-23
origin: docs/superpowers/plans/planv3-backlog.md
---

# feat: Implement Tigger CLI v3 backlog

## Overview

Implement all 15 items from the v3 backlog across four phases: quick wins (S), medium features (M), large features (L), and deferred/speculative items. The backlog originated from a Qwen Code CLI analysis and internal UX review. Items have been consolidated, re-prioritised by effort, and annotated with caveats from a prior simplify + Karpathy review.

## Problem Frame

Tigger is a functional multi-provider AI chat CLI but has UX gaps: silent compaction, no per-command help, append-only memory, weak plan mode enforcement, no file injection syntax, no session persistence, and no project scaffolding command. These gaps reduce discoverability, user confidence, and productivity.

## Requirements Trace

- R1. Compaction must provide visual feedback and show what it did
- R2. `/help` must show descriptions and support per-command detail including `/help agent`
- R3. Memory must support search and delete subcommands
- R4. Plan mode must prevent tool execution before plan confirmation
- R5. Compaction prompt must use structured XML format for higher-quality summaries
- R6. `/summary` command must save session state to markdown
- R7. `@file` syntax must inline file contents with size safety
- R8. LLM must be able to persist facts mid-session via a `remember` tool
- R9. `/init` must scaffold `.tigger/` project files without overwriting
- R10. Per-model config must allow model-specific sampling overrides
- R11. `--continue` must resume a previous session from disk
- R12. Input bar must have styled borders and placeholder text
- R13. Tool calls must be displayable in a collapsible UI or toolbar summary
- R14. Subagent system reminder must inject agent names when infrastructure exists
- R15. Insight/analytics must be available if user demand emerges

## Scope Boundaries

- No changes to the provider protocol or streaming interface (except passing `thinking` param for R10)
- No multi-agent dispatch framework (R14 deferred until that exists)
- No project-type detection in `/init` (generic templates only)
- `/summary` saves to disk only, no cloud sync
- Per-model config only when a concrete model needs different params
- Analytics (R15) is speculative — plan documents but does not implement

## Context & Research

### Relevant Code and Patterns

- **Command pattern:** `(args: str, ctx: RunContext) -> None`, registered in `commands/__init__.py` via `load_builtin_commands()`, extra deps bound with `functools.partial`
- **Config mutation:** `dataclasses.replace()` on frozen `Config`, reassign `ctx.config`
- **Tool registration:** `ToolDef` instances in `tools.py:register_all()`, `registry.register()`
- **UI output:** `ui.py` owns all Rich rendering; `Spinner` context manager at L151; custom amber theme
- **Memory:** `memory.py` — `read_memory()` returns `list[str]`, `append_memory()` writes timestamped lines, `format_for_prompt()` wraps for system prompt injection at startup
- **Compaction:** `compaction.py` — Layer 1 snips tool results, Layer 2 LLM-summarises; `maybe_compact()` called every turn in `loop.py:31`
- **Constants:** `_constants.py` — `CONFIG_DIR = ".tigger"`, `home_config_dir()`; never hardcode `.tigger` elsewhere
- **Test pattern:** pytest with `capsys`, `monkeypatch`, `tmp_path`, fake providers; 167 tests pass

### Institutional Learnings

- TDD discipline: write failing test first, confirm failure, implement, confirm pass
- Bottom-up layering: types -> config -> utilities -> commands -> wiring
- `RunContext` is the only inter-module flow object; tools and provider don't see it
- `estimate_tokens` lives only in `compaction.py` — don't duplicate
- Tool output truncated at 32KB in `registry.execute()` — one place
- `write` tool refuses if file exists — correctness invariant, don't change
- Skills directory (`load_skills_dir`) preferred over flat `skills.md` file
- Old plan docs reference `newcli` and `.ai` — historical, don't update them

## Key Technical Decisions

- **Compaction returns metadata:** `maybe_compact()` will return a `CompactResult` namedtuple with snip/summarize counts rather than mutating `ctx.messages` silently. Rationale: enables both spinner UX and progress breakdown without changing the compaction algorithm.
- **Memory subcommands via arg parsing:** `/memory search <q>` and `/memory delete <n>` dispatch within `cmd_memory` on the first token of `args`. Rationale: consistent with existing `/model` and `/provider` arg parsing patterns; no framework needed.
- **`@file` expansion in REPL, not in loop:** Pre-process `@path` in `main.py` before `run()`. Rationale: keeps `loop.py` pure (it receives text, not file references); size cap enforced at expansion time.
- **Session persistence as JSON lines:** Messages serialised as one JSON object per line in `.tigger/sessions/`. Rationale: append-friendly, human-readable, no schema migration needed; lazy-loaded only on `--continue`.
- **Per-model config as union type:** `ProviderConfig.models` becomes `list[str] | dict[str, ModelConfig]`. Rationale: backward-compatible with existing simple lists; resolution order (model > global > default) is clear.
- **Help descriptions as a dict, not docstrings:** `COMMAND_DESCRIPTIONS: dict[str, str]` in `commands/__init__.py`. Rationale: co-located with registration, greppable, no introspection magic.

## Open Questions

### Resolved During Planning

- **Should `@file` support globs?** No — single file paths only for v1. Globs add complexity with minimal value.
- **Should memory auto-save rebuild the system prompt?** No — accept the lag. Rebuilding mid-session would invalidate the provider's message cache and the complexity isn't justified for a note-taking tool.
- **Should session resume replay tool calls?** No — load messages as-is. Tool results are already in the message history; re-executing would be destructive.

### Deferred to Implementation

- Exact `CompactResult` field names — will emerge from test scenarios
- Whether `@file` needs shell expansion (`~/`) or just literal paths
- Optimal session file naming scheme (timestamp? incrementing ID?)

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```mermaid
graph TB
    subgraph "Phase 1: Quick Wins"
        U1[Compact UX] --> U2[Help Overhaul]
        U2 --> U3[Memory Subcommands]
        U3 --> U4[Plan Mode]
    end

    subgraph "Phase 2: Medium Features"
        U5[Compression Prompt] --> U6[/summary Command]
        U7[@file Syntax]
        U8[Remember Tool]
        U9[/init Command]
        U10[Per-Model Config]
    end

    subgraph "Phase 3: Large Features"
        U11[Session Resume]
        U12[Input Bar Styling]
        U13[Collapsible Tool Display]
    end

    subgraph "Phase 4: Deferred"
        U14[Subagent Reminder]
        U15[Analytics]
    end

    U1 --> U5
    U3 --> U8
    U10 --> U5
```

## Implementation Units

### Phase 1: Quick Wins

- [ ] **Unit 1: Compact UX — spinner + progress breakdown**

**Goal:** Add visual feedback during `/compact` and show what compaction did.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `src/tigger/compaction.py`
- Modify: `src/tigger/commands/compact.py`
- Create: `tests/test_compact_cmd.py`

**Approach:**
- Add a `CompactResult` namedtuple to `compaction.py` with fields for messages snipped, messages summarised, tokens before, tokens after
- Change `maybe_compact()` to return `CompactResult` instead of `None`
- Update `cmd_compact` to wrap `maybe_compact()` in `ui.Spinner` context manager and print the breakdown from `CompactResult`
- Update `loop.py` to handle the return value (ignore it — auto-compaction stays silent)

**Patterns to follow:**
- `ui.Spinner` usage in `main.py` repl loop
- `estimate_tokens()` calls already in `cmd_compact`

**Test scenarios:**
- Happy path: `/compact` with messages above threshold returns correct snip/summarize counts and prints breakdown
- Happy path: `/compact` with `force=True` compacts regardless of threshold
- Edge case: `/compact` with no messages returns zero counts
- Edge case: `/compact` below threshold with `force=False` returns early with no-op result

**Verification:**
- `pytest tests/test_compact_cmd.py` passes
- Running `/compact` in the REPL shows a spinner and prints a breakdown like "Snipped 14 tool results, summarized 12 messages: 5840 → 2100 tokens"

---

- [ ] **Unit 2: Help system overhaul**

**Goal:** Add command descriptions to `/help`, per-command detail with `/help <cmd>`, and `/help agent` documentation.

**Requirements:** R2

**Dependencies:** None

**Files:**
- Modify: `src/tigger/commands/__init__.py`
- Modify: `src/tigger/commands/misc.py`
- Modify: `tests/test_commands.py` (or create `tests/test_help.py`)

**Approach:**
- Add `COMMAND_DESCRIPTIONS: dict[str, str]` in `commands/__init__.py` alongside command registration
- Modify `cmd_help` to: (a) print descriptions next to each command name, (b) if `args` is non-empty, dispatch to per-command detail
- Per-command detail: a `COMMAND_HELP: dict[str, str]` with multi-line usage strings
- Add `/help agent` entry explaining the `agents.md` format and `.tigger/` location

**Patterns to follow:**
- Existing `cmd_help` iteration over `sorted(commands)`
- `cmd_model` arg parsing pattern (split on first space)

**Test scenarios:**
- Happy path: `/help` with no args lists all commands with descriptions
- Happy path: `/help model` shows detailed model command usage
- Happy path: `/help agent` shows agents.md format documentation
- Edge case: `/help nonexistent` prints "Unknown command" message

**Verification:**
- Tests pass
- `/help` output includes one-line descriptions; `/help model` shows detailed usage

---

- [ ] **Unit 3: Memory subcommands (search + delete)**

**Goal:** Add `/memory search <query>` and `/memory delete <n>` subcommands.

**Requirements:** R3

**Dependencies:** None

**Files:**
- Modify: `src/tigger/commands/memory.py`
- Modify: `src/tigger/memory.py`
- Modify: `tests/test_memory.py`

**Approach:**
- Add `search_memory(path, query) -> list[tuple[int, str]]` to `memory.py` — returns matching lines with indices
- Add `delete_memory(path, index: int)` to `memory.py` — removes line by index, rewrites file
- Modify `cmd_memory` to parse first token of `args`: `search`, `delete`, or empty (existing list behavior)
- `/memory delete all` or `/memory clear` wipes the file

**Patterns to follow:**
- `read_memory()` file reading pattern
- `append_memory()` file writing pattern
- `cmd_model` arg dispatch pattern

**Test scenarios:**
- Happy path: `/memory search foo` returns only lines containing "foo" with indices
- Happy path: `/memory delete 3` removes the 3rd entry
- Happy path: `/memory clear` empties the file
- Edge case: `/memory search` with no query prints usage
- Edge case: `/memory delete 99` with only 5 entries prints error
- Edge case: `/memory search nomatch` prints "No matches"

**Verification:**
- `pytest tests/test_memory.py` passes
- Manual REPL test: add entries, search, delete by index, verify

---

- [ ] **Unit 4: Tighter plan mode prompt**

**Goal:** Prevent the model from executing tools before presenting a plan.

**Requirements:** R4

**Dependencies:** None

**Files:**
- Modify: `src/tigger/loop.py`
- Modify: `tests/test_loop.py`

**Approach:**
- Replace the weak plan mode injection string (~line 39) with explicit instructions: forbid edits/tool use, require presenting plan via structured output, model must wait for user confirmation
- Keep it as a system prompt append — no new infrastructure

**Patterns to follow:**
- Existing plan mode injection at `loop.py` L39-43

**Test scenarios:**
- Happy path: in plan mode, the system prompt includes the stronger plan-mode instruction text
- Happy path: the instruction text contains "MUST NOT" and "tool" to enforce no premature execution

**Verification:**
- `pytest tests/test_loop.py` passes
- Manual test: enter plan mode, give a multi-step request, confirm model presents plan before acting

---

### Phase 2: Medium Features

- [ ] **Unit 5: Structured compression prompt**

**Goal:** Replace the loose summarisation prompt with XML `<state_snapshot>` format and fix the 500-char truncation bottleneck.

**Requirements:** R5

**Dependencies:** Unit 1 (CompactResult exists)

**Files:**
- Modify: `src/tigger/compaction.py`
- Modify: `tests/test_compaction.py`

**Approach:**
- Remove or significantly raise the `m.content[:500]` truncation in `summarize_old()`
- Replace the hardcoded prompt string with a structured XML template requesting: `overall_goal`, `key_knowledge`, `file_system_state`, `recent_actions`, `current_plan`
- Keep the same two-layer compaction architecture

**Patterns to follow:**
- Existing `summarize_old()` structure
- Qwen's `getCompressionPrompt()` as inspiration (in `z_no_upload/prompts.ts`)

**Test scenarios:**
- Happy path: `summarize_old()` prompt contains XML tags for structured output
- Happy path: messages longer than 500 chars are not truncated (or truncated at a much higher limit)
- Edge case: empty message list produces valid prompt
- Integration: full `maybe_compact()` with fake provider produces structured summary

**Verification:**
- `pytest tests/test_compaction.py` passes
- Manual test: long session followed by `/compact` produces structured summary with goal/knowledge/actions

---

- [ ] **Unit 6: `/summary` command**

**Goal:** Save a session summary to markdown in `.tigger/summaries/`.

**Requirements:** R6

**Dependencies:** None (but benefits from structured compression prompt if available)

**Files:**
- Create: `src/tigger/commands/summary.py`
- Modify: `src/tigger/commands/__init__.py`
- Create: `tests/test_summary_cmd.py`

**Approach:**
- New `cmd_summary(args, ctx, ai_dir, provider_fn)` that: (a) sends `ctx.messages` to the provider with a summary prompt, (b) saves the response to `.tigger/summaries/YYYY-MM-DD-HHMMSS.md`
- Summary prompt requests: Overall Goal, Key Knowledge, Recent Actions, Current Plan sections
- `ai_dir` is the `.tigger/` path, bound via `partial` in `__init__.py`

**Patterns to follow:**
- `cmd_compact` for calling provider functions from a command
- `append_memory` for file writing patterns
- `_constants.py` for path construction

**Test scenarios:**
- Happy path: `/summary` creates a markdown file in the summaries directory with expected sections
- Happy path: summary file name includes timestamp
- Edge case: summaries directory doesn't exist yet — created automatically
- Edge case: empty session produces a minimal summary

**Verification:**
- Tests pass
- Manual test: after a conversation, `/summary` creates a readable markdown file

---

- [ ] **Unit 7: `@file` syntax**

**Goal:** Allow `@path/to/file` in messages to inline file contents.

**Requirements:** R7

**Dependencies:** None

**Files:**
- Modify: `src/tigger/main.py`
- Modify: `src/tigger/completer.py`
- Create: `tests/test_file_injection.py`

**Approach:**
- Add `expand_file_refs(line: str) -> str` function in `main.py` (or a small `input_processing.py` module)
- Regex match `@(\S+)` patterns, read each file, inline contents with a header like `--- Contents of path ---`
- Enforce a 50KB size cap per file with a warning printed to stderr
- Call `expand_file_refs()` in the REPL before passing to `run()`
- Extend `TiggerCompleter` to offer path completions after `@`

**Patterns to follow:**
- `_get_input()` in `main.py` for REPL input handling
- `TiggerCompleter.get_completions()` for completion patterns

**Test scenarios:**
- Happy path: `@README.md` expands to file contents with header
- Happy path: multiple `@file` references in one message all expand
- Edge case: `@nonexistent.txt` prints warning and leaves reference as-is
- Edge case: file over 50KB prints warning and truncates
- Edge case: `@` alone or `@` followed by space is not expanded

**Verification:**
- Tests pass
- Manual test: type `explain @src/tigger/main.py` and confirm file contents are sent to the model

---

- [ ] **Unit 8: Memory auto-save tool (`remember`)**

**Goal:** Register a `remember` tool so the LLM can persist facts during conversation.

**Requirements:** R8

**Dependencies:** Unit 3 (memory module enhanced)

**Files:**
- Modify: `src/tigger/tools.py`
- Modify: `tests/test_tools.py`

**Approach:**
- Add a `_remember(note: str, *, memory_path: Path) -> str` function in `tools.py`
- Register as a `ToolDef` in `register_all()` with `read_only=False`
- Tool calls `append_memory(memory_path, note)` and returns confirmation
- Accept the lag: system prompt is not rebuilt mid-session

**Patterns to follow:**
- Existing `ToolDef` registration in `register_all()`
- `_bash()` function pattern for tool implementations with bound paths

**Test scenarios:**
- Happy path: calling the remember tool appends a timestamped entry to memory file
- Happy path: tool returns confirmation message
- Edge case: empty note returns error message
- Integration: tool is discoverable in registry and has correct schema

**Verification:**
- `pytest tests/test_tools.py` passes
- Manual test: ask the model to "remember that I prefer tabs" — confirm entry appears in memory

---

- [ ] **Unit 9: `/init` command**

**Goal:** Scaffold `.tigger/` project files interactively.

**Requirements:** R9

**Dependencies:** None

**Files:**
- Create: `src/tigger/commands/init.py`
- Modify: `src/tigger/commands/__init__.py`
- Create: `tests/test_init_cmd.py`

**Approach:**
- New `cmd_init(args, ctx)` that creates `.tigger/` with: `agents.md` (template), `skills/` directory with example `SKILL.md`, `system.md` (customisable system prompt), `hooks.py` (commented-out examples)
- Skip `config.json` — already handled by setup wizard
- Check each file before creating; never overwrite existing files
- Print what was created and what was skipped

**Patterns to follow:**
- `_constants.py` for `CONFIG_DIR`
- `run_setup_wizard()` in `ui.py` for interactive project setup patterns
- `load_agents()` and `load_skills_dir()` for expected file formats

**Test scenarios:**
- Happy path: `/init` in empty directory creates all scaffold files
- Happy path: `/init` with existing `agents.md` skips it and reports "skipped"
- Edge case: `.tigger/` directory doesn't exist — created automatically
- Edge case: all files already exist — nothing created, reports "all files present"

**Verification:**
- Tests pass
- Manual test: `/init` in a fresh project creates usable template files

---

- [ ] **Unit 10: Per-model sampling params**

**Goal:** Allow per-model overrides for temperature, max_tokens, context_limit, top_p, thinking.

**Requirements:** R10

**Dependencies:** None

**Files:**
- Modify: `src/tigger/types.py`
- Modify: `src/tigger/config.py`
- Modify: `src/tigger/provider.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_types.py`

**Approach:**
- Add `ModelConfig` dataclass to `types.py` with optional fields: `temperature`, `max_tokens`, `context_limit`, `top_p`, `thinking`
- Change `ProviderConfig.models` from `list[str]` to `list[str] | dict[str, ModelConfig]`
- Update `load_config()` to parse both formats
- Update `write_config()` to serialise dict format when model configs are non-empty
- Update `switch_model()` to merge model-specific overrides into `Config` via `dataclasses.replace()`
- Update `provider.py:stream()` to pass `thinking` param when set

**Patterns to follow:**
- `ProviderConfig` and `Config` dataclass patterns in `types.py`
- `load_config()` dual-format handling (already handles old flat + new providers format)
- `switch_model()` replacement pattern

**Test scenarios:**
- Happy path: config with dict-style models loads and resolves model-specific temperature
- Happy path: config with list-style models still loads (backward compat)
- Happy path: `switch_model()` merges model overrides with global defaults
- Happy path: `write_config()` preserves dict-style model configs
- Edge case: model not in dict uses global defaults
- Edge case: model config with empty dict `{}` uses all defaults
- Error path: invalid model config field type raises validation error

**Verification:**
- `pytest tests/test_config.py tests/test_types.py` passes
- Manual test: configure per-model temperature, switch models, verify different temperatures apply

---

### Phase 3: Large Features

- [ ] **Unit 11: Session resume (`--continue`)**

**Goal:** Persist sessions to disk and resume with `--continue` flag.

**Requirements:** R11

**Dependencies:** None

**Files:**
- Create: `src/tigger/sessions.py`
- Modify: `src/tigger/main.py`
- Modify: `src/tigger/loop.py`
- Create: `tests/test_sessions.py`

**Approach:**
- New `sessions.py` module with: `save_session(session_dir, messages)`, `load_session(session_dir, session_id) -> list[Message]`, `list_sessions(session_dir) -> list[SessionInfo]`
- Messages serialised as JSON lines in `.tigger/sessions/<timestamp>.jsonl`
- Add `--continue` / `-c` flag to argparse in `main.py`
- On `--continue`: load most recent session, populate `ctx.messages`, skip greeting
- Auto-save: append messages to session file after each turn in `loop.py` or `repl()`
- Lazy-load only — no deserialization at startup unless `--continue` is passed

**Patterns to follow:**
- `Message` dataclass serialisation (need `to_dict()`/`from_dict()` methods)
- argparse setup in `main.py:main()`
- `_constants.py` for session directory path

**Test scenarios:**
- Happy path: session is saved after each turn as JSONL
- Happy path: `--continue` loads the most recent session and populates messages
- Happy path: `list_sessions()` returns sessions sorted by recency
- Edge case: `--continue` with no existing sessions prints error and starts fresh
- Edge case: corrupt JSONL file is handled gracefully (skip bad lines, warn)
- Edge case: very large session file loads without excessive startup delay

**Verification:**
- Tests pass
- Manual test: have a conversation, exit, restart with `--continue`, confirm context is restored

---

- [ ] **Unit 12: Input bar styling**

**Goal:** Add horizontal rules and placeholder text to the input area.

**Requirements:** R12

**Dependencies:** None

**Files:**
- Modify: `src/tigger/main.py`

**Approach:**
- Customise `PromptSession` with `FormattedTextControl` for styled borders
- Add placeholder text like "Type your message or @path/to/file" using prompt_toolkit's `placeholder` parameter
- Use the existing amber theme colours from `ui.py`

**Patterns to follow:**
- Existing `PromptSession` setup in `main.py`
- prompt_toolkit `placeholder` parameter

**Test expectation: none -- pure cosmetic change, visual verification only**

**Verification:**
- Visual inspection: input area has horizontal rules and faint placeholder text
- No functional regressions in REPL input handling

---

- [ ] **Unit 13: Collapsible tool call display / toolbar summary**

**Goal:** Show tool call activity in the UI, either as a collapsible display or a toolbar summary.

**Requirements:** R13

**Dependencies:** None

**Files:**
- Modify: `src/tigger/main.py` (toolbar)
- Modify: `src/tigger/ui.py` (event tracking)

**Approach:**
- **Start with the cheaper alternative:** track last N tool names in a list, display in `_toolbar()`. Evaluate whether this is sufficient before building the full prompt_toolkit Live layout.
- Add a `recent_tools: list[str]` field to `RunContext` or a module-level deque in `ui.py`
- Update `render_event()` to append tool names on `ToolStartEvent`
- Update `_toolbar()` to show last 3-5 tool names

**Patterns to follow:**
- `_toolbar()` in `main.py`
- `render_event()` event dispatch in `ui.py`

**Test scenarios:**
- Happy path: after tool execution, toolbar shows tool name
- Happy path: toolbar shows last N tools, oldest dropped
- Edge case: no tools executed yet — toolbar shows default content only

**Verification:**
- Tests pass
- Manual test: run queries that trigger tools, confirm toolbar updates

---

### Phase 4: Deferred

- [ ] **Unit 14: Subagent system reminder**

**Goal:** Inject available agent names into a system reminder so the model can delegate.

**Requirements:** R14

**Dependencies:** Agent dispatch framework (does not exist yet)

**Files:**
- Modify: `src/tigger/main.py` (system prompt construction)
- Modify: `src/tigger/loop.py` (system prompt injection)

**Approach:**
- Append agent names from loaded `AgentDef` list to the system prompt at startup (not per-turn)
- Format: "Available agents: name1 (description), name2 (description). Use /agent <name> to delegate."
- Only inject when agents are loaded (non-empty list)

**Patterns to follow:**
- Memory injection into system prompt at `main.py` L94-96
- `load_agents()` in `skills.py`

**Test expectation: none -- blocked on agent dispatch infrastructure that doesn't exist yet. Implement when multi-agent support is built.**

**Verification:**
- System prompt contains agent names when agents are loaded
- Model can reference agents by name

---

- [ ] **Unit 15: Insight/analytics prompts**

**Goal:** Post-session analysis of interaction patterns.

**Requirements:** R15

**Dependencies:** Session persistence (Unit 11)

**Files:**
- TBD — large scope, speculative

**Approach:**
- Analyse saved session data for: interaction style, friction points, impressive workflows, future opportunities
- Full analytics feature — only implement if user demand emerges

**Test expectation: none -- speculative feature, not scheduled for implementation**

**Verification:**
- Defer until demand is established

## System-Wide Impact

- **Interaction graph:** `maybe_compact()` return value change (Unit 1) affects `loop.py` and `cmd_compact` — both must handle `CompactResult`. Session auto-save (Unit 11) adds a write after each turn in the REPL or loop.
- **Error propagation:** `@file` expansion errors (Unit 7) must be non-fatal — print warning, leave reference as-is. Session load errors (Unit 11) must be non-fatal — warn and start fresh.
- **State lifecycle:** Memory file concurrent access is not a concern (single-process CLI). Session files should be append-only during a session to avoid data loss.
- **API surface parity:** Per-model config (Unit 10) affects config file format — must remain backward-compatible with existing `list[str]` format.
- **Integration coverage:** Unit 1 (CompactResult) must be tested through both `cmd_compact` and `loop.py` code paths. Unit 8 (remember tool) must be tested through the tool registry, not just the raw function.
- **Unchanged invariants:** `Config` remains frozen. `RunContext` remains the inter-module flow object. `estimate_tokens` stays in `compaction.py`. Tool output 32KB truncation unchanged. `write` tool file-exists refusal unchanged.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `CompactResult` changes break existing `maybe_compact()` callers | Only two callers (`loop.py`, `cmd_compact`). Update both in Unit 1. |
| Per-model config `write_config()` drops dict-form models | Explicit test case for round-trip serialisation in Unit 10 |
| `@file` expansion bloats context for large files | 50KB cap with warning; enforced at expansion time |
| Session JSONL files grow large over time | Not addressed in v3 — future work for session rotation/cleanup |
| `remember` tool writes not visible to model mid-session | Documented decision: accept the lag. System prompt not rebuilt. |
| Plan mode prompt still bypassable by sufficiently determined models | Acceptable — this is a UX guardrail, not a security boundary |

## Sources & References

- **Origin document:** [docs/superpowers/plans/planv3-backlog.md](docs/superpowers/plans/planv3-backlog.md)
- Qwen Code CLI analysis: `z_no_upload/prompts.ts`
- Architecture: `docs/plan.md`, `docs/planv2.md`
- Key modules: `src/tigger/compaction.py`, `src/tigger/memory.py`, `src/tigger/commands/misc.py`, `src/tigger/loop.py`, `src/tigger/config.py`, `src/tigger/types.py`
