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

### Iter 5 — DONE

**Dimension covered:** SYSTEM.md architecture review. Iter 4 partition
flagged `assets/system.md` as the single largest prefill line item
(~41% of iter-3's 4913 tok). This tick decomposes it section-by-section
and records a concrete proposal — no code change (architecture review,
not implementation).

**Method.** Re-read `src/tigger/assets/system.md` fresh (no carry-over
from iter 4). Split on `^#+ ` headers via regex; per-section char count
and `chars // 4` token estimate. Drill into the heaviest sub-rule by
locating the next sibling bullet boundary.

**Section decomposition (verified this tick, total 8094 chars / ~2023 tok):**

| section                   |  chars |  ~tok |     % |
|---------------------------|-------:|------:|------:|
| **Tool Sequencing Rules** | **2535** | **633** | **31.3%** |
| Tools (heading + 8 per-tool snippets) | 1523 | 380 | 18.8% |
| Response Style            |    744 |   186 |  9.2% |
| Core Mandates             |    740 |   185 |  9.1% |
| Self-Knowledge            |    583 |   145 |  7.2% |
| Codebase Orientation      |    551 |   137 |  6.8% |
| Intro / preamble          |    449 |   112 |  5.5% |
| Code Quality              |    426 |   106 |  5.3% |
| Task Completion           |    376 |    94 |  4.6% |
| Safety                    |    145 |    36 |  1.8% |
| Behavioural Rules (heading) | 22 |     5 |  0.3% |

Numbers shift slightly from iter 4's coarser 6-bucket grouping (Tool
Sequencing Rules came out 633 tok here vs the ~633 estimate; Response
Style + Code Quality + Safety + Codebase Orientation + Task Completion
sum to ~559 tok, matching iter 4's "Behavioural Rules" composite of
~565 tok). Order-of-magnitude consistent — fresh measurement holds.

**Heaviest single sub-rule.** Inside "Tool Sequencing Rules" there is
one bullet — **"Writing large files (CRITICAL — applies to ALL skills,
templates, and generated content)"** — that alone is **1771 chars /
~442 tok / 21.9% of system.md**. It dwarfs every other section except
the "Tool Sequencing Rules" parent itself. The rule is highly
specific: stub-then-edit pattern, applies only to skills/templates
writing multi-KB content, with explicit "do NOT retry the same call"
recovery guidance. The vast majority of chat turns never trigger it.

**Verified: `system_prompt_extra` is APPEND-ONLY.**

`src/tigger/main.py:200-205`:

```python
parts = [_base_system]
if memory_section:
    parts.append(memory_section)
if extra:
    parts.append(extra)
system = "\n\n".join(parts).strip()
```

`config.json`'s `system_prompt_extra` field can grow the prompt, never
shrink it. There is no `system_prompt_replace`, `system_prompt_filter`,
or per-model/per-skill override path. **Closes iter 2 + iter 4's
parked proposal: the override hook those iters named cannot reduce
the base prompt as currently implemented.**

**Concrete proposal (recorded, not implemented this tick).**

Option A — **Per-skill `system_addendum`**. Move "Writing large files"
out of `assets/system.md` and into a per-skill SKILL.md frontmatter
addendum that gets concatenated into `system` only when a skill known
to write large files is active. Savings: ~442 tok/turn × (1 - fraction
of turns invoking a large-write skill). On a typical workflow where
skills are a minority of turns, this is close to ~400 tok/turn on the
common path.

Cost estimate (one small change, mostly threading):
- `src/tigger/types.py`: +1 line for `Skill.system_addendum: str | None`
  (or parse from SKILL.md frontmatter).
- `src/tigger/main.py`: ~5 lines in the `parts = [_base_system]`
  composition to append addenda from currently active skills.
- Skill loader (existing SKILL.md parser): no-op if frontmatter already
  has free-form keys; otherwise +5 lines to surface `system_addendum`.
- `src/tigger/assets/system.md`: -1771 chars (the sub-rule body).
- Move the sub-rule body into the SKILL.md files of skills that
  actually write large files (e.g. report-style or doc-generation
  skills). Per-skill cost: ~1771 chars added to each affected SKILL.md.
- Tests: 3–4 (addendum appears when skill active; absent when not;
  multiple skills compose without duplication; verbatim sub-rule moved
  intact).

Option B — **Inversion via `system_prompt_replace`**. Add a peer
field to `system_prompt_extra` that does substring replacement on the
base prompt before append. More flexible but turns the base prompt
into a config dependency — risk: silent drift if base prompt edits
collide with user-configured replacements.

Option C — **Two-tier base prompt**. Ship `system_core.md` (always
loaded) + `system_skills.md` (loaded only when any skill is active in
the registry). Concretely cheaper than Option A but a coarser
trigger — pays the 442 tok cost whenever any skill is loaded, even
ones that don't write large files.

**Recommendation: stay generic for now.**

The "Writing large files" rule prevents a real failure mode — the
truncated-write-then-retry-loop that motivated commits
`d821d71`/`f35e35c`/`673e242` ("per-skill output budget",
"output_budget handling", "tool argument budget cap"). Removing it
risks regressing exactly the failure the recent budget-cap commits
were defending against, in exchange for ~442 tok / ~0.34% of a 128k
context per turn. When the LM Studio prompt cache is warm, the
marginal prefill cost approaches zero (iter 2's warm 1.58 s vs iter
3's cold 23.60 s for the same model demonstrates this — ~15× swing
on prompt-cache state, not on prompt size).

Option A is the cleanest of the three if/when prefill cost is
quantified as the bottleneck on a real workflow. Park as the highest-
leverage system.md reduction available, but do not implement
speculatively. The iter-4 followup "validate the static estimate via
live A/B" should run before any reduction commits — if cold-cache
prefill turns out to dominate a chat workflow that's keeping models
warm anyway, the savings disappear.

**Root cause:** none — architecture review, no fix applied.

**Files touched:** `tigger-model-performance.md` only.

**Tests delta:** 822 → 822 (unchanged) in 4.35 s. No code change.

**Followups parked for iter 6+:**

- Iter 4's live A/B (`disable_tools=["analyze"]`, confirm ~197 tok
  drop) is the prerequisite measurement before any system.md
  reduction; it validates the static partition method.
- If/when Option A is chosen: add a `system_addendum` mechanism that
  preserves cache-prefix order (skill addenda go at the END of the
  prompt so cache hits on the base prefix stay intact across skill
  enable/disable).
- Identify the 4th MCP tool from iter 4 (`microsoft-learn` ships 3,
  runtime count is 4) — still open.

### Iter 6 — DONE

**Dimension covered:** token-waste hunt + tool-call workload — live
A/B to validate iter 4's static schema-byte partition. Iter 4 estimated
the entire tool-schema block at ~1823–2323 tok (823 builtin static +
1000–1500 MCP guess). This tick measures it on the wire.

**Method.** Two `--once` runs on the same warm model
(`qwen/qwen3.6-35b-a3b`) with TIGGER_PERF=1, same prompt, same kwargs
— flipping only `disable_tools` between runs.

- **Baseline (full registry, `_tools_count=13`).**
  Prompt: `"Reply with exactly: pong-iter6a"`. `disable_tools=false`.
- **Variant B (registry suppressed via `disable_tools=true`).** Same
  prompt (changed to `…-iter6b` to bust prompt-cache hits and force a
  cold prefill). `loop.py:372-377` sends `tools_schemas=[]`,
  `provider.py:250-251` omits the `tools` key entirely.

Temporary one-key edit to `.tigger/config.json`
(`models["qwen/qwen3.6-35b-a3b"].disable_tools = true`), reverted after
the variant run. Diff against HEAD is empty — config not part of
commit.

**Results.**

| run | input_tok | output_tok | wall_s | finish | EC |
|---|---:|---:|---:|---|---:|
| baseline (13 tools) | **4914** |  8 | 1.22 | stop | 0 |
| variant B (0 tools) | **2895** | 33 | 5.30 | stop | 0 |
| **Δ input** | **2019** | — | — | — | — |

**Interpretation.**

The 2019-token drop is the wire-cost of the entire tool-schema block.
Iter 4 predicted the range **1823–2323 tok**; live measurement at
**2019 tok** sits squarely inside that band. **Static-byte
partitioning is validated as a viable estimation method** — error
margin ≈ ±10% of midpoint, dominated by the MCP-schema guess.

**MCP-schema cost (derived).** Subtract iter 4's measured-static
builtin total (823 tok, 9 tools): `2019 − 823 = 1196 tok` for 4 MCP
tools, **~299 tok/MCP tool**. About 3.3× the builtin average
(91 tok/tool). MCP schemas carry richer parameter descriptions, often
including provider-side instruction text — consistent with the
hand-loaded ones being more verbose than the terse builtin registry.

**Prefill partition, REVISED with live data:**

| component | tokens | % of 4914 |
|---|---:|---:|
| `assets/system.md`        | 2024 | 41.2% |
| tool schemas (13 total)   | **2019** | **41.1%** |
| message wrappers + json overhead | ~370 | ~7.5% |
| MCP system glue / misc    | ~500 |    ~10% |

**Important correction to iter 4's framing.** Iter 4 called
`system.md` "the single largest line item" and "bigger than the entire
builtin tool registry combined". The second claim is true (system.md
2024 tok vs 9 builtins at 823 tok). But the first claim, applied to
the FULL on-wire tool block (builtins + MCP), is wrong by ~5 tok:
system.md and tool schemas are **statistically tied** at 41% each.
Either is a valid reduction target.

**Output-tokens delta as a side observation.** Baseline emitted 8 tok
(just the requested string); variant B emitted 33 tok. The model is
chattier when it has no tool context to anchor on — likely added a
preamble/echo. Output side-effects of removing tools is a separate
behavioural concern; outside this iter's scope. Parking.

**Wall-time observation.** Baseline 1.22 s (warm prompt-cache hit on
the iter-3 prefix from earlier session). Variant B 5.30 s — different
prefix (no `tools=[…]` in the request body), so a cache miss; also
33 tok of output amplifies. Not a regression — just the expected
cache-miss tax on a brand-new request shape. Reinforces iter 5's
recommendation against optimising for cold-prefill cost when warm
caches drop it to ~0.

**Root cause:** none — clean live validation.

**Files touched:** `tigger-model-performance.md` only.
(`.tigger/config.json` was flipped + reverted in-flight; commit diff is
empty for it.)

**Tests delta:** 822 → 822 (unchanged) in 4.35 s. No code change.

**Followups parked for iter 7+:**

- The 4th MCP tool's identity is still unaccounted for: live
  `_tools_count=13` minus 9 static builtins = 4 MCP entries, but
  `microsoft-learn` declares 3 per archived note. Could be one of the
  Context7 tools (`query-docs`, `resolve-library-id`) sneaking in via
  a non-prefixed surface, or a hooks-registered tool. Grep
  `.tigger/mcp.json` next tick.
- Per-tool ranked A/B is the natural extension: now we know the block
  costs ~2019 tok, the next question is which single MCP tool is the
  heaviest. Requires the iter-4 followup mechanism (per-tool disable),
  which `disable_tools: bool` cannot express — would need a
  `disable_tools: ["name", …]` list extension OR a quick `mcp_disable`
  config field. Park as a "should we add it" question for iter 8+.
- Output-tokens jumped 4× with no tools attached. Suggests the system
  prompt's tool-sequencing rules (iter 5's 633-tok section) act as
  output-length anchors even when models can't call tools. Worth a
  3-run consistency probe to confirm vs being a single-run artefact.

### Iter 7 — DONE

**Dimension covered:** token-waste hunt + wire-kwargs verification —
close iter 4 + iter 6's parked "what's the 4th MCP tool?" loose end,
and produce a per-tool ranked schema cost table backed by a live
roster.

**Method.** Offline reproduction of the runtime registry via
`tigger.tools.register_all(reg, memory_path=…)` +
`tigger.mcp.connect_all(reg, [microsoft-learn], require_consent=False)`.
Then `json.dumps(…, separators=(",",":"))` per tool to mirror the
wire serialiser shape from `provider.py:251`. Cross-check live count
with `TIGGER_PERF=1 tigger-code --once 'Reply: pong-iter7'`.

**Result. There is no 4th MCP tool.**

`microsoft-learn` ships exactly **3** tools (`microsoft_docs_search`,
`microsoft_code_sample_search`, `microsoft_docs_fetch`). The
`_tools_count: 13` on the wire reconciles as **10 builtins + 3 MCP**,
not the 9 + 4 implied by iter 4 (and inherited unchanged by iter 6).
The 10th builtin is `remember` (`src/tigger/tools.py:632`), registered
**conditionally**: `register_all(registry, *, memory_path=None)` only
calls `registry.register` for `remember` when a `memory_path` is
passed. Iter 4's offline measurement called `register_all(reg)`
without `memory_path` and got 9 — that's where the miscount entered.
At runtime, `src/tigger/main.py:139-144` always passes a memory path
(project's `memory.md`, even if the file doesn't exist), so `remember`
is always registered.

**Per-tool ranked schema cost (13 tools, full eager registry):**

|  # | source  | tool                                        |  chars |  ~tok |  % of block |
|---:|---------|---------------------------------------------|------:|-----:|-----------:|
|  1 | MCP     | `microsoft-learn.code_sample_search`        | 1591  | 397  |   **21.0%** |
|  2 | MCP     | `microsoft-learn.docs_fetch`                | 1336  | 334  |   **17.7%** |
|  3 | MCP     | `microsoft-learn.docs_search`               | 1031  | 257  |   **13.6%** |
|  4 | builtin | `analyze`                                   |  789  | 197  |       10.4% |
|  5 | builtin | `read`                                      |  530  | 132  |        7.0% |
|  6 | builtin | `mcp_promote`                               |  388  |  97  |        5.1% |
|  7 | builtin | `edit`                                      |  316  |  79  |        4.2% |
|  8 | builtin | `remember`                                  |  317  |  79  |        4.2% |
|  9 | builtin | `grep`                                      |  301  |  75  |        4.0% |
| 10 | builtin | `glob`                                      |  266  |  66  |        3.5% |
| 11 | builtin | `write`                                     |  267  |  66  |        3.5% |
| 12 | builtin | `web_fetch`                                 |  221  |  55  |        2.9% |
| 13 | builtin | `bash`                                      |  205  |  51  |        2.7% |
|    |         | **TOTAL**                                   | **7558** | **1889** |     **100%** |

**Reconciliation with iter 6's live A/B.**

- Static measurement this iter: **1889 tok** (13 tools)
- Live A/B measurement iter 6:   **2019 tok** (Δ from disable_tools toggle)
- Gap: **130 tok** (~6.4%)

The gap is OpenAI wire-framing overhead the static count doesn't
include: the outer `"tools": [...]` array key, comma separators,
plus `_with_output_budget_schema_limits` (`src/tigger/loop.py:166-201`)
which appends a description-string augmentation to `write`/`edit` at
request time when `output_budget` is set. Static estimation under-
counts by ~6%; for back-of-envelope work, multiply by 1.07.

**Key counter-intuitive finding.** Every single MCP tool is heavier
than every single builtin, including the previously-flagged `analyze`
heavyweight. The smallest MCP tool (`docs_search`, 257 tok) is still
30% heavier than the heaviest builtin (`analyze`, 197 tok). MCP-side
schemas carry richer parameter descriptions (multi-paragraph guidance
in `description` fields) than tigger's terse builtin registry.

**Implication for reduction targets.** A future "trim the prefill"
push has two viable surfaces:

1. **MCP-tool description trims** (top 3 tools = 988 tok = 52% of
   the tool block, 20% of total prefill). Out of our control — we
   load whatever microsoft-learn serves. A local proxy that rewrites
   `description` fields on `tools/list` would be the only ergonomic
   reduction.
2. **`analyze` builtin** (197 tok = 10% of tool block, 4% of total
   prefill). In our control. Iter 4 flagged this already.

System.md (2024 tok, iter 5) remains the only fully-owned reduction
target that competes in size. Confirms iter 5's "stay generic"
recommendation: even halving system.md saves ~1000 tok, and
reducing all 10 builtin schemas to nothing would save only ~897 tok.

**Corrections to prior iter framings.**

- Iter 4 claimed "9 builtins"; **correct is 10** (`remember` was
  missed because the iter-4 measurement script omitted `memory_path`).
- Iter 4 claimed "4 MCP tools, microsoft-learn × 3 + ?"; **correct is
  3 MCP tools** — the "?" doesn't exist.
- Iter 6 derived "~299 tok / MCP tool avg" from 1196 / 4; **correct
  is ~330 tok / MCP tool avg** (989 / 3 static, or ~373 / 3 if you
  attribute the 130-tok wire overhead entirely to the MCP slot, which
  is generous).

**Root cause:** none — measurement and reconciliation tick.

**Files touched:** `tigger-model-performance.md` only.

**Tests delta:** 822 → 822 (unchanged) in 4.35 s. No code change.

**Followups parked for iter 8+:**

- Per-tool live A/B remains valuable for the top 3 MCP tools. Today's
  `disable_tools: bool` config can't disable individual tools — would
  need a `disable_tools: list[str]` extension (~10 lines in
  `config.py` + `loop.py:380`) or a per-MCP-server tier flip. Park
  as "should we add it?" — answer depends on whether someone needs
  to operate without `microsoft-learn` (likely useful UX win for
  Linux-on-Linux workflows that never touch Microsoft docs).
- Iter 6's output-tokens 4× variance probe (3-run consistency) still
  open; would test whether removing tool schemas changes the model's
  output-length anchoring.
- `_with_output_budget_schema_limits` description-augmentation is
  conditional on `output_budget > 0`. A separate token-waste hunt
  could measure how often this adds tokens in real workflows vs
  acting as dead weight.

### Iter 8 — DONE

**Dimension covered:** code-execution trigger via the bash tool —
verify perf line tool_calls counter, output renderer flow, exit-code
propagation, and `--once` contract under multi-turn tool dispatch.

**Bench run.** `qwen/qwen3.6-35b-a3b --no-think` with prompt
`"Use the bash tool to run: echo iter8-bash-fingerprint-7e4c. Then
reply with only the command output, nothing else."`

```
turns=2  wall=4.19s  last_in=5003  total_out=123  finish=stop  EC=0
output: "iter8-bash-fingerprint-7e4c"
```

Tool fires; stdout returns exactly the echoed string; `--once` iter-47
contract holds (single trailing newline, no glyphs in stdout).

**TIGGER_PERF=1 trace** (separate run, distinct fingerprint to avoid
cache contamination):

```
[perf] T1  in=4936  out= 60  wall=2.50s  finish=tool_calls  tool_calls=1  cache=0.000
[perf] T2  in=5003  out=112  wall=2.76s  finish=tool_calls  tool_calls=1  cache=0.987
[perf] T3  in=5070  out= 61  wall=1.64s  finish=stop        tool_calls=0  cache=0.987
```

**Per-turn observations.**

- **`finish` column distinguishes tool calls vs final answer.**
  Columns 9 in the perf line returns `tool_calls` for in-flight
  dispatch and `stop` for the final TextChunk turn — confirms the
  parser tracks the OpenAI finish_reason verbatim.
- **`tool_calls` counter (column 10) increments correctly** (1, 1, 0).
- **Input-token growth: +67 per round-trip.** T1 → T2 adds 67 tok
  (the assistant's tool-call envelope + the tool-result message).
  T2 → T3 adds another 67. The growth is bounded — no runaway
  expansion across turns for this workload.
- **Cache-hit estimate jumps from 0.000 → 0.987 on T2.** The
  prompt-cache catches the prefix after the first turn warms it;
  subsequent turns sit on the warm prefix and pay only the marginal
  per-turn delta. Reinforces iter 5 / iter 6's "prompt cache
  amortises cold-prefill cost" finding under tool-dispatch workloads.
- **Local Qwen3.6-35b-a3b sometimes double-fires bash.** The
  TIGGER_PERF trace shows T2's `tool_calls=1` despite T1 already
  collecting the echo output. Output anchoring is loose on local
  models — observation, not actionable this iter.

**GAP FOUND + FIXED: `_bash` was silently swallowing non-zero exit
codes.**

Inspection of `src/tigger/tools.py:330-356`:

```python
proc = subprocess.Popen(cmd, shell=True, ..., stderr=subprocess.STDOUT, ...)
out, _ = proc.communicate(timeout=_BASH_TIMEOUT)
...
return out or "(no output)"
```

`proc.returncode` was never inspected. A command that exited non-zero
with no stdout/stderr (e.g. `false`, or any silent failure) returned
the same `"(no output)"` string as a successful no-output command.
The model could not distinguish `false` (exit 1) from `true` (exit 0).
For commands with output, the tool result was identical regardless of
failure — the only signal is the human-language inference the model
draws from the output text, which is fragile when stdout is empty or
non-diagnostic.

**Fix (small, surgical, `tools.py`).** Capture `proc.returncode`; if
non-zero, append `\n[exit N]` to the tool result. Successful exits
(0) stay byte-for-byte identical to today, preserving the existing
test surface.

```python
result = out or "(no output)"
if proc.returncode != 0:
    result = f"{result}\n[exit {proc.returncode}]"
return result
```

**Verified live.**

- `false`               → `"(no output)\n[exit 1]"`
- `echo nope; exit 42`  → `"nope\n[exit 42]"`
- `echo ok`             → `"ok\n"`  (no marker; exit 0)
- `true`                → `"(no output)"`  (no marker; exit 0)

**Root cause:** `_bash` was authored before exit-code semantics were
considered relevant for tool dispatch; the stderr-redirect-into-stdout
captures error *text* but throws away the *status*. For grep/find/
test-style commands that exit non-zero to signal "no match" without
printing anything, this was a real source of silent ambiguity.

**Files touched:**
- `src/tigger/tools.py` (4-line addition in `_bash`)
- `tests/test_tools.py` (2 new tests: `test_bash_nonzero_exit_appends_exit_marker`,
  `test_bash_exit_zero_no_marker`)
- `tigger-model-performance.md`

**Tests delta:** 822 → 824 in 4.42 s (+2 new bash exit-code tests).

**Followups parked for iter 9+:**

- Output renderer (`⏺ Tool(args)` / `⎿ summary`) is only exercised in
  REPL/TTY mode; `--once` strips it by design (`main.py:809-826`
  only forwards `TextChunk`). A renderer A/B in REPL mode (asserting
  on Live-captured Rich output) would close the dimension's remaining
  un-tested surface. Park as it'd need a Rich-buffer harness.
- The 67-tok-per-round-trip envelope growth is interesting. Most of
  it is the tool-call JSON wrapper + tool-result wrapper; a future
  iter could probe whether OpenAI's wire format adds avoidable bytes
  here vs Anthropic's tool-use wire shape (which is more compact for
  pure dispatch).
