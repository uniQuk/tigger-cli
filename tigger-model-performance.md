# Tigger model-performance loop — fresh cycle

Branch: `perf/model-bench-01`.
Endpoint: LM Studio at `192.168.2.122:1234/v1` (per `.tigger/config.json`).
Cadence: every 10 min via CronCreate (see job id in the first iter block below).
Fresh-start note: prior iter log is preserved in
`tigger-model-performance-bench01-archive.md`. Conclusions there are
NOT carried forward — this cycle treats the current tree and config as
ground truth and re-derives findings from scratch.

## Goal

For each model in `.tigger/config.json`:

1. Confirm config kwargs (`temperature`, `top_p`, `top_k`, `min_p`,
   `presence_penalty`, `repetition_penalty`, `max_tokens`,
   `chat_template_kwargs.enable_thinking`) actually reach the wire
   (spot-check via `TIGGER_PERF=1`).
2. Verify thinking / non-thinking mode behaves per-model.
3. Capture wall-clock, input/output token counts, and finish reason
   baselines for: simple chat, multi-turn chat, tool-call, code-exec.
4. Drive ONE measurable improvement per loop tick — perf, prompt
   quality, token waste, prompt-system architecture. Tests stay green.
5. Evaluate whether `assets/system.md` should remain generic or split
   into model-specific overrides surfaced via config or the TUI.

## Models under test

Source of truth: `.tigger/config.json` at the start of each tick.
Each iter block re-reads it (slugs may evolve between ticks).

## Bench harness

`/tmp/bench.sh <slug> <--think|--no-think> "<prompt>"` runs
`tigger-code --once` with `TIGGER_PERF=1` and emits one tab-separated
line: `slug | turns | wall_s | last_in | total_out | finish | EC`.

## Iteration log

<!-- Tick N appends a "### Iter N — DONE" block here. -->
