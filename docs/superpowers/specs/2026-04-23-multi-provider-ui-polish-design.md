# Multi-Provider Support & UI Polish — Design Spec

## Goal

Evolve Tigger CLI's config system to support multiple API providers with multiple models each, add runtime model switching, a first-run setup wizard, and a `/provider add` command. Simultaneously polish the UI based on Qwen Code CLI comparison: info box at startup, context percentage in toolbar, friendly time formatting, token count in spinner, and amber/orange theme for highlighted text.

## Architecture

Two independent subsystems that share a delivery:

1. **Provider system** — new config format, backward compat, `ProviderConfig` dataclass, setup wizard, `/model` picker, `/provider add` command.
2. **UI polish** — info box, context %, time formatting, spinner tokens, text theme.

Both touch `config.py`, `ui.py`, `main.py`, and `commands/` but in non-overlapping ways. They can be implemented as sequential tasks in one plan.

## Tech Stack

Python 3.11+, `rich>=13.0`, `prompt_toolkit>=3.0`, `openai>=1.0`, `pytest`

---

## 1. Config Format

### New format

```json
{
  "default_provider": "lmstudio",
  "default_model": "qwen3.6-35b-a3b",
  "providers": {
    "lmstudio": {
      "base_url": "http://192.168.2.122:1234/v1",
      "api_key": "sk-lm-nAzePjpV:7D4FkAhCFHmSP4PaTJQt",
      "models": ["qwen3.6-35b-a3b", "llama-4-scout"]
    },
    "openai": {
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-proj-...",
      "models": ["gpt-4o", "gpt-4o-mini"]
    }
  },
  "context_limit": 128000,
  "max_tokens": 8192,
  "temperature": 0.7,
  "permission_mode": "allow",
  "mode": "ask",
  "max_depth": 4,
  "max_retries": 2,
  "bash_safe_prefixes": ["ls", "git log", "git diff", "cat", "grep", "find", "echo"]
}
```

### New dataclass: `ProviderConfig`

```python
@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    models: list[str]
```

### Changes to `Config`

Add fields:
- `providers: dict[str, ProviderConfig]` — all configured providers
- `active_provider: str` — name of the currently active provider
- `active_model: str` — name of the currently active model

The existing `base_url`, `model`, and `api_key` fields become `@property` computed from the active provider. Since `Config` is currently a frozen dataclass, it must become a regular dataclass (non-frozen) with properties, OR remain frozen with `base_url`/`model`/`api_key` as regular fields that are set from the active provider at construction and updated via `dataclasses.replace()` when switching. **Decision: keep frozen, compute at construction.** When switching models, `dataclasses.replace()` updates `active_provider`, `active_model`, `base_url`, `model`, and `api_key` together. A helper function `switch_model(config, provider_name, model_name) -> Config` handles this.

### Backward compatibility

When `load_config` encounters the old flat format (has `base_url` + `model` at top level, no `providers` key), it auto-migrates in memory:

1. Derive provider name from `base_url` hostname via `urllib.parse.urlparse`. Examples: `http://192.168.2.122:1234/v1` -> `"192.168.2.122"`, `https://api.openai.com/v1` -> `"openai"` (strip `api.` prefix and `.com` suffix for known patterns, otherwise use full hostname).
2. Construct a single-provider `providers` dict.
3. Set `default_provider` and `default_model` from the flat fields.
4. Load proceeds normally.

The old `"permission_mode": "auto"` backward compat (already implemented) continues to work.

No automatic file rewrite — the old format works indefinitely. The file only gets rewritten when the user runs `/provider add` or the setup wizard.

### Config file write utility

A new `write_config(path, config) -> None` function in `config.py` that serializes the current `Config` back to the providers-format JSON. Used by the setup wizard and `/provider add`. This writes the `providers` dict format regardless of what the original file looked like.

---

## 2. First-Run Setup Wizard

### Trigger

In `startup()`, when `find_config()` returns `None`.

### Flow

1. Print welcome: `"No config found. Let's set up your first provider."`
2. Prompt: `Base URL` — hint: `"e.g. http://localhost:1234/v1 or https://api.openai.com/v1"`
3. Prompt: `API key` — hint: `"press Enter for 'local' if none needed"`. Empty input defaults to `"local"`.
4. Prompt: `Model name` — hint: `"e.g. qwen3.6-35b, gpt-4o"`
5. Auto-derive provider name from base_url hostname.
6. Prompt: `Save to project (.ai/) or user (~/.ai/)?` — `[P/u]` default project if cwd has a `.git` or existing `.ai/`, otherwise default user.
7. Create `.ai/` directory if needed, write `config.json` in new providers format.
8. Return the config path so `startup()` continues normally.

### Location

`ui.run_setup_wizard() -> tuple[pathlib.Path, dict]` — returns `(config_path, config_data)`. Uses `rich` console for styled prompts and `input()` for responses (same pattern as `ask_trust_prompt`).

The hostname-to-provider-name derivation is a shared utility in `config.py`: `derive_provider_name(base_url: str) -> str`.

---

## 3. `/model` Command

### No args — interactive picker

Prints a numbered list grouped by provider, prompts for selection:

```
  lmstudio:
    1. qwen3.6-35b-a3b  (active)
    2. llama-4-scout
  openai:
    3. gpt-4o
    4. gpt-4o-mini

Pick [1-4]: 
```

User enters a number. `ctx.config` is replaced with updated active provider/model/base_url/api_key via the `switch_model()` helper.

### With args — direct switch

- `/model gpt-4o` — search all providers for a matching model name. If found in exactly one provider, switch. If ambiguous (same model in multiple providers), print matches and ask user to pick. If not found, print error with available models.
- `/model openai/gpt-4o` — explicit `provider/model` syntax, no ambiguity possible.