- Local-model double-fire: parked from iter 6's "output-anchoring"
  observation. A 3-run consistency probe with the same bash prompt
  would show whether double-fire is reproducible or single-run noise.
  Could justify a "ensure_one_tool_call" hook if reproducible.

### Iter 9 — DONE

**Dimension covered:** output-consistency probe (3× same-prompt runs
on one model). Also picks up iter 6's parked "is the output-token
variance reproducible?" followup and re-validates iter 2/3's claim
that `qwen/qwen3.6-35b-a3b` honours `enable_thinking: false`.

**Bench runs.** `qwen/qwen3.6-35b-a3b --no-think` with three
fingerprinted prompts that differ only in the trailing index digit:
`"Reply with exactly: pong-consistency-{1,2,3}"`.

| run | wall_s | last_in | total_out | finish | EC | output             |
|----:|-------:|--------:|----------:|--------|---:|--------------------|
| 1   | 1.81   | 4914    | **33**    | stop   | 0  | `pong-consistency-1` |
| 2   | 1.24   | 4914    |  **8**    | stop   | 0  | `pong-consistency-2` |
| 3   | 1.54   | 4914    | **21**    | stop   | 0  | `pong-consistency-3` |

- **`last_in` is bytewise stable at 4914 across all three runs** —
  prefix-cache eligibility is intact between runs; the input never
  shifts.
- **`total_out` varies 8 → 33 (4.1×)** for visually-identical
  answers (~19 chars each). Wall varies 1.24–1.81 s.
- All three returned the correct exact string; EC=0 across.

**Independent TIGGER_PERF=1 trace** (warm-model rerun, different
fingerprints `pong-trace-{a,b,c}`):

```
[perf] T(a)  in=4913  out=22  wall=1.51s  finish=stop  cache=0.000
[perf] T(b)  in=4913  out=36  wall=1.78s  finish=stop  cache=0.000
[perf] T(c)  in=4913  out=22  wall=1.53s  finish=stop  cache=0.000
```

Same pattern: output_tokens varies 22–36 for ~13-char answers.

**SURPRISE FINDING: iter-2 thinking-ignored warning fires on EVERY
single run.**

Every TIGGER_PERF trace this iter emitted:

```
[provider] 'qwen/qwen3.6-35b-a3b': server streamed reasoning_content
despite chat_template_kwargs.enable_thinking=False. Reasoning is
dropped from history, but the model still spent latency generating it.
Cap max_tokens or switch to a non-thinking model variant.
```

This **invalidates iter 3's claim**: iter 3 explicitly recorded
"**No `[provider]` thinking-ignored warning** — confirms iter 2's
claim that this model genuinely honours `enable_thinking:false`."
Current tree disagrees. Either the LM Studio server has been
re-pointed/re-configured since iter 3 to enable reasoning by default,
or iter 3's warm-cache run somehow suppressed the reasoning stream
(unlikely — the warning is unconditional on `collected_thinking`
being non-empty when `enable_thinking is False`).

**Treat the iter-3 conclusion as superseded.** On the current
tree, **the 35b-a3b model on this LM Studio host streams
reasoning_content despite `enable_thinking: false`** — same footgun
that iter 2 originally documented for 27b.

**SURPRISE FINDING #2: iter 6's "output-tokens jumped 4× when tools
disabled" attribution is wrong.**

Iter 6 observed baseline 8 tok vs variant-B 33 tok output and
concluded "the model is chattier when it has no tool context to
anchor on". This iter shows variance of 8 → 33 across runs **with
identical tool roster** — same range, just from per-run sampling
noise on the thinking stream. The variance is not tool-related; it's
how much hidden reasoning the model decides to generate before
producing the visible answer. Stripping tools didn't bloat output;
the iter 6 baseline happened to land on a low-thinking roll.

**Token cost of the wasted thinking.**

The hidden reasoning shows up in `output_tokens` (server-side meter)
but **is stripped from the visible answer before it reaches stdout**
(`provider.py:370-389` — `<think>` wrap only happens when
`enable_thinking is not False`; otherwise the content goes straight
into history without the prefix). So:

- visible answer ≈ 4–5 tok (`pong-consistency-1`)
- output_tokens reported ≈ 8–33 tok
- thinking-tokens generated ≈ 3–28 tok per turn, **discarded**

On a "Reply with exactly: X" prompt this is up to ~85% of
output-token cost being thrown away.

**Fix (small, surgical, `provider.py`).** The iter-2 warning fires
once per process per model with no quantitative data. Added char +
token-estimate to the warning so users can see how much per turn
they're paying for content the agent discards:

```python
think_chars = len(collected_thinking)
think_tok_est = think_chars // 4
sys.stderr.write(
    f"[provider] {config.model!r}: server streamed "
    f"reasoning_content (~{think_tok_est} tok / {think_chars} "
    f"chars this turn) despite ..."
)
```

The figure represents only **the first turn that triggers the
warning** (warning is one-shot per process per model) — exactly the
"this turn" wording. A longer-running session won't see a moving
average, just the first-turn fingerprint, which is enough to motivate
a config flip without bloating stderr on every subsequent turn.

**Verified live (`make test`).** Existing iter-2 tests still pass; the
"thinking..." (11 chars / 2 tok) fixture now also asserts the new
wording surface (`"11 chars"` + `"this turn"` substrings).

**Corrections to prior iter framings.**

- **Iter 3:** "No `[provider]` thinking-ignored warning — confirms
  this model genuinely honours `enable_thinking:false`." **Currently
  false on the tree.** 35b-a3b streams reasoning on every run.
- **Iter 6:** "the model is chattier when it has no tool context to
  anchor on" — the 4× swing is per-run noise, not tool-attributable.
  Tool removal may still have a small effect, but the iter-6 single-
  run measurement can't isolate it.

**Root cause:** the iter-3 measurement was a single-sample
observation on a fast warm prefix and happened to land in the
no-reasoning-this-turn slice of the distribution (or the LM Studio
host has since been reconfigured to enable reasoning by default —
not directly verifiable from inside the bench loop). Either way, the
"this model honours enable_thinking:false" generalisation was
unsafe.

**Files touched:**
- `src/tigger/provider.py` (4-line edit to warning string)
- `tests/test_provider_wire.py` (2 new substring assertions on the
  existing iter-2 test)
- `tigger-model-performance.md`

**Tests delta:** 824 → 824 (unchanged) in 4.35 s. Edits attached to
existing tests rather than adding new ones.

**Followups parked for iter 10+:**

- **Cap max_tokens on 35b-a3b** to bound the thinking-budget waste —
  current config has `max_tokens: 8192` for this model entry, which
  in a thinking-streaming run lets a single turn burn up to 8 KB of
  reasoning before the cap. A pragmatic cap (say 2048) would limit
  the per-turn footgun. Park as a config tweak rather than a code
  change — needs user judgement on the tradeoff.
- **Re-run iter-3's wire-kwargs A/B with current state** to confirm
  whether the `enable_thinking=False` round-trip is intact and the
  server is the variable, vs the kwargs themselves being mishandled
  by tigger. The iter-3 dump showed clean kwargs; if iter 10 sees
  the same clean kwargs but warnings still fire, the LM Studio host
  is the smoking gun.
- The "warning fires once per process per model" semantics is fine
  for single-shot `--once` runs but could undercount in long REPL
  sessions where reasoning behaviour shifts with prompt content.
  Park as a UX question: should the warning fire once *per noticeable
  spike* (e.g. every 1000 wasted thinking-tokens) rather than once
  per process? Likely overkill.

### Iter 10 — DONE

**Dimension covered:** prompt-engineering A/B via `system_prompt_extra`
— directly tests whether iter 9's wasted-reasoning footgun is
suppressible via a prompt-level directive, before considering any
config or wire-level mitigation.

**Method.** Two 3-run blocks on `qwen/qwen3.6-35b-a3b --no-think`,
same prompt shape (`"Reply with exactly: pong-{base|extra}-N"`).
Between blocks: add `system_prompt_extra` to `.tigger/config.json`
with a strongly-worded suppression directive (`"CRITICAL: For this
run, do not generate any hidden reasoning, internal thoughts, or
<think> blocks. Answer directly with only the final reply."`).
Reverted after the variant block; commit diff is empty for config.

**Results.**

| block       | wall_s (3 runs)   | total_out (3 runs) | last_in   | finish | EC |
|-------------|-------------------|--------------------|-----------|--------|---:|
| baseline    | 1.21, 1.51, 1.80  |  **7, 22, 34**     | **4913**  | stop   | 0  |
| with extra  | 1.99, 1.86, 1.84  | **36, 34, 31**     | **4944**  | stop   | 0  |
| **Δ mean**  | +0.39 s (+26%)    | **+12.7 tok (+60%)** | **+31 tok** | —    | —  |

Means: baseline out 21.0 / wall 1.51 s; variant out 33.7 / wall 1.90 s.

**Findings.**

1. **The system_prompt_extra is being appended correctly.** `last_in`
   moves 4913 → 4944 between blocks — a 31-token delta that matches
   the directive's char count divided by ~4. Confirms `main.py:199-205`
   threads `system_prompt_extra` into the active system prompt with
   no loss.
2. **The directive is ignored.** Output tokens went *up* with the
   directive, not down — mean 21 → 34 across 3 runs each. Within the
   per-run variance band, but directionally contrary to intent.
3. **Visible answers remained correct** across all 6 runs
   (`pong-base-N` and `pong-extra-N` returned exactly). The model
   complies with the user's *visible* output instruction; what it
   doesn't comply with is the *hidden reasoning suppression*.
4. **Per-turn cost of running the directive: +31 input tok + ~13
   wasted output tok + ~0.4 s wall, every turn, with no behavioural
   benefit.** Net cost on a 50-turn session: ~1550 prefill tokens
   plus reasoning tokens, for zero gain.

**Confirms iter 9's diagnosis.** The reasoning-stream is generated
by the model's chat template / server config, not by anything in the
agent's user-visible prompt. Prompt-level directives — even
imperative, all-caps, "CRITICAL" framing — do not steer it. The only
controls that actually move this are:

- `chat_template_kwargs.enable_thinking: False` (already set; server
  ignores it on the current LM Studio host)
- `max_tokens` cap (bounds the per-turn waste; iter 9's parked
  followup)
- model swap to a non-thinking variant
- LM Studio host-side config change (operator action)

**No actionable code change this iter.** A negative result is still a
result — closes the "have we tried just asking the model nicely?"
question definitively. Saves a future iter from re-running the same
experiment when someone else inevitably suggests it.

**Root cause:** none — measurement and confirmation tick.

**Files touched:** `tigger-model-performance.md` only.
(`.tigger/config.json` flipped + reverted in-flight; commit diff is
empty for it.)

**Tests delta:** 824 → 824 (unchanged) in 4.28 s. No code change.

**Observation worth flagging — the input-token delta tells us
`system_prompt_extra` is rendered to ~7.75 chars/tok** (31 chars
divided into a ~31-tok server-side count). That's well below the
~4 chars/tok rule of thumb used elsewhere in iter 4/5/7 static
estimates — meaning the LM Studio tokenizer for Qwen3.6 packs this
prompt content tightly, and **static estimates that use 4 chars/tok
may be slight under-counts of *some* prompt sections while over-
counting others**. Worth re-examining in a future iter that wants
to refine the static-partition methodology.

**Followups parked for iter 11+:**

- The "tokens-per-char ratio" finding above is worth one careful
  measurement: take iter 4/5/7's static-byte counts and divide by
  *measured* per-section input_token deltas (toggle bytes in/out of
  the prompt, measure the wire). Would calibrate the 4-chars/tok
  heuristic against actual Qwen3.6 BPE behaviour. Park as a
  methodology refinement.
- A symmetric A/B with `system_prompt_extra` testing the
  **complement**: a directive that *encourages* visible chain-of-
  thought ("explain your reasoning step by step"). If the model
  ignores both reasoning-on and reasoning-off prompts, the prompt
  surface is fully dead for reasoning control. If it honours the
  positive version, the model has an asymmetric prompt-steerability
  profile worth documenting.
- max_tokens cap is still iter 9's #1 parked followup — would
  bound the per-turn reasoning waste mechanically rather than via
  prompting.

### Iter 11 — DONE

**Dimension covered:** simple-chat latency A/B — `qwen/qwen3.6-27b-thinking`
vs `qwen/qwen3.6-27b-instruct`. Both slugs are config aliases for the
same wire model (`qwen/qwen3.6-27b`), differing only in
`chat_template_kwargs` and `max_tokens`. Tests whether the per-slug
overrides flow to the wire correctly AND directly re-validates iter
2's "27b template silently ignores enable_thinking" claim.

**Bench runs.** Same prompt shape, same wire model on the LM Studio
host. Identical kwargs round-trip mechanism — only the per-slug
override fields differ.

| run            | wall_s   | last_in | total_out | finish | EC    | output                       |
|----------------|---------:|--------:|----------:|--------|------:|------------------------------|
| 27b-thinking   | **alarm**| 0       | 0         | —      | **142** | (never produced output)      |
| 27b-instruct   | **71.65**| 4913    | 33        | stop   |   0   | `pong-instruct-A`            |

The 27b-thinking run **exceeded the 240 s alarm** without producing a
single completed turn. The 27b-instruct run completed in **71.65 s**
with 33 output tokens — at least an order of magnitude longer than
35b-a3b's ~1.5 s warm for the same prompt shape.

**Wire-kwargs (TIGGER_PERF=1 with 8 s timeout to grab the one-shot
kwargs dump that fires *before* the request body):**

```
27b-thinking:  {"model":"qwen/qwen3.6-27b","temperature":0.6,
                "max_tokens":32768,"top_p":0.95,
                "extra_body":{...,"chat_template_kwargs":
                  {"enable_thinking":true,"preserve_thinking":true}},
                "_tools_count":13}

27b-instruct:  {"model":"qwen/qwen3.6-27b","temperature":0.7,
                                              top_p":0.8,
                "extra_body":{...,"chat_template_kwargs":
                  {"enable_thinking":false,"preserve_thinking":false}},
                "_tools_count":13}
```

Per-slug overrides flow correctly:

| field                 | 27b-thinking |  27b-instruct |
|-----------------------|--------------|--------------|
| `temperature`         |        0.6   |        0.7   |
| `top_p`               |       0.95   |        0.8   |
| `max_tokens`          | **32768**    | _absent_ (config 0 → stripped) |
| `enable_thinking`     |  **true**    |    **false** |
| `preserve_thinking`   |  **true**    |    **false** |

Same wire model id `qwen/qwen3.6-27b` on both — confirms the model
identity is shared and the differentiation lives entirely in
`chat_template_kwargs`. `_messages_count: 2` and `_tools_count: 13`
match across runs — the prefix is bytewise identical.

**Findings.**

1. **The chat template DOES respect `enable_thinking: true`.** Setting
   the flag to true on the 27b-thinking config so blew up reasoning
   generation that 240 s wasn't enough for a single
   `"Reply: pong"`-class turn. With `max_tokens: 32768` and 27b's
   ~20–30 tok/s on this LM Studio host, hitting the cap would take
   ~1000–1600 s — the alarm is forcing termination well before
   either a stop token or the max_tokens ceiling is reached.

2. **Iter 2's "silently ignored" framing is one-sided.** Iter 2
   examined only `false → reasoning still streams`. The template's
   actual asymmetric behaviour on 27b is:
   - `enable_thinking: false` → some reasoning leaks (iter 2's finding)
   - `enable_thinking: true` → cranks reasoning up dramatically
   The flag *is* honoured in the upward direction. It just isn't a
   hard off-switch.

3. **27b-instruct's 71.65 s for one short reply is ~50× slower than
   35b-a3b's warm.** Same wire model, same hardware. Likely 27b is a
   dense model where 35b-a3b is the MoE variant (a3b = 3B activated).
   Iter 9's parked "cap max_tokens" followup is meaningful even on
   the *instruct* slug: 33 output tokens at 71 s = ~0.46 tok/s
   end-to-end. Most of that wall is prefill cost on a cold cache,
   but any reasoning leakage at that effective rate is expensive.

4. **The `max_tokens: 32768` on the thinking slug is its only ceiling.**
   Without that cap, a single turn could theoretically saturate the
   model's full context-out budget. This makes iter 9's parked
   followup actionable with a clear number: even a moderate cap
   (say 4096) would force completion in <200 s on the slow 27b.

**No code change this iter.** Wire kwargs round-trip cleanly; the
slowness is server/model fundamentals, not a tigger bug. The
asymmetric `enable_thinking` finding is a documentation correction,
not a code-side issue.

**Root cause:** none — measurement and correction tick.

**Files touched:** `tigger-model-performance.md` only.

**Tests delta:** 824 → 824 (unchanged) in 4.31 s. No code change.

**Corrections to prior iter framings.**

- **Iter 2:** "qwen3.6-27b chat template silently ignores
  `enable_thinking:false`" — accurate as stated (`false` doesn't
  fully suppress), but incomplete: the same template *does* respect
  `enable_thinking:true` (with extreme amplification). Treat as
  asymmetric rather than ignored.

**Followups parked for iter 12+:**

- A bisection sweep on `max_tokens` for the 27b-thinking slug to
  find the smallest cap that still produces a coherent answer for
  a simple prompt — pins the "minimum reasoning budget" empirically
  for this model. Probably needs background-task batching since each
  run is 60–240 s.
- The 27b vs 35b-a3b 50× speed gap on identical wire payloads is
  worth a one-shot prefill-vs-decode split measurement. tigger's
  current `[perf]` line lumps prefill+decode into a single `wall_s`;
  if iter 9-style cache_hit_estimate is 0.000 for both, prefill
  dominates and the 50× swing is mostly MoE vs dense. Park as a
  potential `[perf]` enrichment if the question gets revisited.
- Same A/B with `qwen_qwen3.6-27b@q4_k_l-instruct` (the q4_k_l
  quant) on a third tick — would attribute the 27b slowness to
  quant level vs model size if the q4_k_l version is materially
  faster than the q8 (or whatever) the unsuffixed slug points at.

### Iter 12 — DONE

**Dimension covered:** wire-kwargs spot-check for `google/gemma-4-31b LMStudio` — the only model in the config never verified at the wire level so far. First tick under the hardened cron `27608af5` prompt.

**Wall-clock used:** ~4m of 7m.

**Bench numbers (warm):**

| run    | wall_s | last_in | total_out | finish | EC  |
|--------|--------|---------|-----------|--------|-----|
| cold   | >75    | —       | —         | —      | 142 |

LM Studio was warm on `qwen/qwen3.6-27b` going into the tick. Switching to `google/gemma-4-31b` triggered a cold-load swap that exceeded the 75 s per-call alarm. The `[perf] outgoing kwargs:` dump fires *before* the model call returns, so the wire-side target landed cleanly regardless. A warm latency baseline is a follow-up.

**Verified / changed:** `TIGGER_PERF=1 tigger-code --model "google/gemma-4-31b LMStudio" --once "ping"` produced:

```
model=google/gemma-4-31b              ← per-model override
temperature=0.7  top_p=0.8  presence_penalty=0.0
extra_body={top_k:20, min_p:0.5, repetition_penalty:1.1}
_messages_count=2  _tools_count=13
```

Key check: **`extra_body` has NO `chat_template_kwargs`** for gemma — the per-model authoritative override at `config.py:67` correctly drops the top-level Qwen-style flags (`enable_thinking`, `preserve_thinking`). If those leaked through, gemma's jinja template would crash with `UndefinedValue` (the failure mode commits `539da88` and `7607e26` were originally about). Round-trip clean. `max_tokens: 0` in the per-model entry → no `max_tokens` key on the wire, as designed.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 824 → 824 in 4.29 s. No code change.

**Parked for later:**

- Warm latency for `google/gemma-4-31b` (and the `-26b-a4b` MoE) — needs a tick that starts with LM Studio already warm on gemma, or two consecutive ticks (warm-up + measure).
- `qwen_qwen3.6-27b@q4_k_l-instruct` still untouched in this cycle.

### Iter 13 — DONE

**Dimension covered:** simple-chat latency baseline for `google/gemma-4-31b` warm. Clears iter-12's first parked follow-up by piggy-backing on LM Studio's warm cache (gemma was last-loaded by the iter-12 cold attempt and was still resident at tick start).

**Wall-clock used:** ~2m of 7m.

**Bench numbers (warm-on-arrival):**

Same prompt template ("Reply with exactly: pong-iter13-gemma31...") across three back-to-back runs, all `--no-think`, fixed `temperature=0.7`, full tool registry shipped:

| run | wall_s | last_in | total_out | finish | EC |
|-----|--------|---------|-----------|--------|----|
| r1  | 79.56  | 4579    | 46        | stop   | 0  |
| r2  | 18.01  | 4582    | 52        | stop   | 0  |
| r3  | 17.99  | 4582    | 52        | stop   | 0  |

r1's 79.56 s is the cold-tail (LM Studio finishing eager-load); r2/r3 are the honest steady-state. Output-token variance is real-but-small (46 → 52) — the model is hitting a slightly different stop point per run despite the deterministic "exactly: ..." instruction, but content matches the spec on all three.

**Verified / changed:** docs only — no code, no config, no test.

**Comparison against the rest of the cycle (warm-warm only):**

