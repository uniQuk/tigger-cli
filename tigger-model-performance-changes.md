# Actual Changes — Tigger Model Performance Bench Cycle 02

## Summary
- **Total ticks:** 65 substantive + 1 aborted (iter 42) = 66 iterations over ~3 weeks.
- **Code-side commits shipped:** 11 across the cycle.
- **Tests delta:** 819 → 830 (+11 new tests).

## Code Changes

| Iter(s) | File(s) touched                              | Change description                                                                                           |
|---------|----------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| 2       | `provider.py`, `tests/test_provider_wire.py` | Added `_thinking_ignored_warned: set[str]`; one-shot stderr warning when server streams reasoning despite `enable_thinking=False`. 3 new tests. |
| 2       | `tools.py`, `tests/test_tools.py`            | `_bash`: capture `proc.returncode`; append `[exit N]` to result on non-zero exit. 2 new tests.                 |
| 9       | `provider.py`, `tests/test_provider_wire.py` | Extended thinking-ignored warning to include char + token estimate (`~N tok / M chars this turn`).             |
| 18      | `loop.py`, `tests/test_loop_perf.py`         | Added `apparent_prefill_tok_per_s` column to `[perf]` TSV output. New test for ≥1000 tok/s cache-hit scenario. |
| 21      | `loop.py`                                    | Comment-only: added decode-share confound caveat to `apparent_prefill_tok_per_s` docstring.                   |
| 34      | `loop.py`                                    | Rewrote `[perf] note:` line to teach the right mental model for reading perf lines.                           |
| 35      | `loop.py`, `tests/test_loop_perf.py`         | Wired `cache likely hit` signal (fires when `apparent_prefill > 100`). 2 new tests.                            |
| 48      | `loop.py`, `tests/test_loop_perf.py`         | Threaded `apparent_prefill=` into the prefill-dominant warning line. Extended existing test.                  |
| 49      | `loop.py`, `tests/test_loop_perf.py`         | Suppressed `cache likely hit` when `prefill-dominant` already fired (avoids contradiction). 1 new test.       |
| 51      | `loop.py`, `tests/test_loop_perf.py`         | Added `model` column to perf TSV header/rows. Updated existing test.                                         |
| 52      | `loop.py`, `tests/test_loop_perf.py`         | `_warn_on_perf_tsv_model_swap()`: reads last TSV row's model column, warns on slug mismatch with cold-load hint. 2 new tests. |
| 62      | `loop.py`                                    | Extracted swap-detection into named helper `_warn_on_perf_tsv_model_swap()` (refactor, no behaviour change).  |

## Test Changes

| Iter(s) | File                                  | Tests added / modified                              |
|---------|---------------------------------------|-----------------------------------------------------|
| 2       | `tests/test_provider_wire.py`         | 3 new: warning fires once, no-warn when clean, no-warn when thinking enabled |
| 2       | `tests/test_tools.py`                 | 2 new: non-zero exit appends marker, zero exit has no marker |
| 9       | `tests/test_provider_wire.py`         | Modified existing test: added substring assertions for new warning wording |
| 18      | `tests/test_loop_perf.py`             | 1 new: cache-hit scenario with ≥1000 tok/s                                          |
| 35      | `tests/test_loop_perf.py`             | 2 new: cache_hit fires when high, silent on cold                                    |
| 48      | `tests/test_loop_perf.py`             | Modified existing test: assert `apparent_prefill=` substring                        |
| 49      | `tests/test_loop_perf.py`             | 1 new: cache_likely_hit suppressed when prefill_dominant fires                      |
| 51      | `tests/test_loop_perf.py`             | Modified existing test: expect 5 trailing columns + model field non-empty           |
| 52      | `tests/test_loop_perf.py`             | 2 new: model_swap warning fires on changed slug, silent on same slug                |

## Docs / Config Changes (no code)

- `tigger-model-performance.md`: primary artifact — all 66 iters documented.
- `CLAUDE.md`: added "Perf instrumentation" section inheriting the 4-signal design.
- `.tigger/config.json` (user-owned, not committed): iter-64 user applied recommendation #1 (`default_model` → `qwen/qwen3.6-35b-a3b`).

## Key Metrics (from bench)

| Metric | Value |
|--------|-------|
| Startup warning silenced | Yes (iter 64) |
| Bash exit-code visibility | Non-zero exits now show `[exit N]` |
| Thinking-ignored warning | Fires once/process with token estimate |
| Cache-hit signal | `apparent_prefill_tok_per_s > 100` → fires `[perf] cache likely hit` |
| Prefill-dominant diagnostic | New column + appended to warning line |
| TSV model identifier | Added as trailing column |
| Model-swap detection | Warns on stderr when previous TSV row's model differs |
