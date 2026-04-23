import json
import pathlib
import pytest
from tigger.types import Config, RunContext, ProviderConfig
from tigger.commands.provider import cmd_provider


def _cfg():
    pc = ProviderConfig(name="local", base_url="http://localhost/v1",
                        api_key="local", models=["qwen3"])
    return Config(
        base_url="http://localhost/v1", model="qwen3", api_key="local",
        providers={"local": pc}, active_provider="local",
    )


def _ctx():
    return RunContext(config=_cfg(), messages=[], system_prompt="s")


def test_provider_no_args_shows_usage(capsys):
    ctx = _ctx()
    cmd_provider("", ctx, pathlib.Path("/tmp/fake.json"))
    out = capsys.readouterr().out
    assert "usage" in out.lower() or "add" in out.lower()


def test_provider_add_new(monkeypatch, tmp_path, capsys):
    from tigger.config import write_config
    config_path = tmp_path / "config.json"
    ctx = _ctx()
    write_config(config_path, ctx.config)

    inputs = iter([
        "cloud",                          # provider name
        "https://api.openai.com/v1",      # base_url
        "sk-test",                        # api_key
        "gpt-4o",                         # model
        "n",                              # don't switch
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    cmd_provider("add", ctx, config_path)

    data = json.loads(config_path.read_text())
    assert "cloud" in data["providers"]
    assert data["providers"]["cloud"]["models"] == ["gpt-4o"]
    assert data["providers"]["cloud"]["base_url"] == "https://api.openai.com/v1"
    assert "cloud" in ctx.config.providers


def test_provider_add_model_to_existing(monkeypatch, tmp_path, capsys):
    from tigger.config import write_config
    config_path = tmp_path / "config.json"
    ctx = _ctx()
    write_config(config_path, ctx.config)

    inputs = iter([
        "local",                          # existing provider
        "llama",                          # new model
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    cmd_provider("add", ctx, config_path)

    data = json.loads(config_path.read_text())
    assert "llama" in data["providers"]["local"]["models"]
    assert "qwen3" in data["providers"]["local"]["models"]


def test_provider_add_switch_yes(monkeypatch, tmp_path, capsys):
    from tigger.config import write_config
    config_path = tmp_path / "config.json"
    ctx = _ctx()
    write_config(config_path, ctx.config)

    inputs = iter(["newprov", "http://new/v1", "k", "newmodel", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    cmd_provider("add", ctx, config_path)

    assert ctx.config.active_provider == "newprov"
    assert ctx.config.model == "newmodel"
