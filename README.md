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
| `rtk` | Enable RTK token optimization for bash commands | `false` (auto-detected) |

---

## RTK Integration

[RTK](https://github.com/rtk-ai/rtk) (Rust Token Killer) is an optional CLI proxy that reduces token consumption by 60-90% on shell command output. Tigger auto-detects RTK at startup — if `rtk` is in your PATH, it's enabled automatically.

When enabled, all bash tool calls are transparently proxied through `rtk`. The agent doesn't know the difference; it just receives cleaner, shorter output.

### Quick start

```bash
# Install RTK (see https://github.com/rtk-ai/rtk for options)
curl -fsSL https://rtk.sh | bash

# Tigger auto-detects it — just start normally
tigger-code
```

### Commands

| Command | Description |
|---|---|
| `/rtk` | Show RTK status (installed, enabled) |
| `/rtk on` | Enable RTK proxy |
| `/rtk off` | Disable RTK proxy |
| `/rtk gain` | Show token savings stats |
| `/rtk gain --history` | Show per-command savings history |

### Configuration

To explicitly enable or disable in `config.json`:

```json
{
  "rtk": true
}
```

When `rtk` is not set in config, tigger auto-detects: if the `rtk` binary is found in PATH, it's enabled. Set `"rtk": false` to disable even when installed.

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

### Commands

Type `exit` or `quit` to leave the REPL. Ctrl+C during a response interrupts it and returns to the prompt.

| Command | Description |
|---|---|
| `/help` | Show all available commands and loaded skills |
| `/model [name]` | Switch model — interactive picker, or `/model gpt-4o` directly |
| `/model prov/name` | Switch to a specific provider's model, e.g. `/model cloud/gpt-4o` |
| `/provider add` | Add a new provider or model interactively |
| `/mode [ask\|plan]` | View or change the interaction mode |
| `/permission [ask\|allow\|bypass]` | View or change tool permission level |
| `/memory` | View persistent memory notes |
| `/remember <note>` | Save a note to persistent memory |
| `/tokens` | Show current token usage vs context limit |
| `/compact` | Manually compact the context window |
| `/skills` | List loaded skills |
| `/agent <name>` | Invoke a sub-agent by name |
| `/rtk` | Show RTK status, toggle on/off, view token savings |
| `/clear` | Clear message history |
| `exit` / `quit` | Exit the REPL |

### Adding new commands

Commands are functions in `src/tigger/commands/` registered in `commands/__init__.py`.

**Simple command** (just args + context):

```python
# src/tigger/commands/misc.py
def cmd_ping(args: str, ctx: RunContext) -> None:
    print("pong")
```

```python
# src/tigger/commands/__init__.py — add to the dict
"ping": misc.cmd_ping,
```

**Command with extra state** (e.g. a file path):

```python
# src/tigger/commands/mycommand.py
def cmd_export(args: str, ctx: RunContext, output_dir: pathlib.Path) -> None:
    # output_dir is bound at startup via functools.partial
    print(f"Exporting to {output_dir}")
```

```python
# src/tigger/commands/__init__.py — bind the extra arg
"export": partial(mycommand.cmd_export, output_dir=some_path),
```

Commands receive `(args: str, ctx: RunContext)` where `args` is everything after the command name (e.g. `/model gpt-4o` passes `"gpt-4o"` as args).

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
