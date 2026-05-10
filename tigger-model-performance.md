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

### Iter 3 — DONE

**Dimension covered:** wire-kwargs verification + first real `[perf]`
timing line of the cycle, both for `qwen/qwen3.6-35b-a3b` — the slug
iter 2 named "the only model that actually honours `enable_thinking:
false`". Coverage gap closed.

**Wire-kwargs (TIGGER_PERF=1, --once "Reply with exactly: pong-iter3").**

```
{"model":"qwen/qwen3.6-35b-a3b","temperature":0.7,"stream":true,
 "max_tokens":8192,"top_p":0.8,"presence_penalty":1.5,
 "extra_body":{"top_k":20,"min_p":0.0,"repetition_penalty":1.0,
  "chat_template_kwargs":{"enable_thinking":false}},
 "stream_options":{"include_usage":true},
 "_messages_count":2,"_tools_count":13}
```

Round-trip is clean. Notable deltas vs the 27b-instruct kwargs from
iter 2:

| key                              | 35b-a3b | 27b-instruct |
|----------------------------------|---------|--------------|
| `temperature`                    | 0.7     | 0.7          |
| `top_p`                          | 0.8     | 0.8          |
| `presence_penalty`               | **1.5** | 0            |
| `max_tokens`                     | **8192**| _absent_ (0→stripped) |
| `chat_template_kwargs.preserve_thinking` | _absent_ | false |

Per-model `max_tokens: 8192` ships intact; per-model `presence_penalty:
1.5` ships intact. Absence of `preserve_thinking` confirms the
serialiser only forwards keys the config sets — no synthetic defaults
leaking into the wire payload (good).

**Timing.**

```
[perf] 1778444375  turn=1  wall=23.60s  compact=0.01s
        in=4913  out=7  msgs=2  prompt_chars=42  finish=stop
        tool_calls=0  continuations=0  delta_chars=42
        tokens_per_sec=0.30  cache_hit_estimate=0.000
[perf] prefill-dominant turn 1: wall=23.6s out=7tok delta_chars=42
```

- **EC=0**, stdout = `pong-iter3` (single trailing newline; iter-58
  contract intact).
- **No `[provider]` thinking-ignored warning** — confirms iter 2's
  claim that this model genuinely honours `enable_thinking:false`.
- **23.60 s wall for 7 output tokens** = 0.30 tok/s overall, but the
  emitted prefill-dominant warning makes it explicit: the cost is the
  4913 input tokens, not the 7 output tokens. Compare to iter 2's
  warm 1.58 s figure — same model, this run is cold prefill. 4913
  input tokens at, say, ~200 tok/s prefill = ~25 s, which lines up.

**Quantifying the tools-schema tax.** Iter 2 parked "4.9k input tokens
flat tax" as an open question. This iter confirms the exact number on
a 35b-a3b round-trip: **4913 input tokens for a 42-char user prompt
across 13 tool schemas**. Per-tool average ≈ 378 input tokens. That
matches the order-of-magnitude expectation for OpenAI-style JSON-schema
serialisation but is worth a closer look in a future iter (split the
tools schemas to measure each one's contribution, or strip-down candidates).

**Root cause:** none — clean spot-check + measurement.

**Files touched:** `tigger-model-performance.md` only.

**Tests delta:** 822 → 822 (unchanged) in 4.33 s. No code change.

**Followup parked for iter 4+:**

- Per-tool prefill cost. Bisect the 13-tool schema by toggling
  `disable_tools` (see commit `28c092d`) across two runs and compare
  `input_tokens` deltas — pin which tool's schema is the heaviest.

### Iter 4 — DONE

**Dimension covered:** token-waste hunt. Iter-3 measured 4913 input
tokens for a 42-char prompt on the 35b-a3b round-trip and parked
"which tool's schema is the heaviest?" Picked up that followup via
**static schema-size measurement** (no LLM calls, no two-run bisection
needed for a first cut).

**Method.** `register_all(ToolRegistry())` + `reg.schemas()` →
`json.dumps(…, separators=(",", ":"))` per tool. Char count, chars/4
≈ token estimate. Same serialiser shape the openai-python SDK uses on
the wire.

**Per-tool schema sizes (9 builtins, eager tier, sorted by char cost):**

| tool          | chars | ~tok | % of tool block |
|---------------|------:|-----:|----------------:|
| `analyze`     |   789 |  197 |           24.0% |
| `read`        |   530 |  132 |           16.1% |
| `mcp_promote` |   388 |   97 |           11.8% |
| `edit`        |   316 |   79 |            9.6% |
| `grep`        |   301 |   75 |            9.1% |
| `write`       |   267 |   67 |            8.1% |
| `glob`        |   266 |   66 |            8.1% |
| `web_fetch`   |   221 |   55 |            6.7% |
| `bash`        |   205 |   51 |            6.2% |
| **total**     | **3293** | **~823** | **100%** |

**Iter-3 4913-token prefill partition (static measurement):**

| component               | chars | ~tok | % of 4913 |
|-------------------------|------:|-----:|----------:|
| `assets/system.md`      |  8094 | 2024 |    ~41%   |
| builtin tool schemas (9)|  3293 |  823 |    ~17%   |
| MCP tool schemas (4 — `microsoft-learn` × 3 + ?)| — | ~1000–1500 | ~25% |
| message wrappers, json overhead, etc. | — | ~500 | ~10% |
| `.tigger/memory.md`     |     0 |    0 |     0%    |

Memory file does not exist in this workspace, so memory injection is
zero this cycle.

**Key counter-intuitive finding.** Iter 3's framing implied the
13-tool schema set was the dominant prefill cost. It's not — at
~823 tokens for the 9 builtins (+ ~1000–1500 for the 4 MCP entries =
~1.8–2.3k total), **the tool registry is the second-largest line item,
not the first**. The single largest is `assets/system.md` at 2024
tokens — bigger than the entire builtin tool registry combined and
more than 2× the heaviest individual tool (`analyze` at ~197 tok).

**`_tools_count: 13` reconciled.** Iter 2/3 saw 13 in the `[perf]
outgoing kwargs` dump. The static registry has 9 builtins; the
remaining 4 are MCP tools loaded at runtime (`microsoft-learn` ships 3
per iter-1 archived note; the fourth is unaccounted for and is a
followup probe).

**Where the schema budget actually goes for builtins.** `analyze` at
24% is the heaviest single tool. If a user is doing pure chat without
needing repomap-style analysis, disabling `analyze` via the
`disable_tools` config (commit `28c092d`) would save ~197 tok per turn.
Across a 50-turn session that's ~10k tokens of prefill — not life-
changing on a 128k context but real, and proportionally large compared
to e.g. trimming `bash` (51 tok).

**Root cause:** none — clean static measurement.

**Files touched:** `tigger-model-performance.md` only.

**Tests delta:** 822 → 822 (unchanged) in 4.35 s. No code change.

**Followups parked for iter 5+:**

- Validate the static estimate against a live A/B: run TIGGER_PERF=1
  with the registry's `analyze` disabled and confirm
  `input_tokens` drops by ~197.
- Identify the 4th MCP tool that's in the runtime count but not in
  `microsoft-learn`'s declared three. Either count or grep
  `.tigger/mcp.json` and the connected-summary log.
- `assets/system.md` is a 2024-token static cost on every turn. Iter
  2 parked the `system_prompt_extra` per-model override idea; iter 4's
  partition makes that the highest-leverage waste-hunt target — even
  a 50% reduction of system.md saves ~1000 tok/turn, dwarfing any
  tool-schema trim.
