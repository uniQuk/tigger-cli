# Tigger perf-loop 01

Branch: `perf/loop-01-iterations` off `main` (commit `f1675e9`)
Loop cadence: every 10 min (cron `*/10 * * * *`, job `ce7e68fc`)
Baseline: 807 tests, ~4.5s

## Goals (recap from /loop)

- Performance: tighten redraws, reduce per-turn rebuilt work, cut prompt duplication.
- Simplification: prefer deletion; reuse existing helpers; one obvious way.
- LLM response quality: less hallucination, better streaming/markdown rendering.
- Avoid: rewrites, new abstraction layers, cosmetic refactors, over-engineering.

## Findings — first read of `loop.py`, `provider.py`, `ui.py`, `main.py`, `compaction.py`

### Performance

1. **Streaming Markdown rebuild per TextChunk** (`ui.py:_start_or_update_live` → `_build_text_renderable`).
   Each text chunk rebuilds the entire Markdown tree by calling `Markdown(body)`
   on the cumulative buffer. With token-granularity chunks this is O(n²) work
   for the lifetime of a long response. Rich Live already throttles its paint
   at 12 Hz, but our `update()` callsite recomputes the heavy renderable per
   chunk regardless. **Fix:** debounce so we only rebuild the renderable when
   ~80 ms have passed since the last rebuild (or when content has grown by a
   meaningful margin). User sees the same smooth streaming; CPU drops.

2. **Schema `deepcopy` on every turn** (`loop.py:_with_output_budget_schema_limits`).
   For each `write`/`edit` schema, a fresh `copy.deepcopy(schema)` runs on every
   provider call. The output is identical across turns of the same `run()` call
   because the budget is fixed there. **Fix:** memoise once per `run()` (or per
   `(id(schemas), budget)`).

3. **`print()` on the post-tool hook path** (`loop.py:691`).
   Bare `print` violates the CLAUDE.md rule (must always go through
   `ui.console.print`) and bypasses theme. The PreToolUse path already does this
   correctly. Fix to keep ANSI/theme consistent and avoid stderr/stdout
   bifurcation in tests.

### Prompt / context duplication

4. **Output-budget hint duplicated.** `loop.py:392-399` adds an env-tail
   message ("Active write/edit payload budget: …") AND we also bake the budget
   into each `write`/`edit` schema's `description` (`_with_output_budget_schema_limits`).
   The model sees the same fact twice on every turn; pure dead tokens. Keep the
   schema description (it is right next to the field at decode time and travels
   with the tool definition) and drop the env-tail message.

### Code simplification candidates (not yet acted on)

5. Two distinct ticker patterns in `ui.py`: the `Spinner` context manager and
   the `_start_activity` / `_stop_activity` pair. They both spawn a daemon thread
   to tick a `console.status`, both share `_turn_start`/`_turn_token_counter`.
   Worth a closer look once the perf wins land. Risk: unifying could break
   call-site contracts (one is a `with`, the other is fire-and-forget). Defer.

6. `_short_tool_name` is called twice per entry in the counts loop
   (`ui.py:162-163`). Trivial.

7. `_perf_kwargs_logged` global in `provider.py` — non-thread-safe but only
   touched when `TIGGER_PERF` is set. Out of scope for now.

### LLM quality / hallucination

8. The system prompt repeats the "stub-then-edit / large write" advice in two
   places (the `### write` line says "use edit instead" and the long
   `Writing large files` block 30 lines down restates it with much more depth).
   Consolidating could shrink the system prompt without losing signal. Defer
   until I have an A/B run via the TUI.

9. Per the user request to drive the TUI live and try different models — that
   needs a working LM endpoint; the box this loop runs on may not have one
   handy. Tracking as TODO for the iteration that has access; for now I am
   focusing on cheap, measurable static wins.

## Iteration log

