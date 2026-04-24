# Tigger CLI — v3 Backlog

Items identified during multi-provider design. These are not part of the current implementation plan but are worth doing in future iterations.

## From Qwen Code CLI prompts.ts analysis
/Volumes/Kingston2TB/Dev/ai-tools/dev-north7-cli/z_no_upload/prompts.ts
1. **Structured compression prompt** — Adopt XML `<state_snapshot>` format for context compaction (overall_goal, key_knowledge, file_system_state, recent_actions, current_plan) instead of the current loose "summarize this" approach. Qwen's `getCompressionPrompt()` uses scratchpad reasoning + structured XML output. Would significantly improve compaction quality.

2. **Project summary export** — `/summary` command to save session summary to markdown. Qwen's `getProjectSummaryPrompt()` generates Overall Goal, Key Knowledge, Recent Actions, Current Plan sections. Could save to `.ai/summaries/`.

3. **Insight/analytics prompts** — Post-session analysis of interaction patterns: `interaction_style`, `friction_points`, `impressive_workflows`, `future_opportunities`, `memorable_moment`, `improvements`. This is a full analytics feature — large scope.

4. **Tighter plan mode prompt** — Qwen's plan mode is more structured: "MUST NOT make any edits... present plan by calling ExitPlanMode tool... supercedes any other instructions". Our plan mode just appends "write a numbered plan before executing". Worth tightening to actually prevent premature execution.

5. **Subagent system reminder** — Inject available `AgentDef` names into a system reminder so the model knows it can delegate. Qwen's `getSubagentSystemReminder()` lists agent types and says "PROACTIVELY use the AGENT tool".

## From Qwen Code CLI UX comparison

6. **Collapsible tool call display** — Qwen shows tool calls in a bordered box with `ctrl+e` to expand/collapse, shows last 5 calls, `ctrl+f` for more. Requires prompt_toolkit Live rendering — significant complexity. Would need a custom `prompt_toolkit` layout with keybindings.

7. **Input bar styling** — Horizontal rules above and below the input area with faint placeholder text like "Type your message or @path/to/file". Requires prompt_toolkit `FormattedTextControl` customization.

8. **`@file` syntax** — Qwen supports `@path/to/file` inline in messages to attach file contents. Pre-processes the input line, reads the file, and prepends content. Useful shorthand — moderate complexity.

9. **Session resume** — `--continue` / `--resume` CLI flags to pick up a previous conversation. Needs conversation persistence (save messages to disk) and a session index.

## Per-model configuration

10. **Per-model sampling params and overrides** — Currently `temperature`, `max_tokens`, `context_limit` are global. Models should support per-model overrides with global values as fallback. The `models` field in a provider would accept either a simple list (`["qwen3", "llama"]`) or a dict with per-model config:
    ```json
    "models": {
      "qwen3.6-35b-a3b": {
        "context_limit": 128000,
        "max_tokens": 8192,
        "thinking": false
      },
      "llama-4-scout": {
        "context_limit": 64000,
        "temperature": 0.6,
        "top_p": 0.9
      }
    }
    ```
    Resolution order: model-specific > global > hardcoded default. Empty object `{}` means use all defaults. New optional per-model fields: `temperature`, `max_tokens`, `context_limit`, `top_p`, `thinking`. Requires a `ModelConfig` dataclass, changes to `switch_model` to merge overrides, and `provider.stream()` to pass `thinking` param. Inspired by Qwen Code's `settings.json` `generationConfig`/`samplingParams` structure. Moderate complexity — touches types.py, config.py, provider.py.

## Compaction UX

11. **Spinner during `/compact`** — When compaction hits layer 2 (LLM summarization), there's no visual feedback while the API call runs. `cmd_compact` should show a spinner (reuse `ui.Spinner`) during the `maybe_compact` call so the user knows it's working. Currently silent — feels broken even when working correctly.

12. **Compact progress breakdown** — Show what compaction actually did: "Snipped 14 tool results (5840 → 4800 tokens), summarized 12 old messages (4800 → 2100 tokens)" instead of just "Compacted: 5840 → 4283". Helps users understand what happened and whether the LLM summary step ran.

## Memory improvements

13. **Memory search** — `/memory search <query>` to grep through memory entries instead of dumping all 50 lines. Simple substring match would be enough.

14. **Memory delete** — `/memory delete <n>` or `/memory clear` to remove entries. Currently append-only with no way to clean up stale notes.

15. **Memory auto-save from conversation** — The model can't currently save to memory on its own. Add a `remember` tool so the LLM can persist key facts/decisions during conversation (e.g. "user prefers tabs over spaces"). Would require adding a tool to the registry that calls `append_memory`.

## Help system

16. **Per-command help** — `/help <command>` should show usage details for a specific command (e.g. `/help model` shows the three switch syntaxes). Currently `/help` ignores any arguments and always shows the full list. Each command handler could have a `__doc__` or a `HELP` constant.

17. **Help descriptions in command list** — `/help` currently just lists command names with no descriptions. Add a one-line description next to each (e.g. `/model — Switch model or provider`).

## Project initialisation

18. **`/init` command** — Interactive project setup that creates `.tigger/` with scaffolded files:
    - `config.json` (already handled by the setup wizard)
    - `agents.md` with example agent definitions
    - `skills.md` with example skill definitions  
    - `system.md` with a customisable system prompt
    - `hooks.py` with commented-out example hooks
    
    Should be smart about existing files — only create missing ones, never overwrite. Could also detect project type (Python, Node, etc.) and tailor the system prompt.

19. **AGENTS.md awareness** — The CLI already loads `agents.md` from `.tigger/` but there's no way to discover this without reading the source. `/init` should create a documented template, and `/help agent` should explain the format.

## System prompt & tool guidance

20. **Tool usage guidance in system prompt** — The model has no instructions on how to use tools effectively. It will do things like `glob **/*` (listing every file in the project) which overwhelms context and can timeout the provider. The system prompt needs a section teaching the model tool best practices:
    - Use specific glob patterns, never `**/*`
    - Prefer `grep` for content search over reading entire files
    - Use `read` with specific paths rather than globbing then reading everything
    - Prefer targeted tool calls over broad sweeps
    
    Claude Code's system prompt has an extensive "Using your tools" section covering this. Tigger needs an equivalent tailored to its own tool set. This is the primary fix — the glob result cap (item 21) is just a safety net.

21. **Tool result size caps** — Safety limits on tool output sent to the model. Currently a `glob **/*` on a large project returns thousands of lines, blowing up context and causing provider timeouts. Glob is now capped at 200 results with a truncation message. Similar caps should be considered for:
    - `read`: truncate very large files with a "(truncated — use offset/limit for specific sections)" message
    - `grep`: cap match count with guidance to narrow the pattern
    - `bash`: cap stdout length
    
    These are guardrails, not the primary solution (see item 20).

## Additional skill dependencies (from prompts.ts)

None identified. The Qwen prompts.ts is self-contained — all system prompt content is inline, no external skill file dependencies. The tool name references (`ToolNames.*`) are just string constants, not separate skill files.
