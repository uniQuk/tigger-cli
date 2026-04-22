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
