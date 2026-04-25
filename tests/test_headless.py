from unittest.mock import patch, MagicMock
from tigger.types import (
    Config, RunContext, TextChunk, AssistantMessage, TurnDoneEvent,
)
from tigger.tools import ToolRegistry
from tigger.hooks import HookRegistry


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
        hooks=HookRegistry(),
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
        hooks=HookRegistry(),
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
        hooks=HookRegistry(),
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
        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert captured.out == "\n"
