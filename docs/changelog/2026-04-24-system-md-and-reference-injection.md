# System Prompt & Skill Reference Auto-Injection

**Date:** 2026-04-24
**Type:** Feature
**Origin:** [Ideation](../ideation/2026-04-24-system-prompt-and-internal-skills-ideation.md) | [Requirements](../brainstorms/2026-04-24-system-md-and-reference-injection-requirements.md) | [Plan](../plans/2026-04-24-001-feat-system-md-and-reference-injection-plan.md)

## Summary

Replaced tigger-code's minimal 3-line default system prompt with a comprehensive, package-bundled `system.md` that provides tool-use discipline, behavioural guardrails, workflow examples, and identity anchoring. Simultaneously activated the existing but unused skill reference loading infrastructure so `references/*.md` files are auto-injected into skill prompts at invocation time.

## What Changed

### 1. Authoritative System Prompt (`src/tigger/assets/system.md`)

A comprehensive system prompt now ships inside the package. It covers:

- **Identity**: "You are Tigger, a terminal-based software engineering agent" — functional role anchoring, not persona-driven
- **Core Mandates**: 7 non-negotiable rules (finish tasks, no emojis, no fabrication, read before edit, confirm destructive commands, stay in project root, don't push without permission)
- **Tool Discipline**: Per-tool guidance for all 8 built-in tools (read, glob, grep, write, edit, bash, web_fetch, remember) with sequencing rules and anti-patterns
- **Workflow Examples**: 4 concrete examples showing correct tool sequences for common tasks (bug fix, add feature, explore codebase, review code)
- **Behavioural Rules**: Response style, code quality, safety constraints, codebase orientation, task completion

**Override model:** If `.tigger/system.md` exists, it fully replaces the package default. Memory from `.tigger/memory.md` is appended after either source (unchanged behaviour).

### 2. Plan-Mode Text Extraction (`src/tigger/assets/plan_mode.md`)

Plan-mode instructions previously hardcoded as a Python string in `loop.py` are now a separate markdown asset file. Loaded via `functools.lru_cache` for efficiency and testability.

### 3. Skill Reference Auto-Injection (`src/tigger/skills.py`)

Skills with a `references/` directory now have their reference files automatically injected into the rendered prompt at invocation time:

- References appear as `## Reference: <filename>` sections prepended before the skill body
- **Default is on** — references are injected unless the skill opts out
- Opt out by adding `inject_references: false` to the skill's YAML frontmatter
- Skills with no `references/` directory are unaffected (silent no-op)

The `how/` skill was updated with `inject_references: false` since its references are subagent prompts, not context for the main prompt.

**Data structure change:** `SkillDef.references` changed from `list[str]` to `list[tuple[str, str]]` storing `(filename, content)` pairs so reference headers can include the original filename.

## Files Changed

| File | Change |
|------|--------|
| `src/tigger/assets/system.md` | New — comprehensive default system prompt |
| `src/tigger/assets/plan_mode.md` | New — plan-mode instructions extracted from Python |
| `src/tigger/main.py` | Load system prompt from package assets instead of hardcoded fallback |
| `src/tigger/loop.py` | Load plan-mode text from asset file via `lru_cache` |
| `src/tigger/skills.py` | Add `inject_references` field, tuple references, updated `render()` |
| `tests/test_skills_dir.py` | Updated for new data structure and injection behaviour, added opt-out test |
| `.tigger/skills/how/SKILL.md` | Added `inject_references: false` |

## Design Decisions

- **Full override, not layered**: `.tigger/system.md` replaces the package default entirely. No `system_append.md`. Memory handles per-project additions. Simplest mental model.
- **Named identity as behavioural anchor**: Local models drift without identity grounding. "You are Tigger" provides a stable anchor without unnecessary persona traits.
- **Default-on injection with opt-out**: Most skills benefit from reference injection. The `inject_references: false` escape hatch handles edge cases like subagent-oriented references.
- **Markdown headers for references**: `## Reference: <filename>` is natural for models trained on markdown, preserves semantic meaning.

## Background

This feature was developed through a structured ideation and planning process:

1. **Ideation**: Analysed Qwen-code's system prompt (900+ lines, conditional assembly, 3 model-specific tool-call format templates) and Gemini CLI's skill architecture (TOML commands, policy files, self-referential skills, behavioural evals). Generated 40 raw ideas from 5 parallel ideation agents, filtered to 7 survivors.

2. **Brainstorming**: Deep-dived into the two highest-leverage, lowest-complexity ideas. Made key product decisions on override model, identity approach, reference injection behaviour, and coverage level.

3. **Planning**: Structured into 5 implementation units with clear dependencies, test scenarios, and verification criteria. Deepened with correctness and scope reviews.

The remaining 5 ideation survivors (internal skills directory, model-aware conditional assembly, core mandates surviving compaction, context budget signalling, skill chaining) are documented for future implementation.
