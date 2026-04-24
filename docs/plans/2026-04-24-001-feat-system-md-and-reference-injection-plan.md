---
title: "feat: Ship authoritative system.md and auto-inject skill references"
type: feat
status: completed
date: 2026-04-24
deepened: 2026-04-24
origin: docs/brainstorms/2026-04-24-system-md-and-reference-injection-requirements.md
---

# feat: Ship authoritative system.md and auto-inject skill references

## Overview

Replace tigger's 3-line default system prompt with a comprehensive, package-bundled system.md that provides tool-use discipline, behavioural guardrails, workflow examples, and identity anchoring. Simultaneously, activate the existing but unused skill reference loading infrastructure so `references/*.md` files are auto-injected into skill prompts at invocation time.

## Problem Frame

Local models like Qwen 27B are sensitive to prompt quality. Without explicit guidance they drift in tone, misuse tools (bash instead of grep, write instead of edit), pause mid-task, and hallucinate tool call formats. Tigger currently ships a 3-line fallback prompt that provides no guardrails. Competitors (Qwen-code, Gemini CLI) ship comprehensive system prompts that dramatically improve output quality.

The skill system already loads `references/*.md` files into `SkillDef.references` (skills.py lines 109-116) but never injects them — the infrastructure is built, the last 5 lines are missing.

(see origin: docs/brainstorms/2026-04-24-system-md-and-reference-injection-requirements.md)

## Requirements Trace

- R1. Ship comprehensive default system.md at `src/tigger/assets/system.md`
- R2. Load package default; `.tigger/system.md` fully overrides
- R3. Memory append unchanged
- R4-R5. Named functional identity ("You are Tigger")
- R6-R9. Tool discipline: per-tool guidance, sequencing rules, anti-patterns, workflow examples
- R10-R14. Behavioural rules: task continuity, tone, safety, code quality, orientation
- R15. Move plan-mode text from loop.py to asset file
- R16-R20. Auto-inject skill references with opt-out via `inject_references: false`

## Scope Boundaries

- No conditional prompt assembly (model-aware fragments, git detection)
- No internal skills directory
- No changes to compaction, memory, or plan mode logic beyond extracting the text
- No new commands or CLI flags
- No changes to skill format beyond `inject_references` frontmatter field

## Context & Research

### Relevant Code and Patterns

- **System prompt loading**: `main.py` lines 86-99 — checks `.tigger/system.md`, falls back to 3-line default, appends memory
- **Skill loading**: `skills.py` `load_skills_dir()` lines 82-133 — iterates skill dirs, parses YAML frontmatter, loads references into `SkillDef.references` list but never uses them
- **Skill rendering**: `skills.py` `render()` lines 19-28 — strips trigger prefix, substitutes `$ARGUMENTS` or appends after `---`
- **Plan mode injection**: `loop.py` lines 40-50 — appends plan mode text to system prompt at runtime when `ctx.config.mode == "plan"`
- **Package build**: `pyproject.toml` uses hatchling with `packages = ["src/tigger"]` — any files under `src/tigger/` are included automatically
- **Existing skills with references**: Only `how/` has a `references/` directory (4 files: critic-prompt.md, explorer-prompt.md, explainer-prompt.md, critique-rubric.md) — these are subagent prompts and should NOT be auto-injected

### Institutional Learnings

- The `how/` skill's references are instructions for forked sub-agents, not context for the main prompt — this is the primary use case for `inject_references: false`

## Key Technical Decisions

- **`Path(__file__).parent / "assets/"`**: Asset loading uses file-relative paths. Hatchling's `packages = ["src/tigger"]` includes the entire directory tree, so `src/tigger/assets/` is automatically packaged. No `importlib.resources` complexity needed.
- **Separate plan-mode fragment**: Plan-mode text lives in `src/tigger/assets/plan_mode.md`, not inside system.md. This keeps system.md clean and avoids needing marker-based extraction. `loop.py` loads it the same way main.py loads system.md.
- **Markdown headers for references**: Injected references use `## Reference: <filename>` headers — natural for models trained on markdown, preserves semantic meaning, no XML confusion for smaller models.
- **`inject_references` defaults to True when absent**: Parsed from YAML frontmatter in `load_skills_dir()`. When the field is missing, default is True. When a skill has no `references/` directory, injection is a silent no-op.