### Implementation

Replace `cmd_model` in `commands/misc.py`. No new file needed — it's a natural extension of the existing command.

---

## 4. `/provider add` Command

### Flow — new provider

```
/provider add

  Provider name (or existing: lmstudio, openai): anthropic
  Base URL: https://api.anthropic.com/v1
  API key: sk-ant-...
  Model name: claude-sonnet-4-20250514

  Added provider 'anthropic' with model 'claude-sonnet-4-20250514'.
  Switch to it now? [Y/n]:
```

### Flow — add model to existing provider

When user enters an existing provider name, skip base_url/api_key prompts:

```
/provider add

  Provider name (or existing: lmstudio, openai): lmstudio
  Model name: deepseek-r1-0528

  Added model 'deepseek-r1-0528' to provider 'lmstudio'.
```

### Persistence

Writes the full config back to the config file using `write_config()`. The config path is passed through from startup (stored in `StartupResult` or passed to the command factory).

### Validation

- Provider name: alphanumeric + hyphens, no spaces.
- Base URL: must start with `http://` or `https://`.
- Model name: non-empty, no duplicates within the same provider.

### Implementation

New file `src/newcli/commands/provider.py` with `cmd_provider(args, ctx, config_path)`. Registered in `commands/__init__.py`.

Only the `add` subcommand is implemented. `/provider` with no args or unknown subcommand prints: `"Usage: /provider add"`.

---

## 5. UI Polish

Based on comparison with Qwen Code CLI (see `tiggervsqwen.md`).

### 5a. Info box next to logo

After the logo, print a right-aligned info box showing:
- Provider name + model (with `/model to change` hint)
- Current working directory
- Tigger version (from package metadata or hardcoded)

Layout: printed as indented lines below the cat mascot (same area as the existing `"a minimal, clean CLI"` subtitle). Not side-by-side with the logo — that would require terminal width detection for alignment. The info replaces or extends the existing footer area. Implementation: a `ui.print_startup_info(provider, model, cwd)` function called after `print_logo()` in startup.

### 5b. Context percentage in toolbar

Change the bottom toolbar from:
```
 qwen3.6-35b  mode:ask  perm:allow  1234/128000 tok
```
to:
```
 qwen3.6-35b  mode:ask  perm:allow  0.9% context
```

The raw token count is still available via `/tokens`. The toolbar shows the percentage for at-a-glance readability (matching Qwen's `14.3% context used`).

### 5c. Friendly time formatting

The turn summary currently shows `696.2s`. For durations over 60 seconds, format as `Xm Ys`. Under 60 seconds, keep `X.Xs`.

Examples: `2.3s`, `45.1s`, `11m 36s`, `1h 2m`.

Implementation: a `ui.format_duration(seconds: float) -> str` utility.

### 5d. Spinner shows token count

The spinner currently shows: `"Crafting a response... · 4s"`

Add a streaming token counter: `"Crafting a response... · 4s · ↓ 264 tokens"`

This requires the spinner to accept an external counter that the streaming loop updates. The `Spinner` context manager gets an optional `token_counter: list[int]` parameter (mutable, same pattern as `output_chars`). The spinner thread reads it on each tick.

### 5e. Highlighted text theme

Currently Rich uses its default theme for syntax highlighting (light blue on grey). Override the Rich console theme to use amber/orange tones matching the logo gradient for:
- Bold/emphasized text
- Code spans in markdown output

Implementation: set `Console(theme=Theme({...}))` with custom styles in `ui.py`.

---

## 6. Code Simplification

### 6a. Extract rendering from main.py

Move `render_event()`, `_flush_text()`, and `_fmt_args()` from `main.py` into `ui.py`. They are rendering logic. `main.py` calls `ui.render_event(event, ctx, output_chars, text_buf)`. Gets `main.py` under ~200 lines.

### 6b. Extract spinner messages

Move `SPINNER_MESSAGES` list from `ui.py` into a `_spinners.py` file (or a top-level constant). `ui.py` imports it. Reduces `ui.py` by ~120 lines so it focuses on rendering functions.

### 6c. Provider name derivation utility

`config.derive_provider_name(base_url: str) -> str` — shared by backward compat migration, setup wizard, and any future use. Simple URL parsing logic in one place.

---

## 7. Backlog (for planv3.md, not this plan)

Items identified from Qwen Code CLI's `prompts.ts` and comparison doc:

1. **Structured compression prompt** — Adopt XML `<state_snapshot>` format for context compaction (overall_goal, key_knowledge, file_system_state, recent_actions, current_plan) instead of the current loose "summarize this" approach.
2. **Project summary export** — `/summary` command to save session summary to markdown (Qwen's `getProjectSummaryPrompt()`).
3. **Insight/analytics prompts** — Post-session analysis (interaction_style, friction_points, impressive_workflows). Separate feature.
4. **Tighter plan mode prompt** — Qwen's plan mode is more structured: "MUST NOT make any edits... present plan by calling ExitPlanMode tool". Our plan mode just says "write a numbered plan". Worth tightening.
5. **Subagent system reminder** — Inject available agent types into system prompt so the model knows it can delegate.
6. **Collapsible tool call display** — Qwen's `ctrl+e`/`ctrl+f` collapsible agent boxes. Requires prompt_toolkit Live rendering — significant complexity.
7. **Input bar styling** — Horizontal rules above/below input area with faint placeholder text. Requires prompt_toolkit customization.
8. **`@file` syntax** — Qwen supports `@path/to/file` to attach file contents to a message. Useful shorthand.
9. **Session resume** — `--continue` / `--resume` flags to pick up a previous conversation.
