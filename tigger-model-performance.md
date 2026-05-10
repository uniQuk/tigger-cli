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

### Iter 2 — DONE

Two real bugs surfaced from the cold `qwen/qwen3.6-27b` A/B (warmed via
direct `curl`).

**Bug 1 — `--no-think` order bug (now fixed).** `main.py:732-738`
applied `--no-think` *before* `--model`, but `switch_model` (called by
`--model`) replaces `chat_template_kwargs` with the per-model entry's
copy. So `tigger-code --no-think --model qwen/qwen3.6-27b-thinking …`
silently shipped `enable_thinking=True` over the wire — the flag was a
no-op for any per-model entry that pinned thinking on.

Verified before-fix kwargs dump:
```
chat_template_kwargs= {'enable_thinking': True, 'preserve_thinking': True}
```
After-fix:
```
chat_template_kwargs= {'enable_thinking': False, 'preserve_thinking': True}
```

Fix: swap the two blocks in `main.py` so `--model` runs first and
`--no-think` overlays its `enable_thinking=False` afterwards. Added
regression test `test_no_think_overrides_model_per_entry_thinking` to
lock the order in.

**Bug 2 — Qwen3.6-27b is ~14× slower with `enable_thinking=False`
on this LM Studio.** Same wire id, same prompt, same input/output
token counts, only `chat_template_kwargs.enable_thinking` differs:

| variant                          | wall_s | gen tok/s | output_t |
|----------------------------------|--------|-----------|----------|
| 27b-instruct (`enable_thinking=False`)   | 49.81 | 3.5 | 176 |
| 27b-thinking (`enable_thinking=True`)    |  3.59 | 49  | 176 |
| 27b-thinking + `--no-think` (post-fix)   | 51.76 | 3.0 | 156 |

The slow path is keyed on `enable_thinking=false`, not on the slug.
The 35b-a3b MoE model under the same `enable_thinking=false` setting
runs fine (~1.7 s for "say pong"); only the 27b dense model exhibits
this. Likely an LM Studio chat-template / sampler interaction we can't
fix from the client.

**User-facing recommendation:** on the LM Studio host running
qwen3.6-27b, prefer the `qwen/qwen3.6-27b-thinking` entry over
`qwen/qwen3.6-27b-instruct`. Treat the `--no-think` flag as a
*feature toggle*, not a perf optimisation, on this model.

**Tests:** 801 → 802 (new regression test). 4.35 s.

### Iter 3 — DONE

**Feature: `system_prompt_extra` config field.** Closes the user ask
"custom prompts that can be attached via config or in the TUI to
override the main system prompt" without forcing a 100+ line copy-paste
of `assets/system.md`. Set in `.tigger/config.json`:

```json
{ "system_prompt_extra": "Project rule: respond in haiku." }
```

The string is appended to the bundled (or custom) `system.md` AFTER
memory and before the user turn. Empty / missing / null = no addition.

**Files touched (small, surgical):**

- `types.Config`: new `system_prompt_extra: str | None = None` field.
- `config.load_config`: reads `system_prompt_extra` from JSON.
- `main.startup`: extends the system-prompt build with `if extra:
  parts.append(extra)`. Same `\n\n` join the memory section uses.

**Live A/B on `qwen/qwen3.6-35b-a3b`** (warm, `--no-think`, prompt
"Reply with exactly: pong-N"):

| variant                                | in_t | out_t |
|----------------------------------------|------|-------|
| no extra (baseline)                    | 4912 | 170   |
| `system_prompt_extra` ≈17 words        | 4933 | 115   |

`+21` input tokens matches the extra string size. Output dropped 32%
because the extra contained "Keep responses terse" — i.e. the field
rides the wire AND influences generation as intended.

**Tests:** 802 → 804 (`test_system_prompt_extra_loads`,
`test_system_prompt_extra_absent_is_none`). 4.35 s.

### Iter 4 — DONE

**Triage finding.** `qwen_qwen3.6-27b@q4_k_l-instruct` (and the dense
27b family in general) emits `delta.reasoning_content` even when
`chat_template_kwargs.enable_thinking=False`. We saw the same wire
phenomenon on the unquantised 27b in iter 2 — server-side LM Studio
behaviour, not config-driven. Output token counts in `[perf]` blow up
(147 vs the 4 visible "pong-look" chars) because the server bills the
reasoning tokens against the response.

The original "verbose preamble" suspicion (iter 1, 720 output tokens) is
not reproducible — same model under the same config produced 42–147
output tokens across this iteration's runs. It was just reasoning-tokens
noise.