## Open Questions

### Resolved During Planning

- **Asset loading mechanism**: `Path(__file__).parent / "assets" / "system.md"` — works with hatchling packaging, no extra config needed.
- **Plan-mode location**: Separate fragment file, not embedded in system.md — cleaner separation, same loading pattern.
- **Reference format**: `## Reference: <filename>` markdown headers — best compatibility with local models.

### Deferred to Implementation

- **Exact system.md prose**: The content of the system prompt (tool descriptions, workflow examples, safety rules) will be written during implementation. The requirements (R4-R14) define what sections are needed; the exact wording is implementation work.
- **Reference injection ordering**: References are currently loaded in sorted filename order. Whether this ordering matters for prompt quality is an implementation-time concern.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
System Prompt Assembly (main.py startup):

  ┌─────────────────────────────────┐
  │ .tigger/system.md exists?       │
  │   yes → read it (full override) │
  │   no  → read assets/system.md   │
  └───────────────┬─────────────────┘
                  │
                  ▼
  ┌─────────────────────────────────┐
  │ memory.md exists?               │
  │   yes → append formatted memory │
  │   no  → skip                    │
  └───────────────┬─────────────────┘
                  │
                  ▼
           system_prompt ready


Plan Mode Injection (loop.py run):

  ┌─────────────────────────────────┐
  │ config.mode == "plan"?          │
  │   yes → read assets/plan_mode.md│
  │          append to system_prompt│
  │   no  → skip                    │
  └─────────────────────────────────┘


Skill Reference Injection (skills.py render):

  ┌─────────────────────────────────┐
  │ skill.inject_references == True │
  │ AND skill.references not empty? │
  │   yes → prepend each reference  │
  │          with ## Reference: name│
  │   no  → skip                    │
  └───────────────┬─────────────────┘
                  │
                  ▼
  ┌─────────────────────────────────┐
  │ render body with $ARGUMENTS     │
  │ or append after ---             │
  └─────────────────────────────────┘
