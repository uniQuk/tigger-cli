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

### Iter 1 — pending
- Streaming Markdown debounce (#1)
- Schema deepcopy cache (#2)
- Hook print fix (#3)
- Drop duplicate output-budget env line (#4)
- Verify: `make test` green, no regressions in `test_ui.py` streaming tests.
