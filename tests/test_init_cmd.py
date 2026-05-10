from __future__ import annotations
from tigger.types import Config, RunContext
from tigger.commands.init import cmd_init
from tigger._constants import CONFIG_DIR


def _ctx():
    return RunContext(config=Config(base_url="http://x", model="m"), messages=[], system_prompt="")


def test_init_creates_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cmd_init("", _ctx())
    ai_dir = tmp_path / CONFIG_DIR
    assert (ai_dir / "system.md").exists()
    assert (ai_dir / "hooks" / "example-hook.md").exists()
    assert (ai_dir / "skills" / "SKILL.md").exists()
    assert (ai_dir / "agents" / "example-agent.md").exists()
    assert (ai_dir / "modes" / "example-mode.md").exists()
    out = capsys.readouterr().out
    assert "Created" in out


def test_init_no_flat_agents_md(tmp_path, monkeypatch):
    """Flat agents.md is no longer scaffolded (deprecated format)."""
    monkeypatch.chdir(tmp_path)
    cmd_init("", _ctx())
    ai_dir = tmp_path / CONFIG_DIR
    assert not (ai_dir / "agents.md").exists()


def test_init_skips_existing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ai_dir = tmp_path / CONFIG_DIR
    ai_dir.mkdir()
    (ai_dir / "system.md").write_text("existing")
    cmd_init("", _ctx())
    assert (ai_dir / "system.md").read_text() == "existing"
    out = capsys.readouterr().out
    assert "Skipped" in out


def test_init_all_exist(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cmd_init("", _ctx())  # create all
    capsys.readouterr()
    cmd_init("", _ctx())  # all exist
    out = capsys.readouterr().out
    assert "Skipped" in out


def test_init_creates_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cmd_init("", _ctx())
    assert (tmp_path / CONFIG_DIR).is_dir()


def test_init_global_seeds_from_internals(tmp_path, monkeypatch, capsys):
    global_dir = tmp_path / ".tigger"
    monkeypatch.setattr("tigger.commands.init.home_config_dir", lambda: global_dir)
    cmd_init("--global", _ctx())
    assert global_dir.exists()
    # Should have real internal skills, not useless templates
    assert (global_dir / "skills" / "_debug" / "SKILL.md").exists()
    assert (global_dir / "skills" / "_commit" / "SKILL.md").exists()
    assert (global_dir / "agents" / "_test-engineer.md").exists()
    assert (global_dir / "modes" / "act.md").exists()
    assert (global_dir / "modes" / "plan.md").exists()
    out = capsys.readouterr().out
    assert "Seeded" in out
    assert "live copies" in out


def test_init_global_already_populated(tmp_path, monkeypatch, capsys):
    global_dir = tmp_path / ".tigger"
    monkeypatch.setattr("tigger.commands.init.home_config_dir", lambda: global_dir)
    cmd_init("--global", _ctx())
    capsys.readouterr()
    # Second call — nothing new
    cmd_init("--global", _ctx())
    out = capsys.readouterr().out
    assert "already populated" in out


def test_init_global_preserves_customizations(tmp_path, monkeypatch, capsys):
    global_dir = tmp_path / ".tigger"
    monkeypatch.setattr("tigger.commands.init.home_config_dir", lambda: global_dir)
    # Pre-create a custom debug skill
    custom_dir = global_dir / "skills" / "debug"
    custom_dir.mkdir(parents=True)
    (custom_dir / "SKILL.md").write_text("my custom debug")
    cmd_init("--global", _ctx())
    # Custom content preserved
    assert (global_dir / "skills" / "debug" / "SKILL.md").read_text() == "my custom debug"


def test_init_force_overwrites_project(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ai_dir = tmp_path / CONFIG_DIR
    ai_dir.mkdir()
    (ai_dir / "system.md").write_text("custom")
    cmd_init("--force", _ctx())
    assert (ai_dir / "system.md").read_text() != "custom"
    out = capsys.readouterr().out
    assert "Overwritten" in out


def test_init_global_seeds_system_md(tmp_path, monkeypatch, capsys):
    global_dir = tmp_path / ".tigger"
    monkeypatch.setattr("tigger.commands.init.home_config_dir", lambda: global_dir)
    cmd_init("--global", _ctx())
    assert (global_dir / "system.md").exists()
    assert (global_dir / "system.md").read_text().strip() != ""


def test_init_global_force_overwrites(tmp_path, monkeypatch, capsys):
    global_dir = tmp_path / ".tigger"
    monkeypatch.setattr("tigger.commands.init.home_config_dir", lambda: global_dir)
    cmd_init("--global", _ctx())
    (global_dir / "system.md").write_text("user-edited")
    capsys.readouterr()
    cmd_init("--global --force", _ctx())
    assert (global_dir / "system.md").read_text() != "user-edited"
    out = capsys.readouterr().out
    assert "Re-seeded" in out


def test_init_seeds_config_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cmd_init("", _ctx())
    cfg = tmp_path / CONFIG_DIR / "config.json"
    assert cfg.exists()
    import json
    data = json.loads(cfg.read_text())
    assert "chat_template_kwargs" in data
    assert "top_k" in data


def test_init_global_seeds_config_json(tmp_path, monkeypatch):
    global_dir = tmp_path / ".tigger"
    monkeypatch.setattr("tigger.commands.init.home_config_dir", lambda: global_dir)
    cmd_init("--global", _ctx())
    assert (global_dir / "config.json").exists()


def test_init_config_backfills_missing_keys_preserves_existing(tmp_path, monkeypatch, capsys):
    """Without --force: user credentials preserved; missing keys backfilled."""
    import json
    monkeypatch.chdir(tmp_path)
    ai_dir = tmp_path / CONFIG_DIR
    ai_dir.mkdir()
    user_cfg = {
        "default_provider": "my-real-server",
        "providers": {"my-real-server": {"base_url": "http://10.0.0.1", "api_key": "secret"}},
        "max_tokens": 999,
    }
    (ai_dir / "config.json").write_text(json.dumps(user_cfg))
    cmd_init("", _ctx())
    after = json.loads((ai_dir / "config.json").read_text())
    assert after["default_provider"] == "my-real-server"
    assert after["providers"]["my-real-server"]["api_key"] == "secret"
    assert after["max_tokens"] == 999
    assert "top_k" in after
    assert "chat_template_kwargs" in after


def test_init_force_overwrites_config_json(tmp_path, monkeypatch, capsys):
    """With --force: config.json is replaced wholesale from the bundled example."""
    import json
    monkeypatch.chdir(tmp_path)
    ai_dir = tmp_path / CONFIG_DIR
    ai_dir.mkdir()
    (ai_dir / "config.json").write_text(json.dumps({"default_provider": "my-real-server"}))
    cmd_init("--force", _ctx())
    after = json.loads((ai_dir / "config.json").read_text())
    assert after["default_provider"] == "local"
    assert after["providers"]["local"]["api_key"] == "sk-replace-me"


def test_init_example_hook_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cmd_init("", _ctx())
    hook_text = (tmp_path / CONFIG_DIR / "hooks" / "example-hook.md").read_text()
    assert "enabled: false" in hook_text


def test_init_without_global_uses_cwd(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cmd_init("", _ctx())
    assert (tmp_path / CONFIG_DIR).is_dir()
    out = capsys.readouterr().out
    assert "Created" in out
