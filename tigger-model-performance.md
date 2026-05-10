# Tigger model-performance loop — fresh cycle

Branch: `perf/model-bench-02` (cut from `main` after merging `perf/model-bench-01`).
Endpoint: LM Studio at `192.168.2.122:1234/v1` (per `.tigger/config.json`).
Cadence: every 10 min via CronCreate (job `c0694165`, `3-59/10 * * * *`).
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

### Iter 1 — DONE

**Goal.** Establish a clean wire-kwargs + latency baseline for one
model under the current tree. Reading nothing forward from the archive.

**Model:** `qwen/qwen3.6-35b-a3b` (LM Studio MoE, `--no-think`).

**Config side (`.tigger/config.json` → this entry):**

```json
"qwen/qwen3.6-35b-a3b": {
  "temperature": 0.7, "top_p": 0.8, "top_k": 20,
  "presence_penalty": 1.5, "max_tokens": 8192,
  "chat_template_kwargs": { "enable_thinking": false }
}
```

**Wire side (`TIGGER_PERF=1` outgoing kwargs):**

```
model=qwen/qwen3.6-35b-a3b
temperature=0.7  max_tokens=8192  top_p=0.8  presence_penalty=1.5
extra_body={top_k:20, min_p:0.0, repetition_penalty:1.0,
            chat_template_kwargs:{enable_thinking:false}}
_messages_count=2  _tools_count=13
```

All overrides round-trip cleanly. `min_p` and `repetition_penalty` in
`extra_body` ride the top-level config defaults (not the per-model
entry) — expected fallthrough.

**Latency (prompt = "Reply with exactly: pong-iter1"):**

| run   | wall_s | in_t | out_t | finish | EC |
|-------|--------|------|-------|--------|----|
| cold  | 27.69  | 4913 | 42    | stop   | 0  |
| warm  |  1.58  | 4915 | 26    | stop   | 0  |

Cold is JIT-load dominated. Warm is the honest steady-state for this
prompt size on this LM Studio host.

**Anomaly logged for a later iter (NOT investigated this tick):**
`default_model` in `.tigger/config.json` is
`"google_gemma-4-31b-it-bartowski"`, but the `providers.lmstudio.models`
dict has no key with that exact slug — closest is
`"google/gemma-4-31b LMStudio"`. Either the resolver tolerates the
miss, the config has a dead default, or the recent
`per-model disable_tools` change (commit `28c092d`) altered lookup
semantics. Park for iter 2+.

**Files touched.** `tigger-model-performance.md` only (docs).

**Tests.** 817 → 817, 4.45 s.
