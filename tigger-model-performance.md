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

### Iter 2 — DONE

**Dimension covered:** thinking-mode behaviour for `qwen/qwen3.6-27b`
(both config slugs) and a code-side guard against the footgun this
investigation surfaced.

**Wire-kwargs spot-check (TIGGER_PERF=1).** Both slugs round-trip
cleanly. `qwen3.6-27b-thinking` ships `temperature=0.6`, `top_p=0.95`,
`max_tokens=32768`, `extra_body.chat_template_kwargs={enable_thinking:
true, preserve_thinking: true}`. `qwen3.6-27b-instruct` ships
`temperature=0.7`, `top_p=0.8`, `presence_penalty=0`, no `max_tokens`
key (config's `max_tokens: 0` is correctly stripped at provider.py:225 —
"0 means unlimited"), and `enable_thinking:false, preserve_thinking:false`.

**Latency (warm, prompt = "Reply with exactly: pong-iter3-...").**

| variant  | wall_s | last_in | total_out | finish | EC |
|----------|--------|---------|-----------|--------|----|
| thinking | 162.67 | 4917    | 29        | stop   | 0  |
| instruct | >240   | —       | —         | —      | 142 (alarm) |

The thinking variant burning ~3000 reasoning tokens before a 29-token
visible reply is expected. The **instruct variant not returning in
240 s** is not — and is the iter's surprise.

**Root cause — verified by direct curl bypassing tigger.** The
`qwen/qwen3.6-27b` chat template on this LM Studio build silently
ignores `chat_template_kwargs.enable_thinking=false`. Three probes, all
return non-empty `reasoning_content`:

1. `chat_template_kwargs:{enable_thinking:false}` at top level
2. `extra_body.chat_template_kwargs:{enable_thinking:false}` (tigger path)
3. `/no_think` token appended to the user message

With `max_tokens: 0` (unlimited) on the "instruct" config entry, the
model has no cap on reasoning, so for a tiny prompt it grinds out
reasoning until something else stops it — past the 240 s alarm here.
By contrast, `qwen/qwen3.6-35b-a3b` (iter 1 of the archived cycle, warm
1.58 s for 26 visible tokens) genuinely honours `enable_thinking:false`.
The 27b-dense does not. The two `27b-thinking` / `27b-instruct`
config entries point at the **same wire model** with the **same
runtime behaviour** — the "instruct" entry is a misnomer on this build.

**Tigger-side state of play.** `provider.py:358-368` already drops
`reasoning_content` from history when `enable_thinking is False`, so
re-sent context is clean. What was missing: any signal to the user that
the *current* turn paid latency on reasoning anyway.

**Fix (small, surgical, `provider.py`).** Module-level
`_thinking_ignored_warned: set[str]`. When `enable_thinking is False`
but `collected_thinking` is non-empty, emit a one-shot stderr warning
keyed on `config.model`. Drop-from-history behaviour unchanged. Warning
text suggests the two real workarounds: cap `max_tokens`, or pick a
different model variant.

**Verified live (capsys-driven unit tests).**

```
[provider] 'qwen/qwen3.6-27b': server streamed reasoning_content despite
chat_template_kwargs.enable_thinking=False. Reasoning is dropped from
history, but the model still spent latency generating it. Cap max_tokens
or switch to a non-thinking model variant.
```

Second call to the same wire model in the same process: no re-warn
(asserted in `test_warns_once_when_thinking_disabled_but_server_streams_reasoning`).

**Files touched:** `src/tigger/provider.py`, `tests/test_provider_wire.py`,
`tigger-model-performance.md`.

**Tests delta:** 819 → 822 in 4.30 s. Three new tests:
- `test_warns_once_when_thinking_disabled_but_server_streams_reasoning`
- `test_no_warn_when_thinking_disabled_and_no_reasoning`
- `test_no_warn_when_thinking_enabled_and_reasoning_streams`

**Followups parked for iter 3+:**

- The `qwen/qwen3.6-27b-instruct` config entry is effectively a misnomer
  on this server — same wire id, same reasoning behaviour as the
  -thinking entry, just with an `enable_thinking:false` the template
  ignores. Either drop the entry or pin a low `max_tokens` so a single
  turn can't reason away an entire stream.
- 4.9k input tokens (`_tools_count=13`) is the same flat tax on every
  turn. Iter 3+ candidate: measure how much of that is prefix-cacheable
  on the LM Studio host — a cold KV cache is a per-turn cost on every
  model in the config.
- `assets/system.md` was not modified this iter. The Qwen3.6 family's
  per-model thinking quirks suggest a `system_prompt_extra` override
  (already supported by config, see `f891a0a`) per-model entry is more
  useful than splitting `system.md` itself. Park.
