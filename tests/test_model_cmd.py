import dataclasses
import pytest
from newcli.types import Config, RunContext, ProviderConfig
from newcli.commands.misc import cmd_model


def _cfg():
    pc1 = ProviderConfig(name="local", base_url="http://localhost/v1",
                         api_key="local", models=["qwen3", "llama"])
    pc2 = ProviderConfig(name="cloud", base_url="https://api.openai.com/v1",
                         api_key="sk-cloud", models=["gpt-4o", "gpt-4o-mini"])
    return Config(
        base_url="http://localhost/v1", model="qwen3", api_key="local",
        providers={"local": pc1, "cloud": pc2},
        active_provider="local", active_model="qwen3",
    )


def _ctx():
    return RunContext(config=_cfg(), messages=[], system_prompt="s")


def test_model_no_args_shows_list(capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "1")
    ctx = _ctx()
    cmd_model("", ctx)
    out = capsys.readouterr().out
    assert "local" in out
    assert "qwen3" in out
    assert "gpt-4o" in out


def test_model_direct_switch_unambiguous(capsys):
    ctx = _ctx()
    cmd_model("gpt-4o", ctx)
    assert ctx.config.model == "gpt-4o"
    assert ctx.config.active_provider == "cloud"
    assert ctx.config.base_url == "https://api.openai.com/v1"


def test_model_direct_switch_with_provider_prefix(capsys):
    ctx = _ctx()
    cmd_model("cloud/gpt-4o-mini", ctx)
    assert ctx.config.model == "gpt-4o-mini"
    assert ctx.config.active_provider == "cloud"


def test_model_not_found(capsys):
    ctx = _ctx()
    cmd_model("nonexistent", ctx)
    out = capsys.readouterr().out
    assert "not found" in out.lower()
    assert ctx.config.model == "qwen3"


def test_model_picker_by_number(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "3")
    ctx = _ctx()
    cmd_model("", ctx)
    assert ctx.config.model == "gpt-4o"
    assert ctx.config.active_provider == "cloud"


def test_model_no_providers_shows_current(capsys):
    cfg = Config(base_url="http://x", model="m")
    ctx = RunContext(config=cfg, messages=[], system_prompt="s")
    cmd_model("", ctx)
    out = capsys.readouterr().out
    assert "m" in out
