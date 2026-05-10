from unittest.mock import patch
from tigger.types import (
    Config, RunContext, TextChunk, AssistantMessage,
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
def test_no_think_overrides_model_per_entry_thinking(mock_startup, capsys, monkeypatch):
    """Iter-2 regression: --no-think must override the per-model
    chat_template_kwargs that --model copies in via switch_model. Before
    the fix, --no-think ran first and was silently overwritten by the
    later --model switch."""
    import pathlib
    from tigger.main import StartupResult
    from tigger.types import ModelConfig, ProviderConfig

    captured: dict = {}

    def capture_provider(system, messages, tools, config):
        captured["chat_template_kwargs"] = dict(config.chat_template_kwargs or {})
        yield AssistantMessage(content="ok", tool_calls=[])

    # Provider with one thinking-on model. --no-think must flip it off.
    thinking_model = ModelConfig(
        chat_template_kwargs={"enable_thinking": True, "preserve_thinking": True}
    )
    provider = ProviderConfig(
        name="local",
        base_url="http://x",
        api_key="local",
        models={"thinker": thinking_model},
    )
    cfg = Config(
        base_url="http://x",
        model="thinker",
        model_slug="thinker",
        api_key="local",
        providers={"local": provider},
        active_provider="local",
        permission_mode="bypass",
        chat_template_kwargs={"enable_thinking": True, "preserve_thinking": True},
    )
    ctx = RunContext(config=cfg, messages=[], system_prompt="")
    mock_startup.return_value = StartupResult(
        ctx=ctx,
        commands={},
        skills=[],
        agents=[],
        registry=ToolRegistry(),
        hook_defs=[],
        provider_fn=capture_provider,
        config_path=pathlib.Path("/tmp/fake.toml"),
    )

    import sys
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with patch("sys.argv", ["tigger", "--no-think", "--model", "thinker", "--once", "hi"]):
        import pytest
        with pytest.raises(SystemExit):
            from tigger.main import main
            main()
    assert captured["chat_template_kwargs"]["enable_thinking"] is False


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


# --- Interactive REPL harness via input() mocking -------------------
# Iter 81: protect interactive-only flows from regression. We can't drive
# prompt_toolkit cleanly from a unit test, but the import-fallback path
# uses plain input() — perfect for deterministic testing.


def _mock_inputs(*lines):
    """Build an input() side_effect that returns each line then raises EOFError."""
    queue = list(lines)
    def _next(prompt=""):
        if not queue:
            raise EOFError
        return queue.pop(0)
    return _next


@patch("tigger.main.startup")
def test_repl_runs_one_turn_then_exits(mock_startup, monkeypatch, capsys):
    """REPL takes one user message, streams a reply, then exits on EOF."""
    from tigger.main import StartupResult, repl
    import pathlib
    import sys
    import builtins

    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(config=cfg, messages=[], system_prompt="You are helpful.")
    result = StartupResult(
        ctx=ctx,
        commands={},
        skills=[],
        agents=[],
        registry=ToolRegistry(),
        hook_defs=[],
        provider_fn=_make_provider("hi from fake llm"),
        config_path=pathlib.Path("/tmp/fake.toml"),
    )

    # Force the prompt_toolkit ImportError fallback so input() is the source.
    real_import = builtins.__import__
    def _fail_pt(name, *args, **kwargs):
        if name.startswith("prompt_toolkit"):
            raise ImportError("forced for test")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", _fail_pt)

    # Mock stdin so isatty returns False (skip interactive trust prompt path).
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(builtins, "input", _mock_inputs("hello"))

    repl(result)

    out = capsys.readouterr().out
    assert "hi from fake llm" in out


@patch("tigger.main.startup")
def test_repl_slash_exit_breaks_loop(mock_startup, monkeypatch, capsys):
    """Typing /exit cleanly leaves the REPL loop."""
    from tigger.main import StartupResult, repl
    import pathlib
    import builtins

    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(config=cfg, messages=[], system_prompt="")
    result = StartupResult(
        ctx=ctx, commands={}, skills=[], agents=[],
        registry=ToolRegistry(), hook_defs=[],
        provider_fn=_make_provider("never reached"),
        config_path=pathlib.Path("/tmp/fake.toml"),
    )

    real_import = builtins.__import__
    def _fail_pt(name, *args, **kwargs):
        if name.startswith("prompt_toolkit"):
            raise ImportError("forced")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", _fail_pt)
    monkeypatch.setattr(builtins, "input", _mock_inputs("/exit"))

    repl(result)
    # No turn should have run — the provider's output should not appear.
    out = capsys.readouterr().out
    assert "never reached" not in out


@patch("tigger.main.startup")
def test_repl_unknown_slash_command_suggests_match(mock_startup, monkeypatch, capsys):
    """Iter 36 did-you-mean: typo /halp suggests /help."""
    from tigger.main import StartupResult, repl
    import pathlib
    import builtins

    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    ctx = RunContext(config=cfg, messages=[], system_prompt="")
    result = StartupResult(
        ctx=ctx,
        # Need at least one real command name so difflib has a haystack.
        commands={"help": lambda *_args, **_kw: None},
        skills=[], agents=[],
        registry=ToolRegistry(), hook_defs=[],
        provider_fn=_make_provider(),
        config_path=pathlib.Path("/tmp/fake.toml"),
    )

    real_import = builtins.__import__
    def _fail_pt(name, *args, **kwargs):
        if name.startswith("prompt_toolkit"):
            raise ImportError("forced")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", _fail_pt)
    monkeypatch.setattr(builtins, "input", _mock_inputs("/halp", "/exit"))

    repl(result)
    out = capsys.readouterr().out
    assert "/halp" in out
    assert "/help" in out  # the suggestion
