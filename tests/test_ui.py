from io import StringIO
from rich.console import Console
from newcli.ui import SPINNER_MESSAGES, print_status, ask_permission


def test_spinner_messages_non_empty():
    assert len(SPINNER_MESSAGES) >= 6
    assert all(isinstance(m, str) for m in SPINNER_MESSAGES)


def test_print_status_contains_model_and_tokens(monkeypatch):
    import newcli.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    print_status(model="qwen3", used=100, limit=8192, mode="ask", permission="allow")
    out = buf.getvalue()
    assert "qwen3" in out
    assert "100" in out
    assert "8192" in out


def test_ask_permission_returns_true_on_y(monkeypatch):
    import newcli.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert ask_permission("bash", {"command": "ls"}) is True


def test_ask_permission_returns_false_on_n(monkeypatch):
    import newcli.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert ask_permission("bash", {"command": "rm -rf /"}) is False


def test_ask_permission_returns_false_on_empty(monkeypatch):
    import newcli.ui as ui_mod
    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert ask_permission("write", {}) is False


from newcli.ui import _gradient_line, _LOGO_LINES


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
