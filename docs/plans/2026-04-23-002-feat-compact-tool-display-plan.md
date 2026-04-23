---
title: "feat: Compact & Batched Tool Call Display"
type: feat
status: active
date: 2026-04-23
---

# feat: Compact & Batched Tool Call Display

## Overview

Replace the verbose inline `⏺ tool_name(args)` output on every tool call with a single grouped summary block rendered after each batch of tool executions. Batch consecutive file-oriented tool calls (read, glob, grep) into one line. This is a UI-only change — no modifications to tool execution, permissions, or the agent loop.

## Problem Frame

When the agent executes many tool calls in a single turn (especially sequences of reads or greps), the terminal fills with noisy per-call lines that obscure the model's reasoning. Users need visibility into *what* was accessed but not a line-by-line log of every call as it happens.

## Requirements Trace

- R1. Tool execution logs must not interleave with assistant text output
- R2. All tool calls within a model round are rendered once as a grouped block
- R3. Repeated file-oriented tool calls (read, glob, grep) are batched into a single line
- R4. Each entry shows tool name + concise human-readable preview
- R5. Permission prompts remain unchanged and render inline
- R6. No changes to tool execution semantics (UI-only)

## Scope Boundaries

- Only `src/tigger/ui.py` is modified (presentation layer)
- The agent loop (`loop.py`) and tool registry are untouched
- Permission flow is untouched — `PermissionEvent` still renders immediately
- The `recent_tools` deque continues to be updated on `ToolStartEvent`

## Context & Research

### Relevant Code and Patterns

- `src/tigger/ui.py:201-226` — `render_event` function: current event dispatch
- `src/tigger/ui.py:182-191` — `_fmt_args`: current argument formatting
- `src/tigger/ui.py:194-198` — `_flush_text`: pattern for buffering and flushing content
- `src/tigger/loop.py:53-123` — Event yield order per model round: `TextChunk...` → `TurnDoneEvent` → `[PermissionEvent?]` → `ToolStartEvent` → `ToolEndEvent` → (repeat for each tool) → (next round or break)
- `src/tigger/types.py:104-130` — Event dataclasses defining available fields

### Event Flow Analysis

Within one `while True` iteration of the agent loop:
1. Model streams text → yields `TextChunk`s
2. Assistant message recorded → yields `TurnDoneEvent`
3. For each tool call: optionally `PermissionEvent`, then `ToolStartEvent`, then `ToolEndEvent`
4. Loop continues for next model round (back to step 1) or breaks

This means `TurnDoneEvent` fires *before* tool execution in each round. Tool summary must therefore flush on the *next* text output or at the very end of the event stream.

## Key Technical Decisions

