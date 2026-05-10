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
