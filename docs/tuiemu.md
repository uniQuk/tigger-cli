# TUI Input Area: Resize Handling Research

## The Problem

Tigger CLI renders full-width horizontal rules (`─` * cols) and a bottom toolbar around the input prompt using prompt_toolkit. When the terminal is resized, the terminal emulator reflows these characters, corrupting prompt_toolkit's cursor position tracking and causing prompt duplication.

This is a **confirmed upstream bug** ([prompt-toolkit #1933](https://github.com/prompt-toolkit/python-prompt-toolkit/issues/1933), Oct 2024, OPEN) with no fix. Related issues: #932 (2019), #29 (2014), #636 (2018).

### Root Cause

```
1. Terminal shrinks → emulator reflows full-width content (wraps to 2+ lines)
2. prompt_toolkit's _on_resize() calls renderer.erase()
3. erase() does cursor_up(stale_y) — but actual cursor moved due to reflow
4. Erases from wrong position → old prompt remains, new one draws below
5. Result: stacked duplicate prompts
```

Additionally, the renderer's height calculation uses `max(min_available_height, last_height, preferred_height)` — the `last_height` term means the rendered area **never shrinks**, causing a persistent gap between the prompt and the bottom toolbar.

---

## How Other Tools Handle This

| Tool | Stack | Approach |
|------|-------|----------|
| **Aider** | prompt_toolkit + Rich | No full-width decorations at all. Simple `> ` prompt, no toolbar, no rules. Sidesteps the problem entirely. |
| **IPython** | prompt_toolkit | No bottom_toolbar. Simple prompt. No explicit resize handling. |
| **Claude Code** | Ink (React for CLI) | Full-screen rendering. Owns the entire terminal. |
| **Qwen CLI** | N/A | Doesn't exist as a terminal tool (uses Gradio web UI). |

---

## Options Evaluated

### Option A: Accept the Limitation (Recommended)

Remove full-width content from prompt_toolkit's managed area. Print rules/toolbar as scrollback.

- **Effort**: Already done
- **Resize**: Works perfectly (managed area is just `❯ `, 2 chars)
- **Tradeoff**: Rules in scrollback wrap on resize (cosmetic only). No live toolbar.
- **This is what Aider and IPython do.**

### Option B: Keep Toolbar with Gap Fix

Keep `bottom_toolbar` but fix the gap using Questionary's `dont_extend_height` trick + `reserve_space_for_menu=0`:

```python
from prompt_toolkit.filters import Always

session = PromptSession(
    bottom_toolbar=toolbar_fn,
    reserve_space_for_menu=0,  # Reduces gap from completion menu reservation
)

# Fix the buffer window to not extend height (closes the gap)
try:
    buf_window = session.layout.container.get_children()[0].content.get_children()[1].content
    buf_window.dont_extend_height = Always()
except (IndexError, AttributeError):
    pass  # Fail silently if layout structure changes
```

Combine with `_on_resize = lambda: None` to prevent duplication. Toolbar stays at stale width during resize, corrects on next prompt cycle.

- **Effort**: ~30 min
- **Resize**: No duplication. Toolbar at stale width until next prompt cycle.
- **Tradeoff**: Fragile layout tree navigation. Toolbar doesn't resize live.

### Option C: Short Decorations (< 30 chars)

Use partial-width decorations that can never wrap:

```python
def _get_input():
    ui.console.print("[dim]───[/dim]")  # Short rule, never wraps
    return _session.prompt("❯ ", bottom_toolbar=short_toolbar)
```

- **Effort**: ~30 min
- **Resize**: Works if ALL managed content stays under ~30 chars
- **Tradeoff**: Rules don't span full width. Less visually impactful.

### Option D: Raw ANSI + readline

Replace prompt_toolkit with Python's readline + manual ANSI escape codes + SIGWINCH handler:

```python
import signal, shutil, readline

def draw_chrome():
    cols = shutil.get_terminal_size().columns
    sys.stdout.write(f"\033[s\033[1A\033[2K\033[90m{'─' * cols}\033[0m\033[u")
    sys.stdout.flush()

signal.signal(signal.SIGWINCH, lambda s, f: draw_chrome())
line = input("❯ ")
```

- **Effort**: 2-3 hours
- **Resize**: Correct (readline is battle-tested C code)
- **Tradeoff**: Lose dropdown completions, placeholder text, styled prompts. Basic tab completion only.

### Option E: Textual Inline Mode (Future)

Textual's `app.run(inline=True)` renders below the cursor without taking over the screen. Handles resize correctly.

- **Effort**: High (build custom input widget)
- **Resize**: Correct
- **Tradeoff**: ~724 KB dependency. Inline mode immature. No built-in history/completion. Not Windows-compatible in inline mode.
- **Status**: Monitor for future versions. Not actionable today.

### Option F: Textual Inline Mode — Deep Assessment

Textual (35.5k stars, v8.2.4, very active) supports `app.run(inline=True)`. Handles resize correctly. Beautiful CSS theming. But the tradeoffs are significant.

#### What You'd Gain
- Correct resize with full-width rules and toolbars
- CSS theming (amber/orange theme trivially via CSS)
- Mouse support, borders, proper layout engine
- Elia (LLM chat TUI) proves the pattern works

#### The Showstopper: Rich Coexistence

**You cannot mix `console.print()` with a running Textual app.** Textual owns the terminal while running. This forces two paths:

**Path 1: Run-exit-run cycle** — Mount Textual for input, exit it, print LLM output with Rich, mount again. Each cycle sets up/tears down an asyncio event loop. Causes visible flicker. Spinner during inference can't be Textual (app is dead).

**Path 2: Full Textual rewrite** — Move ALL rendering into Textual widgets (RichLog, Markdown). Rewrite `ui.py` (~340 lines of Rich rendering). This is what Elia does — it's a full Textual app, not a hybrid.

#### What You'd Lose / Rebuild

| Feature | prompt_toolkit | Textual |
|---------|---------------|---------|
| Command history (up/down) | Built-in `FileHistory` | **DIY** — not built-in ([Discussion #5041](https://github.com/Textualize/textual/discussions/5041)) |
| Tab completion (dropdown) | Built-in `Completer` | 3rd-party `textual-autocomplete` or `Suggester` (inline ghost text only) |
| Rich spinner during inference | `console.status()` works | Must be a Textual widget (or exit Textual first) |
| Windows support | Yes | **No inline mode on Windows** ([#4409](https://github.com/Textualize/textual/issues/4409)) |

#### Dependency Weight

| | prompt_toolkit | textual (extra) |
|---|---|---|
| Wheel | 391 KB | 724 KB |
| Real extra weight | — | ~330 KB (Rich already installed) |
| Startup import | ~115ms | ~200-400ms estimated |

#### Inline Mode Maturity

Introduced v0.55.0 (March 2024). ~2 years old. Has received multiple bug fixes for `inline_no_clear` output being garbled. Known issues: command palette broken in inline ([#4385](https://github.com/Textualize/textual/issues/4385)), no Windows ([#4409](https://github.com/Textualize/textual/issues/4409)). Secondary mode — most Textual apps are fullscreen. Less real-world testing.

#### Verdict

**Don't replace just the input layer.** The Rich coexistence problem is fatal for a "swap the input widget" approach. Textual only makes sense as a **full rewrite** (Elia-style), which gives genuine benefits (layout, CSS, mouse, panels) but is a multi-week effort. Worth considering for a v2 if you want to go full TUI.

---

## Libraries Evaluated and Rejected

| Library | Stars | Last Release | Why Not |
|---------|-------|-------------|---------|
| **cmd2** | 687 | v3.5.0 (Apr 2026) | **Uses prompt_toolkit internally**. Inherits the same resize bug (#1933). Adds command-dispatch framework overhead we don't need. |
| **Pygments** | 12.5k | Active | **Not an input library.** Syntax highlighting only. Already available as a Rich dependency. |
| **click / click-repl** | — | Active | **Uses prompt_toolkit internally.** Same resize bug. |
| **rich.prompt** | — | Active | Too limited. No history, no completion, no toolbar. Essentially `input()` with validation. |
| **questionary** | 1.8k | v2.1.1 (Aug 2025) | **Built on prompt_toolkit.** Same resize bug. Designed for one-shot prompts, not REPL loops. |
| **InquirerPy** | 431 | v0.3.4 (Jun 2022) | **Dead project.** Built on prompt_toolkit. Same resize bug. |
| **prompt_toolkit full_screen** | — | — | Alternate screen buffer has no scrollback. Would need to rebuild a terminal emulator inside a terminal. |
| **Alt-screen toggle** | — | — | User types blind (alt-screen clears visible terminal). |
| **urwid** | 3k | v4.0.0 (Active) | Takes over full terminal. No inline mode. Would replace both Rich and prompt_toolkit. Full rewrite. |
| **py_cui** | — | v0.1.6 (2021) | Dead project. Curses-based, wrong paradigm. |
| **blessed** | 3k | v1.30.0 (Stable) | No input editing. Only `inkey()` character-at-a-time. Useful as a helper but can't replace prompt_toolkit. |
| **curses** | stdlib | — | Full-screen only. No high-level input widgets. Enormous effort for minimal gain. |

**Key finding:** cmd2, click-repl, questionary, and InquirerPy all wrap prompt_toolkit — they inherit the exact same resize bug.

---

## Summary Comparison

| Approach | Resize? | History | Completion | Toolbar | Rules | Effort |
|----------|---------|---------|------------|---------|-------|--------|
| **A: Scrollback rules, no pt toolbar** | Yes | Yes | Yes | Scrollback | Scrollback | Done |
| **B: pt toolbar + gap fix** | No duplication* | Yes | Yes | Yes | Scrollback | 30 min |
| **C: Short decorations** | Yes | Yes | Yes | Short only | Short | 30 min |
| **D: Raw readline + ANSI** | Yes | Basic | Basic | DIY | Yes | 2-3 hrs |
| **F: Textual inline** | Yes | DIY | DIY | Yes | Yes | Days |

*Toolbar at stale width during resize, corrects on next prompt cycle.

---

## Recommendation

**Option A + B combined**: Keep the current scrollback approach for rules, but restore the bottom toolbar with the gap fix applied. This gives:

```
──────────────────  (scrollback — top rule, wraps on resize but harmless)
 model  mode  ctx%  (scrollback — toolbar info)  
❯ Type your message  (prompt_toolkit managed — just the prompt)
```

Or with Option B's gap fix:

```
❯ Type your message  (prompt_toolkit managed)
 model  mode  ctx%  (bottom_toolbar — no gap, stale width on resize)
```

The `_on_resize = lambda: None` workaround prevents duplication. The `dont_extend_height + reserve_space_for_menu=0` fixes eliminate the gap. The toolbar displays at stale width during resize and corrects on the next prompt cycle.

For the top rule, print it as scrollback before `prompt()`. It wraps on resize but that's purely cosmetic in scrollback — it doesn't affect prompt_toolkit's cursor tracking.

---

## References

### Upstream Bugs
- [prompt-toolkit #1933](https://github.com/prompt-toolkit/python-prompt-toolkit/issues/1933) — Resize duplication (OPEN, Oct 2024)
- [prompt-toolkit #932](https://github.com/prompt-toolkit/python-prompt-toolkit/issues/932) — Resize random behavior (2019)
- [prompt-toolkit #29](https://github.com/prompt-toolkit/python-prompt-toolkit/issues/29) — OSX resize weirdness (2014)
- [prompt-toolkit #655](https://github.com/prompt-toolkit/python-prompt-toolkit/issues/655) — Toolbar disable leaves empty line
- [prompt-toolkit #777](https://github.com/prompt-toolkit/python-prompt-toolkit/issues/777) — HSplit gaps

### Workarounds and Patterns
- [Questionary dont_extend_height fix](https://questionary.readthedocs.io/en/1.9.0/_modules/questionary/prompts/common.html)
- [IPython terminal shell](https://github.com/ipython/ipython/blob/main/IPython/terminal/interactiveshell.py) — No toolbar, no resize issues
- [Aider io.py](https://github.com/paul-gauthier/aider) — No full-width decorations

### Alternative Libraries
- [Textual inline mode](https://textual.textualize.io/blog/2024/04/20/behind-the-curtain-of-inline-terminal-applications/)
- [Textual #5041](https://github.com/Textualize/textual/discussions/5041) — Input history discussion
- [Textual #4409](https://github.com/Textualize/textual/issues/4409) — Inline mode Windows support
- [Elia](https://github.com/darrenburns/elia) — Textual-based LLM chat TUI (real-world example)
- [cmd2](https://github.com/python-cmd2/cmd2) — Uses prompt_toolkit internally
- [urwid](https://github.com/urwid/urwid) — Full-screen TUI, no inline mode
