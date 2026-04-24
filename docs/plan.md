## Plan: New CLI — Clean Architecture Design

The goal is everything little-coder gets right (neutral message format, tool registry, two-layer compaction, skill injection, Write-vs-Edit invariant, MCP) minus everything that made it hard to maintain (4200-line god object, config-dict context pipe, import side-effects, sentinel tuples, direct function replacement hooks, unbounded sub-agent depth).

---

```markdown
# newcli — Architecture

A minimal, clean AI agent CLI. One folder. One settings file. No repository required.

---

## Design Principles

1. Every module has one job and fits in ~200 lines
2. Explicit over implicit — no import side-effects, no sentinel tuples, no magic
3. Typed context, not config dict — `RunContext` is a dataclass, not a grab-bag
4. Hooks are middleware, not function replacement
5. One provider target: OpenAI-compatible (works with Ollama, llama.cpp, LM Studio, etc.)
6. Markdown-first config: skills, agents, memory are plain `.md` files

---

## Folder Layout

### Workspace (user's project folder)

```
my-project/
└── .tigger/                    ← agent config folder (or use ~/.tigger/ globally)
    ├── config.json         ← model endpoint, permissions, limits
    ├── skills.md           ← skill definitions (YAML frontmatter blocks)
    ├── agents.md           ← sub-agent type definitions
    ├── hooks.py            ← optional Python hooks (middleware)
    ├── mcp.json            ← MCP server configs
    └── memory.md           ← auto-managed persistent notes