- **Buffer tool calls, flush on next text or turn end**: Since `TurnDoneEvent` precedes tool execution in each round, the tool summary block should be flushed when the next `TextChunk` arrives (indicating the model is responding after seeing tool results) or when the event stream ends (handled by `_flush_text` in main.py's turn-end path). This naturally places the tool block between tool execution and the model's next response.

- **Flush tool buffer alongside text buffer**: Add a `_flush_tools` call at the same points `_flush_text` is called (before tool events and at turn end), plus a new flush point: when `TextChunk` arrives and the tool buffer is non-empty. This keeps the tool summary visually separated from model text.

- **Batchable tool set is fixed**: `read`, `glob`, `grep` are the batchable tools. Bash and other tools render individually. This avoids over-abstraction while covering the high-frequency cases.

- **Preview extraction is tool-specific**: Each batchable tool has a known primary argument (`file_path` for read, `pattern` for glob/grep). Extract the meaningful value from that field. Non-batchable tools fall back to truncated `_fmt_args`.

- **Tool buffer is module-level state**: Following the existing pattern of `recent_tools` (module-level `deque`), the tool buffer uses module-level state in `ui.py`. Reset happens implicitly — the buffer is drained on flush.

## Open Questions

### Resolved During Planning

- **Where to render the tool block?** After tool execution completes, before the next model text. Flushing on next `TextChunk` arrival achieves this naturally.
- **How to handle PermissionEvent interleaving?** Permission prompts still render immediately (R5). The tool buffer accumulates around them — a denied tool still appears in the buffer (marked if needed), and granted tools proceed normally. The permission prompt itself is not buffered.

### Deferred to Implementation

- **Exact truncation threshold for (+N more)**: Start with showing 5 items before truncating. Adjust based on visual testing.
- **Whether denied tools should appear in the summary**: Likely yes with a `(denied)` suffix, but verify during implementation what feels right.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
State: _tool_buffer: list[tuple[str, str]]  # (tool_name, preview_string)

On ToolStartEvent:
  - append (name, preview) to buffer
  - update recent_tools (existing behavior)
  - suppress the inline print

On ToolEndEvent:
  - if denied or error: annotate the last buffer entry
  - otherwise: silent (existing behavior for success)

On TextChunk (when buffer non-empty):
  - flush tool buffer as grouped block
  - then append text as normal

On TurnDoneEvent:
  - flush tool buffer (if non-empty)
  - flush text buffer (existing behavior)

Flush tool buffer:
  - group consecutive same-name batchable entries
  - render each group as one line
  - render non-batchable entries individually
  - clear buffer
```

Rendered output shape:
```
──────── tools ────────
read: main.py, ui.py, config.py (+2 more)
grep: "load_config"
bash: ls -la
───────────────────────
```

## Implementation Units

- [x] **Unit 1: Tool buffer and preview extraction**

**Goal:** Introduce the tool buffer, preview extraction logic, and the flush rendering function.

**Requirements:** R2, R3, R4

**Dependencies:** None

**Files:**
- Modify: `src/tigger/ui.py`
- Modify: `tests/test_ui.py`

**Approach:**
- Add a module-level `_tool_buffer: list[tuple[str, str]]` (following `recent_tools` pattern)
- Add `_extract_preview(name, args)` → returns a short human-readable string:
  - `read` → basename from `file_path` arg
  - `glob` → `pattern` arg
  - `grep` → `pattern` arg (quoted)
  - `bash` → `command` arg truncated to ~60 chars
  - fallback → truncated `_fmt_args` output
- Add `_flush_tool_buffer()` that:
  - groups consecutive entries with the same name where name is in `BATCHABLE_TOOLS = {"read", "glob", "grep"}`
  - renders each group: `name: preview1, preview2 (+N more)` with truncation after ~5 items
  - renders non-batchable entries individually: `name: preview`
  - wraps output in a rule-bordered block using Rich
  - clears the buffer

**Patterns to follow:**
- `_flush_text` (line 194) for the flush pattern
- `_fmt_args` (line 182) for argument formatting style
- `recent_tools` (line 27) for module-level mutable state

**Test scenarios:**
- Happy path: `_extract_preview("read", {"file_path": "/foo/bar/baz.py"})` returns `"baz.py"`
- Happy path: `_extract_preview("grep", {"pattern": "load_config"})` returns `'"load_config"'`
- Happy path: `_extract_preview("glob", {"pattern": "**/*.py"})` returns `"**/*.py"`
- Happy path: `_extract_preview("bash", {"command": "ls -la"})` returns `"ls -la"`
- Edge case: `_extract_preview("bash", {"command": "a" * 100})` truncates to ~60 chars with `...`
- Edge case: `_extract_preview("unknown_tool", {"x": 1})` falls back to truncated repr
- Happy path: `_flush_tool_buffer` with 3 reads groups them into one line
- Happy path: `_flush_tool_buffer` with interleaved read, grep, read produces three lines (batching only consecutive)
- Edge case: `_flush_tool_buffer` with 7 reads shows 5 + `(+2 more)`
- Edge case: `_flush_tool_buffer` with empty buffer produces no output

**Verification:**
- All new unit tests pass
- `_extract_preview` returns concise, readable strings for each tool type
- `_flush_tool_buffer` output matches the expected grouped format

---

- [x] **Unit 2: Wire buffer into render_event**

**Goal:** Modify `render_event` to buffer tool calls instead of printing inline, and flush the buffer at the right moments.

**Requirements:** R1, R2, R5, R6

**Dependencies:** Unit 1

**Files:**
- Modify: `src/tigger/ui.py`
- Modify: `tests/test_ui.py`

**Approach:**
- In `render_event`, on `ToolStartEvent`:
  - Still update `recent_tools` (preserve existing behavior)
  - Call `_extract_preview` and append to `_tool_buffer`
  - Remove the inline `console.print(f"⏺ ...")` call
- On `ToolEndEvent`:
  - If denied or error, annotate the corresponding buffer entry (or append a note)
  - Keep existing error/denied output for immediate feedback — these still print inline since the user needs to see them
- On `TextChunk`:
  - If `_tool_buffer` is non-empty, call `_flush_tool_buffer()` before appending text
- On `TurnDoneEvent`:
  - Call `_flush_tool_buffer()` before `_flush_text(text_buf)`

**Patterns to follow:**
- Existing `render_event` dispatch structure
- `_flush_text` call placement

**Test scenarios:**
- Happy path: Render a sequence of `ToolStartEvent` → `ToolEndEvent` → `TextChunk` — tool summary block appears before text, no inline `⏺` lines
- Happy path: Render `ToolStartEvent` → `ToolEndEvent` → `TurnDoneEvent` — tool summary block appears before turn end
- Happy path: Multiple reads followed by a grep followed by text — reads batched, grep separate, all in one block before text
- Edge case: Single tool call — renders without batching, still in the block format
- Edge case: `PermissionEvent` between tool calls — permission prompt renders immediately, surrounding tools still buffered
- Edge case: No tool calls in a turn — no tool block rendered
- Integration: `ToolEndEvent` with `permitted=False` — denied message still appears inline, tool appears in summary
- Integration: `ToolEndEvent` with `error=True` — error still appears inline

**Verification:**
- Existing `test_recent_tools_populated_on_tool_start` still passes
- No inline `⏺ tool_name(args)` lines appear for normal tool execution
- Tool summary block appears exactly once per batch of tool executions
- Permission prompts render immediately, not buffered
- Error and denial messages still render inline for immediate user feedback

## System-Wide Impact

- **Interaction graph:** Only `render_event` in `ui.py` changes. The caller in `main.py` (lines 252-254) is unaffected — it still calls `render_event` per event. The agent loop (`loop.py`) is untouched.
- **Error propagation:** Tool errors and denials still surface immediately via inline prints. The summary block is additive.
- **State lifecycle risks:** The `_tool_buffer` is module-level mutable state. It must be fully drained on every flush to prevent stale entries leaking across turns. The flush-on-TextChunk and flush-on-TurnDoneEvent ensure this.
- **Unchanged invariants:** `recent_tools` deque behavior, `PermissionEvent` rendering, `_flush_text` behavior, all tool execution semantics.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Buffer not flushed in edge case (e.g., exception mid-turn) | The buffer is small and stateless across turns. Main loop's `except KeyboardInterrupt` already handles cleanup. Worst case: a few tool entries are lost on interrupt, which is acceptable. |
| Forked skill runs share module-level buffer | `run_forked` in `loop.py` doesn't call `render_event` — it only collects `TextChunk` content. No conflict. |
| Rich rule/panel rendering inconsistency across terminal widths | Use simple `console.rule` or manual separator strings rather than Rich Panel to keep it lightweight and predictable. |

## Sources & References

- `src/tigger/ui.py` — primary modification target
- `src/tigger/loop.py` — event yield order reference
- `src/tigger/types.py` — event dataclass definitions
- `tests/test_ui.py` — existing test patterns
