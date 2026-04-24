# Tigger CLI — Setup Guide

## First Run

If no config exists, Tigger launches an interactive setup wizard:

```
No config found. Let's set up your first provider.

  Base URL (e.g. http://localhost:1234/v1): http://192.168.2.122:1234/v1
  API key (Enter for 'local'): sk-my-key
  Model name (e.g. qwen3, gpt-4o): qwen3.6-35b-a3b
  Save to [P]roject or [u]ser (~/.tigger/)? [P/u]: p

  Config saved to /path/to/project/.tigger/config.json
```

This creates a `.tigger/config.json` in your project (or `~/.tigger/config.json` for user-level). You can also create the file manually.

## Config File Location

Tigger searches for `.tigger/config.json` by walking up from the current directory, then falls back to `~/.tigger/config.json`. Project-level configs override user-level.

```
my-project/
  .tigger/
    config.json      <-- project config (takes priority)
    skills/          <-- project skills
    system.md        <-- custom system prompt (optional)
    memory.md        <-- agent memory
~/.tigger/
  config.json        <-- user-level fallback
```

## Config Examples

### Single provider (simple)

The minimal config for a local LLM server:

```json
{
  "default_provider": "lmstudio",
  "default_model": "qwen3.6-35b-a3b",
  "providers": {
    "lmstudio": {
      "base_url": "http://192.168.2.122:1234/v1",
      "api_key": "sk-lm-your-key-here",
      "models": ["qwen3.6-35b-a3b"]
    }
  }
}
```

### Single provider, multiple models

Load several models in LM Studio and switch between them:

```json
{
  "default_provider": "lmstudio",
  "default_model": "qwen3.6-35b-a3b",
  "providers": {
    "lmstudio": {
      "base_url": "http://192.168.2.122:1234/v1",
      "api_key": "sk-lm-your-key-here",
      "models": [
        "qwen3.6-35b-a3b",
        "llama-4-scout",
        "deepseek-r1-0528"
      ]
    }
  }
}
```

### Multiple providers

Mix local and cloud APIs:

```json
{
  "default_provider": "lmstudio",
  "default_model": "qwen3.6-35b-a3b",
  "providers": {
    "lmstudio": {
      "base_url": "http://192.168.2.122:1234/v1",
      "api_key": "sk-lm-your-key-here",
      "models": ["qwen3.6-35b-a3b", "llama-4-scout"]
    },
    "openai": {
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-proj-your-openai-key",
      "models": ["gpt-4o", "gpt-4o-mini"]
    },
    "anthropic": {
      "base_url": "https://api.anthropic.com/v1",
      "api_key": "sk-ant-your-anthropic-key",
      "models": ["claude-sonnet-4-20250514"]
    },
    "ollama": {
      "base_url": "http://localhost:11434/v1",
      "api_key": "local",
      "models": ["qwen3:8b", "llama3.1:8b"]
    }
  }
}
```

### Full config with all options

```json
{
  "default_provider": "lmstudio",
  "default_model": "qwen3.6-35b-a3b",
  "providers": {
    "lmstudio": {
      "base_url": "http://192.168.2.122:1234/v1",
      "api_key": "sk-lm-your-key-here",
      "models": ["qwen3.6-35b-a3b", "llama-4-scout"]
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

### Legacy flat format (still supported)

The old single-provider format is auto-migrated in memory on load:

```json
{
  "base_url": "http://192.168.2.122:1234/v1",
  "model": "qwen3.6-35b-a3b",
  "api_key": "sk-lm-your-key-here",
  "context_limit": 128000,
  "max_tokens": 8192,
  "temperature": 0.7,
  "permission_mode": "allow"
}
```

This works indefinitely. The file is only rewritten to the new format when you use `/provider add`.

## Config Options Reference

| Field | Default | Description |
|-------|---------|-------------|
| `default_provider` | first provider | Provider to use on startup |
| `default_model` | first model of default provider | Model to use on startup |
| `providers` | (required) | Dict of named providers |
| `context_limit` | `8192` | Max context window tokens |
| `max_tokens` | `2048` | Max tokens per response |
| `temperature` | `0.7` | Sampling temperature |
| `permission_mode` | `"allow"` | `ask` (prompt every tool), `allow` (auto-approve safe tools), `bypass` (auto-approve all) |
| `mode` | `"ask"` | `ask` (normal) or `plan` (numbered plan before action) |
| `max_depth` | `4` | Max nested agent depth for forked skills |
| `max_retries` | `2` | Retries on empty responses or hallucinated tools |
| `bash_safe_prefixes` | `[]` | Shell command prefixes auto-approved in `allow` mode |

### Provider fields

| Field | Default | Description |
|-------|---------|-------------|
| `base_url` | (required) | OpenAI-compatible API endpoint |
| `api_key` | `"local"` | API key. Use `"local"` for servers that don't require one |
| `models` | (required) | List of model names available from this provider |

## Commands

### /model — Switch models

```
/model                       # Interactive picker — shows numbered list grouped by provider
/model gpt-4o                # Direct switch — searches all providers
/model openai/gpt-4o-mini   # Explicit provider/model — no ambiguity
```

Interactive picker example:

```
  lmstudio:
    1. qwen3.6-35b-a3b  (active)
    2. llama-4-scout
  openai:
    3. gpt-4o
    4. gpt-4o-mini

Pick [1-4]: 3
Switched to openai/gpt-4o
```

### /provider add — Add a new provider or model

Add a new provider:

```
/provider add

  Provider name (or existing: lmstudio, openai): anthropic
  Base URL: https://api.anthropic.com/v1
  API key: sk-ant-your-key
  Model name: claude-sonnet-4-20250514

  Added provider 'anthropic' with model 'claude-sonnet-4-20250514'.
  Switch to it now? [Y/n]: y
  Switched to anthropic/claude-sonnet-4-20250514
```

Add a model to an existing provider:

```
/provider add

  Provider name (or existing: lmstudio, openai): lmstudio
  Model name: deepseek-r1-0528

  Added model 'deepseek-r1-0528' to provider 'lmstudio'.
```

Both operations persist to `.tigger/config.json` immediately.

### Other useful commands

```
/mode plan         # Switch to plan mode (agent writes plan before acting)
/mode ask          # Switch back to normal mode
/permission ask    # Prompt before every tool call
/permission allow  # Auto-approve safe tools (reads, greps)
/permission bypass # Auto-approve everything
/tokens            # Show raw token usage
/clear             # Clear conversation history
/compact           # Force context compaction
/skills            # List loaded skills
/help              # Show all commands
```

## Workspace Trust

On first run in a new directory, Tigger asks whether to trust the workspace:

```
Trust workspace: /path/to/project
  Continue? [Y/n]:
```

- **Y** (default) — full access, trust persisted to `~/.tigger/trusted_paths.json`
- **n** — read-only mode (only read, glob, grep, web_fetch tools available)

## Custom System Prompt

Create `.tigger/system.md` to override the built-in system prompt:

```markdown
You are a senior Python developer.
Always write tests for new code.
Never use emojis.
```

If this file doesn't exist, Tigger uses its default prompt.
