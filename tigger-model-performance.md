# Tigger model-performance loop

Branch: `perf/model-bench-01` off `main` (commit `51ea0c4`).
Loop cadence: every 10 min via CronCreate (job `58a63124`, `*/10 * * * *`).
Endpoint: LM Studio at `192.168.2.122:1234/v1`.

## Goal

For each of the 6 configured models in `.tigger/config.json`:

1. Confirm config kwargs (temperature, top_p, top_k, presence_penalty,
   `chat_template_kwargs.enable_thinking`) actually reach the wire.
2. Verify thinking / non-thinking switch behaves per-model.
3. Capture wall-clock + token-rate baselines for chat and tool-call prompts.
4. Drive a perf or quality fix per loop tick — small, surgical, tests green.

Models under test (slug → wire id):

| # | Slug                                    | Wire id                           | Thinking | Sampler |
|---|-----------------------------------------|-----------------------------------|----------|---------|
| 1 | `qwen/qwen3.6-35b-a3b`                  | `qwen/qwen3.6-35b-a3b` (MoE)      | off      | t=0.7, top_p=0.8, pp=1.5 |
| 2 | `qwen/qwen3.6-27b-thinking`             | `qwen/qwen3.6-27b`                | on       | t=0.6, top_p=0.95 |
| 3 | `qwen/qwen3.6-27b-instruct`             | `qwen/qwen3.6-27b`                | off      | t=0.7, top_p=0.80 |
| 4 | `qwen_qwen3.6-27b@q4_k_l-instruct`      | `qwen_qwen3.6-27b@q4_k_l` (q4)    | off      | t=0.7, pp=1.5 |
| 5 | `gemma-4-31b-it`                        | `gemma-4-31b-it`                  | n/a      | t=1.0, top_p=0.95, top_k=64, min_p=0.5 |
| 6 | `gemma-4-26b-a4b-it`                    | `gemma-4-26b-a4b-it` (MoE)        | n/a      | t=0.7, min_p=0.5 |

## Bench harness

`/tmp/bench.sh <slug> <flag> <prompt>` runs `tigger-code --once` with
`TIGGER_PERF=1` (which dumps outgoing kwargs + a tab-separated perf line
to stderr, see `provider.py:265`). Output columns: `slug | wall_s | in_t
| out_t | finish | EC`.

## Iteration log

### Iter 1 — DONE (`HEAD`)

**Bug found and fixed.** `.tigger/system.md` was a **3-line placeholder**
("Customise your system prompt here. This will be prepended to every
conversation.") whose docstring lied. `resolve.resolve_file` returns the
**first** existing tier — so the placeholder was *replacing* the
106-line bundled `assets/system.md`, not prepending. The model
effectively had no instructions in this project's tigger sessions.

A/B on `qwen/qwen3.6-35b-a3b` with prompt "Reply with exactly: pong-X":

| variant                      | wall_s | in_t | out_t |
|------------------------------|--------|------|-------|
| placeholder (3 lines)        | 27.76  | 2063 | 160   |
| bundled (proper, 106 lines)  |  5.67  | 4912 | 118   |
| bundled (warm, 2nd run)      |  1.74  | 4911 |  ~10 (just "pong-A") |

Counter-intuitive but real: a **larger, well-formed system prompt is
~5–16× faster** because the model emits a focused response instead of
160 tokens of speculation. With 4912 input tokens vs 2063 the prefill
was actually *faster* (3.18s vs ~3s) — KV cache + warm load.

**Fix:** root cause was `commands/init.py:_TEMPLATES["system.md"]` —
every project running `/init` got that 3-line lie. Dropped the entry
from `_TEMPLATES` so `/init` no longer scaffolds a project `system.md`
at all; the bundled prompt now wins via fallthrough. Three init tests
updated to assert the new behaviour. Local `.tigger/system.md` also
removed (was already untracked via `.gitignore`).

**Wire-kwargs confirmed (`TIGGER_PERF=1` dump for `qwen3.6-35b-a3b`):**

```
model=qwen/qwen3.6-35b-a3b
temperature=0.7   max_tokens=8192   top_p=0.8   presence_penalty=1.5
extra_body={top_k:20, min_p:0.0, repetition_penalty:1.0,
            chat_template_kwargs:{enable_thinking:false}}
```

All per-model overrides round-trip from `config.json` to the OpenAI
client kwargs correctly. `chat_template_kwargs` rides via `extra_body`
(LM Studio / vLLM convention), already covered by `provider.py:241`.

**Other models this tick:**

- `qwen/qwen3.6-27b-instruct`: cold (first hit) — `tigger-code --once`
  hit the 240 s harness timeout. Likely LM Studio JIT-loading.
- `qwen_qwen3.6-27b@q4_k_l-instruct`: 123.11 s, 720 output tokens for
  the same "say pong" prompt — q4 quant produced verbose preamble
  (model identifies itself, narrates) before the answer. Production
  unfriendly without further sampler tuning.
- `gemma-4-31b-it`, `gemma-4-26b-a4b-it`: EC=2 (provider error). Direct
  `curl` to `/v1/chat/completions` for `gemma-4-31b-it` also timed out
  at 20 s, so this is endpoint-side (not loaded yet). Carried to iter 2.
- `qwen/qwen3.6-27b-thinking`: cold (240 s timeout). Carried to iter 2.

**Tests:** 801 → 801, 4.37 s. No code change beyond removing the
placeholder file.

### Backlog for next ticks

- **Iter 2:** rerun the cold models with longer warmup + retry; capture
  thinking vs no-thinking deltas on `qwen/qwen3.6-27b`.
- **Iter 3:** propose `system_prompt_extra` config field. Right now
  customising the system prompt is all-or-nothing (override only). A
  small `system_prompt_extra` (in `config.json`) appended to the bundled
  prompt would let users add project-specific instructions without
  copy-pasting 106 lines.
- **Iter 4:** check whether the `q4_k_l` quant's verbose-preamble issue
  is sampler-driven (the only model in `config.json` with `presence_
  penalty=1.5` *and* `repetition_penalty=1`). The 35b-a3b also has
  `pp=1.5` but is concise — so it's likely weight-quality, not config.
  Skip the fix; document the recommendation.
- **Iter 5+:** look for tool-call format quirks across models, prompt
  duplication, redraw cost.
