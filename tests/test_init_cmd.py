from __future__ import annotations
import pathlib
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
    assert (ai_dir / "hooks.py").exists()
    assert (ai_dir / "skills" / "SKILL.md").exists()
    assert (ai_dir / "agents" / "example-agent.md").exists()
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


def test_init_without_global_uses_cwd(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cmd_init("", _ctx())
    assert (tmp_path / CONFIG_DIR).is_dir()
    out = capsys.readouterr().out
    assert "Created" in out