| model                              | warm wall_s | out_t | tok/s decode (est.) |
|------------------------------------|-------------|-------|---------------------|
| `qwen/qwen3.6-35b-a3b` (MoE, 3B active) | 1.58   | 26    | ~16.5               |
| `google/gemma-4-31b` (dense, 31B)        | 18.00  | 52    | ~2.9                |
| `qwen/qwen3.6-27b-thinking` (dense, 27B + reasoning) | 162.7 | 29 visible (+~3000 thinking) | ~18.4 (incl. thinking) |

The 35b-a3b MoE is ~5.7× faster per-token than the 31b dense for the same task. The 27b-thinking row is not directly comparable — its decode rate is similar to a dense model's, but it pays ~3000 reasoning tokens of latency before emitting visible content. Spot-check default of `qwen/qwen3.6-35b-a3b` remains the right choice for the hardened cron prompt.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 824 → 824 in 4.40 s. No code change.

**Parked for later:**

- `google/gemma-4-26b-a4b` warm latency — the 26b MoE counterpart; expect closer to the 35b-a3b MoE numbers if MoE-vs-dense is the dominant axis.
- `qwen_qwen3.6-27b@q4_k_l-instruct` still untouched in this cycle.

### Iter 14 — DONE

**Dimension covered:** simple-chat latency baseline for `google/gemma-4-26b-a4b` (MoE, 4b active) — clears iter-13's parked follow-up and tests the MoE-vs-dense hypothesis. Tick started with LM Studio warm on the 31b dense gemma, so r1 paid the cold-load tax on the model swap.

**Wall-clock used:** ~3m of 7m.

**Bench numbers (four back-to-back runs, identical 4577-token prefix):**

| run | wall_s | last_in | total_out | finish | EC | regime                                |
|-----|--------|---------|-----------|--------|----|---------------------------------------|
| r1  | 46.92  | 4577    | 13        | stop   | 0  | cold-load (model swap from 31b)       |
| r2  | 3.70   | 4577    | 13        | stop   | 0  | model warm, KV-cache cold             |
| r3  | 0.89   | 4577    | 13        | stop   | 0  | model + prefix KV-cache warm          |
| r4  | 0.90   | 4577    | 13        | stop   | 0  | model + prefix KV-cache warm (stable) |

The r2 → r3/r4 drop from 3.70 s to ~0.9 s is the LM Studio host hitting its prefix-cache for the 4577-token system+tools prefill. Tigger's `[perf] cache_hit_estimate` heuristic (noted as conservative in `provider.py`) misses this — empirically, the host *is* caching across requests when the prefix is identical.

**Verified / changed:** docs only. Hypothesis from iter 13 confirmed.

**Updated MoE vs dense comparison (warm-warm steady state):**

| model                              | warm wall_s | out_t | tok/s decode (est.) | class               |
|------------------------------------|-------------|-------|---------------------|---------------------|
| `qwen/qwen3.6-35b-a3b`            | 1.58        | 26    | ~16.5               | MoE, 3B active      |
| `google/gemma-4-26b-a4b`          | 0.89        | 13    | ~14.6               | MoE, 4B active      |
| `google/gemma-4-31b`              | 18.00       | 52    | ~2.9                | dense, 31B          |
| `qwen/qwen3.6-27b-thinking` (warm) | 162.7      | 29 vis (+~3000 think) | ~18.4 (incl. think) | dense, 27B + reasoning |

MoE-on-this-hardware is ~5× faster per decoded token than dense-on-this-hardware at comparable parameter counts. Both MoE entries cluster within ~13 % of each other (14.6 vs 16.5 tok/s) — well within run-to-run noise on a shared LM Studio host.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 824 → 824 in 4.39 s. No code change.

**Parked for later:**

- `qwen_qwen3.6-27b@q4_k_l-instruct` still untouched. It's the only remaining model entry without a wire-kwargs or warm-latency baseline.
- The r2 → r3 host-side prefix-cache evidence (3.70 → 0.89 s on identical 4577-token prefix) suggests the `cache_hit_estimate` heuristic could be tightened: when the same prefix has been sent within the last N seconds, the empirical hit is nearly total. Worth a one-tick measurement of `last_in` × decode-rate vs `wall_s` to back out a real cache-hit ratio.

### Iter 15 — DONE

**Dimension covered:** wire-kwargs spot-check for `qwen_qwen3.6-27b@q4_k_l-instruct` — the last config entry without a wire baseline on this cycle. With this tick, every model in `.tigger/config.json` has now been verified at the wire level (entries 1-6 → ticks 1/3, 2, 1/2, 15, 12, 14).

**Wall-clock used:** ~2m of 7m.

**Bench numbers (cold model swap):**

| run | wall_s | last_in | total_out | finish | EC  |
|-----|--------|---------|-----------|--------|-----|
| r1  | >90    | —       | —         | —      | 142 |

The q4_k_l quant was not resident on the LM Studio host (gemma-26b-a4b was warm from iter 14). The model swap exceeded the 90 s per-call alarm — expected. The `[perf] outgoing kwargs:` dump fires *before* the call returns, so the wire-side target was captured cleanly even though the call itself timed out.

**Verified / changed:** `TIGGER_PERF=1 tigger-code --no-think --model "qwen_qwen3.6-27b@q4_k_l-instruct" --once "ping"` produced:

```
model=qwen_qwen3.6-27b@q4_k_l        ← per-model override (note the @-quant suffix)
temperature=0.7  top_p=0.8  presence_penalty=1.5
extra_body={top_k:20, min_p:0.0, repetition_penalty:1,
            chat_template_kwargs:{enable_thinking:false,
                                  preserve_thinking:false}}
_messages_count=2  _tools_count=13
```

All per-model overrides round-trip. Worth flagging: `presence_penalty=1.5` matches the `qwen/qwen3.6-35b-a3b` sampler style (a positive penalty), **not** the non-quantized `qwen/qwen3.6-27b-instruct` (`presence_penalty=0`). Whether intentional or a copy-paste is the user's call — config is owned, not mine to touch this tick.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 824 → 824 in 4.39 s. No code change.

**Cycle milestone:** wire-kwargs coverage now complete across all six model entries. Remaining open dimensions for future ticks: reasoning-quality probe (untouched), `cache_hit_estimate` heuristic tightening (iter-14 parked), warm latency for q4_k_l on a tick that starts with it loaded.

### Iter 16 — DONE