```

## Implementation Units

- [x] **Unit 1: Create assets directory and system.md**

**Goal:** Write the comprehensive default system prompt that ships with the package.

**Requirements:** R1, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14

**Dependencies:** None

**Files:**
- Create: `src/tigger/assets/system.md`

**Approach:**
- Write the system prompt as a markdown file with clear sections
- Open with named functional identity (R4-R5)
- Tool discipline section documenting each tool with sequencing rules and anti-patterns (R6-R8)
- 3-5 workflow examples showing correct tool sequences (R9) — model on Qwen-code's examples but adapted for tigger's tool names
- Behavioural rules section covering task continuity, tone, safety, code quality (R10-R13)
- Codebase orientation instruction (R14) — prompt-instructed, not code-level
- Target comprehensive coverage; with 128K context there is no token budget pressure

**Patterns to follow:**
- Qwen-code's system prompt structure: identity → tool guidance → workflow examples → behavioural rules → safety constraints
- Qwen-code's "Core Mandates" pattern for non-negotiable rules
- Gemini's strict-development-rules.md for code quality directives

**Test expectation:** None — this is a static content file. Verified through integration in Unit 2.

**Verification:**
- File exists at `src/tigger/assets/system.md`
- Contains sections for: identity, tool discipline (all 8 tools), workflow examples, behavioural rules, safety, codebase orientation
- No hardcoded model names or provider-specific content

---

- [x] **Unit 2: Extract plan-mode text to asset fragment**

**Goal:** Move the plan-mode instructions from Python code to a loadable markdown file.

**Requirements:** R15

**Dependencies:** None (can be done in parallel with Unit 1)

**Files:**
- Create: `src/tigger/assets/plan_mode.md`
- Modify: `src/tigger/loop.py`

**Approach:**
- Create `plan_mode.md` containing the current plan-mode text from loop.py lines 40-50
- In loop.py, replace the inline string with a file read: load from `Path(__file__).parent / "assets" / "plan_mode.md"`
- Use a lazy-load function with `functools.lru_cache` to avoid repeated file reads while remaining testable (`.cache_clear()` in tests)
- Preserve the existing conditional: only append when `ctx.config.mode == "plan"`
- If `plan_mode.md` is missing, raise a clear error (same pattern as system.md missing-asset handling)
- Note: both Unit 1 and Unit 2 create files in `src/tigger/assets/` — ensure the directory exists (mkdir if needed)

**Patterns to follow:**
- Same `Path(__file__).parent / "assets"` pattern used by Unit 3

**Test scenarios:**
- Happy path: plan mode enabled, plan_mode.md content is appended to system prompt
- Happy path: plan mode disabled (mode="ask"), no plan text appended
- Edge case: verify the appended text matches the original hardcoded string exactly (no regression)

**Verification:**
- `loop.py` no longer contains inline plan-mode prompt text
- Plan mode behaviour is unchanged when tested manually

---

- [x] **Unit 3: Load system.md from package assets in main.py**

**Goal:** Replace the 3-line fallback with the package-bundled system.md while preserving `.tigger/system.md` override.

**Requirements:** R1, R2, R3

**Dependencies:** Unit 1 (system.md must exist)

**Files:**
- Modify: `src/tigger/main.py`
- Test: `tests/test_main.py` (or appropriate existing test file)

**Approach:**
- In `startup()`, replace the hardcoded fallback (lines 90-96) with a read from `Path(__file__).parent / "assets" / "system.md"`
- Preserve the existing override logic: if `.tigger/system.md` exists, use it instead
- Preserve memory append logic unchanged (line 99)
- The loading order remains: user override > package default > (error if missing)

**Patterns to follow:**
- Existing pattern at main.py lines 86-88 for reading `.tigger/system.md`

**Test scenarios:**
- Happy path: no `.tigger/system.md` exists — package default is loaded, contains identity section
- Happy path: `.tigger/system.md` exists — user file fully replaces package default
- Happy path: memory.md exists — appended after system prompt regardless of which source was used
- Edge case: `.tigger/system.md` is empty — treated as valid override (empty string), memory still appended
- Error path: package `assets/system.md` missing (packaging error) — raises clear error with actionable message, not raw FileNotFoundError
- Integration: full startup produces a RunContext with system_prompt containing the expected content

**Verification:**
- `tigger init` in a new project gets comprehensive system prompt without user authoring
- Existing projects with custom `.tigger/system.md` are unaffected

---

- [x] **Unit 4: Add inject_references to SkillDef and render()**

**Goal:** Auto-inject loaded references into skill prompts at invocation time, with opt-out.

**Requirements:** R16, R17, R18, R19, R20

**Dependencies:** None (independent of Units 1-3)

**Files:**
- Modify: `src/tigger/skills.py`
- Modify: `tests/test_skills_dir.py` — update existing reference assertions for new data structure, update/invert `test_render_does_not_auto_inject_references`
- Test: `tests/test_skills_dir.py`

**Approach:**
- Add `inject_references: bool = True` field to `SkillDef` dataclass
- In `load_skills_dir()`, parse `inject_references` from frontmatter: `fm.get("inject_references", True)`
- Store reference filenames alongside content — change `references` from `list[str]` to `list[tuple[str, str]]` where each tuple is `(filename, content)`. Update existing test assertions in `tests/test_skills_dir.py` that check `.references` as `list[str]` (lines 79-81, 91-92, 154)
- In `render()`, references are prepended before the existing render logic. The existing `$ARGUMENTS` substitution or `---` appending is unchanged — references are simply prepended to whatever `render()` currently produces
- Update the existing `test_render_does_not_auto_inject_references` test to verify the new default-on behaviour (references ARE injected by default), and add a separate test for `inject_references: false`

**Patterns to follow:**
- Existing `render()` method structure — the injection is prepended before the body, similar to how `$ARGUMENTS` substitution works
- Existing `load_skills_dir()` parsing pattern for frontmatter fields like `tools`, `context`

**Test scenarios:**
- Happy path: skill with references/ dir and default frontmatter — references are injected with `## Reference: <name>` headers
- Happy path: skill with `inject_references: false` — references loaded but not injected
- Happy path: skill with no references/ dir — render unchanged, no error
- Happy path: skill with `inject_references` absent from frontmatter — defaults to True
- Edge case: skill with empty references/ dir (no .md files) — render unchanged
- Edge case: reference injection combined with `$ARGUMENTS` placeholder — references prepended, arguments substituted in body
- Edge case: reference injection combined with no placeholder — references prepended, arguments appended after `---`
- Integration: the `how/` skill with `inject_references: false` renders identically to current behaviour
- Edge case: legacy-loaded skill (via flat `skills.md`, not directory) — has no references, `inject_references` defaults to True, render unchanged

