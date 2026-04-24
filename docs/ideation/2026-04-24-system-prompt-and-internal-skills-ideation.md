---
date: 2026-04-24
topic: system-prompt-and-internal-skills
focus: Design system.md and internal skills architecture for tigger-code by analysing Qwen-code and Gemini CLI approaches
---

# Ideation: System Prompt & Internal Skills Architecture

## Codebase Context

**Project:** tigger-code — Python TUI for local AI models (Qwen 27B primarily), built on prompt_toolkit with OpenAI-compatible streaming.

**Current state:**
- System prompt is 3 lines: "You are a helpful AI agent. Never use emojis... When given a multi-step task, continue working through all steps until fully complete."
- Override via `.tigger/system.md` (flat file, no conditional logic)
- Memory auto-appended from `.tigger/memory.md`
- Plan mode appended as Python string in `loop.py` lines 43-50
- Skills in `.tigger/skills/` with YAML frontmatter, triggers, tool restrictions, inline/fork modes, references/ and assets/ subdirectories
- 128K token context (increased from 8192 testing default)
- Two-layer compaction: snip old tool results + LLM summarise to XML snapshot

**Competitor analysis:**
- **Qwen-code**: 900+ line conditionally-assembled system prompt with model-aware tool-call format templates, Core Mandates section, 6 workflow examples, CLI-optimised tone. Ships 5 commands (commit, PR, review, bugfix, issue), 6 skills (structured-debugging, e2e-testing, docs-audit, terminal-capture, qwen-code-claw), 1 agent (test-engineer). Bugfix chains: issue → agent → reproduce → fix → verify → test.
- **Gemini CLI**: TOML commands injecting full source context, 10 skills with policy.toml per skill, self-referential introspect/prompt-suggest commands, behavioral evals testing agent decisions, strict-development-rules.md referenced by multiple commands as single source of truth.

**Context:** 128K token context window — token budgeting is not a primary constraint. The system prompt can be as rich as needed.

## Ranked Ideas

### 1. Ship an Authoritative system.md with Tool-Use Discipline
**Description:** Replace the 3-line default prompt with a comprehensive system.md bundled inside the package (`src/tigger/assets/system.md`). Covers: tool-use discipline (prefer grep over read-then-scan, never glob `**/*`, read before edit), task continuity (finish what you start), response tone (concise, no filler, no emoji), safety constraints (confirm before destructive bash), codebase-orientation ritual, workflow examples, and explicit behavioural guidance. User's `.tigger/system.md` fully overrides it. With 128K context, the prompt can be as rich as needed.
**Rationale:** Every competitor ships significant prompt scaffolding. Tigger ships nothing. This is the single highest-leverage change — it pays dividends on every interaction. Local models like Qwen 27B are especially responsive to explicit behavioral guardrails because they lack the RLHF-level training of cloud models. Qwen-code's 900-line prompt proves extensive guidance works.
**Downsides:** Risk of over-constraining creative tasks. Maintenance burden as the tool evolves.
**Confidence:** 95%
**Complexity:** Low
**Status:** Explored (brainstormed 2026-04-24)

