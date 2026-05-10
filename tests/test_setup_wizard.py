import json
import pathlib


def test_run_setup_wizard_creates_config(monkeypatch, tmp_path):
    import tigger.ui as ui_mod
    from io import StringIO
    from rich.console import Console

    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))

    inputs = iter([
        "http://localhost:1234/v1",   # base_url
        "",                            # api_key (defaults to "local")
        "qwen3",                       # model
        "p",                           # save to project
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    config_path, _ = ui_mod.run_setup_wizard(project_dir=tmp_path)

    assert config_path == tmp_path / ".tigger" / "config.json"
    assert config_path.exists()

    data = json.loads(config_path.read_text())
    assert "providers" in data
    assert data["default_model"] == "qwen3"
    provider_name = data["default_provider"]
    assert data["providers"][provider_name]["base_url"] == "http://localhost:1234/v1"
    assert data["providers"][provider_name]["models"] == ["qwen3"]


def test_run_setup_wizard_user_location(monkeypatch, tmp_path):
    import tigger.ui as ui_mod
    from io import StringIO
    from rich.console import Console

    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))

    inputs = iter([
        "https://api.openai.com/v1",
        "sk-test",
        "gpt-4o",
        "u",                          # save to user
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "fakehome")

    config_path, _ = ui_mod.run_setup_wizard(project_dir=tmp_path)

    assert config_path == tmp_path / "fakehome" / ".tigger" / "config.json"
    assert config_path.exists()


def test_run_setup_wizard_empty_api_key_defaults_to_local(monkeypatch, tmp_path):
    import tigger.ui as ui_mod
    from io import StringIO
    from rich.console import Console

    buf = StringIO()
    monkeypatch.setattr(ui_mod, "console", Console(file=buf, highlight=False, markup=False))

    inputs = iter(["http://x/v1", "", "m", "p"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    config_path, _ = ui_mod.run_setup_wizard(project_dir=tmp_path)
    data = json.loads(config_path.read_text())
    prov = next(iter(data["providers"].values()))
    assert prov["api_key"] == "local"