**Verification:**
- Skills with references get richer prompts
- Skills without references are unchanged
- `inject_references: false` prevents injection

---

- [x] **Unit 5: Update how/ skill frontmatter**

**Goal:** Opt the `how/` skill out of reference injection since its references are subagent prompts.

**Requirements:** R18

**Dependencies:** Unit 4 (inject_references field must be implemented)

**Files:**
- Modify: `.tigger/skills/how/SKILL.md`

**Approach:**
- Add `inject_references: false` to the YAML frontmatter
- No other changes to the skill

**Patterns to follow:**
- Existing frontmatter fields in the how/ skill

**Test expectation:** None — verified by Unit 4's integration test scenario.

**Verification:**
- `how/` skill's YAML frontmatter contains `inject_references: false`
- Running `/how` produces the same output as before (references used by subagents, not injected into main prompt)

## System-Wide Impact

- **Interaction graph:** System prompt flows from `main.py startup()` → `RunContext.system_prompt` → `loop.py run()` (plan mode append) → provider API call. Reference injection flows from `skills.py render()` → returned prompt string → main loop message construction. These are independent paths that do not interact.
- **Error propagation:** If `assets/system.md` is missing (packaging error), `startup()` should raise a clear error rather than silently falling back. If a reference file fails to read, the existing warning pattern (skills.py line 115) handles it gracefully.
- **State lifecycle risks:** None — all changes are stateless. System prompt is built fresh each session. References are loaded once at startup and injected at invocation time.
- **API surface parity:** No external API changes. The `inject_references` frontmatter field is a new optional field in an existing format.
- **Integration coverage:** The key cross-layer scenario is: startup loads package system.md → plan mode appends fragment → skill invocation injects references → provider receives the complete assembled prompt. This end-to-end flow should be manually verified.
- **Unchanged invariants:** Memory append behaviour, skill trigger matching, forked skill execution, hook system — all unchanged.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| System.md prose quality — poor tool descriptions could make model behaviour worse than the current minimal prompt | Write iteratively, test with Qwen 27B on representative tasks, compare against old 3-line prompt |
| References data structure change (storing filenames alongside content) will break existing test assertions | `tests/test_skills_dir.py` has 6 assertions against `.references` as `list[str]`. These tests must be updated as part of Unit 4 to expect `list[tuple[str, str]]`. No production code outside `load_skills_dir()` reads `.references` |
| Package asset not included in distribution | Hatchling's `packages = ["src/tigger"]` includes the full directory tree. Verify with `pip install -e .` and check the asset is accessible |

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-24-system-md-and-reference-injection-requirements.md](docs/brainstorms/2026-04-24-system-md-and-reference-injection-requirements.md)
- Related code: `src/tigger/main.py` (startup, system prompt loading)
- Related code: `src/tigger/skills.py` (SkillDef, render, load_skills_dir)
- Related code: `src/tigger/loop.py` (plan mode injection)
- Related ideation: `docs/ideation/2026-04-24-system-prompt-and-internal-skills-ideation.md`
