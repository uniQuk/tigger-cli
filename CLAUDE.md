# Project conventions for AI agents

> Read this before iterating on tigger-code. It captures load-bearing
> patterns established across 82 polish iterations (see
> `private-docs/tui-polish-iterations.md` for the full retrospective).

## Codebase layout

```
src/tigger/
├── _constants.py   ← app identity + config paths
├── main.py         ← entry point + REPL
├── loop.py         ← agent loop generator
├── types.py        ← all dataclasses + events
├── config.py       ← config loader + validation
├── provider.py     ← OpenAI-compat streaming client
├── tools.py        ← tool implementations + registry
├── permissions.py  ← permission gating
├── compaction.py   ← context window management
├── skills.py       ← skill/agent markdown loader
├── hooks.py        ← hook middleware system
├── memory.py       ← memory read/write
├── mcp.py          ← MCP client
├── ui.py           ← all rendering — Rich theme lives here
└── commands/       ← one file per slash command (themed via ui.console)
```

## Rich theming conventions (load-bearing)

Every user-visible surface routes through `ui.console.print` with a
unified colour palette:

| Element | Colour | Examples |
|---|---|---|
| Slash commands (`/cmd`) | cyan | `/help`, `/compact` |
| CLI flags (`--flag`) | cyan | `--once`, `--no-think` |
| Named entities (skills, agents, providers, hooks, tools) | magenta | `review`, `lmstudio`, `bash` |
| Field labels in panels (`Mode:`, `Path:`) | dim | `Mode:` `act` |
| Successful-action prefix | dim `✓` | `✓ Resumed`, `✓ Mode set to` |
| Triggers, captured patterns | yellow | `"foo"`, `(disabled)` |
| Errors / serious failures | red | error bodies, panels |
| Warnings | yellow | `[mcp] Warning:`, `[hooks] Warning:` |
| Notice glyph (skill/file/summary load) | dim `↪` `↳` `↺` | `↪ skill: review` |
| Interrupt glyph | yellow `↩` | `↩ interrupted · 4m 5s` |
| Tool-call indicator | gray `⏺` | `⏺ Read(loop.py)` |
| Tool-output prefix | dim `⎿` | `⎿ bash: command not found` |

### Threshold colour-coding

Used for context %, success rate, RTK savings:

| % | Colour |
|---|---|
| 0–49 | green |
| 50–79 | yellow |
| 80–100 | red |

## Markup escaping (gotcha)

To pass a literal `[` through Rich's markup parser, the **rendered string**
must contain `\[`. To get `\[` from a Python source string, you need
**two** backslashes: `"\\[mcp]"`. Single-backslash `"\[mcp]"` triggers
`SyntaxWarning: invalid escape sequence` on Python 3.12+ and the literal
`\` may or may not survive depending on Python version.

```python
# ✗ wrong — SyntaxWarning, fragile literal
console.print(f"[dim]\[mcp] connected[/dim]")

# ✓ right — explicit double-backslash
console.print(f"[dim]\\[mcp] connected[/dim]")

