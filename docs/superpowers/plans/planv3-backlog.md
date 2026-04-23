# Tigger CLI — v3 Backlog

Items identified during multi-provider design. These are not part of the current implementation plan but are worth doing in future iterations.

## From Qwen Code CLI prompts.ts analysis

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

## Additional skill dependencies (from prompts.ts)

None identified. The Qwen prompts.ts is self-contained — all system prompt content is inline, no external skill file dependencies. The tool name references (`ToolNames.*`) are just string constants, not separate skill files.