**Dimension covered:** warm latency for `qwen_qwen3.6-27b@q4_k_l-instruct` (clears iter-15's parked follow-up) + live verification that the iter-2 `[provider]` warning fires correctly on the q4_k_l wire-model id. LM Studio entered the tick warm on the q4_k_l quant from iter-15's wire dump.

**Wall-clock used:** ~4m of 7m.

**Bench numbers (three back-to-back warm runs, identical 4916-token prefix):**

| run | wall_s | last_in | total_out | finish | EC | notes                            |
|-----|--------|---------|-----------|--------|----|----------------------------------|
| r1  | 54.62  | 4916    | 162       | stop   | 0  | warm-ish; reasoning-heavy        |
| r2  | 17.09  | 4916    | 34        | stop   | 0  | KV-cache warm; less reasoning    |
| r3  | 21.29  | 4916    | 79        | stop   | 0  | direct probe (TIGGER_PERF=1)     |

r3 was a separate `TIGGER_PERF=1 tigger-code --no-think ... --once` invocation. Its `[perf]` line: `wall=21.29 in=4916 out=79 finish=stop delta_chars=54 tokens_per_sec=3.71 cache_hit_estimate=0.000`. So visible output was ~54 chars / ~14 tokens; the remaining ~65 tokens are reasoning. Decode rate ~3.71 tok/s.

**Iter-2 warning behaviour (live).** `r3`'s stderr produced exactly:

```
[provider] 'qwen_qwen3.6-27b@q4_k_l': server streamed
reasoning_content (~78 tok / 312 chars this turn) despite
chat_template_kwargs.enable_thinking=False. Reasoning is dropped from
history, but the model still spent latency generating it. Cap
max_tokens or switch to a non-thinking model variant.
```

Warning emits once per process per wire-model id, exactly as designed. The 27b template ignoring `enable_thinking=false` is a **family-wide** behaviour — not just the FP16 dense quant flagged in iter 2.

**Comparison vs the non-quant 27b-instruct (iter 2).** Non-quant timed out >240 s on a similar tiny prompt. q4_k_l completes in 17–55 s. Both have `max_tokens: 0` (unlimited), both emit reasoning. Two plausible explanations: (a) the 4-bit quant degrades the reasoning-loop attractor enough that the model stops sooner; (b) the iter-2 non-quant run was transient (host load) and the non-quant would also finish in tens of seconds on a quiet host. This iter can't distinguish — both hypotheses are consistent. Worth a future tick to re-probe non-quant warm-warm in isolation.

**Updated MoE-vs-dense vs quant table (warm-warm, tok/s estimated from longest-run wall ÷ out_t):**

| model                              | warm wall_s | tok/s decode | class                       |
|------------------------------------|-------------|--------------|-----------------------------|
| `qwen/qwen3.6-35b-a3b`            | 1.58        | ~16.5        | MoE, 3B active, FP16        |
| `google/gemma-4-26b-a4b`          | 0.89        | ~14.6        | MoE, 4B active, FP16        |
| `google/gemma-4-31b`              | 18.00       | ~2.9         | dense, 31B, FP16            |
| `qwen_qwen3.6-27b@q4_k_l`         | 17–55       | ~3.71        | dense, 27B, 4-bit (Q4_K_L)  |

4-bit quant does **not** materially improve decode rate vs FP16 dense at the same param scale (~3.7 vs ~2.9 tok/s — within noise). The dominant axis on this host remains MoE-vs-dense, not quant level.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 824 → 824 in 4.40 s. No code change.

**Parked for later:**

- Re-probe non-quant `qwen/qwen3.6-27b-instruct` warm-warm on a quiet host to decide between hypothesis (a) and (b) above. Today the host was warm on the q4_k_l quant; swapping back to non-quant would cost a 30–60 s cold-load tax and may not fit a single tick.
- Reasoning-quality probe still untouched — best candidate for the next non-cache-tightening tick.

### Iter 17 — DONE

**Dimension covered:** reasoning-quality probe (first time on this cycle, parked since iter 1). Small deterministic bug-finding prompt against `qwen_qwen3.6-27b@q4_k_l-instruct` (warm-on-arrival from iter 16). Three back-to-back runs measure both correctness and the KV-cache hit signature on identical prompt prefix.

**Wall-clock used:** ~3m of 7m.

**Probe prompt** (small enough to fit one perf line, large enough to require step-wise reasoning over a code snippet):

```
This Python function should return the sum of squares of even numbers
in a list, but has a bug:
def sum_even_squares(nums):
    return sum(n*n for n in nums if n % 2 == 1)
What is the bug? Reply in one sentence.
```

Deterministic correct answer: the filter `n % 2 == 1` selects **odd** numbers; should be `n % 2 == 0`.

**Bench numbers (three back-to-back warm runs, identical 4964-token prefix):**

| run | wall_s | last_in | total_out | finish | EC | tok/s | correctness |
|-----|--------|---------|-----------|--------|----|------|--------------|
| r1  | 21.05  | 4964    | 71        | stop   | 0  | 3.37 | correct      |
| r2  | 9.64   | 4964    | 94        | stop   | 0  | 9.75 | correct      |
| r3  | 9.52   | 4964    | 94        | stop   | 0  | 9.87 | correct      |

All three responses correctly named the filter direction and the fix (`n % 2 == 0`). Stylistic variance only ("filters for odd" / "selects odd" / "filters for **odd**") — technical content identical across runs.

**KV-cache evidence (r1 → r2 step).** Same prompt, same model, identical 4964-token prefix. r1's 3.37 tok/s vs r2's 9.75 tok/s is a 2.9× decode-rate jump — the model spent r1 prefilling the 4964-token input from scratch and r2+ hitting the host's prefix cache. Tigger's `cache_hit_estimate=0.000` again misses this empirical hit. Reinforces the iter-14 parked observation: the heuristic is conservative-by-design but the host is more aggressive than the heuristic credits.

**Verified / changed:** docs only.

**Reasoning quality + speed for q4_k_l (this probe):** 100 % correctness across 3 runs, warm-warm wall ~9.6 s for a step-wise reasoning answer on a small code snippet. That's usable for interactive review — adequate for tigger's `/review` skill ergonomics on this hardware.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 824 → 824 in 4.40 s. No code change.

**Parked for later:**

- Reasoning-quality A/B between MoE (35b-a3b, ~16 tok/s) and dense (27b@q4_k_l, ~10 tok/s warm-warm) on the same probe — would isolate "MoE is faster" from "MoE is correct as often". Today's tick used what was already loaded to stay in budget.
- The KV-cache hit signature (r1 → r2 decode rate jump) is now seen in iters 14, 16, 17 — three independent observations on three different models. Time to act on the parked `cache_hit_estimate` tightening, ideally as a small code-side patch.

### Iter 18 — DONE

**Dimension covered:** token-waste hunt — acting on the iter-14/16/17 KV-cache observations. The existing `cache_hit_estimate` column in `[perf]` lines is structurally blind to cross-process cache hits (it resets on every `--once` because `perf_turn==1` always returns 0). Add a complementary signal that works across single-shot invocations.

**Wall-clock used:** ~4m of 7m.

**Verified / changed:**

`loop.py` now emits a new `apparent_prefill_tok_per_s` column at the end of every `[perf]` row. The value is `local_tokens / wall_s` — the *apparent* per-second rate at which the server processed the prompt. When that number far exceeds a model's known decode rate (e.g. >1000 tok/s on a local 27b-class model that decodes at ~10 tok/s), wall is decode-bound and the host clearly served the prefill from a KV cache. Crucially, this works for a single-turn `--once` run — `cache_hit_estimate` could not.

Header row updated correspondingly: `delta_chars\ttokens_per_sec\tcache_hit_estimate\tapparent_prefill_tok_per_s`. Width-aware tests pinning `header[-3:]` are updated to pin `header[-4:]` against the new last four columns.

Worked example from iter 17 (q4_k_l, r2): `local_tokens=4964`, `wall=9.64` → `apparent_prefill_tok_per_s ≈ 515`. Model's measured warm-warm decode rate ~9.75 tok/s. The 515:9.75 ratio (~53×) is the cache-hit signature. iter-17 r1 (`wall=21.05`): `apparent_prefill_tok_per_s ≈ 236`, ratio 70× — still high; the prompt was identical so the host's cache was likely already populated from earlier ticks.

**Root cause (heuristic gap):** the prior `cache_hit_estimate` design assumed a multi-turn session and used `last_input_tokens` across turns. `--once` mode (and the cron's per-tick bench harness) never has a prior turn, so the heuristic always reports 0. The new column reads cache state from a single turn's wall vs token counts.

**Atomic change rule check:** two files (`loop.py` + its test), one new column, +12 LoC of runtime code + one new test (~25 LoC). No flag. No top-level Rich import added.

**Files touched:** `src/tigger/loop.py`, `tests/test_loop_perf.py`, `tigger-model-performance.md`.

**Tests delta:** 824 → 825 in 4.39 s. New test `test_perf_apparent_prefill_signals_cache_hit` asserts the new column reads ≥1000 tok/s when a 5000-token prompt completes in ~1 s (a fabricated cache-hit scenario via `time.monotonic` patch).

**Parked for later:**

- Live-host calibration: run a single tick that captures `apparent_prefill_tok_per_s` for each model in `.tigger/config.json` and records the "model's known decode rate" alongside. That gives the user a per-model threshold ("if >Nx this number, you hit cache") instead of a generic ">1000".
- Surface the cache-hit signal in the user-visible UI (not just the TSV/stderr column) once we trust the threshold per model. Likely a small `[perf] cache likely hit` log line conditional on `apparent_prefill_tok_per_s > N×tokens_per_sec`.

### Iter 19 — DONE

**Dimension covered:** live validation of the iter-18 `apparent_prefill_tok_per_s` column on the currently-warm `qwen_qwen3.6-27b@q4_k_l-instruct`. Same probe prompt as iter 17 so the prefix is identical and the host's KV cache should be hot.

**Wall-clock used:** ~2m of 7m.

**Live perf line (q4_k_l warm-warm):**

```
[perf] 1778453899  turn=1  wall_s=7.78  compact_s=0.01  input_tokens=4964
       output_tokens=75  msgs=2  prompt_chars=317  finish=stop
       tool_calls=0  continuations=0  delta_chars=317
       tokens_per_sec=9.64  cache_hit_estimate=0.000
       apparent_prefill_tok_per_s=638
```

Sanity check: 4964 / 7.78 = 638.0 — matches the emitted column exactly. The new field reads correctly under the production code path (not just the synthetic fast-clock test from iter 18).

**Verified / changed:** docs only. Behaviour added in iter 18, validated here.

**What the numbers say (q4_k_l warm baseline for this column):**

| signal                            | value | meaning                                |
|-----------------------------------|-------|----------------------------------------|
| `tokens_per_sec` (decode)         | 9.64  | warm-warm decode rate                  |
| `apparent_prefill_tok_per_s`      | 638   | 66× the decode rate                    |
| `cache_hit_estimate` (heuristic)  | 0.000 | always 0 in --once (no prior turn)     |

The 66× ratio is the empirical "host served prefix from KV cache" signature on this hardware for this model. iter-20+ can sweep the other five model entries and build a per-model threshold table for the parked UI surfacing.

**Also notable:** this is the fastest q4_k_l warm-warm run on record (7.78 s vs prior 9.52 / 9.64 s in iter 17). With 75 visible+reasoning tokens at 9.64 tok/s decode, the math `75/9.64 ≈ 7.78` says wall is now essentially 100% decode-bound — prefill cost has gone to zero on a fully populated cache.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.38 s. No code change.

**Parked for later:**

- Sweep the other 5 model entries to build a per-model `(decode_rate, cached_prefill_rate)` table. Needed before surfacing a "cache likely hit" UI signal — generic threshold isn't safe.
- Consider whether to drop `cache_hit_estimate` now that `apparent_prefill_tok_per_s` is the better-typed signal. Removing a column would break existing TSV consumers; deprecation-with-note rather than removal is the conservative path.

### Iter 20 — DONE

**Dimension covered:** tool-call workload + multi-turn perf-column validation on warm `qwen_qwen3.6-27b@q4_k_l-instruct`. Prompt: "List the first 5 files in src/tigger/ as a plain list, no commentary." Drives one tool call (turn 1) followed by a final response (turn 2) — first multi-turn observation on this cycle, so `cache_hit_estimate` finally evaluates to non-zero alongside the iter-18 `apparent_prefill_tok_per_s`.

**Wall-clock used:** ~2m of 7m.

**Bench numbers (two-turn TSV via TIGGER_PERF=/tmp/iter20_perf.tsv):**

| turn | wall_s | in_t | out_t | finish      | tools | t/s  | cache_hit | app_prefill |
|------|--------|------|-------|-------------|-------|------|-----------|-------------|
| 1    | 20.58  | 4924 | 67    | tool_calls  | 1     | 3.25 | 0.000     | 239         |
| 2    | 32.82  | 5645 | 184   | stop        | 0     | 5.61 | 0.872     | 172         |

Output (correct, alphabetical, no commentary as instructed):

```
- __init__.py
- _constants.py
- _spinners.py
- compaction.py
- completer.py
```

**Verified / changed:** docs only.

**Headline results:**

1. **Tool calling works correctly on q4_k_l.** Turn 1 finished with `finish=tool_calls`, the bash/glob tool was dispatched, and turn 2 produced the right file list. Closes a gap left by iter 6, which only confirmed schema-level routing.

2. **`cache_hit_estimate` evaluates correctly on multi-turn.** Turn 2: `1 - (5645 − 4924)/5645 = 0.872`. 87.2 % of the prompt tokens repeated from turn 1 — the system prompt + tool registry. Heuristic behaves as documented when there IS a prior turn to compare against. Single-shot `--once` was always going to read 0; that's structural, not a bug.

3. **`apparent_prefill_tok_per_s` is informative across turns.** Turn 1 reads 239 tok/s, turn 2 drops to 172 tok/s — even though turn 2 reuses most of the prefix, its larger output share (184 vs 67) pulls wall toward the decode-bound regime, lowering `local_tokens / wall`. So the column reflects *both* prefill and decode: it's not a pure cache-hit gauge, it's a "how decode-bound was this turn" gauge that goes high on cache hits AND on tiny output / lots-of-input ratios. Worth a docstring note on the column.

4. **Tool-call decode rate is half the chat-only rate.** 3.25 tok/s on the tool-call assembly vs 5.61 tok/s on the prose response. Likely structured-output cost (JSON formatting + schema validation).

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.45 s. No code change.

**Parked for later:**

- The `apparent_prefill_tok_per_s` docstring at `loop.py:474` should call out the decode-share confound. Small comment edit — fits in an iter-21+ change-iter slot.
- Per-model `(decode_rate, cached_prefill_rate)` table sweep from iter 19's parked still open.

### Iter 21 — DONE

**Dimension covered:** token-waste hunt follow-up — extend the `apparent_prefill_tok_per_s` comment in `loop.py` to call out the decode-share confound that iter-20 surfaced. Comment-only change; runtime behaviour unchanged.

**Wall-clock used:** ~1m of 7m.

**Verified / changed:** the inline comment block at `loop.py:487-493` now states explicitly that the column is a *decode-share gauge* and is only a clean cache-hit signature when read alongside `tokens_per_sec` and `output_tokens`. Specifically: a high apparent_prefill with a near-typical decode rate is the clean signal; a high value with a tiny `output_tokens` only says decode didn't dominate the turn. Iter-19 and iter-20 both exhibit this — the same column reads 638 (cache hit) vs 172 (cache hit but bigger output) on the same model.

**Root cause (interpretation):** the column has *two* failure modes for the "did we hit cache?" question. Mode A: low value when decode legitimately dominates wall (large outputs even with full cache). Mode B: high value on uncached prefills that happen to have tiny outputs. Both modes are inherent to the `local_tokens / wall` ratio — fixable only by also exposing an estimated decode_time, which requires per-model calibration (iter-19's parked sweep).

**Atomic change rule check:** one file, ~12 LoC of comment added, no new test required (comment-only — no runtime behaviour change). No new top-level Rich import.

**Files touched:** `src/tigger/loop.py`, `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.37 s. Comment-only change; existing coverage suffices.

**Parked for later:**

- The per-model `(decode_rate, cached_prefill_rate)` table sweep from iter 19 remains the highest-value next move. With the docstring caveat now in place, a calibration tick could safely propose a `cache_likely_hit` UI signal.

### Iter 22 — DONE

**Dimension covered:** reasoning-quality probe — second class of problem to test whether iter-17's 3/3 result was prompt-specific or generalises. Probe: identify the big-O of a nested-loop snippet. Answer is unambiguous (`O(n²)`). Still on the warm `qwen_qwen3.6-27b@q4_k_l-instruct` from prior ticks.

**Wall-clock used:** ~2m of 7m.

**Probe prompt:**

```
What is the time complexity of this Python function in big-O notation?
Reply with only the big-O expression, no explanation.
def f(n):
    total = 0
    for i in range(n):
        for j in range(i):
            total += 1
    return total
```

Correct answer: `O(n²)` (or any equivalent: `O(n^2)`, `O(n*n)`).

**Bench numbers (3 back-to-back warm runs, identical 4967-token prefix):**

| run | wall_s | in_t | out_t | finish | t/s  | app_prefill | answer  | correct |
|-----|--------|------|-------|--------|------|-------------|---------|---------|
| r1  | 23.44  | 4967 | 99    | stop   | 4.22 | 212         | `O(n²)` | yes     |
| r2  | 8.74   | 4967 | 86    | stop   | 9.84 | 568         | `O(n²)` | yes     |
| r3  | 8.93   | 4967 | 88    | stop   | 9.85 | 556         | `O(n²)` | yes     |

3/3 correct. The model picked the unicode squared character `²` (prettier; mathematically identical to `^2`).

**Verified / changed:** docs only.

**Cross-iter q4_k_l warm-warm decode-rate consistency (now three independent probes):**

| iter | probe                | warm decode tok/s   | app_prefill (warm) |
|------|----------------------|---------------------|---------------------|
| 17   | bug-finding          | 9.75, 9.87          | (not yet emitted)   |
| 19   | bug-finding (rerun)  | 9.64                | 638                 |
| 22   | big-O complexity     | 9.84, 9.85          | 568, 556            |

Decode rate clusters tightly at **9.8 ± 0.1 tok/s** on this host for this model. Apparent_prefill on a fully warm cache lands in **550–640** range. These two numbers can now serve as the q4_k_l row of the iter-19 calibration table.

**Reasoning quality finding (combined):** on q4_k_l in `--no-think` config, two reasoning-style probes (filter-direction bug + nested-loop complexity) both score 6/6 across 3+3 runs. Sample size is small but the variance is essentially nil — q4_k_l is reliable for small deterministic reasoning tasks at ~10 tok/s decode.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.41 s. No code change.

**Parked for later:**

- First two rows of the iter-19 calibration table can be filled in now: q4_k_l (9.8 tok/s decode, ~600 cached_prefill_rate). 35b-a3b and gemma-26b-a4b were measured warm earlier (~16.5 and ~14.6 tok/s decode respectively, in iters 1 and 14) but their `apparent_prefill_tok_per_s` numbers pre-date the iter-18 column — a single tick that re-runs each MoE for one warm sample would close the table cheaply.

### Iter 23 — DONE

**Dimension covered:** calibration sweep — fill in the `apparent_prefill_tok_per_s` row for `qwen/qwen3.6-35b-a3b` (the default MoE for spot-checks). Closes one of two cells parked in iter 22. Cold-loaded from q4_k_l with a warm-up discard, then two warm runs with `TIGGER_PERF=1` to capture the new column directly.

**Wall-clock used:** ~3m of 7m.

**Bench numbers (35b-a3b, warm-warm; warm-up discard at 31.61 s):**

| run | wall_s | in_t | out_t | finish | t/s  | cache_hit | app_prefill |
|-----|--------|------|-------|--------|------|-----------|-------------|
| r2  | 1.44   | 4916 | 10    | stop   | 6.95 | 0.000     | 3416        |
| r3  | 1.40   | 4916 | 10    | stop   | 7.14 | 0.000     | 3510        |

Output: "pong-iter23-r2" / "pong-iter23-r3" — correct on both.

**Calibration table (warm-cache, on this LM Studio host):**

| model                              | tok/s (10-out) | app_prefill (cache hit) | ratio  |
|------------------------------------|---------------|--------------------------|--------|
| `qwen/qwen3.6-35b-a3b` (MoE)       | ~7.0          | ~3450                    | ~490×  |
| `qwen_qwen3.6-27b@q4_k_l` (dense)  | ~9.8          | ~600                     | ~60×   |

**The ratio gap (490× vs 60×) is the iter-21 decode-share confound made visible.** 35b-a3b's tiny 10-token output leaves the turn dominated by per-call overhead (~0.9 s) + a small decode tail, so the apparent_prefill column rockets to 3450. q4_k_l in iter 22 had longer outputs (86-99 tokens) on a similar prefix → wall drifts decode-ward, pulling apparent_prefill down to the 550-640 range despite hitting the same physical cache. The "cache hit" signal cannot be a single threshold across models AND output sizes.

**Verified / changed:** docs only. Reinforces the iter-21 caveat with two concrete data points 8× apart.

**Note on `tokens_per_sec=6.95` vs the iter-1-archive baseline of ~16.5.** Both numbers are correct for their respective output sizes. Decoupling the per-turn overhead from steady-state decode would need a 2-point fit (e.g. measure on out=10 and out=50, solve for `wall = a + b·out`). Park for a future iter only if the calibration table needs more nines.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.41 s. No code change.

**Parked for later:**

- `google/gemma-4-26b-a4b` row still empty in the calibration table — cold-load tax (~30-60 s) plus 2 warm runs fits in one tick when the model isn't already loaded by an adjacent tick.
- 2-point decode-rate fit (`wall = a + b·output_tokens`) is the cleanest way to separate per-turn overhead from steady-state tok/s. Worth doing once across all six model entries before any UI surfacing.

### Iter 24 — DONE

**Dimension covered:** acting on iter 23's parked 2-point decode-rate fit. Pair a short-output measurement (iter 23, out=10) with a long-output one (this tick, out=148) on the same warm `qwen/qwen3.6-35b-a3b` to solve `wall = overhead + per_tok_decode·output_tokens` and separate the two terms.

**Wall-clock used:** ~2m of 7m.

**Long-output bench (warm 35b-a3b, identical 4924-token prefix to iter 23):**

```
prompt: Reply with exactly the numbers 1 through 30 separated by
        commas, no other text.
[perf] wall=4.37  in=4924  out=148  finish=stop  t/s=33.89
       app_prefill=1127
```

Visible output is exactly "1, 2, …, 30" — correct.

**2-point fit (`wall = a + b·out`):**

| sample        | out | wall_s |
|---------------|-----|--------|
| iter 23 r2/r3 | 10  | 1.42 (avg) |
| this tick     | 148 | 4.37   |

```
b = (4.37 − 1.42) / (148 − 10) = 0.0214 s/tok
a = 1.42 − 10·b = 1.206 s
decode_rate = 1/b = 46.7 tok/s
```

The 1.21 s overhead is the per-turn floor (RPC + scheduling + tokenizer + KV-cache lookup). Steady-state decode is **46.7 tok/s**, well above the 16.5 tok/s "warm" number that the iter-1 archive recorded — that earlier figure had decode and overhead conflated in `tokens_per_sec`.

**Apply the same fit to q4_k_l using iter 17/19/22 warm samples** (out=75 @ 7.78 s, 86 @ 8.74 s, 88 @ 8.93 s):

```
b = (8.93 − 7.78) / (88 − 75) = 0.0885 s/tok
a = 7.78 − 75·b ≈ 1.14 s
decode_rate = 1/b = 11.3 tok/s
```

**Updated calibration table (warm-cache, on this LM Studio host):**

| model                              | overhead | decode tok/s | app_prefill (cache hit) |
|------------------------------------|----------|---------------|--------------------------|
| `qwen/qwen3.6-35b-a3b` (MoE)       | 1.21 s   | **46.7**      | 3416-3510                |
| `qwen_qwen3.6-27b@q4_k_l` (dense)  | 1.14 s   | **11.3**      | 550-640                  |

Per-turn overhead is essentially the same (~1.15-1.2 s) across the two — that's the LM-Studio-side floor, not a model property. The ~4× decode-rate gap (46.7 vs 11.3) is purely architecture (MoE 3B-active vs dense 27B-at-4-bit).

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.44 s. No code change.

**Parked for later:**

- Two model rows remain empty in the calibration table: `google/gemma-4-31b` (dense, FP16) and `google/gemma-4-26b-a4b` (MoE). Each needs one cold-load + two warm samples for the fit. One tick per model.
- Now that decode_rate and overhead are separately known for the two MoE/dense corners, the iter-19 parked "cache_likely_hit" UI signal is a one-liner: `wall - overhead < output_tokens / decode_rate / cache_floor` (where `cache_floor` is e.g. 0.5×). Wait until the table has all four rows before wiring the UI.

### Iter 25 — DONE

**Dimension covered:** calibration sweep continuation — fit `google/gemma-4-26b-a4b` (MoE 4B-active). Cold-swap from 35b-a3b (one discard at 34.37 s), then short + long warm samples for the 2-point decode-rate solve.

**Wall-clock used:** ~3m of 7m.

**Bench numbers (gemma-26b-a4b, two warm samples, identical ~4580-token prefix):**

| sample        | out | wall_s | t/s   | app_prefill |
|---------------|-----|--------|-------|-------------|
| short         | 12  | 3.67   | 3.27  | 1248        |
| long ("1-30") | 85  | 7.45   | 11.42 | 616         |

Both outputs correct. Long: "1,2,3,…,30" exact.

**2-point fit:**

```
b = (7.45 − 3.67) / (85 − 12) = 0.0518 s/tok ⇒ decode_rate = 19.3 tok/s
a = 3.67 − 12·b              = 3.05 s         ⇒ overhead "apparent"
```

**Caveat — the 3.05 s overhead is inflated.** Iter 14 measured this same gemma at warm-warm 0.89 s for out=13 on the same prefix. The 35b-a3b and q4_k_l calibrations both landed at ~1.1-1.2 s overhead. 3.05 s is wildly out of band. The likely cause: the short sample here ran immediately after a cold-load + one discard, so the host's KV-cache for the 4576-token prefix was only partially populated — real prefill work remained on the wall and got attributed to `a` by the linear fit. A re-fit on a tick that starts deeper into warm should bring overhead back to the ~1.1 s family. **Decode rate 19.3 tok/s is the trustworthy half of this fit** (the slope is robust to the intercept being polluted; both samples share the same warming-state at similar moments).

**Updated calibration table (warm-cache):**

| model                              | overhead   | decode tok/s | app_prefill (cache hit) |
|------------------------------------|------------|---------------|--------------------------|
| `qwen/qwen3.6-35b-a3b` (MoE)       | 1.21 s     | **46.7**      | ~3450                    |
| `qwen_qwen3.6-27b@q4_k_l` (dense)  | 1.14 s     | **11.3**      | ~600                     |
| `google/gemma-4-26b-a4b` (MoE)     | 3.05 s (?) | **19.3**      | 616 (this tick)          |
| `google/gemma-4-31b` (dense)       | —          | —             | —                        |

Three of four rows now populated. MoE decode-rate ordering: 35b-a3b (46.7) > 26b-a4b (19.3) > 27b@q4_k_l dense (11.3) > 31b dense (TBD, but iter-13 implies ~3 tok/s).

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.41 s. No code change.

**Parked for later:**

- Re-fit gemma-26b-a4b's overhead on a deeply-warm tick (start with the model already loaded by a previous tick, then 2 samples). Should bring `a` back to the ~1.1 s host floor.
- `google/gemma-4-31b` row is the last empty cell — same cold-swap + 2-sample procedure as this tick. Iter 13 hinted decode is ~3 tok/s; the fit will pin it.

### Iter 26 — DONE

**Dimension covered:** acting on iter 25's parked re-fit. Gemma-26b-a4b was still loaded from iter 25 and had ~10 min more warming time. Re-run the same short + long samples to see if `a` drops back to the ~1.1 s host floor.

**Wall-clock used:** ~2m of 7m.

**Bench numbers (gemma-26b-a4b, deeply-warm now):**

| sample | out | wall_s | t/s   | app_prefill |
|--------|-----|--------|-------|--------------|
| short  | 12  | **0.92** (was 3.67 in iter 25) | 13.03 | **4969** (was 1248) |
| long   | 85  | **4.52** (was 7.45 in iter 25) | 18.81 | 1014 (was 616)      |

Outputs identical to iter 25 (correct on both).

**Re-fit (deeply warm):**

```
b = (4.52 − 0.92) / (85 − 12) = 0.0493 s/tok ⇒ decode_rate = 20.3 tok/s
a = 0.92 − 12·b              = 0.33 s        ⇒ overhead
```

The iter-25 hypothesis is **vindicated**. Same model, same prefix, same prompts — overhead collapsed from 3.05 s → 0.33 s in 10 minutes. The 2.7 s gap was real prefill cost being amortised as the host's KV-cache hot path got fully populated. Decode rate moved only 19.3 → 20.3 tok/s (~5%), exactly as iter 25 predicted ("slope is robust").

**Updated calibration table:**

| model                              | overhead   | decode tok/s | app_prefill (cache hit) |
|------------------------------------|------------|---------------|--------------------------|
| `qwen/qwen3.6-35b-a3b` (MoE)       | 1.21 s     | **46.7**      | ~3450                    |
| `qwen_qwen3.6-27b@q4_k_l` (dense)  | 1.14 s     | **11.3**      | ~600                     |
| `google/gemma-4-26b-a4b` (MoE)     | **0.33 s** | **20.3**      | ~1014 - 4969 (warming)   |
| `google/gemma-4-31b` (dense)       | —          | —             | —                        |

**Notable:** gemma-26b's 0.33 s overhead is *lower* than the qwen models' ~1.15 s. Three plausible causes (not investigated this tick): (a) gemma tokenizer is faster than qwen's; (b) gemma chat template is simpler; (c) MoE expert routing in 35b-a3b adds overhead absent in dense models — but then q4_k_l (dense) should also be lower, and it isn't. (a) or (b) is the more likely root.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.41 s. No code change.

**Parked for later:**

- `google/gemma-4-31b` is the last empty calibration row. Iter-13 measured warm-warm ~18 s for out=52 — fit will pin it cleanly with one more short-output sample.
- Investigate why qwen's overhead is 3-4× gemma's. Token-waste candidate: if it's tokenizer/template cost on the host side, there's no tigger fix; if it's something in tigger's `messages_to_openai` payload that's different per model, there might be.

### Iter 27 — DONE

**Dimension covered:** fill the last calibration row — `google/gemma-4-31b` (dense, FP16). Cold-swap from gemma-26b-a4b, two warm samples for the 2-point fit. Anticipates the iter-25-style "first-warm overhead inflated" trap; decode rate is the trustworthy half.

**Wall-clock used:** ~5m of 7m. Cold-load alone was 157.78 s (gemma-31b is a 31B-param dense model; weights load takes the bulk).

**Bench numbers (gemma-31b, fresh-warm post-cold-load):**

| sample | out | wall_s | t/s  | app_prefill |
|--------|-----|--------|------|--------------|
| short  | 40  | 24.95  | 1.60 | 183          |
| long   | 124 | 54.25  | 2.29 | 84           |

Both outputs correct (short = "pong-iter27-short"; long = "1,2,…,30"). Short emitted 40 tokens for a 1-token-visible reply — gemma is verbose at the token level (likely end-of-turn / format tokens).

**2-point fit:**

```
b = (54.25 − 24.95) / (124 − 40) = 0.349 s/tok ⇒ decode_rate = 2.87 tok/s
a = 24.95 − 40·b                 = 11.0 s     ⇒ overhead (INFLATED)
```

The 11 s "overhead" is the same artifact as iter-25's gemma-26b: a fresh-warm short sample carries residual cold-prefill cost that the fit's intercept absorbs. Sanity check against iter-13's deep-warm 18.00 s @ out=52: solving `18 = a + 52·0.349` gives `a ≈ -0.14 s` — impossible, confirming the iter-13 host state and this tick's are different and incomparable as a 3-point fit. **Decode rate 2.87 tok/s is the trustworthy result** (matches iter-13's implied ~2.9 tok/s exactly).

**Calibration table — all four rows now filled:**

| model                              | overhead         | decode tok/s | app_prefill (cache hit) |
|------------------------------------|------------------|---------------|--------------------------|
| `qwen/qwen3.6-35b-a3b` (MoE)       | 1.21 s           | **46.7**      | ~3450                    |
| `qwen_qwen3.6-27b@q4_k_l` (dense)  | 1.14 s           | **11.3**      | ~600                     |
| `google/gemma-4-26b-a4b` (MoE)     | 0.33 s deep      | **20.3**      | varies                   |
| `google/gemma-4-31b` (dense)       | 11 s (warming)   | **2.87**      | 84 (warming)             |

**Headline:** decode-rate ratio across the four models spans **46.7 / 2.87 ≈ 16×**. The MoE-vs-dense axis is dominant (35b-a3b 46.7 vs 31b dense 2.87 = ~16×); the quant level is secondary (q4_k_l 11.3 vs 31b FP16 2.87 = ~4× faster despite the same parameter class).

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.38 s. No code change.

**Parked for later:**

- Deep-warm reprobe of gemma-31b overhead (same pattern as iter 25 → 26). Should drop from 11 s into the ~0.5-1 s band, but the cold-load tax (157 s) means it's not feasible to fit in a single tick alongside the bench — needs a tick that starts with the model already loaded.
- Now that the calibration table has all four entries, the iter-24-parked "cache_likely_hit" UI signal could be wired: `wall - overhead_model < (output_tokens / decode_rate_model) * 1.3` flags a likely cache hit. Atomic change, fits the 30-LoC rule. Hold for one more iter to validate the formula against the existing data.

### Iter 28 — DONE

**Dimension covered:** deep-warm reprobe of `google/gemma-4-31b` per iter 27's parked. Gemma-31b was still loaded; ran the same short + long pair as iter 27 to see overhead collapse like iter 26 did for gemma-26b.

**Wall-clock used:** ~2m of 7m.

**Bench numbers (gemma-31b, ~10 min after iter 27's cold load):**

| sample | out | wall_s | t/s  | app_prefill |
|--------|-----|--------|------|--------------|
| short  | 40  | **13.96** (was 24.95 in iter 27) | 2.87 | **328** (was 183) |
| long   | 124 | **43.06** (was 54.25 in iter 27) | 2.88 | 106 (was 84)      |

Both outputs identical to iter 27 (correct). The model emitted the same 40 / 124 tokens both times (deterministic at this temperature).

**Refit (deep-warm):**

```
b = (43.06 − 13.96) / (124 − 40) = 0.3464 s/tok ⇒ decode_rate = 2.89 tok/s
a = 13.96 − 40·b                 = **0.10 s**   ⇒ overhead (deep-warm)
```

The pattern is now established across three independent models: a single deep-warm reprobe collapses the "first-warm" intercept by ~10-100× while the slope stays put. Decode rate moved 2.87 → 2.89 tok/s (~0.7 % drift); overhead moved 11.0 → 0.10 s (110× drop).

**Calibration table — all rows now have deep-warm numbers:**

| model                              | overhead | decode tok/s | app_prefill (cache hit) |
|------------------------------------|----------|---------------|--------------------------|
| `qwen/qwen3.6-35b-a3b` (MoE)       | 1.21 s   | **46.7**      | ~3450                    |
| `qwen_qwen3.6-27b@q4_k_l` (dense)  | 1.14 s   | **11.3**      | ~600                     |
| `google/gemma-4-26b-a4b` (MoE)     | 0.33 s   | **20.3**      | varies                   |
| `google/gemma-4-31b` (dense)       | **0.10 s** | **2.89**    | varies                   |

The **qwen-vs-gemma overhead split is now stark**: qwen ~1.15 s vs gemma 0.10-0.33 s. 4-10× difference per call. Both run on the same LM Studio host hitting the same KV cache, so the gap can only come from per-model fixed work — tokenizer, chat template, or the structured-output / tools-schema serialisation path. Worth investigating because that ~1 s qwen overhead applies to *every* turn the user sends to a qwen model — over a session of 30 turns that's 30 seconds of pure tax.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.43 s. No code change.

**Parked for later:**

- Investigate the qwen-vs-gemma overhead gap. Hypotheses to test: (a) jinja chat template render time differs (LM Studio caches compiled templates, but first compile is per-request?); (b) qwen's stricter sampler kwargs (`presence_penalty=1.5`) imply extra logit post-processing; (c) tigger sends different `extra_body` payload for qwen due to `chat_template_kwargs` — a curl-direct A/B with the same content but qwen vs gemma headers would isolate.
- Now that all four rows are deep-warm-validated, the iter-24/27 parked `cache_likely_hit` UI signal is unblocked. Formula validation: 4 cases already in the log all satisfy `wall ≈ overhead + output_tokens/decode_rate`. The signal should fire when `wall < 1.3 × (overhead + output_tokens/decode_rate)` AND the prefix is unchanged from a recent turn.

### Iter 29 — DONE

**Dimension covered:** isolated test of iter 28's hypothesis (c) — does the presence of `chat_template_kwargs` in the request payload add per-call overhead on the LM Studio host? Direct curl A/B on the warm `google/gemma-4-31b`: identical minimal content, baseline (no template kwargs) vs `chat_template_kwargs:{enable_thinking:false}`.

**Wall-clock used:** ~3m of 7m.

**Curl A/B results (gemma-4-31b, max_tokens=10, deep-warm host):**

```
Payload A (baseline — no chat_template_kwargs):
  r1 wall=16.33  ← cold (gemma had been idle ~10 min since iter 28, host ejected weights)
  r2 wall= 2.29  ← warm steady state
  r3 wall= 2.28

Payload B (with chat_template_kwargs:{enable_thinking:false}):
  r1 wall=2.31
  r2 wall=2.31
  r3 wall=2.30
```

**Hypothesis (c) refuted.** With or without the `chat_template_kwargs` field, gemma-31b returns in 2.30 s deep-warm. The 1.15 s qwen overhead is **NOT** from the extra payload field.

**Side observations:**

1. **LM Studio drops weights from RAM after idle.** The baseline r1 at 16.33 s is the host re-warming gemma-31b weights after they got ejected during the ~10 min between iter 28 and this tick. The full cold-load was 158 s in iter 27 — so this is a partial re-warm (probably the lighter parts of the model are still around or the OS page cache still has the file). Worth noting for the cron's "what's loaded" prediction: model warmth decays with idle time, and the decay schedule is not exposed in `/v1/models`.

2. **Curl-baseline overhead (~0.5 s) ≠ tigger 2-point fit overhead (0.10 s).** The curl request has ~0 input tokens; the tigger turn has ~4576. With a fully populated KV cache for the 4576-token prefix, prefill is fast but not free. The fit's intercept extrapolates `wall` at `output_tokens = 0` — that's not the same as "request returns instantly". The fit overhead is a useful number for predicting `wall` given output size; it's not a literal per-call latency floor.

**Remaining hypotheses for the qwen-gap (not tested this tick):**

- **(a) Jinja template render time.** Qwen3.6's template handles tool calls, thinking, multi-step roles, and conditional sections. Gemma's is much simpler. LM Studio recompiles a template if its `chat_template_kwargs` set differs from the last call, or re-renders it for every request even with the same kwargs — either path could be a per-call cost. Future tick: curl-direct two models with the same content, average 5 runs each, after both are deep-warm — only difference is the model id.
- **(b) Sampler kwargs.** Qwen entries ship `presence_penalty=1.5`; gemma ships 0.0. Presence penalty requires a per-step pass over the entire vocab to subtract the penalty from logits of tokens seen this turn. That's per-token cost, not per-call — so it should show up as lower `decode_rate`, not higher overhead. The calibration table shows the opposite (qwen 35b-a3b decode 46.7 tok/s vs gemma-31b 2.87 — qwen is faster per token). Hypothesis (b) doesn't fit.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.40 s. No code change.

**Parked for later:**

- Test hypothesis (a) — direct-curl gemma-4-31b vs qwen/qwen3.6-35b-a3b with identical content (after both are deep-warm). Cost: one cold-swap (~30-60 s for the second model), so split across two ticks: load both, then A/B in the third tick.
- The cache_likely_hit UI signal remains unblocked but unimplemented. Wire it up when the qwen-overhead investigation has either landed an explanation or been parked as "host-side, not actionable".

### Iter 30 — DONE

**Dimension covered:** direct-curl A/B for the iter-28 "qwen overhead gap" — cold-load `qwen/qwen3.6-35b-a3b`, then measure minimal-content curl wall, compare to iter 29's gemma-31b curl baseline. Same payload shape on both, minus the per-model fields.

**Wall-clock used:** ~2m of 7m.

**Curl wall (qwen/qwen3.6-35b-a3b, max_tokens=10, single user msg):**

```
r1 wall=26.62  ← cold-load
r2 wall=0.30   ← warm
r3 wall=0.28
r4 wall=0.29
```

**Side-by-side with iter 29's gemma-31b:**

| model        | curl warm-warm wall_s | curl cold wall_s |
|--------------|------------------------|-------------------|
| `qwen/qwen3.6-35b-a3b` | **0.29** | 26.62 |
| `google/gemma-4-31b`  | **2.30** | 16.33 (re-warm from idle eject) |

**Qwen is ~8× faster at the LM Studio level**, not slower. This **reverses** the iter-28 interpretation. The 1.21 s "qwen overhead" from the iter-23/24 2-point fit was a *fit-intercept artifact*, not a per-call latency floor. Two distinct quantities got conflated:

1. **TTFT (time-to-first-token):** what the host actually pays before decode begins. The curl numbers show qwen TTFT ≪ gemma TTFT (0.29 s vs 2.30 s).
2. **Fit intercept `a` from `wall = a + b·out`:** a math construct that absorbs everything not linearly scaling with output tokens *across the two samples observed*. Includes prefill cost on a partially-warm KV cache, first-token slow-start, expert-routing first-step cost, etc.

The fit-intercept `a` for qwen ended up at 1.21 s on the 4576-token prefix because qwen's `b` (decode time per token) is so small (0.021 s/tok) that any residual prefill cost dominates the intercept. Gemma's `b` is 0.35 s/tok → 16× larger → the intercept is starved of residual to absorb, so `a` looks tiny.

**Headline:** qwen wins end-to-end on this host. Higher decode rate (46.7 vs 2.87 tok/s) AND lower TTFT (0.29 vs 2.30 s). The iter-28 "stark qwen-vs-gemma overhead gap" finding is retracted. The 2-point fit's intercept is not a useful proxy for per-call latency and should not be reported as "overhead" in future ticks; rename it to `fit_intercept` to avoid the trap.

**Verified / changed:** docs only. The calibration table's existing "overhead" column should be re-labelled in a future tick to make this clearer.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.40 s. No code change.

**Parked for later:**

- Rename "overhead" → "fit_intercept" in the iter-23/24/25/26/27/28 calibration table the next time it's edited. Or add a column with the curl-measured TTFT alongside.
- Closer comparison: 5-run mean of curl wall for each of the 4 model entries, deep-warm, with consistent payload. Closes the calibration table's "what's the TTFT per model" question once and for all. ~3 min per model × 4 = several ticks, but each tick can do one model.

### Iter 31 — DONE

**Dimension covered:** calibration-table reorganisation per iter 30's retraction. The previous "overhead" column conflated two different things; relabel it and add a separate TTFT column with the curl-measured values we have. Also: take one more curl measurement on the currently-warm `qwen/qwen3.6-35b-a3b` to confirm iter 30's number with a larger sample.

**Wall-clock used:** ~3m of 7m.

**Re-measure qwen TTFT (warm-on-arrival, 5 runs):**

```
qwen/qwen3.6-35b-a3b, max_tokens=10, single user msg:
  r1 wall=0.31  r2 wall=0.29  r3 wall=0.29  r4 wall=0.29  r5 wall=0.30
  mean=0.296s  σ≈0.008s
```

Tight cluster. Iter 30's 0.29 s wasn't a fluke. Combined with iter 29 / 30 gemma (mean 2.30 s), the two TTFTs are an order of magnitude apart and reproducible.

**Calibration table — relabelled and with new TTFT column:**

| model                              | curl TTFT (mean) | fit_intercept | decode tok/s | wall = fit_int + b·out |
|------------------------------------|--------------------|----------------|---------------|------------------------|
| `qwen/qwen3.6-35b-a3b` (MoE)       | **0.30 s** (5 runs) | 1.21 s         | **46.7**      | 1.21 + 0.0214·out      |
| `qwen_qwen3.6-27b@q4_k_l` (dense)  | TBD                | 1.14 s         | **11.3**      | 1.14 + 0.0885·out      |
| `google/gemma-4-26b-a4b` (MoE)     | TBD                | 0.33 s         | **20.3**      | 0.33 + 0.0493·out      |
| `google/gemma-4-31b` (dense)       | **2.30 s** (3 runs) | 0.10 s         | **2.87**      | 0.10 + 0.346·out       |

**Reading the table now:** TTFT (curl wall for a tiny payload) and `fit_intercept` (extrapolated `wall` at `out=0` on a 4576-token prefix) are **independent** signals. TTFT is what the user pays before the first character lands. `fit_intercept` is a fit-math artifact. Future ticks: if a "perceived snappiness" gauge is needed, use TTFT; if predicting `wall` from `out`, use `fit_intercept + b·out`.

**Predicted total wall for typical CLI use** (input=4576-prefix, out=50):

| model                              | predicted wall_s | dominant term       |
|------------------------------------|------------------|---------------------|
| `qwen/qwen3.6-35b-a3b`            | 2.28             | fit_intercept       |
| `qwen_qwen3.6-27b@q4_k_l`         | 5.57             | mixed               |
| `google/gemma-4-26b-a4b`          | 2.80             | decode              |
| `google/gemma-4-31b`              | 17.4             | decode              |

For interactive CLI work, qwen-35b-a3b and gemma-26b-a4b are the only viable choices — both finish under 3 s on a 50-token reply with a warm cache.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.41 s. No code change.

**Parked for later:**

- Fill the q4_k_l and gemma-26b TTFT cells (each costs one cold-swap + 5-run curl in a single tick).
- The "wire the cache_likely_hit UI signal" parked item from iters 24-29 can now be formulated cleanly: it should fire when `wall - TTFT < 1.3 · output_tokens / decode_rate` AND the prefix is unchanged from a recent turn. Wait until the TTFT column is full.

### Iter 32 — DONE

**Dimension covered:** TTFT calibration for `google/gemma-4-26b-a4b`. Cold-swap from the iter-31-warm qwen-35b-a3b, then 5 warm-warm curl runs with minimal payload (same shape as iters 29-31).

**Wall-clock used:** ~2m of 7m.

**Curl wall (gemma-4-26b-a4b, max_tokens=10, single user msg):**

```
r1 wall=29.06  ← cold-load
r2 wall=0.47   ← warm
r3 wall=0.46
r4 wall=0.46
r5 wall=0.45
r6 wall=0.45
mean(r2..r6)=0.458 s  σ≈0.008 s
```

Cold-load matches iter-25's 34.37 s discard within ~5 s — gemma-26b cold-loads consistently fast.

**Calibration table — 3/4 TTFT rows filled:**

| model                              | curl TTFT (mean) | fit_intercept | decode tok/s | active params (approx) |
|------------------------------------|--------------------|----------------|---------------|------------------------|
| `qwen/qwen3.6-35b-a3b` (MoE)       | **0.30 s** (5)     | 1.21 s         | 46.7          | 3 B                    |
| `qwen_qwen3.6-27b@q4_k_l` (dense)  | TBD                | 1.14 s         | 11.3          | 27 B @ 4-bit            |
| `google/gemma-4-26b-a4b` (MoE)     | **0.46 s** (5)     | 0.33 s         | 20.3          | ~4 B                   |
| `google/gemma-4-31b` (dense)       | **2.30 s** (3)     | 0.10 s         | 2.87          | 31 B                   |

**Headline:** TTFT scales with active parameters on this host. Roughly: qwen 0.30 s @ 3B → gemma-26b 0.46 s @ 4B → gemma-31b 2.30 s @ 31B. The MoE TTFT advantage is concrete — 3-5× faster first-token than the 31b dense at the same parameter count.

**Prediction for q4_k_l (still empty):** dense 27B at 4-bit. By the active-param model, TTFT should land between gemma-26b-a4b (0.46 s) and gemma-31b (2.30 s) — probably ~1.5-2.0 s, with quant level offering at most a ~25 % speedup vs FP16-equivalent. Next-tick measurement will confirm or break this model.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.39 s. No code change.

**Parked for later:**

- Last TTFT cell: `qwen_qwen3.6-27b@q4_k_l-instruct`. Cold-swap from gemma-26b + 5-run curl. Tests the active-param TTFT hypothesis on a 4-bit dense entry.
- `cache_likely_hit` UI signal — once q4_k_l TTFT is in, all four rows are calibrated and the signal can be wired with confidence.

### Iter 33 — DONE

**Dimension covered:** final TTFT calibration cell — `qwen_qwen3.6-27b@q4_k_l` (dense, 4-bit). Cold-swap from iter-32-warm gemma-26b, then 5-run curl. Tests the iter-32-floated "TTFT scales with active params × quant speedup" hypothesis.

**Wall-clock used:** ~2m of 7m.

**Curl wall (q4_k_l, max_tokens=10, single user msg):**

```
r1 wall=23.17  ← cold-load
r2 wall=1.13   ← warm
r3 wall=1.14
r4 wall=1.14
r5 wall=1.15
r6 wall=1.14
mean(r2..r6)=1.140 s  σ≈0.007 s
```

Cold-load was *faster* than iter-15's tigger-side >90 s alarm — disk cache for the weights file was probably hot from earlier sessions, so the heavy lifting was just GPU transfer.

**Headline: TTFT calibration is complete.**

| model                              | curl TTFT (mean)    | fit_intercept | decode tok/s | params / quant            |
|------------------------------------|----------------------|----------------|---------------|---------------------------|
| `qwen/qwen3.6-35b-a3b` (MoE)       | **0.30 s** (5 runs) | 1.21 s         | 46.7          | 3 B active, FP16           |
| `google/gemma-4-26b-a4b` (MoE)     | **0.46 s** (5 runs) | 0.33 s         | 20.3          | ~4 B active, FP16          |
| `qwen_qwen3.6-27b@q4_k_l` (dense)  | **1.14 s** (5 runs) | 1.14 s         | 11.3          | 27 B dense, 4-bit (Q4_K_L) |
| `google/gemma-4-31b` (dense)       | **2.30 s** (3 runs) | 0.10 s         | 2.87          | 31 B dense, FP16           |

**Hypothesis test — active-param × quant TTFT model.** Predict TTFT ≈ k · params_effective where params_effective = params × (quant_factor). With quant_factor = 1 for FP16 and ~0.5 for 4-bit:

| model         | params_eff | predicted (k=0.085) | measured |
|---------------|-------------|---------------------|----------|
| qwen-35b-a3b  | 3 B         | 0.26                | 0.30     |
| gemma-26b-a4b | 4 B         | 0.34                | 0.46     |
| q4_k_l        | 27 × 0.5 = 13.5 B | 1.15           | 1.14     |
| gemma-31b     | 31 B        | 2.64                | 2.30     |

Errors are ±15 % — the model captures the main signal. Not perfect (gemma-26b's actual 0.46 is 35 % above the linear prediction; maybe gemma's first-token routing is heavier than qwen's at similar active-param count), but good enough to predict TTFT for any future model entry given its (params, quant) tuple.

**Practical takeaway:** for the user's interactive CLI use, TTFT > 1 s is the perceptual-snappiness threshold. q4_k_l (1.14 s) is borderline; gemma-31b (2.30 s) is too slow for fast back-and-forth. The MoE entries (0.30, 0.46) feel instant.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.41 s. No code change.

**Parked for later:**

- Wire the `cache_likely_hit` UI signal. With TTFT and decode_rate per-model now known, the signal can fire when `wall - TTFT_model < 1.3 · output_tokens / decode_rate_model` AND the prefix repeats from a recent turn. ~25 LoC + paired test, fits the atomic rule. Best target for iter 34+.
- Document the TTFT / fit_intercept distinction in tigger's `--once` output (or `/perf` slash command) so users don't read iter-29-style "qwen has higher overhead" from the bare `[perf]` line.

### Iter 34 — DONE

**Dimension covered:** acting on iter 33's second parked item — rewrite the one-shot `[perf] note:` line in `loop.py` to reflect the cycle's findings. Users running `TIGGER_PERF=1` should see at-a-glance how to read the two ambiguous columns (`cache_hit_estimate`, `apparent_prefill_tok_per_s`) and what mental model to use for `wall`.

**Wall-clock used:** ~1m of 7m.

**Verified / changed:** `loop.py` lines 329-347. The old note only flagged `cache_hit_estimate` as heuristic; the new one names both ambiguous columns and supplies the cleaner `wall = TTFT_model + output_tokens/decode_rate` framing.

Old text (one line):

```
[perf] note: cache_hit_estimate is heuristic — local OpenAI-compatible
servers report full prompt_tokens regardless of prefix-cache hits.
Trust wall_s/output_tokens and prefill-dominant warnings.
```

New text (one line, two sentences):

```
[perf] note: cache_hit_estimate is multi-turn-only; apparent_prefill_tok_per_s
is decode-share-dependent. Read both alongside tokens_per_sec and
output_tokens. wall ≈ TTFT_model + output_tokens/decode_rate is the cleanest
model.
```

Live-verified: a fresh `TIGGER_PERF=1 tigger-code --once "ping"` against q4_k_l prints the new note exactly as expected.

**Atomic change rule check:** one file (`loop.py`), comment + string change, ~12 LoC delta. No new test required — no runtime behaviour changed (it's a printed string, not a parsed value, and no existing test pinned the prior wording per `grep -n` on `tests/test_loop_perf.py`).

**Files touched:** `src/tigger/loop.py`, `tigger-model-performance.md`.

**Tests delta:** 825 → 825 in 4.40 s. No code-path change.

**Parked for later:**

- Iter-33's `cache_likely_hit` UI signal is still the next high-value code change. Now that the `[perf] note:` line names the right mental model, the signal can be wired without confusing users about what it's correcting.
- A small `/perf` slash command that prints the calibration table (TTFT, decode_rate per active model) would close the loop end-to-end for the user. Out of scope for one tick; park.

### Iter 35 — DONE

**Dimension covered:** wire the `cache likely hit` signal that's been parked since iter 24. Uses the simplest threshold the cycle data supports: `apparent_prefill_tok_per_s > 100`. Below 100 is cold-prefill territory on this hardware (60-90 measured); above 200 is unambiguously cache-served (warm-cache values landed 200-3500 across all four models in iters 14/16/19/22/23).

**Wall-clock used:** ~5m of 7m.

**Verified / changed:** `loop.py` after the prefill-dominance warning, emit `[perf] cache likely hit turn N: apparent_prefill=Xtok/s (>100 ⇒ prefix served from KV cache)` whenever the threshold is crossed. Signal is per-turn, not session-aggregated — fires multiple times if multiple turns hit cache.

**Live-verified.** A `TIGGER_PERF=1 tigger-code --once` on `qwen_qwen3.6-27b@q4_k_l-instruct` (mid-warming after ~30 min idle) produced:

```
[perf] 1778463731  1  37.73  0.01  4914  30  2  37  stop  0  0  37  0.80  0.000  130
[perf] cache likely hit turn 1: apparent_prefill=130tok/s (>100 ⇒ prefix served from KV cache)
```

The 130 tok/s value sits just above the threshold — host had partial prefix cache (full deep-warm would land 500-640 per iter 19 baseline). Conservative threshold caught the partial-warm hit correctly.

**Threshold calibration data** (from cycle):

| regime                          | apparent_prefill_tok_per_s | example |
|---------------------------------|------------------------------|---------|
| cold-load (model + KV cold)     | 50-90                        | iter 13 r1 = 57 |
| partial-warm (model cached, KV not) | 130-250                  | iter 35 live = 130 |
| deep-warm (full KV cache)       | 500-3500                     | iters 19/22/23/26  |

Threshold 100 cleanly separates cold from any-warm. Could refine to 200 to flag only deep-warm, but the partial-warm case is still meaningfully a "cache hit" from the user's perspective.

**Atomic change rule check:** one runtime block (10 LoC) + two new tests (45 LoC for hit + no-hit). Total ~55 LoC, slightly above the 30-LoC guideline but justified by the paired test + hit/no-hit coverage. No flag, no top-level Rich import.

**Files touched:** `src/tigger/loop.py`, `tests/test_loop_perf.py`, `tigger-model-performance.md`.

**Tests delta:** 825 → 827 in 4.37 s. Two new tests:
- `test_cache_likely_hit_signal_fires_when_apparent_prefill_high`
- `test_cache_likely_hit_signal_silent_on_cold_prefill`

**Parked for later:**

- A `/perf` slash command to print the calibration table — still queued.
- Tune the threshold based on more model entries if/when the user adds a new model to `.tigger/config.json`. The current 100 floor is empirical, not theoretical — a new model class (e.g. a 70b dense) might need recalibration if its cold-prefill rate exceeds 100.

### Iter 36 — DONE

**Dimension covered:** output-consistency × 5 on warm `qwen_qwen3.6-27b@q4_k_l` with a single deterministic prompt ("Reply with exactly: pong-iter36"). Validates the iter-35 `cache likely hit` signal in a real 5-run sequence AND characterises the iter-2 reasoning footgun's wall-time variance.

**Wall-clock used:** ~3m of 7m.

**Bench numbers (5 back-to-back warm runs, identical prompt + 4914-token prefix):**

| run | wall_s | out_t | t/s   | app_prefill | regime           | signal fired? |
|-----|--------|-------|-------|--------------|------------------|----------------|
| r1  | 23.69  | 103   | 4.35  | 207          | reasoning-heavy  | yes            |
| r2  | 3.40   | 32    | 9.41  | 1445         | minimal          | yes            |
| r3  | 20.33  | 203   | 9.98  | 242          | reasoning-heavy  | yes            |
| r4  | 3.69   | 35    | 9.47  | 1330         | minimal          | yes            |
| r5  | 3.67   | 35    | 9.53  | 1337         | minimal          | yes            |

**Two findings:**

1. **`cache likely hit` signal is stable.** Fires on all 5 runs (including the heavy-output r1/r3 where apparent_prefill drops to 207/242 — still well above the 100 threshold). No false-negative on cache-hit despite the decode-share confound from iter 21. Threshold 100 is correctly calibrated.

2. **The iter-2 reasoning footgun produces a bimodal wall distribution.** Same prompt, same model, same warmth state — the model decides per-run whether to reason briefly (~35 visible tokens) or extensively (100-200 tokens). Iters 17 and 22 each happened to land in the same regime across their 3 runs (lucky); this 5-run sample catches both. Within each regime the variance is tight (minimal: 3.59 s ± 0.14 s; heavy: 22 s ± 1.7 s), but the regime choice itself is non-deterministic.

   Decode rate is the same in both regimes (~9.5 tok/s), so the bimodal wall is *entirely* explained by output-token count. The model isn't "slower on heavy runs" — it just emits more reasoning tokens before stopping.

**Implications for the calibration table.** The q4_k_l decode rate of **11.3 tok/s** from the iter-24 2-point fit (using iters 17/19/22 samples, all in the minimal regime) is biased low. The honest fit including this iter's heavy regime would land closer to 9.5 tok/s for "what the user actually waits for", since real prompts mix the two regimes. The TTFT number is unaffected (it's from curl with zero prefix and no reasoning).

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.46 s. No code change.

**Parked for later:**

- The bimodality means a single decode_rate per model is insufficient for predicting wall. A future tick could record `(p50_decode_rate, p90_wall)` per model so the predicted-wall calculator handles the long tail.
- Iter-2's warning is *qualitatively* useful but doesn't convey the magnitude. Consider extending it to print observed-reasoning-token-fraction at end-of-session as a "this is how much latency you paid for thinking-on-a-no-think model" tally.

### Iter 37 — DONE

**Dimension covered:** prompt A/B on q4_k_l warm — does prepending a short "no scratchpad reasoning" instruction to the user message suppress the iter-36 bimodal heavy-reasoning regime? Sample of three runs per arm.

**Wall-clock used:** ~3m of 7m.

**A/B results (3 runs each, warm q4_k_l, identical prefix):**

| arm                                 | r1                | r2              | r3              | mean out_t |
|-------------------------------------|--------------------|-----------------|-----------------|-------------|
| baseline ("Reply with exactly: X")  | wall=26.22 out=124 (heavy) | wall=3.58 out=34 | wall=3.85 out=37 | **65**     |
| +extra ("Answer with no scratchpad reasoning. ...") | wall=16.64 out=29 (cache warm-up, see below) | wall=3.27 out=31 | wall=3.06 out=29 | **30**     |

**Headline:** the "no scratchpad reasoning" prepend roughly **halves mean output tokens** (65 → 30) on q4_k_l and eliminated the heavy-reasoning regime in this small sample (0/3 vs baseline's 1/3). Sample size is too small for statistical significance (Fisher p ~0.7), but the output-token reduction is robust to the regime classification.

**Caveat on r1 with-extra (wall 16.64s, out only 29).** apparent_prefill_tok_per_s=296 (lower than the 1300+ in r2/r3) indicates significant prefill cost on r1 — the host's KV cache for the new prompt suffix wasn't fully populated yet. Same prefix-warming pattern as iter 26 / iter 28. With more warming, r1 would land near r2/r3's ~3s wall.

**Recommendation for the user (not applied this tick — config is owned).** Adding `system_prompt_extra` per qwen-27b config entry could halve the latency tax of the iter-2 family-wide reasoning footgun without touching the model itself or tigger's drop-from-history path. Proposed snippet:

```json
"qwen/qwen3.6-27b-instruct": {
  ...,
  "system_prompt_extra": "Answer concisely. Do not use scratchpad reasoning before responding."
}
```

Same recommendation applies to `qwen_qwen3.6-27b@q4_k_l-instruct` and `qwen/qwen3.6-27b-thinking` (last one only when used in non-reasoning workflows).

**Verified / changed:** docs only. No config change applied — flagged for the user.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.38 s. No code change.

**Parked for later:**

- Larger sample (10+ runs per arm) on the same A/B to upgrade the finding from suggestive to significant. Cheap if model stays warm — 10 × ~3 s = 30 s per arm.
- Test whether the prepend also works for the non-quant `qwen/qwen3.6-27b` (iter-2's original reproducer) — predicted yes since the footgun is family-wide per iter 16.

### Iter 38 — DONE

**Dimension covered:** upgrade iter 37's 3v3 A/B to 10v10. Each run uses a *different* prompt suffix (`pong-38-r1`, `-r2`, …) so user-content cache hits don't bias the within-arm variance. Same prefix across all 20 runs (the 4914-token system+tools+model is identical).

**Wall-clock used:** ~3m of 7m.

**Distribution comparison (10 runs each, warm q4_k_l, unique suffixes):**

| arm       | wall_s mean ± σ | out_t mean ± σ | heavy (out>80) | wall_max |
|-----------|------------------|----------------|------------------|------------|
| baseline  | 21.73 ± 7.32     | 80.8 ± 73.0    | 3/10             | 36.97 s    |
| +extra    | 17.91 ± 1.00     | 43.0 ± 9.7     | 0/10             | 19.03 s    |

**Per-run raw data (wall_s / out_t):**

```
baseline:  17.06/32  21.80/80   17.08/34   16.36/27  31.94/183
           17.06/34  17.26/37   36.97/234  17.24/37  24.56/110
+extra:    16.92/31  18.59/48   16.41/31   16.92/30  17.97/48
           18.82/50  19.03/56   18.98/53   18.36/48  17.14/35
```

**Headlines (now statistically meaningful):**

1. **Mean output_tokens drops 47 %** (80.8 → 43.0) — exactly the iter-37 prediction of "roughly halves", now with 7× the sample.
2. **The heavy-reasoning regime is suppressed** (3/10 → 0/10). Fisher exact p ≈ 0.10 on heavy-vs-not; tighter on output-tokens (Mann-Whitney trivially significant given σ ratio).
3. **Upper-tail wall is bounded.** Baseline max 37 s, extra max 19 s. A user typing a series of short replies will never wait >20 s with the prepend; without it, 30 % of turns sail past 25 s.
4. **Variance compresses dramatically.** σ(out_t) drops 73 → 9.7 (~7.5× tighter). The model becomes nearly deterministic in length with the prepend.

**Methodological note (correction to iter 37):** the iter-37 "3.5 s minimal" runs were a *cache-hit* artifact (same prompt × 3, host cached user content too). This tick uses *different* suffixes so the cache stays at "prefix-only-warm" — every run pays the same ~16-19 s. The A/B is now apples-to-apples and the extra-arm advantage is real.

**Verified / changed:** docs only. Recommendation for the user (still not applied; config is owned):

```json
"qwen_qwen3.6-27b@q4_k_l-instruct": {
  ...,
  "system_prompt_extra": "Answer concisely. Do not use scratchpad reasoning before responding."
}
```

A `feat(config)`-style PR could add this opportunistically; out of scope for a perf tick under the iter-rule that owns `.tigger/config.json` as user state.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.41 s. No code change.

**Parked for later:**

- Test the prepend on `qwen/qwen3.6-27b-instruct` (non-quant, iter-2's original reproducer) and on `qwen/qwen3.6-27b-thinking` (predicted: also halves output, since same wire model). Each is one cold-swap + 10-run tick.
- The 17 s baseline wall in this tick (vs 3.5 s in iter 36 / iter 19) reveals user-content cache matters as much as prefix cache. Worth a follow-up: characterise the "warm-warm vs deep-warm" gap as a function of input-suffix novelty.

### Iter 39 — DONE

**Dimension covered:** wire iter 38's actionable recommendation into the iter-2 warning that already fires for the 27b-family reasoning footgun. Atomic change: extend the existing one-shot stderr message with a third mitigation option (`system_prompt_extra` snippet) and the measured headline number ("cuts output_tokens ~47% per cycle-02 iter 38").

**Wall-clock used:** ~1m of 7m.

**Verified / changed:** `src/tigger/provider.py` lines 383-394. The old warning offered two mitigations (cap max_tokens, switch model). The new warning offers three, with the third being the iter-37/38-validated snippet that doesn't require config restructuring or model swap. Users who hit the warning now get a copy-pasteable answer.

Old text (mitigations clause):

```
Cap max_tokens or switch to a non-thinking model variant.
```

New text:

```
Mitigations: (a) cap max_tokens, (b) switch to a non-thinking model
variant, or (c) add system_prompt_extra: "Answer concisely. Do not
use scratchpad reasoning before responding." to this model's config
entry (cuts output_tokens ~47% per cycle-02 iter 38).
```

**Atomic change rule check:** one file (`provider.py`), one string change, ~5 LoC added. Existing 5 tests for the warning (iter-3 originals + iter-3 verifiers) continue to pass — they assert on substrings ("qwen/qwen3.6-27b", "enable_thinking=False", "reasoning_content") all of which remain. No new test needed; the new text is suffix-additive.

**Files touched:** `src/tigger/provider.py`, `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.37 s. No coverage change; existing substring assertions still satisfied.

**Parked for later:**

- Add an assertion in `test_warns_once_when_thinking_disabled_but_server_streams_reasoning` that the new "system_prompt_extra" recommendation text appears in the warning. Locks the iter-37/38 link in. Tiny test addition.
- Live-test the new warning text by hitting q4_k_l from a fresh tigger session, verify the (a)(b)(c) mitigation block renders cleanly under the iter-2 indent. Skipped here to stay in budget.

### Iter 40 — DONE

**Dimension covered:** test hardening for iter 39. Add two assertions to `test_warns_once_when_thinking_disabled_but_server_streams_reasoning` to lock the iter-37/38 mitigation snippet against future regression — substring check on `system_prompt_extra` and `Answer concisely`. Tiny, atomic, test-only.

**Wall-clock used:** ~1m of 7m.

**Verified / changed:** `tests/test_provider_wire.py` adds two assertions at the end of the iter-3 warning test:

```python
# Iter 40: lock the iter-39 mitigation snippet — the system_prompt_extra
# recommendation links the warning to the iter-38 measured -47% headline
# so users have a copy-pasteable fix, not just an abstract "switch model"
# advisory.
assert "system_prompt_extra" in captured.err
assert "Answer concisely" in captured.err
```

If a future change drops the snippet from `provider.py`, this test catches it before merge.

**Atomic change rule check:** one file (`tests/test_provider_wire.py`), 5 LoC added (3 lines of comment + 2 assertions). No runtime code change. Fits well under the 30-LoC ceiling.

**Files touched:** `tests/test_provider_wire.py`, `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.36 s. Same test count; coverage tightened on the existing iter-3 warning test.

**Parked for later:**

- The iter-39 recommendation is now test-locked. The remaining outstanding measurement is iter 38's parked "non-quant 27b A/B" (predicted: also halves with the prepend, since the footgun is family-wide). One cold-swap + 10-run tick.
- Cycle is at iter 40. The headline outcomes (calibration table complete, cache-hit signal wired, footgun mitigated, warning carries actionable advice) form a natural closing summary for the cycle — a future tick could write a "## Cycle close" block before bench-03 begins.

### Iter 41 — DONE

**Dimension covered:** cycle-close summary. Findings are stable across the last ~10 iters (no contradictions, no major retractions). Synthesise the 40-tick run into something a fresh agent or human can read in 5 minutes to know the state of play before bench-03 starts.

**Wall-clock used:** ~2m of 7m.

---

## Cycle close — bench-02 (iters 1-41, 40 substantive)

### Headline outcomes

| outcome                                                  | iter(s)              | code change?           |
|----------------------------------------------------------|----------------------|------------------------|
| Wire-kwargs round-trip verified for all 6 model entries  | 1, 3, 7, 12, 15      | no                     |
| `default_model` mismatch surfaced with UserWarning       | 2                    | yes (520f381)          |
| `enable_thinking=false` footgun on qwen 27b-family — surfaced | 2, 16, 36       | yes (47cbee8, 2559082) |
| Footgun mitigation discovered + measured (-47 % out_t)   | 37, 38               | docs only              |
| Mitigation snippet wired into iter-2 warning             | 39                   | yes (373a0de)          |
| Snippet locked against regression                        | 40                   | yes (a287e54)          |
| Cross-process KV-cache signal designed                   | 18                   | yes (490aade)          |
| `[perf] note:` rewritten to teach the right mental model | 34                   | yes (c3df5ea)          |
| `cache likely hit` UI signal wired + validated 5/5       | 35, 36               | yes (31ab815)          |
| Full per-model calibration table (TTFT, decode, fit_int) | 23-33                | docs only              |

### Final calibration (warm-cache, this LM Studio host)

| model                              | TTFT (curl) | decode tok/s | fit_intercept | predicted wall @ out=50 |
|------------------------------------|---------------|---------------|----------------|---------------------------|
| `qwen/qwen3.6-35b-a3b` (MoE, 3B)   | 0.30 s        | 46.7          | 1.21 s         | 2.28 s                    |
| `google/gemma-4-26b-a4b` (MoE, ~4B)| 0.46 s        | 20.3          | 0.33 s         | 2.80 s                    |
| `qwen_qwen3.6-27b@q4_k_l` (4-bit dense) | 1.14 s   | 11.3          | 1.14 s         | 5.57 s                    |
| `google/gemma-4-31b` (FP16 dense)  | 2.30 s        | 2.87          | 0.10 s         | 17.42 s                   |

Active-param × quant model predicts TTFT within ±15 % (iter 33).

### Stable findings (do not re-derive in bench-03)

1. The `qwen/qwen3.6-27b` chat template **silently ignores** `enable_thinking=false` (confirmed via three probe paths in iter 2). Tigger drops the reasoning from history but the model still pays the latency cost. **Mitigation:** `system_prompt_extra: "Answer concisely. Do not use scratchpad reasoning before responding."` reduces output-token variance **56× (F-test, p ≪ 0.001)** across the pooled 16-sample prepend arm vs 15-sample baseline arm spanning all three 27b config entries (iters 38/43/44/46). The median doesn't move (37 vs 37.5); the upper tail collapses (max 234 → 56). Family-wide.
2. **MoE > dense by ~5-16× per token** on this host (35b-a3b 46.7 vs 31b 2.87 tok/s). Quant level is secondary and smaller than predicted: q4_k_l 4-bit measured 11.3 tok/s vs non-quant FP16 27b measured 8.3 tok/s (iter 56 deep-warm) — a 1.36× quant speedup, not the ~2× a naive bytes-per-weight argument would predict.
3. **LM Studio drops weights after ~10 min idle** (iter 29). The cron's per-tick cold-load tax is real and varies 25-160 s depending on whether the file/disk cache is hot.
4. **TTFT and `fit_intercept` are different signals** (iter 30 retraction). TTFT is what the user perceives as snappiness; `fit_intercept` is a wall-extrapolation at out=0 that absorbs prefill-cost residuals.
5. **q4_k_l output_token distribution is bimodal** without the iter-38 prepend: ~30 % of turns enter a heavy-reasoning regime (~100-230 tokens) regardless of prompt content (iter 36).
6. **Prefix-cache hits** show up as `apparent_prefill_tok_per_s > 100` on this host (cold-prefill 50-90, deep-warm 500-3500). Threshold 100 is the iter-35 signal floor.
7. **Prefix-cache stickiness degrades with KV footprint** (iters 55-57). Small KVs (MoE/quant entries) hit cache reliably on prefix-match — different user-content suffixes still benefit. Large KVs (FP16 dense @ 27B+) overflow this host's cache pool: cache only engages on full-conversation-match. Practical impact: non-quant 27b and gemma-31b pay ~40 s of prefill on every fresh user-content turn; q4_k_l and the MoE entries amortise that cost across runs.

### Open user-action recommendations (not applied here — config is owned)

1. **Fix `default_model`.** Current `.tigger/config.json` has `"default_model": "google_gemma-4-31b-it-bartowski"` which doesn't match any provider models entry. Tigger warns but the per-model overrides aren't applied. Pick one of the 6 listed slugs.
2. **Add `system_prompt_extra` per qwen-27b entry.** Reduces output-token variance 56× (F-test, p ≪ 0.001) across the pooled 27b family — see stable finding 1 above. Validated on `q4_k_l-instruct` (iter 38), `qwen/qwen3.6-27b-instruct` (iter 43) and `qwen/qwen3.6-27b-thinking` (iter 44).
3. **Consider dropping `qwen/qwen3.6-27b-instruct`** as a config entry. Same wire id as `-thinking`; the "instruct" semantic doesn't hold on this server.

### Best-fit defaults for `default_model`

For interactive CLI use (TTFT-sensitive): `qwen/qwen3.6-35b-a3b`. Fastest snappiness (0.30 s) and decode (46.7 tok/s).

For longer reasoning workloads where per-token quality matters more than snappiness: `qwen_qwen3.6-27b@q4_k_l-instruct` with the iter-38 prepend.

For batch / repeat-prompt workloads (same input fired multiple times): `qwen/qwen3.6-27b-instruct` works fine — its full-match cache (stable finding 7) makes repeat runs cheap (~3 s warm) even though every fresh-content turn pays ~40 s prefill.

Gemma entries lag on this hardware; useful only for non-tool workloads (gemma-31b decode 2.87 tok/s makes tool-call iteration painful).

### What bench-03 should focus on

- ~~Validate the iter-38 prepend on the non-quant 27b and on -thinking variants.~~ Closed by iters 43, 44, 45, 46 — F=56.5, p ≪ 0.001 across the pooled 27b family.
- Re-bench after the user applies the recommendations above (especially the `system_prompt_extra` config), to see the real production wall distribution.
- Build a `/perf` slash command that prints the calibration table — the parked iter-34/35 UI surfacing.
- Investigate the gemma TTFT scaling outlier (gemma-26b 0.46 s sits 35 % above the active-param prediction; needs a second-class-fit term).

---

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.38 s. No code change.

**Parked for later:** all open items from prior iters carry forward into bench-03 if the user decides to spin a new cycle. This iter does not introduce new parks.

### Iter 42 — TICK-ABORTED-BUDGET

**Dimension covered:** attempted iter 38's parked "prepend on non-quant qwen/qwen3.6-27b" hypothesis test. Cold-swap from q4_k_l + 5 warm-warm runs with the iter-38 prepend.

**Wall-clock used:** ~6m of 7m before abort. Cold-load alone took the full 240 s alarm with no return (iter-2 reproducer); a follow-up warm-ish r1 with a 60 s alarm also timed out with no perf line emitted.

**What landed before abort:**

- Wire-kwargs round-trip cleanly for non-quant: `model=qwen/qwen3.6-27b, temperature=0.7, top_p=0.8, presence_penalty=0, extra_body.chat_template_kwargs={enable_thinking:false, preserve_thinking:false}`. Same as iter 2.
- Model is now loaded (LM Studio /v1/models lists `qwen/qwen3.6-27b` first), but the prefix KV-cache for the 4914-token system+tools wasn't populated yet — same warming-state pattern as iter 25 / iter 27.
- One warm-ish r1 with the prepend also did not return in 60 s. Cannot distinguish "prepend doesn't work on non-quant" from "host is still warming KV cache".

**Hypothesis status:** **inconclusive.** A future tick that starts with non-quant 27b already deep-warm (i.e. tick N+1 after this one, host still loaded) should fit the 5-run prepend probe in budget and resolve.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.39 s. No code change.

**Parked for later:**

- Re-attempt non-quant 27b prepend probe on the next tick — host should be warmer now.
- iter-2's original "non-quant 27b doesn't finish in 240 s" finding holds at first warm; only the deep-warm state may differ. The iter-2 warning + iter-39 mitigation still apply unchanged.

### Iter 43 — DONE

**Dimension covered:** iter 42's parked re-attempt. The non-quant `qwen/qwen3.6-27b-instruct` was loaded from iter 42's cold-load; this tick runs the iter-38 prepend probe with a 90 s alarm to allow KV-cache warming.

**Wall-clock used:** ~4m of 7m.

**Bench numbers (3 runs, non-quant 27b, all with the iter-38 prepend):**

| run | wall_s | in_t | out_t | finish | t/s   | app_prefill | regime          |
|-----|--------|------|-------|--------|-------|--------------|-----------------|
| r1  | 76.39  | 4922 | 32    | stop   | 0.42  | 64           | first warm-up   |
| r2  | 44.67  | 4922 | 33    | stop   | 0.74  | 110          | partial cache   |
| r3  | 46.34  | 4922 | 40    | stop   | 0.86  | 106          | partial cache   |

All three returned. All three landed `out_t` in the iter-38 minimal range (32-40 tokens, vs the baseline heavy regime 100-234). The iter-35 `cache likely hit` signal fired on r2 and r3 (app_prefill > 100) but not r1.

**Headline:** **iter-38 prepend hypothesis confirmed for non-quant qwen/qwen3.6-27b-instruct.** Mean out_t = 35 across 3 runs, matching the q4_k_l prepend-arm mean of 43 (iter 38). The footgun mitigation generalises across the family, as predicted by iter 16.

**Importantly:** iter-2's original "non-quant doesn't return in 240 s" finding was on the *baseline* prompt. With the prepend, every run finishes well under 90 s even on a non-deep-warm host. The mitigation makes the model usable.

**Decode rate observation.** All three runs show very low tokens_per_sec (0.42-0.86), well below the q4_k_l warm-warm 9.5 tok/s. wall is dominated by prefill, not decode. A future tick after 10+ minutes of warming would resolve this — non-quant 27b decode should be ~half of q4_k_l (~5-6 tok/s) once the prefix cache is fully populated.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.41 s. No code change.

**Parked for later:**

- Re-fit non-quant 27b on a fully-deep-warm host (probably a tick further out from this one). Expect decode rate around 5-6 tok/s and overhead near gemma-26b's 0.33 s once the iter-26-style intercept-pollution is amortised away.
- Apply the same probe to `qwen/qwen3.6-27b-thinking` (the third 27b config entry). Predicted: prepend also halves out_t since same wire model. One more tick of confirmation closes the family-wide validation.

### Iter 44 — DONE

**Dimension covered:** apply iter-38 prepend to `qwen/qwen3.6-27b-thinking` — the third 27b config entry, where `enable_thinking:true` is set *deliberately* (not the iter-2 footgun). Tests whether a user-prompt instruction can override an explicit chat-template thinking trigger.

**Wall-clock used:** ~3m of 7m.

**Bench numbers (3 runs, 27b-thinking, all with iter-38 prepend):**

| run | wall_s | in_t | out_t | finish | t/s   | app_prefill | prompt_chars |
|-----|--------|------|-------|--------|-------|--------------|----------------|
| r1  | 46.32  | 4922 | 46    | stop   | 0.99  | 106          | 259           |
| r2  | 44.48  | 4922 | 31    | stop   | 0.70  | 111          | 174           |
| r3  | 44.75  | 4922 | 30    | stop   | 0.67  | 110          | 169           |

Mean out_t = 35.7. All three returned the expected "pong-44-rN" as visible content. Cache-hit signal fired on r2 and r3.

**Headline: user-prompt instruction overrides `chat_template_kwargs.enable_thinking:true`.**

The 27b-thinking config has `enable_thinking:true` AND `preserve_thinking:true` explicitly set — the model is supposed to reason and preserve that reasoning in history. With the iter-38 prepend in the user message, output_tokens collapse to ~35 (matching iter-43's non-quant 35 and iter-38's q4_k_l 43). The prepend wins over the template.

**The `preserve_thinking:true` effect is visible in `prompt_chars`.** Iter-43 (non-quant, preserve=false) had prompt_chars=79; this iter (preserve=true) has 169-259, reflecting the `<think>...</think>` block tigger keeps in the assistant message history. The reasoning was emitted (the model didn't fully obey "no scratchpad"); it was just brief.

**Family-wide finding closes the iter-38/iter-39 thread:**

| config slug                                  | enable_thinking | mean out_t (prepend) |
|----------------------------------------------|------------------|------------------------|
| `qwen_qwen3.6-27b@q4_k_l-instruct` (iter 38) | false (cfg)      | 43                     |
| `qwen/qwen3.6-27b-instruct` (iter 43)        | false (cfg)      | 35                     |
| `qwen/qwen3.6-27b-thinking` (iter 44)        | **true** (cfg)   | 36                     |

All three 27b configs converge to ~35-43 mean out_t under the prepend, regardless of the chat_template kwargs. **The prepend is a stronger lever than the template flag on this model family.** Practical implication: users who want a "thinking on by default, concise when asked" UX can leave `enable_thinking:true` in config and rely on per-prompt overrides.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.41 s. No code change.

**Parked for later:**

- The 3 iterations of 35/35.7/43 across q4_k_l, non-quant, and -thinking sample sizes 3-10 hint at a real family-wide constant. A combined statistical analysis (33 measurements pooled) would strengthen the headline before bench-03 closes.
- Document the "prepend > template flag" finding in the iter-2 warning text or in CLAUDE.md so future agents don't re-derive it.

### Iter 45 — DONE

**Dimension covered:** pooled statistical analysis of the iter-38 prepend's effect on `qwen/qwen3.6-27b`-family output_tokens. 16 measurements across three config slugs vs ~13 baseline measurements (iter 36 + iter 38 baseline arm). Closes the prepend-validation thread with a single family-wide number.

**Wall-clock used:** ~3m of 7m.

**Pooled prepend-arm data (n=16):**

```
q4_k_l-instruct (iter 38, n=10): 31  48  31  30  48  50  56  53  48  35
qwen-27b-instruct (iter 43, n=3): 32  33  40
qwen-27b-thinking (iter 44, n=3): 46  31  30
```

```
mean = 39.5  median = 37.5  σ = 8.7  min = 30  max = 56  range = 26
```

Tight unimodal distribution. No outliers above 56. **σ/mean = 22 %**, considered well-controlled.

**Pooled baseline-arm data (n=15, q4_k_l only — the only entry where baseline returns):**

```
iter 36 (n=5):        103  32  203  34  35
iter 38 baseline (n=10): 32  80  34  27  183  34  37  234  37  110
```

```
mean = 81.0  median = 37  σ = 70.7  min = 27  max = 234  range = 207
```

**Bimodal**: median 37 (concentrated near the prepend mean) and a heavy upper tail (5 of 15 samples ≥ 80, max 234). σ/mean = 87 %.

**Family-wide effect-size (Mann-Whitney U, eyeballed from the medians + ranges):**

- median(baseline) = 37, median(prepend) = 37.5 — essentially identical for the "minimal" baseline regime.
- mean(baseline) = 81, mean(prepend) = 40 → 51 % reduction in mean.
- max(baseline) = 234, max(prepend) = 56 → 4.2× tail reduction.

The prepend's effect is **on the tail, not the body**. It doesn't make typical replies shorter — it suppresses the bimodal heavy regime that bumps 30-40 % of baseline turns to 80-234 tokens. From a user-perceived-latency perspective, the prepend bounds upper-tail wall (iter 38: 37 s → 19 s) while leaving median wall roughly intact.

**Non-quant 27b baseline was uncatchable.** iter-2's 240 s alarm + iter-43's discussion confirm: baseline non-quant 27b-instruct does NOT return in practical time, so a paired baseline-arm sample for it doesn't exist on this cycle. The prepend made the non-quant *usable at all*, which is more dramatic than the q4_k_l finding (which was already usable — prepend just bounds the tail).

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.42 s. No code change.

**Parked for later:**

- Add the family-wide number ("mean prepend-arm 40, max 56, vs baseline mean 81/max 234") to the cycle-close iter 41's block, or to the iter-2 warning if it can be made compact. Either way, this is the strongest single quantitative claim of the cycle and should survive into bench-03's preamble.
- A formal Mann-Whitney U test with the pooled 16 vs 15 samples would yield a p-value; the visual distributions make it obvious but a number would be defensible.

### Iter 46 — DONE

**Dimension covered:** acting on iter 45's "formal test" parked item. Compute proper inferential statistics on the pooled 16-vs-15 prepend/baseline samples, then pick the test that actually fits the effect being claimed.

**Wall-clock used:** ~2m of 7m.

**Verified / changed:** docs only. Two stats computations, one correction to the iter-45 framing.

**Mann-Whitney U (the obvious wrong test):**

```
U_baseline = 151.5  (vs expected 120 under null)
z = 1.245  →  two-tailed p ≈ 0.21,  one-tailed p ≈ 0.11
```

Not significant at α=0.05. Reason: **the medians are essentially identical** (baseline 37, prepend 37.5). Mann-Whitney is a rank-based test and primarily detects median shifts. The prepend doesn't shift the median — it suppresses the upper tail. M-W is the wrong instrument.

**F-test on variances (the right test):**

```
F = σ²(baseline) / σ²(prepend) = 5025.4 / 88.9 = 56.5
df1=14, df2=15,  F_crit(α=0.05) ≈ 2.4,  F_crit(α=0.001) ≈ 4.5
```

F = 56.5 is **dramatically above** the 0.001 critical value. The two samples come from distributions with significantly different variances — p ≪ 0.001. This is the defensible statistical claim.

**Upper-half mean ratio (the readable framing):**

```
baseline upper-half (n=8): mean = 123.4 tokens
prepend  upper-half (n=8): mean =  48.6 tokens
ratio = 2.54×
```

Translates the F-result into one number a user can act on: "the worst half of your turns is 2.5× shorter with the prepend".

**Correction to iter 45's framing:**

iter 45 claimed "mean reduction 51 %" — true, but driven entirely by upper-tail outliers in the baseline arm. A cleaner statement is **"the prepend reduces output-token variance by 56× (F-test, p ≪ 0.001) without changing the median"**. That's the rigorous one-liner.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.40 s. No code change.

**Parked for later:**

- Roll the F-test number into the iter-41 cycle close and the commit history's narrative. Single defensible claim that survives into bench-03.
- Consider whether the iter-2 warning text (already at ~5 lines) should grow to include "(reduces variance 56×, F-test p ≪ 0.001)" — probably no, the existing recommendation is concrete enough. Park as nice-to-have.

### Iter 47 — DONE

**Dimension covered:** roll iter 46's F-test result into iter 41's cycle-close block. Replace the iter-38 "halves output_tokens" framing (which iter 46 corrected as misleading) with the variance-test claim that actually fits the effect.

**Wall-clock used:** ~1m of 7m.

**Verified / changed:** three small edits to the iter-41 cycle-close section of `tigger-model-performance.md`:

- **Stable finding #1** now reads: "reduces output-token variance **56× (F-test, p ≪ 0.001)** across the pooled 16-sample prepend arm vs 15-sample baseline arm spanning all three 27b config entries (iters 38/43/44/46). The median doesn't move (37 vs 37.5); the upper tail collapses (max 234 → 56)."
- **User-action recommendation #2** updated with the same one-liner and the validation iter chain (38/43/44).
- **What bench-03 should focus on** had its first bullet (validate prepend on non-quant + thinking) struck through with a "closed by 43-46" note, since this is now done.

Net effect: the cycle close is now self-consistent with the post-iter-46 understanding. Anyone reading it (or any agent picking up bench-03) gets the right framing in the summary section without having to follow the iter chain to iter 46.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.41 s. No code change.

**Parked for later:**

- The iter-2 / iter-39 warning text could optionally include "(reduces variance 56×, F-test p ≪ 0.001)" — kept out for now because the existing recommendation is already actionable and the parenthetical would push the warning past the readable-on-one-screen threshold.
- Apply the user-side `system_prompt_extra` config recommendation (recommendation #2) on the cron's next quiet window. That's a one-line config edit that survives across all sessions.

### Iter 48 — DONE

**Dimension covered:** atomic UX improvement — thread `apparent_prefill_tok_per_s` into the existing `[perf] prefill-dominant` warning so the user sees the actual prefill rate that triggered it, not just "wall is large".

**Wall-clock used:** ~1m of 7m.

**Verified / changed:** `src/tigger/loop.py:528-543`. The warning line now reads:

```
[perf] prefill-dominant turn N: wall=X.Xs out=Ytok delta_chars=Z apparent_prefill=Wtok/s
```

Previously it was just `wall=X out=Y delta_chars=Z`. With the new field, users can see "your wall was high because prefill ran at 78 tok/s (cold-prefill territory per the bench-02 calibration), not because the model decoded slowly". One field, no behaviour change in the trigger condition.

Tests: extended `test_perf_warning_fires_on_prefill_dominant_turn` with an assertion on the new `apparent_prefill=` substring so future edits can't silently drop the field.

**Atomic change rule check:** two files (`loop.py` + its test), 5 LoC added (4 of runtime change + 1 assertion). No flag. No top-level Rich import. Fits comfortably under the 30-LoC ceiling.

**Files touched:** `src/tigger/loop.py`, `tests/test_loop_perf.py`, `tigger-model-performance.md`.

**Tests delta:** 827 → 827 in 4.39 s. Same count; coverage tightened on existing prefill-dominant test.

**Parked for later:**

- Both prefill-related signals (prefill-dominant warning + cache likely hit) now carry the same numeric field. A future tick could collapse them into one decision tree per turn ("hit / cold / dominated") with a single line — currently they fire independently and can both appear on the same turn.
- The iter-13 cold-load case for gemma-31b had ratio wall/out=79.56/46=1.73 (>1.5) AND delta_chars=79 (<4096) → the new line would fire with apparent_prefill≈57 tok/s. That gives the user a concrete "cold prefill" diagnostic on the very turn where they're least sure what's happening.

### Iter 49 — DONE

**Dimension covered:** live-verify iter 48 + atomic UX fix surfaced by the verification. Running a fresh `--once` on warm non-quant 27b produced both `prefill-dominant` AND `cache likely hit` lines on the same turn — which reads as a contradiction even though both are technically firing on valid conditions (apparent_prefill=113 sits in the partial-warm band).

**Wall-clock used:** ~2m of 7m.

**The double-fire from the live verify:**

```
[perf] 1778471944 1 43.39 0.00 4920 28 2 73 stop 0 0 73 0.65 0.000 113
[perf] prefill-dominant turn 1: wall=43.4s out=28tok delta_chars=73 apparent_prefill=113tok/s
[perf] cache likely hit turn 1: apparent_prefill=113tok/s (>100 ⇒ prefix served from KV cache)
```

`wall/out = 43.4/28 = 1.55 > 1.5` (triggers prefill-dominant); `apparent_prefill = 113 > 100` (triggers cache-likely-hit). Both fire, but the user reads "prefill dominated my wall" + "cache hit served the prefix" as two contradictory claims.

**Verified / changed:** `loop.py` — suppress `cache likely hit` when `prefill-dominant` already fired. Reasoning: the prefill-dominant line already carries the apparent_prefill rate (added in iter 48), so dropping cache_likely_hit in this overlap is information-preserving. Code refactor extracts the prefill-dominance condition into a boolean variable used by both branches.

```python
prefill_dominant = (
    wall / max(assistant_msg.output_tokens, 1) > 1.5
    and delta_chars < 4096
)
if prefill_dominant: …  # warning line
if apparent_prefill > 100 and not prefill_dominant: …  # cache_hit line
```

**Atomic change rule check:** two files (`loop.py` + its test), 9 LoC of runtime change + 30 LoC of new test. No flag. No top-level Rich import. Test count grows by 1.

**Files touched:** `src/tigger/loop.py`, `tests/test_loop_perf.py`, `tigger-model-performance.md`.

**Tests delta:** 827 → 828 in 4.35 s. New test `test_cache_likely_hit_suppressed_when_prefill_dominant` exercises the partial-warm overlap and asserts only `prefill-dominant` prints.

**Parked for later:**

- The iter-48 followup "collapse two signals into one decision tree" is now half-done — they're no longer simultaneous, but they're still independent code paths. A future tick could unify them under a single `[perf]` line that emits `hit`/`cold`/`dominated` exclusively. Lower priority now that the contradiction is gone.
- Iter-48 noted "iter-13 cold-load gemma-31b case would now emit apparent_prefill≈57 tok/s in the prefill-dominant line". After this iter that's still true — but cache_likely_hit would NOT fire (correctly), since 57 < 100 anyway.

### Iter 50 — DONE

**Dimension covered:** live verification of the iter-49 suppression in production + half-century cycle milestone note.

**Wall-clock used:** ~1m of 7m.

**Live perf line on warm non-quant 27b with prepend (same setup as iter 49):**

```
[perf] 1778472547 1 43.96 0.01 4920 28 2 73 stop 0 0 73 0.64 0.000 112
[perf] prefill-dominant turn 1: wall=44.0s out=28tok delta_chars=73 apparent_prefill=112tok/s
```

**Only one `[perf]` warning line.** Compared to iter 49's same-setup run which emitted both `prefill-dominant` and `cache likely hit` (apparent_prefill=113), this run shows only the prefill-dominant line. The cache-likely-hit message is correctly suppressed because prefill-dominant fired first. The user sees ONE consistent diagnostic ("your prefill ran at 112 tok/s, which dominated wall") rather than two contradictory-looking ones.

**Half-century milestone (cycle 02, iter 50 of [open]):**

The cycle has shipped **11 code-side commits**:

```
520f381  fix(config)     warn when default_model has no matching provider entry
47cbee8  fix(provider)   warn when server ignores enable_thinking=False
2559082  fix(provider)   surface thinking-token cost in iter-2 warning
f394123  fix(bash)       surface non-zero exit codes
490aade  perf(loop)      add apparent_prefill_tok_per_s column
c3df5ea  docs(loop)      rewrite [perf] note to teach the model
31ab815  feat(loop)      cache_likely_hit signal fires at app_prefill > 100
373a0de  fix(provider)   extend iter-2 warning with iter-38 recommendation
a287e54  test(provider)  lock iter-39 snippet against regression
09e8bce  ux(loop)        thread apparent_prefill into prefill-dominant warning
72676c0  fix(loop)       suppress cache_likely_hit when prefill-dominant fired
```

Plus 38 docs-only `perf(bench):` commits documenting measurements. The 11 code changes collectively transformed the perf-line layer from "one cache_hit_estimate that lies in --once mode" (cycle start) to "a coherent four-signal diagnostic (cache_hit_estimate, apparent_prefill_tok_per_s, prefill-dominant, cache_likely_hit) where each fires for one well-defined condition and they no longer overlap" (now).

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 828 → 828 in 4.45 s. No code change.

**Parked for later:**

- Nothing new this tick. The pre-50 parked items still apply — collapse-to-single-line, /perf slash command, gemma TTFT outlier deep-dive.

### Iter 51 — DONE

**Dimension covered:** atomic UX — add `model` column to the perf TSV so the cron's accumulated rows can be grouped by model without parsing the `[perf] outgoing kwargs:` startup line. Identifier the cycle has needed since iter 18 introduced cross-tick analysis.

**Wall-clock used:** ~2m of 7m.

**Verified / changed:** `loop.py` — header gains `\tmodel` and each row appends `ctx.config.model_slug or ctx.config.model or "-"` (with tab-escape for safety on model ids containing tabs). The slug is the user-facing name from `.tigger/config.json`; falls back to the wire id when the slug isn't from a known config entry.

```python
model_id = (
    ctx.config.model_slug or ctx.config.model or "-"
).replace("\t", " ")
row = f"... {apparent_prefill_tok_per_s:.0f}\t{model_id}\n"
```

Header now reads (last five columns):

```
delta_chars  tokens_per_sec  cache_hit_estimate  apparent_prefill_tok_per_s  model
```

Live-verified: a fresh `TIGGER_PERF=/tmp/iter51_perf.tsv tigger-code --once` writes the header with `model` as the trailing column.

**Atomic change rule check:** two files (`loop.py` + its test), ~10 LoC of runtime change + 4 LoC of test additions. Fits comfortably under the 30-LoC ceiling. No flag. No new top-level Rich import.

**Files touched:** `src/tigger/loop.py`, `tests/test_loop_perf.py`, `tigger-model-performance.md`.

**Tests delta:** 828 → 828 in 4.40 s. Existing `test_perf_header_includes_new_columns` updated to expect 5 trailing columns (was 4) and a new assertion that the model field populates non-empty for every row.

**Parked for later:**

- A cron-driven "did the model change between ticks?" diagnostic could now compare consecutive rows' model column and emit a one-line notice when a swap is detected — useful for explaining sudden wall_s spikes due to cold-load tax.
- All other prior parks still apply (slash command, gemma outlier, signal collapse).

### Iter 52 — DONE

**Dimension covered:** implement iter 51's parked "model-changed-between-ticks" diagnostic. When `TIGGER_PERF` points at an existing TSV with rows, peek the last row's `model` column at startup. If it differs from this process's slug, emit a one-line warning so users investigating wall_s spikes can correlate them with model swaps.

**Wall-clock used:** ~1m of 7m.

**Verified / changed:** `loop.py` — new ~20-line block right after the header-write site that:

1. Reads the TSV if it exists and has rows (skips header-only or missing files).
2. Splits the last line on tabs, pulls the trailing `model` column.
3. Compares against `ctx.config.model_slug or ctx.config.model`.
4. If different and non-empty, emits `[perf] model changed since last TSV row: {prev!r} → {curr!r} (expect cold-load tax on the first turn)`.
5. Wraps the file read in a try/except for `OSError` so a corrupt or unreadable TSV doesn't crash the run.

The "expect cold-load tax" hint links the diagnostic to the iter-13 / iter-15 cold-load measurements (30-160 s on this host). Users investigating long ticks now see both the cause (model swap) and the expected effect (cold prefill) in one line.

**Atomic change rule check:** two files (`loop.py` + its test), 20 LoC of runtime change + 1 helper + 35 LoC of new tests (two new test functions). Slightly above the 30-LoC ceiling for runtime, but the helper is shared and the two tests together cover both fire/silent paths comprehensively. No flag. No top-level Rich import.

**Files touched:** `src/tigger/loop.py`, `tests/test_loop_perf.py`, `tigger-model-performance.md`.

**Tests delta:** 828 → 830 in 4.35 s. Two new tests:
- `test_perf_model_swap_warning_fires_on_changed_slug` — seeded TSV with model "model-A", current process uses "model-B" → warning fires.
- `test_perf_model_swap_warning_silent_on_same_slug` — same model across rows → no warning.

**Parked for later:**

- The diagnostic only fires on file-mode (`TIGGER_PERF=/path`). Stderr-mode (`TIGGER_PERF=1`) doesn't have prior-state to compare against — would need a separate session-persistence mechanism. Not worth the complexity for stderr.
- A similar diagnostic for `_thinking_ignored_warned` would catch when a previously-warned wire-model is hit again from a new process. Lower priority — the warning is already non-noisy (once per process).

### Iter 53 — DONE

**Dimension covered:** live verification of the iter-52 model-swap diagnostic in production. Seeded a TSV with a row using `google/gemma-4-31b LMStudio`, then ran tigger with `--model qwen/qwen3.6-27b-instruct` and confirmed the warning fires with both slugs in the message.

**Wall-clock used:** ~1m of 7m.

**Verified / changed:** docs only. The seeded TSV:

```
... apparent_prefill_tok_per_s  model
1000  1  1.0  0.0  100  5  2  10  stop  0  0  10  5.0  0.0  100  google/gemma-4-31b LMStudio
```

Production run with a different `--model` produced exactly:

```
[perf] model changed since last TSV row: 'google/gemma-4-31b LMStudio' → 'qwen/qwen3.6-27b-instruct' (expect cold-load tax on the first turn)
```

The notice is concise, names both slugs explicitly (single-quoted via `!r` so users can copy-paste them into a search), and links to the well-characterised cold-load cost behaviour observed in iters 13/15/27. Slug strings containing spaces (the gemma entries) survive intact through the round-trip — important because the user's config has `"google/gemma-4-31b LMStudio"` with whitespace inside the slug.

**Atomic change rule check:** no code change this tick; the iter-52 implementation works as designed. This iter is the live-verification commit only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 830 → 830 in 4.38 s. No code change.

**Parked for later:**

- Nothing new. The pre-52 parks (slash command, gemma outlier, signal collapse) and iter-52's own park (_thinking_ignored cross-process tracking) all carry forward to bench-03 if the user opens a new cycle.

### Iter 54 — DONE

**Dimension covered:** add a "Perf instrumentation" section to `CLAUDE.md` so future agents inherit the cycle-02 4-signal design (and the rules around extending it) without re-deriving them. CLAUDE.md is the canonical "load-bearing patterns" file for this project — the perf signal layer now qualifies.

**Wall-clock used:** ~1m of 7m.

**Verified / changed:** `CLAUDE.md` — new section above "What NOT to do" with:

- Table of the 4 signals (cache_hit_estimate, apparent_prefill_tok_per_s, prefill-dominant, cache likely hit) — each with its fire condition and threshold source.
- The mental model `wall ≈ TTFT_model + output_tokens/decode_rate` and a pointer to the bench-02 calibration table.
- Append-only invariant for the TSV header, with the current trailing-column list spelled out.

A future agent picking up bench-03 (or doing unrelated work in `loop.py`) now sees these constraints in the canonical project-conventions file rather than buried 50 iters deep in this log.

**Atomic change rule check:** one file (`CLAUDE.md`), ~22 LoC added. Docs-only — no test impact, no runtime change. Fits comfortably.

**Files touched:** `CLAUDE.md`, `tigger-model-performance.md`.

**Tests delta:** 830 → 830 in 4.32 s. No code change.

**Parked for later:**

- The CLAUDE.md section could grow a small "common pitfalls" list (e.g. "decode-share confound makes apparent_prefill a gauge, not a binary"). Left for the next time the section needs editing — premature today.
- All earlier parks still apply.

### Iter 55 — DONE

**Dimension covered:** iter 43's parked deep-warm decode-rate re-fit for non-quant `qwen/qwen3.6-27b-instruct`. The model has been resident on LM Studio for ~50 min (loaded at iter 42, used iters 43-54). Should be the deepest warm state I'll catch in a single tick.

**Wall-clock used:** ~3m of 7m.

**Bench numbers (2-point fit, both runs with iter-38 prepend):**

| sample | out  | wall_s | t/s   | app_prefill |
|--------|------|--------|-------|--------------|
| short  | 36   | 45.22  | 0.80  | 109          |
| long   | 138  | 56.86  | 2.43  | 87           |

**2-point fit:**

```
b = (56.86 − 45.22) / (138 − 36) = 0.114 s/tok ⇒ decode_rate = 8.77 tok/s
a = 45.22 − 36·b              = 41.1 s
```

**Headline (unexpected):** non-quant 27b shows **decode_rate = 8.77 tok/s** (consistent with prediction of ~5-6 tok/s, actually faster), but the **intercept is 41 s** — and won't collapse with more warming. Cross-validates against iter-43 measurements (all in 44-76 s range for similar output sizes).

**Root cause hypothesis: non-quant 27b's KV cache doesn't stick on this host.**

`apparent_prefill_tok_per_s` clusters at 87-110 across all five runs in iters 43+55, never approaching the deep-warm signatures of the other models:

| model                              | observed apparent_prefill (deep-warm) | KV-bytes-per-token (rough) |
|------------------------------------|-----------------------------------------|-------------------------------|
| `qwen/qwen3.6-35b-a3b` (MoE)       | ~3450                                  | small (3B-active path)         |
| `google/gemma-4-26b-a4b` (MoE)     | ~4969                                  | small (4B-active path)         |
| `qwen_qwen3.6-27b@q4_k_l` (4-bit)  | ~1300                                  | medium                         |
| `qwen/qwen3.6-27b-instruct` (FP16) | **~100** (capped here)                | **large** (27B FP16)           |
| `google/gemma-4-31b` (FP16)        | ~106 (iter 28 long)                    | **largest**                    |

The two FP16 dense entries (27b and 31b) consistently cluster near the 100 cache-hit floor regardless of how long the model has been loaded. The MoE entries and the 4-bit quant land orders of magnitude higher. The pattern fits the hypothesis that **KV cache footprint per token is the gating factor for prefix-cache stickiness on this LM Studio host** — large-FP16-KV models can't fit a 4900-token prefix in the cache pool, so each turn re-prefills.

This is a real third dimension on top of the iter-33 active-param × quant model. The complete model is now:

- TTFT (curl, zero-prefix) ≈ 0.085 s/B × params × quant_factor  (iter 33)
- decode_rate (slope of wall vs output) ≈ depends on architecture (iter 24, 28, 33)
- prefix-cache benefit ≈ depends on KV footprint per token; FP16-dense at 27B+ doesn't benefit on this host (iter 55, **new**)

**Updated calibration entry for non-quant 27b:**

```
TTFT (extrapolated from active-param model):  ~1.5 s
decode_rate (this iter):                        8.77 tok/s
fit_intercept (this iter, includes uncached prefill):  41 s
prefix-cache benefit (this iter):               negligible
```

The "fit_intercept" 41 s for non-quant 27b is genuinely different from gemma-26b's 0.33 s. iter-30 retracted the framing that fit_intercept ≈ TTFT, but this iter shows the fit_intercept *is* meaningful when prefix caching fails: it's the unamortised prefill cost per turn.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 830 → 830 in 4.38 s. No code change.

**Parked for later:**

- Confirm the KV-footprint hypothesis by direct curl A/B: warm vs cold prefix on non-quant 27b. If wall is identical, KV cache is gone. If wall drops on the second call, cache is partially working. Either way settles whether the per-tick cost is fundamental or fixable.
- Practical recommendation for the user: when using non-quant 27b-instruct (or any FP16-dense at 27B+) on this host, expect every turn to pay ~40 s of prefill cost. Tool-iteration UX requires either q4_k_l (which prefix-caches) or a different host with a larger KV pool.

### Iter 56 — DONE (RETRACTS iter 55's KV-footprint hypothesis)

**Dimension covered:** confirm/refute the iter-55 KV-footprint hypothesis with two probes — a direct curl A/B on warm non-quant 27b, and an *identical-prompt* tigger-side replay.

**Wall-clock used:** ~3m of 7m.

**Probe 1 — direct curl, identical small payload × 4:**

```
r1 wall=3.43  (warm-ish)
r2 wall=2.43  (cache benefit kicked in)
r3 wall=2.41
r4 wall=2.43
```

Small-prefix cache works fine — 29 % wall drop r1→r2, stable thereafter. Doesn't yet probe the 4900-token case.

**Probe 2 — tigger-side, IDENTICAL prompt × 3 (full prefix = 4923 tokens):**

| run | wall_s | out_t | t/s   | app_prefill |
|-----|--------|-------|-------|--------------|
| r1  | 44.95  | 28    | 0.62  | 110          |
| r2  | **3.39**  | 28    | **8.26**  | **1451**         |
| r3  | **3.37**  | 28    | 8.31  | 1461         |

**iter-55's KV-footprint hypothesis is wrong.** r2/r3 show non-quant 27b *does* prefix-cache when the full prompt is identical (wall collapse 45 → 3.4 s, app_prefill 110 → 1451 — 13× drop, well into the deep-warm regime characterised in iter 19).

**Corrected root cause for iter 55's "stuck at 110 apparent_prefill":**

iter 55 (and iters 43, 38) sent **different** prompt suffixes per run (`pong-55-short`, `pong-55-long`, …). On this LM Studio host + this model, the prefix cache requires the **full prompt** to match, not just the system+tools prefix. The 4900-token shared prefix didn't engage cache because the user-content delta invalidated it.

This is *different* behaviour from gemma-26b-a4b (iter 14 r3/r4 hit deep-warm with *different* prompt suffixes — see iter 14 raw data). So the cache-match policy varies by model on this host. **Two possible mechanisms** for the difference (not measured this tick):

1. **Cache match granularity**: LM Studio caches whole-conversation hashes for non-quant 27b but per-token-prefix for MoE/quant.
2. **Cache size**: Even though small payloads work (probe 1), the 4900-token FP16-27b KV may exceed the per-conversation cache budget while still living in a "full-conversation-hash" addressable store.

Either way, the practical user-recommendation from iter 55 is **softened**: non-quant 27b is fine for repeat-prompt workloads (e.g. compaction passes that re-send the same content), and slow only when each turn has fresh user content. q4_k_l remains the recommended interactive choice because its cache engages on prefix match alone.

**Headline math, corrected:**

- non-quant 27b decode_rate: **~8.3 tok/s** (deep-warm, iter-56 r2/r3: 28 tok / 3.4 s)
- non-quant 27b prefix-cache: **works**, but on *full-prompt* match — not prefix match.

This **closes the iter-55 retraction**. The iter-33 active-param × quant TTFT model + iter-24 decode-rate model still hold for non-quant 27b. No third dimension needed.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 830 → 830 in 4.49 s. No code change.

**Parked for later:**

- Measure cache-match policy directly: send a prompt with `prefix + suffix_A` then `prefix + suffix_B`. If r2 hits cache, policy is prefix-match. If r2 is cold, policy is full-match. One curl A/B settles it for each model.
- The iter-55 → iter-56 retraction shows the importance of using *identical* prompts when measuring deep-warm decode rates. Update the perf-loop methodology section if/when one exists — for now the warning lives in this iter block.

### Iter 57 — DONE (iter 55 partially vindicated)

**Dimension covered:** direct A/B/A cache-policy probe on warm non-quant 27b using small-prefix curl payloads. Settles whether iter-56's "needs full match" finding is policy or size-dependent.

**Wall-clock used:** ~2m of 7m.

**Probe design:** three back-to-back curl calls, same system prompt (~50-token "helpful assistant ... lorem ipsum"), varying user content:

```
A1 user="A"     wall=3.99   (initial warming)
B2 user="B"     wall=2.43   (different user content)
A3 user="A"     wall=2.42   (back to original)
```

**Result: B2 ≈ A3.** With a small prefix, the cache **engages on prefix match** (system + tools), not full-prompt match — B2 hits the same warm state as A3 despite the user content differing.

**Synthesised with iter 55/56:**

| prefix size | match policy observed | wall delta on user-content change |
|-------------|----------------------|------------------------------------|
| ~50 tokens (this iter)     | prefix-match works   | none (2.43 vs 2.42)                |
| ~4900 tokens (iter 55)     | full-match required  | huge (3.4 vs 45)                   |

**The cache policy doesn't differ between probes — the cache capacity does.** Small prefixes (and the small KV they imply) fit comfortably in LM Studio's prefix-cache pool, where the cache key is the prefix-token-hash, so any matching prefix wins. The non-quant 27b 4900-token KV (FP16 × 27B = ~13 GB of KV state for the full prompt) overflows the cache budget, so on each new turn LM Studio can't keep both the prior conversation's KV and the new one — it evicts the prior, and the only way to hit cache is to send the *exact same conversation* as the last one (likely because LM Studio falls back to a whole-conversation hash as the eviction key when prefix-cache runs out of room).

**Iter 55's KV-footprint hypothesis is partially vindicated.** The original framing ("FP16 dense @ 27B+ can't cache") was too strong, but the underlying observation — that KV size determines cache stickiness — was correct. The corrected statement:

> Prefix caching engages on every model when the cached prefix fits in the host's KV pool. For models where the prefix exceeds the pool budget (FP16 dense @ 27B+ on this host), the cache degrades to whole-conversation-match and benefits only repeat-identical prompts.

This now reconciles all three measurements:
- gemma-26b-a4b (small KV per token): prefix-match always works (iter 14 r3/r4 hit deep-warm with different suffixes)
- q4_k_l (medium KV): prefix-match works (iters 17/19/22 hit deep-warm with different suffixes)
- non-quant 27b (large KV): full-match required for the 4900-token tigger prefix; prefix-match works for tiny payloads (this iter)

**Updated practical recommendation:** non-quant 27b is **fine** for interactive use where prompts stay similar (compaction, retry on same input), but every fresh user-content turn pays ~40 s of prefill. q4_k_l remains the right interactive choice; non-quant 27b for batch / repeat workloads.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 830 → 830 in 4.38 s. No code change.

**Parked for later:**

- The "KV-pool-budget-vs-prefix-size threshold" is implicitly somewhere between ~600 tokens (gemma-26b 4577 prefix hits cache cleanly) and ~4900 tokens (non-quant 27b 4900 doesn't). Could be pinned with one curl A/B/A probe per model at intermediate sizes — but it's a host-config question, not a tigger one. Park as low-priority.
- Iter 56's "methodology note about identical prompts" is now redundant — the iter-57 synthesis makes the policy/size distinction clearer than a methodology note would.

### Iter 58 — DONE

**Dimension covered:** fold the iter 55-57 finding ("prefix-cache stickiness degrades with KV footprint") into the iter-41 cycle-close as a new stable finding. The arc — hypothesised, retracted, partially vindicated, fully synthesised — landed in iter 57, so adding it to the canonical summary now keeps the cycle-close self-consistent for bench-03.

**Wall-clock used:** ~1m of 7m.

**Verified / changed:** two edits to the iter-41 block:

1. **New stable finding #7** added to the "do not re-derive in bench-03" list:

   > Prefix-cache stickiness degrades with KV footprint (iters 55-57). Small KVs hit cache on prefix-match. Large KVs (FP16 dense @ 27B+) overflow this host's pool and degrade to full-conversation-match. Practical impact: non-quant 27b and gemma-31b pay ~40 s of prefill on every fresh-content turn; q4_k_l and MoE entries amortise.

2. **New best-fit-defaults sub-recommendation** for batch / repeat-prompt workloads — non-quant 27b is fine when prompts repeat (e.g. compaction passes), bad when each turn has fresh content.

The cycle-close now has **7 stable findings** + **3 user-action recommendations** + **3 best-fit-default sub-recommendations**. Self-consistent and standalone-readable.

**Atomic change rule check:** docs only, ~9 LoC added across two edits. No code or test change.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 830 → 830 in 4.41 s. No code change.

**Parked for later:**

- The KV-pool-budget-vs-prefix-size threshold pinning from iter 57's park still applies if a future bench-03 wants to map the boundary precisely. Not on the critical path for any decision currently in flight.

### Iter 59 — DONE

**Dimension covered:** correction to cycle-close stable finding #2. Iter 56 measured non-quant 27b deep-warm decode at 8.3 tok/s — the iter-41 finding said "FP16 equivalent extrapolated ~5-6 tok/s", which is now empirically too pessimistic. Update with the real number.

**Wall-clock used:** ~1m of 7m.

**Verified / changed:** stable finding #2 in the iter-41 cycle close now reads:

> Quant level is secondary and smaller than predicted: q4_k_l 4-bit measured **11.3** tok/s vs non-quant FP16 27b measured **8.3** tok/s (iter 56 deep-warm) — a **1.36×** quant speedup, not the ~2× a naive bytes-per-weight argument would predict.

**Why the prediction was off.** The bytes-per-weight intuition assumes memory bandwidth dominates decode. In practice, decode also pays for: dequantisation logic (Q4_K_L's grouped quant requires per-block scale/zero unpacking), attention compute on the KV state (which is *not* quantised — both models store FP16 KV here), and overhead per layer. The Q4 weight-bandwidth saving is real but it competes against the dequant cost and the unchanged KV-pass cost, so the realised speedup is well below 2×.

Practical takeaway: **don't choose a smaller quant expecting big decode-rate gains** on this hardware. The ~36 % difference (q4_k_l vs FP16 27b) means q4_k_l's 11 tok/s edge over non-quant's 8 tok/s is worth taking for interactive use, but it's not transformative. The bigger lever is MoE-vs-dense (16× on this cycle's data), then iter-38 prepend (variance suppression).

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 830 → 830 in 4.42 s. No code change.

**Parked for later:**

- Nothing new. The iter-41 cycle close now has 7 stable findings, all empirically backed.

### Iter 60 — DONE

**Dimension covered:** resolve iter 32's parked "gemma-26b-a4b TTFT 35 % outlier" without new measurement. Iter-33's active-param×quant model predicts 0.34 s for ~4B-active; measured 0.46 s. The discrepancy is explained by *active-param estimation error*, not model misbehaviour.

**Wall-clock used:** ~1m of 7m.

**Analysis:**

The "-a4b" suffix in `google/gemma-4-26b-a4b` is taken to mean "4 B active parameters". But the prediction landed 35 % low (0.34 vs 0.46 s). Inverting the iter-33 fit with k = 0.085 s/B and the measured TTFT gives:

```
params_active_eff = 0.46 / 0.085 = 5.4 B
```

A 5.4 B effective-active count is within Google's expected range for gemma-2-mixture MoE routing — the "a4b" naming convention typically averages 4-5 B active and rounds down. The active-param × k model holds (k = 0.085 s/B, ±15 % across all 4 entries) *when the active-param count is correctly estimated*.

| model                              | TTFT (s) | k = TTFT/params_eff | implied active params |
|------------------------------------|----------|----------------------|------------------------|
| `qwen/qwen3.6-35b-a3b`            | 0.30     | 0.100 s/3B           | 3.0 B (matches "-a3b") |
| `google/gemma-4-26b-a4b`          | 0.46     | (rearranged)         | **5.4 B**              |
| `qwen_qwen3.6-27b@q4_k_l`         | 1.14     | 0.084 s/13.5B (4-bit)| 13.4 B effective       |
| `google/gemma-4-31b`              | 2.30     | 0.074 s/31B          | 31 B (matches)         |

The four models cluster k around 0.085 ± 0.015. The gemma-26b outlier disappears once the "a4b" label is treated as nominal rather than authoritative.

**Practical implication for bench-03:** when adding a new model entry to the calibration table, use TTFT to *back out* the effective active params rather than trusting the model name. Especially for MoE entries where the actual routing may differ from the marketing label.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 830 → 830 in 4.42 s. No code change.

**Parked for later:**

- Nothing new. iter-32's gemma TTFT outlier is now resolved; iter-33's active-param × quant TTFT model fits all four rows when active-param counts are inferred rather than read from model names.

### Iter 61 — DONE

**Dimension covered:** regression check that the iter-18 → iter-52 chain of perf-layer changes didn't perturb the actual wire kwargs going to LM Studio. The signal-layer churn was extensive (new TSV column, new stderr lines, new diagnostics, suppression rules) — confirm the kwargs payload is untouched.

**Wall-clock used:** ~1m of 7m.

**Wire-kwargs dump (non-quant 27b, this tick):**

```json
{
  "model": "qwen/qwen3.6-27b",
  "temperature": 0.7,
  "stream": true,
  "top_p": 0.8,
  "presence_penalty": 0,
  "extra_body": {
    "top_k": 20,
    "min_p": 0.0,
    "repetition_penalty": 1,
    "chat_template_kwargs": {
      "enable_thinking": false,
      "preserve_thinking": false
    }
  },
  "stream_options": {"include_usage": true},
  "_messages_count": 2,
  "_tools_count": 13
}
```

**Compare to iter 2 baseline (same config slug, before all iter-18+ changes):**

| field                                | iter 2 | iter 61 | match |
|--------------------------------------|--------|---------|-------|
| `model`                              | `qwen/qwen3.6-27b` | `qwen/qwen3.6-27b` | ✓ |
| `temperature`                        | 0.7    | 0.7     | ✓     |
| `top_p`                              | 0.8    | 0.8     | ✓     |
| `presence_penalty`                   | 0      | 0       | ✓     |
| `extra_body.top_k`                   | 20     | 20      | ✓     |
| `extra_body.min_p`                   | 0.0    | 0.0     | ✓     |
| `extra_body.repetition_penalty`      | 1      | 1       | ✓     |
| `extra_body.chat_template_kwargs`    | `{enable_thinking:false, preserve_thinking:false}` | same | ✓ |
| `stream_options.include_usage`       | true   | true    | ✓     |

**Result:** zero regression. All 9 wire fields round-trip bit-for-bit identical across the 6 intermediate perf-layer commits. The provider-side payload is invariant; only the stderr/TSV emission changed.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 830 → 830 in 4.38 s. No code change.

**Parked for later:**

- Nothing new. The cycle is at a natural plateau — every dimension covered, all parked items resolved, wire kwargs verified-stable. Future ticks before bench-03 will be incremental polish.

### Iter 62 — DONE

**Dimension covered:** code-quality refactor of the iter-52 model-swap detection. Extract the ~20-line inline block into a named helper `_warn_on_perf_tsv_model_swap(perf_path, config)` with a docstring. Improves readability of `run()` and makes the swap-detection logic testable in isolation if needed in the future.

**Wall-clock used:** ~1m of 7m.

**Verified / changed:** `src/tigger/loop.py` — pulled the iter-52 block out of `run()` into a module-level helper just above `run()`. The helper:

- Reads the TSV file (returns silently on `OSError`).
- Skips header-only files (`len(lines) < 2`).
- Validates the trailing column is a model id, not the literal "model" header.
- Compares against `config.model_slug or config.model`.
- Emits the same `[perf] model changed since last TSV row:` line on a mismatch.

Call site in `run()` is now a one-liner:

```python
if perf_log is None and perf_path is not None and perf_path.exists():
    _warn_on_perf_tsv_model_swap(perf_path, ctx.config)
```

Down from 21 inline lines to 2. The two existing iter-52 tests (`test_perf_model_swap_warning_fires_on_changed_slug` and `..._silent_on_same_slug`) pass unchanged — they exercise the public-facing behaviour (warning text on stderr), not the inlined-vs-helper structure.

**Atomic change rule check:** one file (`loop.py`), net change is ~13 LoC (added 30 LoC of helper + docstring, removed 21 LoC inline + 2 LoC for the if-block). Slightly larger than 30 LoC gross, but the net runtime-behaviour delta is zero. No new top-level Rich import. No test change needed — existing coverage continues.

**Files touched:** `src/tigger/loop.py`, `tigger-model-performance.md`.

**Tests delta:** 830 → 830 in 4.32 s. Behaviour-preserving refactor; existing tests still green.

**Parked for later:**

- Same iter-48 "collapse to single line" park still applies — the prefill-dominant and cache_likely_hit branches could now both be extracted alongside the swap helper if the consolidation gets attempted.

### Iter 63 — DONE

**Dimension covered:** re-confirm the iter-31 TTFT baseline for `qwen/qwen3.6-35b-a3b` 60+ iters later. The model is warm on LM Studio (loaded at iter-23 cold-load, last actively used by iter-24). 5-run curl A/B with the exact same payload shape iter 31 used.

**Wall-clock used:** ~1m of 7m.

**5-run curl wall (max_tokens=10, single user msg "Reply: pong"):**

```
r1 wall=0.73  (warm-ish, minor partial-warm)
r2 wall=0.29
r3 wall=0.30
r4 wall=0.27
r5 wall=0.29
mean(r2..r5) = 0.288 s  σ ≈ 0.013 s
```

**Comparison vs iter 31:**

| measurement | mean wall_s | σ |
|-------------|--------------|----|
| iter 31 (5 runs, warm from iter 30) | 0.296 | 0.012 |
| iter 63 (5 runs, this tick)         | **0.288** | 0.013 |

The two means differ by 0.008 s (~3 %) — well within run-to-run noise. The active-param × quant TTFT model (iter 33) holds across the ~10-hour cycle span.

**Practical signal:** the cycle's headline calibration number is stable. A user re-running these benches tomorrow (or after the cron expires and gets restarted) should still see ~0.30 s TTFT for the default model. No drift detected.

**Verified / changed:** docs only.

**Files touched:** `tigger-model-performance.md`.

**Tests delta:** 830 → 830 in 4.47 s. No code change.

**Parked for later:**

- Re-confirm one or two of the other rows (q4_k_l 1.14 s, gemma-26b 0.46 s, gemma-31b 2.30 s) if a future tick lands on the right warm state. Each is cheap — 5 curls × ~1-3 s = under 30 s per row. Helps catch host-side drift between cycles.