# ✓ also right — raw string
console.print(rf"[dim]\[mcp] connected[/dim]")
```

This caught us in iter 41/82 — `mcp.py` had 11 sites with the wrong
form. Always use `\\[` in normal Python strings.

## Indent for startup-banner content

Welcome content (logo, cat, model line, `tip:`) is left-padded **6 spaces**
to align under the gradient logo. Any startup notice that prints alongside
should match:

```python
console.print(f"      [dim]\\[mcp] connected:[/dim] [magenta]{names}[/magenta]")
console.print(f"      [yellow]\\[hooks] Warning:[/yellow] {msg}")
console.print( "      [dim]↺ recent session context loaded[/dim]")
```

Runtime notices (during a turn or after) start at column 0:

```python
ui.console.print(f"\n[yellow]↩ interrupted[/yellow] [dim]· {parts}[/dim]")
```

## Helpers (not sys-imports)

These are **module-level utilities** in `ui.py` that other modules import
when they need to render in the unified theme:

| Helper | Purpose |
|---|---|
| `_short_tool_name(name)` | `mcp__server__tool` → `server.tool` for spinner / flush / summary |
| `format_session_id(stem)` | `YYYYMMDD-HHMMSS` → `Mon DD, HH:MM` |
| `format_duration(secs)` | `4.5s` / `5m 12s` / `1h 4m` |
| `_extract_preview(name, args)` | Compact preview for tool spinner / flush / permission panel |
| `_summarize_tool_output(name, output)` | `(N lines)` / `(N matches)` / `(N files)` / single-line verbatim |
| `_make_edit_diff(args)` | Unified diff for `edit` tool, capped to 20 lines |
| `_make_output_preview(output)` | First 5 lines of bash output, capped at 100 chars/line |
| `_render_indented_block(text)` | Picks diff colouring vs plain dim based on content |
| `_split_think(text)` | Pull `<think>...</think>` blocks (incl. mid-stream open tags) out of text |
| `_build_text_renderable(text)` | Group of segments for Rich Live streaming |
| `_stop_live()` / `_reset_tool_buffer()` | Resource cleanup on exception paths |
| `print_error_panel(title, msg, hint=None)` | Red bordered panel for serious errors |

When you add a new render path, **prefer composing existing helpers**
over re-implementing the styling. The audit trail in
`private-docs/tui-polish-iterations.md` shows which surfaces use which
helper.

## Slash command pattern

```python
def cmd_foo(args: str, ctx: RunContext) -> None:
    from tigger.ui import console  # lazy import — keeps import-time cycles out

    if not args.strip():
        # Status display
        console.print(f"[bold]Foo:[/bold] [cyan]{ctx.config.foo}[/cyan]")
        return

    # Validate
    if args.strip() not in VALID_VALUES:
        console.print(
            f"[red]Invalid foo[/red] {args.strip()!r}. "
            f"[dim]Try:[/dim] {', '.join(VALID_VALUES)}"
        )
        return

    # Mutate via dataclasses.replace — never assign to ctx.config attributes
    ctx.config = dataclasses.replace(ctx.config, foo=args.strip())
    console.print(f"[dim]✓ Foo set to[/dim] [cyan]{args.strip()}[/cyan]")
```

Then register in `commands/__init__.py`:
- Add a one-line description to `COMMAND_DESCRIPTIONS` (shown in `/help`).
- Add a multi-line usage block to `COMMAND_HELP` (shown by `/help <name>`).
  References to `/cmd` and `--flag` are auto-highlighted by iter 50's regex.
- Wire into the dispatcher dict in `load_builtin_commands`.

## Testing

```bash
make test         # pytest tests/ -q
make test-v       # verbose
```

807+ tests as of iter 82. Test patterns:

- **`tests/test_ui.py`** — direct calls into `ui.py` helpers + render_event
  with synthesized events. Capture via `monkeypatch.setattr(ui_mod, "console", Console(file=buf))`.
- **`tests/test_headless.py`** — `--once` mode end-to-end with mocked startup.
  Includes the iter-81 REPL harness (force `prompt_toolkit` ImportError +
  mock `input()`).
- **Slash command tests** — one test file per command, asserts on
  `capsys.readouterr().out` (warnings now route through stdout via
  `ui.console`, not `sys.stderr`, since iter 67-70).

When you add a new themed surface, cover both the happy path and the
error path. Threshold-based colouring (50%/80%) deserves a test per band.

## --once contract

Iter 47 codified the contract:

```bash
tigger-code --once "..."
```

- **stdout**: model's answer, exactly one trailing `\n` (no double-newline)
- **stderr**: warnings and notices (compaction, stall watchdog, errors)
- **exit code**: 0 (ok) / 1 (empty) / 2 (network/provider) / 130 (SIGINT)
- **welcome banner**: silenced (no logo, no MCP notice, no tip)

Don't break this. If you add a new failure mode, pick the right exit code
and route the message to stderr.

## What NOT to do

- **Don't `print()` directly** to stdout from any module. Always go through
  `ui.console.print` — even for warnings (route to stdout, the test suite
  expects `captured.out + captured.err` for the audit-style warnings from
  iters 67-70).
- **Don't introduce new `[tag]` literals without escaping**. Always use
  `\\[tag]` (see Markup escaping above).
- **Don't add new `Notice`-style events** without considering whether they
  belong on stderr (operational, like compaction) or stdout (user-facing,
  like skill match).
- **Don't break the iter-47 contract** for `--once`. Scripting consumers
  rely on `0/1/2/130`.
- **Don't import Rich at module top-level in `loop.py` / `mcp.py` /
  `parsing.py`**. The lazy `from tigger.ui import console` inside functions
  keeps these modules independently importable for tests.

## Where to start

If a fresh agent picks up the work:

1. `tigger-code --once "ping"` — confirm the baseline is intact.
2. `tigger-code --help` — see the full surface in one screen.
3. `private-docs/tui-polish-iterations.md` — full retrospective (82 iters).
4. `make test` — should be green at 800+.
5. Then iterate. Prefer **functional gaps** over more cosmetic polish.