```

The agent discovers `.tigger/` by walking up from `cwd`. Falls back to `~/.tigger/` for global defaults.
Both directories are merged: project `.tigger/` overrides global `~/.tigger/`.

### CLI Source

```
src/
├── main.py             ← entry point + REPL            (~150 lines)
├── loop.py             ← agent loop generator           (~200 lines)
├── types.py            ← all dataclasses + events       (~100 lines)
├── config.py           ← config loader + validation     (~80 lines)
├── provider.py         ← OpenAI-compat streaming client (~150 lines)
├── tools.py            ← tool implementations + registry (~300 lines)
├── permissions.py      ← permission gating              (~60 lines)
├── compaction.py       ← context window management      (~120 lines)
├── skills.py           ← skills/agents markdown loader  (~100 lines)
├── hooks.py            ← hook middleware system         (~80 lines)
├── memory.py           ← memory read/write              (~60 lines)
└── mcp.py              ← MCP client                     (~150 lines)
```

Total: ~1550 lines. No file dominates.

---

## Configuration (`config.json`)

```json
{
  "base_url": "http://localhost:11434/v1",
  "model": "qwen3.5",
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

Loaded once at startup into a `Config` dataclass. Validated on load. Fields have sane defaults.
No runtime mutation — config is read-only after startup.

---

## Core Data Types (`types.py`)

### Config

```python
@dataclass(frozen=True)
class Config:
    base_url: str
    model: str
    api_key: str = "local"
    context_limit: int = 8192
    max_tokens: int = 2048
    temperature: float = 0.7
    permission_mode: str = "auto"   # auto | manual | accept-all
    max_depth: int = 4
    max_retries: int = 2
    bash_safe_prefixes: list[str] = field(default_factory=list)
```

### RunContext

Replaces the config-dict context pipe. Typed, explicit, and passed by reference.

```python
@dataclass
class RunContext:
    config: Config
    messages: list[Message]
    system_prompt: str
    depth: int = 0
    allowed_tools: list[str] | None = None   # None = all tools
    turn: int = 0
```

Tools receive only what they need — not the full context. The registry calls `tool.func(args)`.
Only the agent loop and hooks see `RunContext`.

### Message (neutral format)

```python
@dataclass
class Message:
    role: str                           # "user" | "assistant" | "tool"
    content: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    tool_call_id: str | None = None     # for role="tool"
    name: str | None = None             # for role="tool"
```

Provider conversion (Anthropic blocks, OpenAI `tool_calls` array) happens only inside
`provider.py`. The rest of the codebase only ever sees `Message`.

### Events (typed, not tuples)

```python
@dataclass
class TextChunk:
    content: str

@dataclass
class ToolStartEvent:
    call_id: str
    name: str
    args: dict

@dataclass
class ToolEndEvent:
    call_id: str
    name: str
    output: str
    error: bool = False
    permitted: bool = True

@dataclass
class PermissionEvent:
    call_id: str
    name: str
    args: dict
    # REPL reads this and sets .granted before continuing
    granted: bool = False

@dataclass
class TurnDoneEvent:
    input_tokens: int
    output_tokens: int
```

No sentinel tuples. Commands that need to trigger agent queries call `loop.run()` directly.

---

## The Agent Loop (`loop.py`)

Clean generator. Single responsibility: run one multi-turn exchange.

```
run(query, ctx) →
  1. Prepend query to ctx.messages
  2. maybe_compact(ctx)
  3. stream from provider
  4. for each text chunk → yield TextChunk
  5. when turn completes:
     a. record assistant message
     b. yield TurnDoneEvent
     c. if no tool calls → break
     d. for each tool call:
        - check permission → yield PermissionEvent if manual
        - run before-hooks
        - execute tool
        - run after-hooks
        - yield ToolStartEvent / ToolEndEvent
        - record tool result
  6. loop (back to step 2 for next turn)
```

Small-model adaptations are a separate step called before streaming:

```
prepare_context(system, messages, ctx) →
  1. compress_system_prompt(system, ctx.config)   # if context_limit < 4096
  2. inject_skills(system, ctx)                   # relevant skills from skills.md
  3. prune_messages(messages, ctx.config)          # keep tail + fill from head
  → returns (effective_system, effective_messages)
```

This is always called. For large-context models (e.g., Claude, GPT-4) with full context, it's
nearly a no-op — compression budget is large enough that nothing gets stripped.

### Retry loop

If the model returns an empty response, hallucinated tool name, or malformed args:
- Build a correction message: `{"role": "user", "content": "Your last response was empty / used unknown tool X. Try again."}`
- Append and re-stream. Max `config.max_retries` times.

---

## Tool System (tools.py)

### Registry

```python
class ToolRegistry:
    def __init__(self): self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef): self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None: ...
    def schemas(self) -> list[dict]: ...          # JSON schemas for provider
    def execute(self, name: str, args: dict) -> str: ...
```

No side-effects. Initialized once in `main.py`, passed to the agent loop.

### Tool definition

```python
@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict           # JSON Schema
    func: Callable[[dict], str]
    read_only: bool = False    # auto-approved in all modes
    safe: bool = False         # auto-approved in "auto" mode
```

Tools are registered explicitly at startup:

```python
def register_all(registry: ToolRegistry):
    registry.register(ToolDef("read",      ..., read_only=True))
    registry.register(ToolDef("glob",      ..., read_only=True))
    registry.register(ToolDef("grep",      ..., read_only=True))
    registry.register(ToolDef("write",     ..., read_only=False))
    registry.register(ToolDef("edit",      ..., read_only=False))
    registry.register(ToolDef("bash",      ..., safe=False))    # safe checked per-command
    registry.register(ToolDef("web_fetch", ..., read_only=True))
```

MCP tools are registered in the same registry with `mcp__<server>__<name>` prefix.

### The Write-vs-Edit invariant

`write` returns an error string if the path exists: `"File already exists. Use 'edit' to modify existing files."`.
This is tool-level logic, not framework-level. Simple.

### Output truncation

Tool results capped at 32KB inside `registry.execute()`. One place, one implementation.

---

## Permissions (`permissions.py`)

Single function. Tool metadata drives the decision. No hardcoded tool names.

```python
def check(tool: ToolDef, mode: str, args: dict) -> bool:
    if tool.read_only:
        return True
    if mode == "accept-all":
        return True
    if mode == "auto":
        if tool.safe:
            return True
        if tool.name == "bash":
            cmd = args.get("command", "")
            return any(cmd.startswith(p) for p in config.bash_safe_prefixes)
        return False        # ask
    return False            # manual: caller must prompt
```

Adding a new tool with `safe=True` in its `ToolDef` automatically gets auto-approved.
No edits to `permissions.py` required.

---

## Hooks (`hooks.py` system + `.tigger/hooks.py` user file)

Hooks are middleware lists. No function replacement.

### System-level

```python
@dataclass
class HookRegistry:
    before: dict[str, list[Callable]] = field(default_factory=dict)  # tool_name → [fn]
    after: dict[str, list[Callable]] = field(default_factory=dict)

def run_before(call: ToolCallRecord, ctx: RunContext, registry: HookRegistry) -> ToolCallRecord:
    for fn in registry.before.get(call.name, []) + registry.before.get("*", []):
        call = fn(call, ctx)
    return call

def run_after(result: ToolEndEvent, ctx: RunContext, registry: HookRegistry) -> ToolEndEvent:
    for fn in registry.after.get(result.name, []) + registry.after.get("*", []):
        result = fn(result, ctx)
    return result
```

### User hooks (`.tigger/hooks.py`)

```python
# .tigger/hooks.py — loaded at startup if present
from newcli.hooks import on_before, on_after   # decorators that register into the hook registry

@on_before("write", "edit")
def backup_before_modify(call, ctx):
    import shutil, os
    path = call.args.get("path")
    if path and os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    return call

@on_after("bash")
def log_commands(result, ctx):
    with open(".tigger/bash_log.txt", "a") as f:
        f.write(result.output + "\n")
    return result
```

Hooks are loaded once at boot by `importlib.util.spec_from_file_location`. Clean, composable,
multiple hooks on the same tool work fine. No global state outside the `HookRegistry` instance.

---

## Skills Markdown (`skills.md`)

One file. Multiple skill blocks separated by `---`. Each block has YAML frontmatter + prompt body.

```markdown
---
name: review
triggers: [/review]
tools: [read, grep, glob]
context: inline
---
Review the code at $ARGUMENTS. Check for logic errors, security issues, and edge cases.
Report findings concisely.

---
name: refactor
triggers: [/refactor]
tools: [read, edit, bash]
context: fork
---
Refactor $ARGUMENTS. Preserve behavior. Improve clarity. Run tests after.
```

**`context: inline`** — prompt is injected into the current agent loop as a user message.
**`context: fork`** — spawns a new `RunContext` with `depth + 1`, isolated message history,
restricted to `tools` list. Returns result as string. Depth capped at `config.max_depth`.

Skills are loaded at startup into a `list[SkillDef]`. Trigger matching: exact slash-command
or keyword in the user message.

---

## Agents Markdown (`agents.md`)

Defines named agent personas. Used when a skill has `context: fork` and names an agent,
or via `/agent <name> <query>` command.

```markdown
---
name: reviewer
system_prompt: |
  You are a careful code reviewer. Focus on correctness, security, and clarity.
  Be terse. Format findings as a numbered list.
tools: [read, grep, glob]
model: null
---

---
name: coder
system_prompt: |
  You are an expert programmer. Write clean, idiomatic code.
  Always read existing files before editing.
tools: [read, write, edit, bash, glob, grep]
model: null
---
```

`model: null` inherits from `config.json`. Can override per-agent for e.g. a faster model
for the reviewer.

---

## MCP Integration (`mcp.py` + `.tigger/mcp.json`)

```json
{
  "servers": {
    "filesystem": {
      "transport": "stdio",
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."]
    },
    "github": {
      "transport": "http",
      "url": "http://localhost:3001/sse"
    }
  }
}
```

MCP servers are connected **explicitly at boot** (not in a background thread). A 3-second
connect timeout per server. Failed servers log a warning and are skipped — they don't block startup.

Tools registered as `mcp__filesystem__read_file`, etc. into the same `ToolRegistry`.
Naming follows the same convention as little-coder (Claude Code compatible).

---

## Memory (`memory.md`)

Simple append-only Markdown. Read at startup, last 50 lines injected into system prompt.
No YAML frontmatter, no confidence scores, no AI consolidation — just human-readable notes.

```markdown
## Memory

- [2026-04-22] Prefer pytest for Python tests
- [2026-04-22] API is at http://localhost:8000, uses JWT auth
```

Written via `/remember <note>` command. That's it.

---

## Provider (`provider.py`)

One target: OpenAI-compatible chat completions with streaming (`stream=True`).
No Anthropic-specific SDK. No Ollama-specific SDK. Just `openai` Python client or raw `httpx`.

```python
def stream(
    system: str,
    messages: list[Message],
    tools: list[dict],
    config: Config,
) -> Generator[TextChunk | AssistantMessage, None, None]:
    # Convert Message list → OpenAI format
    # POST /chat/completions with stream=True
    # Yield TextChunk for text deltas
    # Yield AssistantMessage when stream ends (with full tool_calls extracted)
```

Text-based tool fallback (for models that don't emit tool_calls JSON):
Parse ` ```tool ` blocks from the assistant text. Repair malformed JSON.
Configured per-model via `"prefer_text_tools": true` in `config.json`.

---

## Compaction (compaction.py)

Proven two-layer approach from little-coder. Clean extraction.

```python
def maybe_compact(messages: list[Message], config: Config, provider_fn) -> list[Message]:
    tokens = estimate_tokens(messages)           # chars / 3.5 heuristic
    if tokens < config.context_limit * 0.7:
        return messages
    # Layer 1: snip old tool results (no LLM call)
    messages = snip_old_results(messages)        # keep first 50% + last 25% of old results
    if estimate_tokens(messages) < config.context_limit * 0.7:
        return messages
    # Layer 2: LLM summarize old portion (real API call)
    return summarize_old(messages, config, provider_fn)
```

`estimate_tokens` is one function, one place. Not duplicated.

---

## REPL (`main.py`)

Thin shell. No business logic. ~150 lines.

```python
def repl(ctx: RunContext):
    commands = load_builtin_commands()      # /compact, /memory, /skills, /help, /agent
    skills = load_skills(".tigger/skills.md")   # loaded once

    while True:
        try:
            line = input(status_line(ctx) + "> ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not line:
            continue

        # Skill trigger check
        skill = match_skill(line, skills)
        if skill:
            line = skill.render(line)       # substitute args, inline or fork
            if skill.context == "fork":
                run_forked(line, skill, ctx)
                continue

        # Slash command
        if line.startswith("/"):
            name, _, args = line[1:].partition(" ")
            handler = commands.get(name)
            if handler:
                handler(args, ctx)
            else:
                print(f"Unknown command: /{name}")
            continue

        # Agent query
        for event in run(line, ctx):
            render_event(event, ctx)
```

Commands have a single signature: `(args: str, ctx: RunContext) -> None`. They call `run()`
directly if they need agent output. No sentinel returns, no tuple dispatch.

### Status line

Simple one-liner before each prompt:
```
[qwen3.5 · 4231/8192 tokens · ~8 msgs left] >
```

---

## Startup Sequence (`main.py`)

```
1. find_ai_dir(cwd)          → locate .tigger/ (walk up + ~/.tigger/ fallback)
2. load_config()             → parse config.json → Config (validated)
3. ToolRegistry()
4. tools.register_all(registry)
5. mcp.connect_all(registry, ".tigger/mcp.json")   → blocking, 3s timeout per server
6. hooks = load_hooks(".tigger/hooks.py")           → importlib, safe try/except
7. skills = load_skills(".tigger/skills.md")
8. agents = load_agents(".tigger/agents.md")
9. system = build_system_prompt(config, skills, memory)
10. ctx = RunContext(config, messages=[], system_prompt=system)
11. repl(ctx)
```

One clean startup sequence. No background threads. No import side-effects.
If `.tigger/hooks.py` doesn't exist, `hooks` is an empty `HookRegistry`. No error.

---

## Builtin Commands

| Command | Description |
|---------|-------------|
| `/help` | List commands and skills |
| `/compact` | Force compaction now |
| `/remember <note>` | Append to memory.md |
| memory | Show memory.md |
| `/skills` | List loaded skills |
| `/agent <name> <query>` | Run query with named agent persona |
| `/clear` | Clear message history |
| `/tokens` | Show current token usage |
| `/model <name>` | Switch model (updates ctx.config) |

Each is a standalone function ~20-40 lines. All live in their own file or in a `commands/`
submodule, not in `main.py`.

---

## What Is Explicitly Excluded

| Feature | Reason |
|---------|--------|
| Multi-provider SDK (Anthropic, Ollama SDK) | OpenAI-compat covers all targets |
| Sub-agent orchestration (worker/brainstorm) | Add via skills/agents.md when needed |
| Task management system | Out of scope; add as MCP server |
| Plugin system | `.tigger/hooks.py` and `skills.md` are sufficient |
| Cloud sync | Out of scope |
| Voice / video | Out of scope |
| Telegram integration | Out of scope |
| Proactive background daemon | Out of scope |
| AI memory consolidation | Simple append is enough |
| Deliberation / parallel branches | Add if benchmarks demand it |
| Git checkpoint hooks | Handled by user's `.tigger/hooks.py` |
| Sentinel tuple dispatch | Replaced by direct function calls |
| Import side-effect registration | Replaced by explicit `register_all()` |

---

## Key Invariants

1. **`RunContext` is the only thing that flows between modules.** Tools don't see it. Provider doesn't see it. Only the loop and hooks do.
2. **Config is frozen after startup.** No runtime mutation via dict.
3. **Hooks are middleware, not function replacement.** A hook can modify a call or result; it cannot replace the tool.
4. **Depth is capped at `config.max_depth` (default 4).** Forked skills check depth before spawning.
5. **Write refuses if file exists.** Always. Not configurable. This is a correctness invariant.
6. **`estimate_tokens` lives in one place** (compaction.py), imported everywhere else.
7. **Tool output is truncated at 32KB** inside `registry.execute()`. One place.

---

## File Budget Summary

| File | Lines | Responsibility |
|------|-------|----------------|
| main.py | ~150 | Entry, REPL, startup |write 
| provider.py | ~150 | OpenAI-compat streaming |
| tools.py | ~300 | Tool implementations + registry |
| permissions.py | ~60 | Permission gating |
| compaction.py | ~120 | Two-layer context management |
| skills.py | ~100 | Markdown skill/agent loader |
| hooks.py | ~80 | Middleware hook system |
| memory.py | ~60 | Memory read/write |
| mcp.py | ~150 | MCP client |
| **Total** | **~1550** | |
```