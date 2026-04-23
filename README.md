# tigger-code

A minimal, clean AI agent CLI. One folder. One settings file. No repository required.

Built as a clean-architecture alternative to monolithic agent CLIs — every module has one job, config is a typed dataclass, and hooks are middleware rather than function replacement.

---

## Features

- **OpenAI-compatible provider** — works with OpenAI, Ollama, LM Studio, llama.cpp, and any other OpenAI-compatible endpoint
- **Typed context** — `RunContext` is a dataclass, not a config-dict grab-bag
- **Neutral message format** — provider conversion happens only inside `provider.py`
- **Skill injection** — define skills as YAML frontmatter blocks in a plain `.md` file
- **Sub-agent support** — spawn forked agents with configurable depth limits
- **Two-layer compaction** — context window management with configurable limits
- **MCP client** — connect Model Context Protocol servers via `mcp.json`
- **Middleware hooks** — `hooks.py` for custom pre/post processing
- **Persistent memory** — auto-managed `memory.md` injected into the system prompt
- **Slash commands** — `/memory`, `/skills`, `/agent`, `/compact`, and more

---

## Requirements

- Python 3.11+
- An OpenAI-compatible API endpoint (local or remote)

---

## Installation

```bash
git clone <repo>
cd dev-north7-cli
pip install -e .
```

Or use the Makefile:

```bash
make install      # pip install -e .
make dev          # pip install -e ".[dev]"
```

---

## Configuration

The CLI discovers `.tigger/` by walking up from the current working directory, then falls back to `~/.tigger/` for global defaults. Both directories are merged — project `.tigger/` overrides global `~/.tigger/`.

Create `.tigger/config.json` in your project or home directory:

```json
{
  "base_url": "http://localhost:11434/v1",
  "model": "qwen2.5",
  "api_key": "local",
  "context_limit": 8192,
  "max_tokens": 2048,
  "temperature": 0.7,
  "permission_mode": "allow",
  "max_depth": 4,
  "max_retries": 2,
  "bash_safe_prefixes": ["ls", "git log", "git diff", "cat", "grep", "find", "echo"]
}
```

| Field | Description | Default |
|---|---|---|
| `base_url` | OpenAI-compatible API endpoint | required |
| `model` | Model name | required |
| `api_key` | API key (`"local"` for local endpoints) | `"local"` |
| `context_limit` | Max context window tokens | `8192` |
| `max_tokens` | Max tokens per response | `2048` |
| `temperature` | Sampling temperature | `0.7` |
| `permission_mode` | `ask` \| `allow` \| `bypass` | `"allow"` |
| `max_depth` | Max sub-agent recursion depth | `4` |
| `max_retries` | Retries on provider error | `2` |
| `bash_safe_prefixes` | Commands that don't require permission | `[]` |

---

## Project layout

```
my-project/
└── .tigger/
    ├── config.json     ← model endpoint, permissions, limits
    ├── skills.md       ← skill definitions (YAML frontmatter blocks)
    ├── agents.md       ← sub-agent type definitions
    ├── hooks.py        ← optional Python middleware hooks
    ├── mcp.json        ← MCP server configs
    └── memory.md       ← auto-managed persistent notes
```

---

## Usage

```bash
tigger-code
```

The REPL shows a status line with the current model and token usage.

### Slash commands

| Command | Description |
|---|---|
| `/memory` | View and edit persistent memory |
| `/skills` | List loaded skills |
| `/agent <name>` | Invoke a sub-agent by name |
| `/compact` | Manually compact the context window |
| `/help` | Show available commands |

---

## Skills

Define skills in `.tigger/skills.md` using YAML frontmatter blocks:

```markdown
---
name: review
trigger: "review this"
context: fork
system: "You are a meticulous code reviewer."
---
Review the following carefully: {{input}}
```

A skill with `context: fork` runs in an isolated sub-agent and returns only the result, leaving the main conversation unchanged.

---

## Hooks

Drop a `hooks.py` in `.tigger/` to intercept the agent loop as middleware:

```python
def before_turn(ctx, messages):
    # modify messages before sending to provider
    return messages

def after_turn(ctx, event):
    # inspect or log events
    pass
```

---

## Source layout

```
src/tigger/
├── _constants.py   ← app identity + config paths       (~20 lines)
├── main.py         ← entry point + REPL                (~250 lines)
├── loop.py         ← agent loop generator               (~170 lines)
├── types.py        ← all dataclasses + events           (~115 lines)
├── config.py       ← config loader + validation         (~165 lines)
├── provider.py     ← OpenAI-compat streaming client     (~110 lines)
├── tools.py        ← tool implementations + registry    (~270 lines)
├── permissions.py  ← permission gating                  (~25 lines)
├── compaction.py   ← context window management          (~90 lines)
├── skills.py       ← skill/agent markdown loader        (~160 lines)
├── hooks.py        ← hook middleware system              (~70 lines)
├── memory.py       ← memory read/write                  (~20 lines)
└── mcp.py          ← MCP client                         (~100 lines)
```

---

## Running tests

```bash
make test         # or: python -m pytest tests/ -q
make test-v       # verbose
make lint         # ruff check + format check
```

---

## License

MIT
