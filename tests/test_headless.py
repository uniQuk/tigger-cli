from unittest.mock import patch, MagicMock
from tigger.types import (
    Config, RunContext, TextChunk, AssistantMessage, TurnDoneEvent,
)
from tigger.tools import ToolRegistry


def _make_provider(text="Hello!"):
    def fake_stream(system, messages, tools, config):
        yield TextChunk(content=text)
        yield AssistantMessage(content=text, tool_calls=[])
    return fake_stream


@patch("tigger.main.startup")
def test_once_prints_output(mock_startup, capsys):
    """--once runs a single turn and prints text to stdout."""
    from tigger.main import StartupResult
    import pathlib

    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(config=cfg, messages=[], system_prompt="You are helpful.")
    result = StartupResult(
        ctx=ctx,
        commands={},
        skills=[],
        agents=[],
        registry=ToolRegistry(),
        hook_defs=[],
        provider_fn=_make_provider("headless output"),
        config_path=pathlib.Path("/tmp/fake.toml"),
    )
    mock_startup.return_value = result

    with patch("sys.argv", ["tigger", "--once", "say hello"]):
        import pytest
        with pytest.raises(SystemExit) as exc_info:
            from tigger.main import main
            main()
        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "headless output" in captured.out


@patch("tigger.main.startup")
def test_once_does_not_start_repl(mock_startup):
    """--once should never call repl()."""
    from tigger.main import StartupResult
    import pathlib

    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(config=cfg, messages=[], system_prompt="You are helpful.")
    result = StartupResult(
        ctx=ctx,
        commands={},
        skills=[],
        agents=[],
        registry=ToolRegistry(),
        hook_defs=[],
        provider_fn=_make_provider("ok"),
        config_path=pathlib.Path("/tmp/fake.toml"),
    )
    mock_startup.return_value = result

    with patch("sys.argv", ["tigger", "--once", "hi"]), \
         patch("tigger.main.repl") as mock_repl:
        import pytest
        with pytest.raises(SystemExit):
            from tigger.main import main
            main()
        mock_repl.assert_not_called()


@patch("tigger.main.startup")
def test_once_does_not_prompt_for_trust_when_piped(mock_startup, capsys, monkeypatch):
    """F022 regression: a non-interactive --once invocation must not deadlock
    on the trust prompt. main() should detect non-TTY stdin and pass
    interactive=False to startup()."""
    import pathlib
    from tigger.main import StartupResult

    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(config=cfg, messages=[], system_prompt="")
    mock_startup.return_value = StartupResult(
        ctx=ctx,
        commands={},
        skills=[],
        agents=[],
        registry=ToolRegistry(),
        hook_defs=[],
        provider_fn=_make_provider("ok"),
        config_path=pathlib.Path("/tmp/fake.toml"),
    )

    # Simulate piped stdin (no TTY).
    import sys
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with patch("sys.argv", ["tigger", "--once", "hi"]):
        import pytest
        with pytest.raises(SystemExit):
            from tigger.main import main
            main()
    # startup() must have been called with interactive=False and auto_trust=False.
    _, kwargs = mock_startup.call_args
    assert kwargs.get("interactive") is False
    assert kwargs.get("auto_trust") is False


@patch("tigger.main.startup")
def test_trust_flag_sets_auto_trust(mock_startup, capsys, monkeypatch):
    """--trust forwards auto_trust=True to startup()."""
    import pathlib
    from tigger.main import StartupResult

    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(config=cfg, messages=[], system_prompt="")
    mock_startup.return_value = StartupResult(
        ctx=ctx,
        commands={},
        skills=[],
        agents=[],
        registry=ToolRegistry(),
        hook_defs=[],
        provider_fn=_make_provider("ok"),
        config_path=pathlib.Path("/tmp/fake.toml"),
    )

    import sys
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with patch("sys.argv", ["tigger", "--once", "hi", "--trust"]):
        import pytest
        with pytest.raises(SystemExit):
            from tigger.main import main
            main()
    _, kwargs = mock_startup.call_args
    assert kwargs.get("auto_trust") is True


@patch("tigger.main.startup")
def test_startup_failure_prints_error_and_exits(mock_startup, capsys):
    """F019 regression: a startup() exception must produce a clean error
    message and exit(1), not a traceback."""
    mock_startup.side_effect = FileNotFoundError("missing.json")
    with patch("sys.argv", ["tigger", "--once", "hi"]):
        import pytest
        with pytest.raises(SystemExit) as exc_info:
            from tigger.main import main
            main()
        assert exc_info.value.code == 1


@patch("tigger.main.startup")
def test_once_empty_response(mock_startup, capsys):
    """--once with empty model response prints just a newline."""
    from tigger.main import StartupResult
    import pathlib

    def empty_provider(system, messages, tools, config):
        yield AssistantMessage(content="", tool_calls=[])

    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(config=cfg, messages=[], system_prompt="You are helpful.")
    result = StartupResult(
        ctx=ctx,
        commands={},
        skills=[],
        agents=[],
        registry=ToolRegistry(),
        hook_defs=[],
        provider_fn=empty_provider,
        config_path=pathlib.Path("/tmp/fake.toml"),
    )
    mock_startup.return_value = result

    with patch("sys.argv", ["tigger", "--once", "hi"]):
        import pytest
        with pytest.raises(SystemExit) as exc_info:
            from tigger.main import main
            main()
        # New contract (iter 47): empty response is a failure for scripting,
        # so exit non-zero with a stderr explanation rather than exit 0 silently.
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "empty response" in captured.err
