from io import StringIO
from rich.console import Console
from tigger._spinners import SPINNER_MESSAGES
from tigger.ui import ask_permission


def test_spinner_messages_non_empty():
    assert len(SPINNER_MESSAGES) >= 6
    assert all(isinstance(m, str) for m in SPINNER_MESSAGES)


def test_ask_permission_returns_true_on_y(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert ask_permission("bash", {"command": "ls"}) is True


def test_ask_permission_returns_false_on_n(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert ask_permission("bash", {"command": "rm -rf /"}) is False


def test_ask_permission_returns_false_on_empty(monkeypatch):
    import tigger.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert ask_permission("write", {}) is False


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

from tigger.types import TextChunk, ToolEndEvent, TurnDoneEvent, PermissionEvent


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
    assert "a.py, b.py, c.py" in out
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
    """Single tool shows singular 'tool'."""
    _tool_buffer.clear()
    _tool_buffer.append(("bash", "ls"))
    msg = _tool_counter_message()
    assert "1 tool " in msg
    assert "bash" in msg
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