### Iter 1 — DONE (`768d9e9`)
- Streaming Markdown debounce: throttle `_start_or_update_live` rebuilds to
  ~80 ms (matches Rich Live's 12 Hz paint cadence). On a long stream this
  drops the per-chunk `Markdown(body)` re-parse from once-per-token to
  ~12 rebuilds/sec. `_flush_text` syncs the renderable on stop so the final
  on-screen frame is always current. (#1)
- Hook print fix: `loop.py` PostToolUse now goes through `ui.console.print`
  with the `\[hook]` styling, matching the PreToolUse path and the
  CLAUDE.md "no bare `print()`" rule. (#3)
- Test update: `test_text_chunks_stream_visibly_via_live` sleeps past the
  rebuild interval between chunks to exercise the new throttle path.
- Tests: 807 → 807 (green, 4.7 s).
- Schema deepcopy cache (#2) examined and skipped: per-turn deepcopy cost
  is ~50 µs each, two `write`/`edit` schemas — total ~10 ms over a long
  session. Not worth the cache-invalidation complexity for that gain.

### Iter 2 — DONE
- Drop env-tail "Active write/edit payload budget" line. The same constraint
  already rides on every `write`/`edit` schema's `description` and
  `maxLength` (set by `_with_output_budget_schema_limits`); the env-tail was
  pure duplication. Saves ~30 prompt tokens per turn. (#4)
- Collapse two near-identical env-tail tests into one schema-level ceiling
  test (`test_tool_arg_ceiling_caps_schema_when_max_tokens_unbounded`). Net
  test count -1; no coverage loss because the schema description is now the
  authoritative surface.
- Trim a `_short_tool_name(name)` double call in `_tool_counter_message`.
  Tiny but the function gets hit on every tool start.
- Tests: 807 → 806 (green, 4.7 s).

### Iter 3 — DONE
- Replace bare `print()` at the end of the `TurnDoneEvent` branch with
  `console.line()`. Matches the "always go through `ui.console`" rule from
  CLAUDE.md, keeps the routing consistent for tests that capture
  `console.file`, and is a one-line correctness fix.
- Tests: 806 → 806 (green).

### Iter 4 — DONE (loop tick 2)
- **Bug fix:** the `Request timed out` exception branch in `main.py` REPL
  was the only error path that didn't call `ui._reset_tool_buffer()`.
  Stale tool entries from the aborted turn would leak into the next
  turn's flush as phantom rows. Add the missing call to match the
  `KeyboardInterrupt`, `httpx.*`, and `openai.APIError` branches.
- **Dedup:** in `mcp.connect_all`, two consecutive `except` handlers
  (`McpTransportError` then `Exception`) had byte-identical bodies. Since
  `McpTransportError` is already an `Exception` subclass, a single
  `except Exception` covers both. Removes 5 lines, no behavior change.
- Tests: 806 → 806 (green, 4.65 s).

### Iter 5 — DONE (loop tick 2)
- Drop `test_format_duration_under_minute`: it asserted on `45.1 → "45.1s"`,
  which exercises the same `s < 60` branch and same `f"{seconds:.1f}s"`
  format string as `test_format_duration_short` (`2.3 → "2.3s"`). Pure
  duplicate; no coverage loss. The remaining 5 tests still cover zero,
  short, minutes, exact-minute boundary, and hour boundary.
- Tests: 806 → 805 (green, 4.65 s).

### Iter 6 — DONE (loop tick 3)
- Live-validated the loop-1 throttle change: `make install` into `.venv`,
  ran `tigger-code --once …` against the LM Studio endpoint at
  `192.168.2.122:1234`. Stall watchdog fired correctly at 60 s, response
  rendered with the throttled streaming path, no regressions observed.
  Also verified `--no-think` fast path: 17 s end-to-end for `2+2`.
- Drop the duplicate "No emojis" rule in `assets/system.md`. The
  authoritative version lives in Core Mandates #2 ("Never use emojis…");
  the Response Style line 122 was a less-strong restatement that created
  ambiguity (mandate or preference?). Keeping the Core Mandate as single
  source of truth and stripping the duplicate. ~7 prompt tokens saved per
  turn, no tests reference the removed phrase.
- Tests: 805 → 805 (green, 4.64 s).

### Iter 7 — DONE (loop tick 4)
- **Spinner format dedup.** Both spinner implementations (the `Spinner`
  context manager and the `_start_activity` fire-and-forget pair) hand-
  built the same `[#999999]msg · elapsed · ↓ N tokens[/]` line in their
  tick loops. Extracted `_format_spinner_line()` and routed both through
  it. Centralises the layout so the two ticks can't drift apart, and
  drops ~10 lines net. The intentional differences between the two
  spinners (tick rate, rotation cadence, cleanup contract) stay where
  they were.
- **Prompt dedup, second pass.** Dropped two duplicate Anti-Patterns
  lines: "Do not use `write` on an existing file" (already in `### write`
  and Tool Sequencing) and "Do not glob `**/*` from project root"
  (already in `### glob`). Saves ~30 prompt tokens per turn. The
  bash-replacement Anti-Patterns (cat, grep, find, generic bash) stay —
  they aren't echoed in the tool descriptions.
- Live-tested via `tigger-code --no-think --once …` against LM Studio:
  model returned the requested exact string, spinner UX visually
  unchanged.
- Tests: 805 → 805 (green, 4.62 s).

### Iter 8 — DONE (loop tick 5)
- **`tools._grep`:** drop one redundant `pathlib.Path(path)` construction
  on the workspace-exclude line; reuse the `base` Path computed three
  lines up. Trivial, but `_grep` runs on every search call.
- **Test dedup:** `test_ask_permission_returns_false_on_n` exercises the
  same `answer == "y"` path as `test_ask_permission_returns_false_on_empty`
  — both inputs go down the "not 'y'" branch. Dropped the `n` case; empty
  remains and covers the boundary.
- **Test dedup:** `test_plan_mode_injects_via_environment_kwarg` and
  `test_custom_mode_injects_body` ran the same code path (mode body
  injected via the `environment` kwarg) with different mode names.
  Dropped the plan-specific test; the custom-mode one is more general.
- Tests: 805 → 803 (green, 4.62 s).

### Iter 9 — DONE (loop tick 6)
- **Test dedup:** `test_maybe_compact_layer1_triggers` was subsumed by
  `test_maybe_compact_returns_compact_result_with_snip_count` — both run
  the no-provider snip path and assert that compaction happened. Dropped
  the layer1 test; the snip-count one has the more specific field-level
  assertion.
- **Prompt dedup:** trimmed the redundant trailing "Always read before
  edit." from the `### read` description in `assets/system.md`. Core
  Mandate #4 ("Always read a file before editing it. Never edit blind.")
  is the absolute version; the same paragraph also says "Use this to
  understand code before modifying it." The trailing sentence was a
  third-time restate. Saves a few prompt tokens per turn.
- Tests: 803 → 802 (green, 4.67 s).

## Backlog for the next loop tick

The remaining items are interesting but require either an LLM endpoint to
A/B verify, or are low-yield enough to not justify changing on the static-
analysis pass alone.

- **Drive the TUI live and try different models.** Compare reasoning vs
  non-reasoning models, with/without `--no-think`, on identical prompts.
  Capture token-rate, prompt-cache behaviour, and hallucination rate.
  Needs a local endpoint reachable from the loop sandbox.
- **System prompt consolidation.** `system.md` repeats the stub-then-edit
  policy in two places (the brief `### write` line + the long `Writing
  large files` block). Could merge into one section, drop ~20 lines, save
  prompt tokens on every turn. Need to A/B that the model still respects
  the rule after the merge.
- **`_active_mode_body` / `_lazy_tools_prompt_line` per-turn rebuilds.**
  Both run on every turn but their inputs change rarely (mode toggle,
  tool registration). Caching is straightforward but the per-turn cost is
  microseconds — not worth touching unless a profile says otherwise.
- **`estimate_tokens` on the bottom toolbar.** Called by prompt_toolkit's
  `bottom_toolbar` callback on every keystroke when `complete_while_typing=
  True`. The `(n, chars)` cache short-circuits the tiktoken cost, but the
  cache *key* still walks every message per keystroke. Likely fine; flag
  if a long session gets jankier than a short one.
- **`tests/test_ui.py` is 104 tests / 1140 lines.** Most are tightly
  scoped, but the `format_duration_*` set has 6 single-assertion tests for
  one tiny function — could be `pytest.parametrize`d (no count change but
  removes ~25 lines). Defer until I have an actual case for it.
