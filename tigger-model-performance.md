# Tigger model performance — bench cycle 02

Fresh cycle on `perf/model-bench-02`. Prior cycles archived (see
`tigger-model-performance-bench01-archive.md` etc., not loaded). Each
tick records its own measurements; no findings carried forward.

## Cycle ground truth (recorded at start)

- Branch: `perf/model-bench-02` · HEAD `520f381`
- Provider: `lmstudio` @ `http://192.168.2.122:1234/v1`
- `default_model`: `google_gemma-4-31b-it-bartowski` — **does not** match
  any key in `providers.lmstudio.models`. Tigger warns at startup and
  sends the slug verbatim with no per-model overrides applied. See
  iter 1 — the warning path is intentional and harmless if you always
  pass `--model <known-slug>` for benches.
- Known model slugs in config (in declaration order):
  1. `qwen/qwen3.6-35b-a3b`
  2. `qwen/qwen3.6-27b-thinking` → wire `qwen/qwen3.6-27b` + thinking
  3. `qwen/qwen3.6-27b-instruct` → wire `qwen/qwen3.6-27b` + no thinking
  4. `qwen_qwen3.6-27b@q4_k_l-instruct` → wire `qwen_qwen3.6-27b@q4_k_l`
  5. `google/gemma-4-31b LMStudio` → wire `google/gemma-4-31b`
  6. `google/gemma-4-26b-a4b LMStudio` → wire `google/gemma-4-26b-a4b`
- Server-loaded IDs (LM Studio /v1/models, abridged): `qwen/qwen3.6-27b`,
  `google/gemma-4-31b`, `google/gemma-4-26b-a4b`, `mistral-medium-3.5-128b`,
  `nvidia/nemotron-3-nano-omni`, `qwen_qwen3.6-27b@q4_k_l`,
  `qwen_qwen3.6-27b@q8_0`, `unsloth/qwen3.6-35b-a3b`,
  `unsloth/gemma-4-31b-it`, `unsloth/gemma-4-26b-a4b-it`.
- Test suite: **819 passed** in 4.40 s at cycle start.
- Bench harness: `/tmp/bench.sh <slug> <--think|--no-think> "<prompt>"`,
  240 s per-turn alarm.

---

### Iter 1 — DONE

**Dimension covered:** wire-kwargs round-trip verification.

**What was verified:** `qwen/qwen3.6-27b-instruct` slug → per-model
overrides apply correctly. Captured outgoing kwargs from
`TIGGER_PERF=1 tigger-code --no-think --model qwen/qwen3.6-27b-instruct --once "ping"`:

```
[perf] outgoing kwargs: {
  "model": "qwen/qwen3.6-27b",          ← from per-model override
  "temperature": 0.7,                   ← per-model
  "stream": true,
  "top_p": 0.8,                          ← per-model
  "presence_penalty": 0,                 ← per-model
  "extra_body": {
    "top_k": 20,                         ← per-model
    "min_p": 0.0,                        ← per-model
    "repetition_penalty": 1,             ← per-model
    "chat_template_kwargs": {
      "enable_thinking": false,          ← per-model AND --no-think
      "preserve_thinking": false         ← per-model
    }
  },
  "stream_options": {"include_usage": true},
  "_messages_count": 2,
  "_tools_count": 13
}
```

Every per-model override from `.tigger/config.json` is present in the
outgoing wire payload. `--no-think` correctly forces
`chat_template_kwargs.enable_thinking=false` on top of (already-false)
per-model setting — idempotent, no double-encoding. `_tools_count: 13`
confirms the full tool registry is shipped on a tools-allowed turn even
for a trivial "ping" — expected.

**Bench numbers:** N/A — the run hit the 60 s local alarm before any
`[perf]` timing line was emitted (model on shared GPU, single "ping"
turn against a 13-tool schema costs more than 60 s on this host
right now). The outgoing-kwargs dump fires *before* the request goes
out, so verification still succeeded.

**Pre-existing warning observed:**
`UserWarning: default_model 'google_gemma-4-31b-it-bartowski' has no
matching entry in providers.lmstudio.models`. Origin: `config.py:162`,
intentional. Triggers because the value of `default_model` in
`.tigger/config.json` (`google_gemma-4-31b-it-bartowski`) doesn't appear
as a key in `providers.lmstudio.models` (which has six slugs, none of
them this string). Behavior: tigger sends the slug verbatim as the
wire id and applies *no* per-model overrides. Logged here for the
cycle, not fixed — code path is correct; the config has drifted from
what the user intended.

**Root cause:** none — clean spot-check.

**Files touched:** only `tigger-model-performance.md` (created).

**Tests delta:** 819 → 819 (unchanged) in 4.40 s. No code change.
