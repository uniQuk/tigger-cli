# newcli

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

---

## Configuration

The CLI discovers `.ai/` by walking up from the current working directory, then falls back to `~/.ai/` for global defaults. Both directories are merged — project `.ai/` overrides global `~/.ai/`.

Create `.ai/config.json` in your project or home directory:

```json
{
  "base_url": "http://localhost:11434/v1",
  "model": "qwen2.5",
  "api_key": "local",
  "context_limit": 8192,
  "max_tokens": 2048,
  "temperature": 0.7,
  "permission_mode": "auto",
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
| `permission_mode` | `auto` \| `manual` \| `accept-all` | `"auto"` |
| `max_depth` | Max sub-agent recursion depth | `4` |
| `max_retries` | Retries on provider error | `2` |
| `bash_safe_prefixes` | Commands that don't require permission | `[]` |

---

## Project layout

```
my-project/
└── .ai/
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
newcli
```

The REPL shows a status line with the current model and token usage:

```
[qwen2.5 · 142/8192 tokens] >
```

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

Define skills in `.ai/skills.md` using YAML frontmatter blocks:

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

Drop a `hooks.py` in `.ai/` to intercept the agent loop as middleware:

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
src/newcli/
├── main.py         ← entry point + REPL            (~150 lines)
├── loop.py         ← agent loop generator           (~200 lines)
├── types.py        ← all dataclasses + events       (~100 lines)
├── config.py       ← config loader + validation     (~80 lines)
├── provider.py     ← OpenAI-compat streaming client (~150 lines)
├── tools.py        ← tool implementations + registry (~300 lines)
├── permissions.py  ← permission gating              (~60 lines)
├── compaction.py   ← context window management      (~120 lines)
├── skills.py       ← skill/agent markdown loader    (~100 lines)
├── hooks.py        ← hook middleware system         (~80 lines)
├── memory.py       ← memory read/write              (~60 lines)
└── mcp.py          ← MCP client                     (~150 lines)
```

---

## Running tests

```bash
pytest
```

---

## License

MIT
