from io import StringIO
from rich.console import Console
from tigger.ui import SPINNER_MESSAGES, ask_permission


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
    ui_mod.render_event(event, _make_ctx(), [0], [])
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