### 2. Internal Skills Directory — Package-Bundled, Composable Primitives
**Description:** Add a second skill-loading path from inside the installed package (`src/tigger/internal/skills/`). Internal skills load before user skills, use the same SKILL.md format, and are not shown in `/help` by default (`/help --all` reveals them). Users can shadow any internal skill by placing a same-named skill in `.tigger/skills/`. Initial set: `debug` (structured debugging), `commit` (conventional commits), `review` (code review), and a self-referential `tigger-self` (knows tigger's own commands, config format, skill syntax).
**Rationale:** Both Qwen and Gemini ship self-referential skills — Qwen has `qwen-code-claw`, Gemini has `introspect.toml`. Without self-knowledge, the model can't help users extend tigger or explain its own capabilities. The shadow-override mechanism means power users can replace any internal skill without patching the package. `skills.py` `load_skills_dir()` is already a clean, reusable function — adding a second load path is minimal code.
**Downsides:** Must maintain internal skills as the CLI evolves. Naming collisions with user skills need clear resolution rules. Adds a maintenance surface.
**Confidence:** 90%
**Complexity:** Low-Medium
**Status:** Unexplored

### 3. Model-Aware Conditional Prompt Assembly
**Description:** Replace the flat `system.md` load with a lightweight assembler that detects runtime context (git repo, model family, permission mode, active tools) and concatenates only relevant prompt sections. Internal fragments live in `internal/system/` (e.g., `git.md`, `plan_mode.md`, `tool_hints_qwen.md`). Model family detection from the model name string injects format-specific tool-call hints. The plan-mode block currently hardcoded in `loop.py` moves into this system.
**Rationale:** Qwen-code ships 3 different tool-call format templates because local models are inconsistent in how they format tool calls. Conditional assembly ensures only relevant guidance is sent per model/context. The `loop.py` lines 43-50 plan-mode append is already conditional logic; this systematises it.
**Downsides:** More moving parts than a flat file. Debugging "what prompt was actually sent?" becomes harder (mitigated by an introspect command). Over-engineering risk if only 2-3 conditions ever exist.
**Confidence:** 82%
**Complexity:** Medium
**Status:** Unexplored

### 4. Core Mandates That Survive Compaction
**Description:** Define a `mandates` section (in system.md or as `.tigger/mandates.md`) that is injected LAST in the assembled prompt and explicitly marked as overriding all other instructions. Mandates are short absolute rules: "never glob `**/*`", "never write outside project root", "when context exceeds 60%, proactively compact". Critically, mandates are re-injected after compaction — they survive the lossy summarisation that compaction performs.
**Rationale:** Currently all instructions are peer-level — compaction can summarise away behavioural constraints. Qwen's "Core Mandates" section explicitly overrides everything else. Mandate persistence ensures coherent long sessions where constraints aren't forgotten after compaction.
**Downsides:** Mandates that are too aggressive can make the model overly cautious. The "survives compaction" mechanism needs careful implementation.
**Confidence:** 78%
**Complexity:** Medium
**Status:** Unexplored

### 5. Context Budget as a First-Class Behavioural Signal
**Description:** Inject a dynamic context-awareness line into the system prompt at every turn showing current context utilisation. The toolbar already calculates this for the human UI — this surfaces the same signal to the model so it can adjust behaviour proactively (e.g. triggering compaction, being more focused with tool results).
**Rationale:** The model has zero visibility into how much context it's consuming. The bottom toolbar shows context% to the human but not to the model. Making the model context-aware enables it to participate in context management rather than being a passive recipient of compaction.
**Downsides:** Dynamic injection adds complexity to every turn. The model may over-optimise for brevity at the expense of quality. Lower priority now that context is 128K.
**Confidence:** 75%
**Complexity:** Medium
**Status:** Unexplored

### 6. Skill Chaining via `uses:` Frontmatter
**Description:** Add an optional `uses:` list in skill YAML frontmatter naming other skills this skill depends on. When tigger loads the skill, it resolves the dependency graph. For fork-mode dependencies, the sub-skill runs first and its result is passed forward. This is the Qwen pattern where `bugfix` uses `debug` uses `test-engineer` — changes to any sub-skill improve every skill that depends on it.
**Rationale:** Currently every user skill must re-explain every sub-procedure inline. A `bugfix` skill re-explains debugging methodology, test writing, and verification. With chaining, it says `uses: [debug, test-engineer]` and each sub-skill carries its own evolved prompt. `run_forked()` in `loop.py` is already the right execution mechanism — no new infrastructure needed.
**Downsides:** Dependency resolution adds complexity. Circular dependencies need detection.
**Confidence:** 72%
**Complexity:** Medium-High
**Status:** Unexplored

### 7. Auto-Inject Skill References as Few-Shot Examples
**Description:** When a skill has `references/examples.md` (or any `references/example*.md`), automatically inject it into the rendered prompt as an `## Examples` section before the user's arguments. The skill author writes input/output pairs. This formalises the existing unused infrastructure — `skills.py` already loads all `references/*.md` into `SkillDef.references` but never injects them.
**Rationale:** Few-shot examples are the single highest-ROI prompt improvement for local models — they anchor format, tone, and reasoning concretely. The infrastructure is already there (references loaded at skills.py line 108-116), only the 5-line injection step in `render()` is missing. Well-chosen examples often matter more than elaborate instruction prose.
**Downsides:** Risk of example-overfitting where the model copies examples too literally.
**Confidence:** 85%
**Complexity:** Low
**Status:** Explored (brainstormed 2026-04-24)

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | Tighter plan mode with edit gating | Subsumable as one mandate + one internal skill |
| 2 | Per-skill policy.toml files | Already covered by `tools[]` in YAML frontmatter |
| 3 | Behavioural evals framework | Too complex for current project stage |
| 4 | Behavioural self-test on boot | Risky — probe may confuse the model; better as manual /selftest later |
| 5 | Skill health scoring / stats | Premature — need skills to exist before measuring them |
| 6 | Memory learning loop (auto-remember) | Low priority vs prompt and skill architecture |
| 7 | Deferred tool descriptions (short to full) | Engineering complexity unclear relative to benefit |
| 8 | Model-variant skill loading (SKILL.qwen.md) | Over-engineering — conditional assembly handles model differences more cleanly |
| 9 | Template inheritance (extends: base) | Conditional assembly is simpler and more flexible |
| 10 | Session resume fingerprint | Niche use case |
| 11 | Context compression skill | Already have two-layer compaction; guidance doc is more targeted |
| 12 | Per-model system_append in config.json | Subsumed by conditional assembly |
| 13 | Hypothesis-journal tool | Good within debug internal skill, not standalone |
| 14 | Project-type detection at startup | Small — one fragment in conditional assembly |
| 15 | Self-introspect command | Not critical — add as internal skill later |
| 16 | Git auto-injection at startup | Small — one fragment in conditional assembly |
| 17 | Compaction guidance document | Subsumable into mandates system |
| 18 | Progressive/lazy reference injection | Over-engineering for current skill count |

## Session Log
- 2026-04-24: Initial ideation — 40 raw, 7 survivors
- 2026-04-24: Brainstorming ideas #1 (system.md) and #7 (auto-inject references) together — 40 raw candidates from 5 parallel agents, 28 unique after dedupe, 3 cross-cutting syntheses, 7 survivors. Grounded in analysis of Qwen-code prompts.ts, .qwen/ directory, and .gemini/ directory.
