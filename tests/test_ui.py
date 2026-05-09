from io import StringIO
from rich.console import Console
from tigger._spinners import SPINNER_MESSAGES
from tigger.types import PermissionRequest
from tigger.ui import ask_permission


def test_spinner_messages_non_empty():
    assert len(SPINNER_MESSAGES) >= 6
    assert all(isinstance(m, str) for m in SPINNER_MESSAGES)


def test_ask_permission_returns_true_on_y(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert ask_permission(PermissionRequest("c", "bash", {"command": "ls"})) is True


def test_ask_permission_returns_false_on_n(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert ask_permission(PermissionRequest("c", "bash", {"command": "rm -rf /"})) is False


def test_ask_permission_returns_false_on_empty(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert ask_permission(PermissionRequest("c", "write", {})) is False


from tigger.ui import format_duration


def test_format_duration_short():
    assert format_duration(2.3) == "2.3s"


def test_format_duration_under_minute():
    assert format_duration(45.1) == "45.1s"


def test_format_duration_minutes():
    assert format_duration(696.2) == "11m 36s"


def test_format_duration_exact_minute():
    assert format_duration(60.0) == "1m 0s"


def test_format_duration_hour():
    assert format_duration(3720.0) == "1h 2m"


def test_format_duration_zero():
    assert format_duration(0.0) == "0.0s"


def test_print_startup_info_contains_model(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    ui_mod.print_startup_info(provider="lmstudio", model="qwen3", cwd="/home/user/project")
    out = buf.getvalue()
    assert "qwen3" in out
    assert "lmstudio" in out
    assert "/home/user/project" in out


def test_print_startup_info_contains_model_hint(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    ui_mod.print_startup_info(provider="x", model="m", cwd="/tmp")
    out = buf.getvalue()
    assert "/model" in out


from tigger.ui import _gradient_line, _LOGO_LINES


def test_gradient_line_spaces_pass_through():
    result = _gradient_line("  ABC", 5)
    assert result.startswith("  ")


def test_gradient_line_non_spaces_get_color_markup():
    result = _gradient_line("ABC", 3)
    assert "[#" in result


def test_gradient_line_leftmost_is_amber():
    # t=0 → g=179=0xb3, so color is #ffb300
    result = _gradient_line("X", 1)
    assert "[#ffb300]" in result


def test_gradient_line_rightmost_is_orange_red():
    # t=1 → g=69=0x45, so color is #ff4500
    # With max_width=2 and col=1: t = 1/(2-1) = 1.0
    result = _gradient_line("AB", 2)
    assert "[#ff4500]" in result


def test_logo_lines_constant_non_empty():
    assert len(_LOGO_LINES) == 6
    assert all(isinstance(line, str) and len(line) > 0 for line in _LOGO_LINES)


# --- recent_tools tests ---

from tigger.ui import recent_tools
from tigger.types import ToolStartEvent, RunContext, Config, TrustLevel


def _make_ctx():
    cfg = Config(base_url="http://localhost:1234/v1", model="test", api_key="local")
    return RunContext(config=cfg, messages=[], system_prompt="", trust_level=TrustLevel.ALWAYS)


def test_recent_tools_populated_on_tool_start(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    ui_mod.recent_tools.clear()
    event = ToolStartEvent(call_id="c1", name="bash", args={"command": "ls"})
    ui_mod.render_event(event, [0], [])
    assert "bash" in ui_mod.recent_tools


def test_recent_tools_max_5():
    recent_tools.clear()
    for i in range(7):
        recent_tools.append(f"tool{i}")
    assert len(recent_tools) == 5
    assert list(recent_tools) == ["tool2", "tool3", "tool4", "tool5", "tool6"]


def test_recent_tools_shown_in_toolbar():
    import tigger.ui as ui_mod
    ui_mod.recent_tools.clear()
    ui_mod.recent_tools.append("bash")
    ui_mod.recent_tools.append("write")
    from tigger.main import _toolbar
    toolbar_text = _toolbar(_make_ctx())
    assert "tools: bash, write" in toolbar_text


# --- _extract_preview tests ---

from tigger.ui import _extract_preview


def test_extract_preview_read():
    assert _extract_preview("read", {"path": "/foo/bar/baz.py"}) == "baz.py"


def test_extract_preview_grep():
    assert _extract_preview("grep", {"pattern": "load_config"}) == '"load_config"'


def test_extract_preview_glob():
    assert _extract_preview("glob", {"pattern": "**/*.py"}) == "**/*.py"


def test_extract_preview_bash_short():
    assert _extract_preview("bash", {"command": "ls -la"}) == "ls -la"


def test_extract_preview_bash_long_truncates():
    cmd = "a" * 100
    result = _extract_preview("bash", {"command": cmd})
    assert len(result) == 60
    assert result.endswith("...")


def test_extract_preview_unknown_tool_fallback():
    result = _extract_preview("unknown_tool", {"x": 1})
    assert "x=" in result


# --- _flush_tool_buffer tests ---

from tigger.ui import _flush_tool_buffer, _tool_buffer


def test_flush_tool_buffer_empty_no_output(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()
    _flush_tool_buffer()
    assert buf.getvalue() == ""


def test_flush_tool_buffer_batches_consecutive_reads(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()
    _tool_buffer.extend([("read", "a.py"), ("read", "b.py"), ("read", "c.py")])
    _flush_tool_buffer()
    out = buf.getvalue()
    assert "read:" in out
    assert "a.py, b.py, c.py" in out
    assert len(_tool_buffer) == 0


def test_flush_tool_buffer_interleaved_not_batched(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()
    _tool_buffer.extend([("read", "a.py"), ("grep", '"foo"'), ("read", "b.py")])
    _flush_tool_buffer()
    out = buf.getvalue()
    lines = [l for l in out.splitlines() if "read:" in l or "grep:" in l]
    assert len(lines) == 3


def test_flush_tool_buffer_truncates_long_batch(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()
    _tool_buffer.extend([("read", f"f{i}.py") for i in range(7)])
    _flush_tool_buffer()
    out = buf.getvalue()
    assert "(+2 more)" in out


# --- render_event integration tests ---

from tigger.types import TextChunk, ToolEndEvent, TurnDoneEvent


def test_render_event_buffers_tools_flushes_on_text(monkeypatch):
    """ToolStart events buffer; tool block appears when TextChunk arrives."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()

    ui_mod.render_event(ToolStartEvent("c1", "read", {"path": "/a/b.py"}), [0], [])
    ui_mod.render_event(ToolEndEvent("c1", "read", "ok"), [0], [])
    # No output yet — buffered.
    mid = buf.getvalue()
    assert "tools" not in mid

    ui_mod.render_event(TextChunk("hello"), [0], [])
    out = buf.getvalue()
    assert "tools" in out
    assert "b.py" in out


def test_render_event_flushes_on_turn_done(monkeypatch):
    """Tool block renders on TurnDoneEvent if no text follows."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()

    ui_mod.render_event(ToolStartEvent("c1", "bash", {"command": "ls"}), [0], [])
    ui_mod.render_event(ToolEndEvent("c1", "bash", "ok"), [0], [])
    ui_mod.render_event(TurnDoneEvent(0, 0), [0], [])
    out = buf.getvalue()
    assert "tools" in out
    assert "ls" in out


def test_render_event_batches_multiple_reads(monkeypatch):
    """Multiple consecutive reads appear as one batched line."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()

    for i, name in enumerate(["a.py", "b.py", "c.py"]):
        ui_mod.render_event(ToolStartEvent(f"c{i}", "read", {"path": f"/x/{name}"}), [0], [])
        ui_mod.render_event(ToolEndEvent(f"c{i}", "read", "ok"), [0], [])

    ui_mod.render_event(ToolStartEvent("c3", "grep", {"pattern": "foo"}), [0], [])
    ui_mod.render_event(ToolEndEvent("c3", "grep", "ok"), [0], [])

    ui_mod.render_event(TextChunk("result"), [0], [])
    out = buf.getvalue()
    # Each successful tool now carries an output summary; check files appear
    # in order even though inline (summary) markers sit between them.
    for needle in ("a.py", "b.py", "c.py"):
        assert needle in out
    assert out.index("a.py") < out.index("b.py") < out.index("c.py")
    assert '"foo"' in out


def test_render_event_no_tools_no_block(monkeypatch):
    """No tool block when there are no tool calls."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()

    ui_mod.render_event(TextChunk("hello"), [0], [])
    ui_mod.render_event(TurnDoneEvent(0, 0), [0], [])
    out = buf.getvalue()
    assert "tools" not in out


def test_render_event_no_inline_bullet(monkeypatch):
    """The old inline ⏺ format no longer appears."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()

    ui_mod.render_event(ToolStartEvent("c1", "bash", {"command": "echo hi"}), [0], [])
    out = buf.getvalue()
    assert "\u23fa" not in out  # ⏺ should not appear


def test_render_event_denied_still_inline(monkeypatch):
    """Denied tool message still prints inline."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()

    ui_mod.render_event(ToolStartEvent("c1", "bash", {"command": "rm -rf /"}), [0], [])
    ui_mod.render_event(ToolEndEvent("c1", "bash", "(denied)", permitted=False), [0], [])
    out = buf.getvalue()
    assert "(denied)" in out


def test_render_event_error_still_inline(monkeypatch):
    """Error output still prints inline."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()

    ui_mod.render_event(ToolStartEvent("c1", "bash", {"command": "bad"}), [0], [])
    ui_mod.render_event(ToolEndEvent("c1", "bash", "command not found", error=True), [0], [])
    out = buf.getvalue()
    assert "command not found" in out


def test_render_event_successful_tool_end_stops_activity(monkeypatch):
    """A final successful tool call must not leave the live activity indicator running."""
    import tigger.ui as ui_mod
    stops: list[bool] = []
    monkeypatch.setattr(ui_mod, "_start_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui_mod, "_stop_activity", lambda: stops.append(True))
    _tool_buffer.clear()

    ui_mod.render_event(ToolStartEvent("c1", "write", {"path": "/tmp/x"}), [0], [])
    ui_mod.render_event(ToolEndEvent("c1", "write", "Written: /tmp/x"), [0], [])

    assert stops


def test_render_event_recent_tools_still_updated(monkeypatch):
    """recent_tools deque still gets updated on ToolStartEvent."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()
    ui_mod.recent_tools.clear()

    ui_mod.render_event(ToolStartEvent("c1", "read", {"path": "/a.py"}), [0], [])
    assert "read" in ui_mod.recent_tools


# --- ThinkingEvent and activity status tests ---

from tigger.types import ThinkingEvent
from tigger.ui import _start_activity, _stop_activity, _tool_counter_message


def test_thinking_event_starts_spinner(monkeypatch):
    """ThinkingEvent starts an activity spinner."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()
    ui_mod._stop_activity()

    ui_mod.render_event(ThinkingEvent(), [0], [])
    assert ui_mod._activity_status is not None
    ui_mod._stop_activity()


def test_thinking_event_flushes_tool_buffer(monkeypatch):
    """ThinkingEvent flushes any pending tool buffer before starting spinner."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()
    ui_mod._tool_call_ids.clear()
    ui_mod._tool_summaries.clear()
    ui_mod._stop_activity()

    _tool_buffer.extend([("read", "a.py"), ("read", "b.py")])
    ui_mod.render_event(ThinkingEvent(), [0], [])
    out = buf.getvalue()
    assert "tools" in out
    assert "a.py, b.py" in out
    assert len(_tool_buffer) == 0
    ui_mod._stop_activity()


def test_text_chunk_stops_thinking_spinner(monkeypatch):
    """TextChunk stops the thinking spinner."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()
    ui_mod._stop_activity()

    ui_mod.render_event(ThinkingEvent(), [0], [])
    assert ui_mod._activity_status is not None
    ui_mod.render_event(TextChunk("hello"), [0], [])
    assert ui_mod._activity_status is None


def test_tool_start_shows_counter(monkeypatch):
    """ToolStartEvent starts an activity counter showing tool count."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    _tool_buffer.clear()
    ui_mod._stop_activity()

    ui_mod.render_event(ToolStartEvent("c1", "read", {"path": "/a.py"}), [0], [])
    assert ui_mod._activity_status is not None
    ui_mod.render_event(ToolStartEvent("c2", "read", {"file_path": "/b.py"}), [0], [])
    assert ui_mod._activity_status is not None
    ui_mod._stop_activity()


def test_tool_counter_message_format():
    """_tool_counter_message produces expected format."""
    _tool_buffer.clear()
    _tool_buffer.extend([("read", "a.py"), ("read", "b.py"), ("grep", '"foo"')])
    msg = _tool_counter_message()
    assert "3 tools" in msg
    assert "read\u00d72" in msg  # read×2
    assert "grep" in msg
    _tool_buffer.clear()


def test_tool_counter_message_single():
    """Single active tool shows its preview Claude-style: ⏺ Bash(ls)."""
    _tool_buffer.clear()
    _tool_buffer.append(("bash", "ls"))
    msg = _tool_counter_message()
    assert "Bash(ls)" in msg
    _tool_buffer.clear()


def test_tool_counter_message_single_no_preview():
    """Single tool with empty preview just shows the capitalized name."""
    _tool_buffer.clear()
    _tool_buffer.append(("read", ""))
    msg = _tool_counter_message()
    assert "Read" in msg
    assert "()" not in msg
    _tool_buffer.clear()


def test_loop_yields_thinking_event():
    """The agent loop yields ThinkingEvent before looping back for another model call."""
    from tigger.loop import run
    from tigger.tools import ToolRegistry
    from tigger.types import AssistantMessage, ToolCallRecord, Config, RunContext, TrustLevel

    registry = ToolRegistry()
    from tigger.types import ToolDef
    registry.register(ToolDef(
        name="test_tool", description="test", parameters={},
        func=lambda args: "ok", read_only=True,
    ))

    call_count = [0]

    def fake_provider(system, messages, tools, config):
        call_count[0] += 1
        if call_count[0] == 1:
            yield AssistantMessage(
                content="calling tool",
                tool_calls=[ToolCallRecord(call_id="c1", name="test_tool", args={})],
            )
        else:
            yield TextChunk("done")
            yield AssistantMessage(content="done", tool_calls=[])

    cfg = Config(base_url="http://localhost:1234/v1", model="test", api_key="local")
    ctx = RunContext(config=cfg, messages=[], system_prompt="", trust_level=TrustLevel.ALWAYS)

    events = list(run("test", ctx, registry, provider_fn=fake_provider))
    event_types = [type(e).__name__ for e in events]
    assert "ThinkingEvent" in event_types


# --- inline <think> handling ---


def test_split_think_extracts_blocks():
    from tigger.ui import _split_think
    segs = _split_think("<think>reasoning</think>\n\nfinal answer")
    assert segs == [("think", "reasoning"), ("text", "final answer")]


def test_split_think_no_tags():
    from tigger.ui import _split_think
    segs = _split_think("just a plain answer")
    assert segs == [("text", "just a plain answer")]


def test_split_think_only_tags():
    from tigger.ui import _split_think
    segs = _split_think("<think>just thinking</think>")
    assert segs == [("think", "just thinking")]


def test_flush_text_renders_think_visibly(monkeypatch):
    """Inline <think>...</think> must not be swallowed by Markdown."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(
        ui_mod,
        "console",
        Console(file=buf, width=80, highlight=False, markup=True),
    )
    text_buf = ["<think>I should answer 289.</think>\n\nThe answer is **289**."]
    ui_mod._flush_text(text_buf)
    out = buf.getvalue()
    assert "I should answer 289." in out  # think is visible (was swallowed before)
    assert "289" in out  # final answer still rendered
    assert text_buf == []


def test_flush_text_skips_empty_segments(monkeypatch):
    """Whitespace-only segments don't print empty lines."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(
        ui_mod,
        "console",
        Console(file=buf, width=80, highlight=False, markup=True),
    )
    ui_mod._flush_text(["<think>   </think>\n\n"])
    out = buf.getvalue().strip()
    assert out == ""


# --- permission prompt rendering ---


def test_ask_permission_uses_panel(monkeypatch):
    """ask_permission should render a bordered panel, not raw repr(args)."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(
        ui_mod,
        "console",
        Console(file=buf, width=80, highlight=False, markup=True, force_terminal=False),
    )
    monkeypatch.setattr("builtins.input", lambda _: "y")
    huge = "x" * 5000
    ask_permission(PermissionRequest("c", "write", {"path": "/tmp/foo.py", "content": huge}))
    out = buf.getvalue()
    assert "╭" in out and "╯" in out          # panel borders rendered
    assert huge not in out                    # 5KB content not splatted into prompt
    assert "Write" in out                      # tool name capitalized in title
    assert "foo.py" in out                     # path shown


def test_extract_preview_write_returns_basename():
    """write/edit previews should show just the basename, not the content."""
    from tigger.ui import _extract_preview
    assert _extract_preview("write", {"path": "src/a/b.py", "content": "x" * 99}) == "b.py"
    edit_args = {"path": "/tmp/x.py", "old_string": "a", "new_string": "b"}
    assert _extract_preview("edit", edit_args) == "x.py"


# --- streaming text via Rich Live ---


def test_text_chunks_stream_visibly_via_live(monkeypatch):
    """TextChunks should produce buffer growth chunk-by-chunk (Live), not only at flush."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(
        ui_mod,
        "console",
        Console(file=buf, width=80, force_terminal=True, highlight=False),
    )
    ui_mod._tool_buffer.clear()
    ui_mod._live = None
    text_buf = []

    chunks = ["Hello", " world", "!"]
    growths = []
    for c in chunks:
        before = len(buf.getvalue())
        ui_mod.render_event(TextChunk(c), [0], text_buf)
        if ui_mod._live is not None:
            ui_mod._live.refresh()
        growths.append(len(buf.getvalue()) - before)

    # Every chunk should have produced output, not just the last flush.
    assert all(g > 0 for g in growths), f"streaming did not grow per chunk: {growths}"
    assert "Hello world!" in buf.getvalue().replace("\x1b[2K", "")
    ui_mod.render_event(TurnDoneEvent(0, 0), [0], text_buf)
    assert ui_mod._live is None  # Live cleaned up at flush


def test_flush_text_without_live_renders_explicitly(monkeypatch):
    """When _flush_text is called directly (no live running), it still renders."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(
        ui_mod,
        "console",
        Console(file=buf, width=80, highlight=False),
    )
    ui_mod._live = None
    ui_mod._flush_text(["hello world"])
    assert "hello world" in buf.getvalue()


# --- tool output summary ---


def test_summarize_tool_output_lines():
    from tigger.ui import _summarize_tool_output
    out = "\n".join(["x"] * 421)
    assert _summarize_tool_output("read", out) == "421 lines"


def test_summarize_tool_output_grep_uses_matches():
    from tigger.ui import _summarize_tool_output
    assert _summarize_tool_output("grep", "a:1\nb:2\nc:3") == "3 matches"


def test_summarize_tool_output_glob_uses_files():
    from tigger.ui import _summarize_tool_output
    assert _summarize_tool_output("glob", "a.py\nb.py") == "2 files"


def test_summarize_tool_output_single_line_returned_verbatim():
    from tigger.ui import _summarize_tool_output
    assert _summarize_tool_output("bash", "    661 ui.py") == "661 ui.py"


def test_summarize_tool_output_truncates_long_single_line():
    from tigger.ui import _summarize_tool_output
    long = "x" * 200
    s = _summarize_tool_output("bash", long)
    assert s.endswith("...")
    assert len(s) <= 60


def test_summarize_tool_output_empty_returns_empty():
    from tigger.ui import _summarize_tool_output
    assert _summarize_tool_output("read", "") == ""
    assert _summarize_tool_output("read", "\n\n") == ""


def test_tool_end_attaches_summary_to_buffered_entry(monkeypatch):
    """ToolEnd's output summary should land in the buffered entry."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    ui_mod._tool_buffer.clear()
    ui_mod._tool_call_ids.clear()
    ui_mod._tool_summaries.clear()

    ui_mod.render_event(ToolStartEvent("c1", "read", {"path": "a.py"}), [0], [])
    ui_mod.render_event(ToolEndEvent("c1", "read", "\n".join(["x"] * 50)), [0], [])
    ui_mod.render_event(TextChunk("done"), [0], [])

    out = buf.getvalue()
    assert "a.py" in out
    assert "(50 lines)" in out


def test_startup_info_includes_help_tip(monkeypatch):
    """Startup tip line should mention /help so new users discover commands."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=True))
    ui_mod.print_startup_info(provider="lmstudio", model="qwen3", cwd="/tmp/x")
    out = buf.getvalue()
    assert "/help" in out
    assert "tip" in out.lower()


# --- edit diff rendering ---


def test_make_edit_diff_basic():
    from tigger.ui import _make_edit_diff
    diff = _make_edit_diff({
        "path": "foo.py",
        "old_string": "a\nb\nc",
        "new_string": "a\nB\nc",
    })
    assert "@@" in diff
    assert "-b" in diff
    assert "+B" in diff
    assert "foo.py" not in diff  # header dropped


def test_make_edit_diff_no_change_returns_empty():
    from tigger.ui import _make_edit_diff
    assert _make_edit_diff({"path": "x", "old_string": "x", "new_string": "x"}) == ""


def test_make_edit_diff_truncates_long_diffs():
    from tigger.ui import _make_edit_diff
    old = "\n".join(f"line{i}" for i in range(50))
    new = "\n".join(f"NEW{i}" for i in range(50))
    diff = _make_edit_diff({"path": "x", "old_string": old, "new_string": new}, max_lines=10)
    assert "more diff lines" in diff
    assert diff.count("\n") <= 10  # capped


def test_render_diff_lines_colorises():
    from tigger.ui import _render_diff_lines
    out = _render_diff_lines("@@ -1,2 +1,2 @@\n-old\n+new\n context")
    assert any("[green]" in line and "+new" in line for line in out)
    assert any("[red]" in line and "-old" in line for line in out)
    assert any("[cyan]" in line and "@@" in line for line in out)


def test_edit_tool_end_renders_diff_in_flush(monkeypatch):
    """A successful edit's diff should appear under its buffered entry."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(
        ui_mod, "console",
        Console(file=buf, width=80, highlight=False, markup=True, force_terminal=False),
    )
    ui_mod._tool_buffer.clear()
    ui_mod._tool_call_ids.clear()
    ui_mod._tool_summaries.clear()
    ui_mod._tool_details.clear()

    ui_mod.render_event(
        ToolStartEvent("c1", "edit",
                       {"path": "x.py", "old_string": "foo\nbar", "new_string": "foo\nBAR"}),
        [0], [],
    )
    ui_mod.render_event(ToolEndEvent("c1", "edit", "Edited x.py"), [0], [])
    ui_mod.render_event(TextChunk("done"), [0], [])
    out = buf.getvalue()
    assert "edit:" in out
    assert "-bar" in out
    assert "+BAR" in out


def test_edit_tool_failure_drops_diff(monkeypatch):
    """A failed edit must not leave its diff dangling in the next flush."""
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(
        ui_mod, "console",
        Console(file=buf, width=80, highlight=False, markup=True, force_terminal=False),
    )
    ui_mod._tool_buffer.clear()
    ui_mod._tool_call_ids.clear()
    ui_mod._tool_summaries.clear()
    ui_mod._tool_details.clear()

    ui_mod.render_event(
        ToolStartEvent("c1", "edit",
                       {"path": "x.py", "old_string": "foo", "new_string": "bar"}),
        [0], [],
    )
    ui_mod.render_event(
        ToolEndEvent("c1", "edit", "Error: not found", error=True),
        [0], [],
    )
    ui_mod.render_event(TextChunk("done"), [0], [])
    out = buf.getvalue()
    # No green/red diff bodies leaked into the flush
    assert "+bar" not in out
    assert "-foo" not in out