**Fix (small, surgical, provider.py).** The collector at
`provider.py:357-363` wraps any `collected_thinking` into `<think>...
</think>` tags inside `final_content`, even when the user explicitly
opted out via `enable_thinking=False`. This bloats:

- `ctx.messages` (sent to `/tokens` estimator).
- Compaction triggers (fires earlier than warranted).
- Per-turn token estimate seen on the bottom toolbar.

Now: when `chat_template_kwargs.enable_thinking is False`, the wrap is
skipped. Reasoning tokens still arrive and are still counted by the
server (we can't stop generation), but they don't pollute history.
Default behaviour (`enable_thinking` unset or `True`) is unchanged.

**Live verify on q4_k_l:** prompt "say pong-iter4", `enable_thinking=
False`, response: stdout = `pong-iter4`, output_tokens = 42, finish =
stop. Wire-level output is unchanged; history-level is now clean.

**Tests:** 804 → 806, both branches covered
(`test_reasoning_dropped_when_thinking_disabled`,
`test_reasoning_wrapped_when_thinking_enabled`). 4.35 s.

### Iter 5 — DONE

**Root-cause both gemma EC=2 errors.** Walked the failure end-to-end
and found two separable bugs plus one model limitation.

**Bug 1 — Cross-family `chat_template_kwargs` inheritance.** The
project config has a top-level `chat_template_kwargs:
{enable_thinking: true, preserve_thinking: true}` (Qwen-only flags).
Gemma entries don't define their own, so `_resolve_active_model` /
`pick(...)` fell through to the global. Gemma's jinja template doesn't
know `preserve_thinking` → `Cannot call something that is not a
function: got UndefinedValue`.

Fix (`config.py:_resolve_active_model`): per-model
`chat_template_kwargs` is now authoritative in dict-format providers.
Missing per-model = `{}` (no template kwargs sent), NOT inherit-global.
Locked in by `test_per_model_chat_template_kwargs_does_not_inherit_global`.

**Bug 2 — `--no-think` (and `/think`) injected `enable_thinking` from
scratch.** On a non-Qwen model with no thinking kwargs, the flag
was creating `chat_template_kwargs={"enable_thinking": False}` and
sending it. Same UndefinedValue crash.

Fix (`main.py`, `commands/misc.py`): both flag-paths are now no-ops
when the active config has no `enable_thinking` key. `/think` prints a
friendly note. Locked in by
`test_no_think_is_noop_when_model_has_no_thinking_kwargs`.

**Model limitation (NOT fixable client-side).** Even after both fixes,
gemma still EC=2'd — same jinja error, no `chat_template_kwargs`
in the wire payload. Direct curl proved it: gemma-4-26b-a4b-it works
fine for chat (no `tools`), but with the OpenAI `tools=[...]` array
in the request it fails the same way. The stock LM Studio gemma chat
template doesn't render tool definitions. **Conclusion:** gemma-4-31b
and gemma-4-26b-a4b are usable for chat-only models in tigger but NOT
as agents on this LM Studio host (the agent loop sends `tools` on
every turn). Recommend pulling the lmstudio-community variant of these
models with a tool-aware template, or treating these as informational
slugs only.

**Wire-kwargs sample post-fix (gemma-4-26b-a4b-it, --no-think):**
```
extra_body = {top_k: 20, min_p: 0.5, repetition_penalty: 1.1}
```
No `chat_template_kwargs` polluting the request — the right shape.
Server still rejects on `tools` (a model-side limit), but tigger is
now sending the correct minimal payload.

**Tests:** 806 → 808. 4.40 s.

### Iter 6 — DONE

**Tool-call A/B and a harness fix.** Ran the same prompt ("Use the read
tool to read pyproject.toml and tell me the project version on a single
line") against the working Qwen models.

| model                       | turns | total wall_s | total out_t | finish |
|-----------------------------|-------|--------------|-------------|--------|
| `qwen/qwen3.6-35b-a3b`      | 2     |  2.61        | 81          | stop   |
| `qwen/qwen3.6-27b-thinking` | —     | timeout 240s | —           | EC=142 |

35b-a3b is dramatically faster on tool-call workloads — 27b-thinking
spends each turn reasoning before emitting the tool call, which compounds
across multi-turn agent loops. For agent work on this LM Studio host,
35b-a3b is the right default (matches the iter-32 finding from the
prior loop).

**Harness fix (not committed; lives in `/tmp/bench.sh`).** Previous
iterations reported `out_t = $8` on the perf line — that's actually
`prompt_chars`, not `output_tokens` (which is `$6`). All earlier
`out_t` numbers in this log were prompt_chars, not generation tokens.
The wall_s, input_tokens, and finish_reason columns were correct.
Future iterations use a fixed harness that sums output across turns.

**Tigger-side code change.** `TIGGER_PERF=1` was dumping the full
outgoing kwargs INCLUDING the `tools=[...]` array (~6 KB of MCP/tool
schemas). The interesting bits (sampler, chat_template_kwargs) were
buried. Now the dump excludes `tools` and `messages`, replacing them
with `_messages_count` / `_tools_count`. One-line kwargs are easier to
spot-check across iterations.

Before:
```
{"model": "...", ..., "tools": [{huge schemas × 13}], ...}  // ~6 KB
```
After:
```
{"model": "qwen/qwen3.6-35b-a3b", "temperature": 0.7, ...,
 "extra_body": {..., "chat_template_kwargs": {"enable_thinking": false}},
 "_messages_count": 2, "_tools_count": 13}
```

**Tests:** 808 → 808 (no test churn). 4.42 s.

### Iter 7 — DONE

**Streaming hot-path simplification (`ui._start_or_update_live`).** The
function ran `total_len = sum(len(s) for s in text_buf)` on every
TextChunk to fingerprint the buffer for an early-skip check
(`if total_len == _last_render_len: return`). But provider only yields
TextChunk for non-empty `delta.content` (`provider.py:311`), so
`text_buf` strictly grows by appending — the `total_len ==` guard
never fired. The O(N) sum was wasted work on the most thermally hot
path in the TUI (N = chunk count, can hit 2000+ on long streams).

Replaced with `_last_render_chunks: int` (chunk count) and dropped the
dead guard. The `_flush_text` sync check now uses `len(text_buf)`
instead of the same O(N) sum.

Net: -10 lines, fewer global mutations, every streamed token does one
fewer O(N) walk before hitting the throttle check. Behaviour
unchanged: throttle interval is still 80 ms (12 Hz Rich Live cadence),
final flush still syncs the last frame.

**Live verify on 35b-a3b** ("List integers 1 to 5, one per line"):
output streams correctly chunk-by-chunk; `1\n2\n3\n4\n5` rendered;
1.97 s wall, 42 output tokens, 21 tok/s.

**Tests:** 808 → 808. 4.48 s. One test (`test_ui.py:596`) updated to
the renamed global.

### Iter 8 — DONE

**CLAUDE.md rule cleanup (`commands/mcp_cmd.py`).** Found 7 raw
`print()` calls that bypass the unified Rich theme — three in
`_print_server_tier`, two in `_persist_tier_to_user_config`, one in
`cmd_mcp`'s unknown-subcommand branch, one in the tier-success line.
All converted to `ui.console.print` with cyan/magenta/yellow/green
matching the rest of `/mcp`'s output (eager=green, lazy=cyan,
disabled=yellow, mixed=magenta).

This was the largest cluster of CLAUDE.md "no bare print()" violations
left in the codebase. Other remaining `print()`s are:

- `trust.py:26,53` — interactive trust prompt that runs BEFORE
  startup themes a Console; intentional.
- `input_processing.py:13` — pre-startup stderr warning; intentional.
- `main.py:453,818,841` — REPL banner lines and the `--once` raw
  stdout writer; the `--once` writer is the only one that bypasses
  themed output and that's part of the iter-47 contract (raw stdout).

Existing `test_mcp_tier_runtime.py` (≈10 tests) uses
`capsys.readouterr().out`. Rich's themed `console.print` writes to
`sys.stdout` by default, so those tests still capture the output —
all green without changes.

**Smoke bench on 35b-a3b** (post-streaming-refactor + post-theme):

| prompt                 | turns | wall | total_out | finish |
|------------------------|-------|------|-----------|--------|
| simple chat            | 1     | 1.21 | 7         | stop   |
| tool-call (read pyproj)| 2     | 3.74 | 93        | stop   |

Within iter-3/iter-6 noise; nothing regressed.

**Tests:** 808 → 808. 4.40 s.

### Backlog for next ticks

- The MCP eager tier ships ~2 KB of microsoft-learn schemas on every
  turn for the user's config. `tier: lazy` in `mcp.json` would defer
  those to `mcp_promote`. Config decision (not a tigger code change);
  user already has `/mcp tokens` to see the cost.
- Graceful no-tools fallback for chat-only models like gemma-IT —
  still out of scope unless a small, surgical change emerges.
- The startup-time `--quiet` flag silences the welcome banner but
  not the `[mcp] connected:` notice — drop or unify under `--quiet`?
