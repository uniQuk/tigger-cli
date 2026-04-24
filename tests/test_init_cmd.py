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


def test_init_global_creates_in_home(tmp_path, monkeypatch, capsys):
    global_dir = tmp_path / ".tigger"
    monkeypatch.setattr("tigger.commands.init.home_config_dir", lambda: global_dir)
    cmd_init("--global", _ctx())
    assert global_dir.exists()
    assert (global_dir / "system.md").exists()
    assert (global_dir / "hooks.py").exists()
    assert (global_dir / "skills" / "SKILL.md").exists()
    assert (global_dir / "agents" / "example-agent.md").exists()
    out = capsys.readouterr().out
    assert str(global_dir) in out


def test_init_global_skips_existing(tmp_path, monkeypatch, capsys):
    global_dir = tmp_path / ".tigger"
    global_dir.mkdir(parents=True)
    (global_dir / "system.md").write_text("my global prompt")
    monkeypatch.setattr("tigger.commands.init.home_config_dir", lambda: global_dir)
    cmd_init("--global", _ctx())
    assert (global_dir / "system.md").read_text() == "my global prompt"
    out = capsys.readouterr().out
    assert "Skipped" in out


def test_init_without_global_uses_cwd(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cmd_init("", _ctx())
    assert (tmp_path / CONFIG_DIR).is_dir()
    # Should NOT create in a global location
    out = capsys.readouterr().out
    assert "Created" in out


def test_init_global_creates_agents_dir_template(tmp_path, monkeypatch, capsys):
    global_dir = tmp_path / ".tigger"
    monkeypatch.setattr("tigger.commands.init.home_config_dir", lambda: global_dir)
    cmd_init("--global", _ctx())
    agent_file = global_dir / "agents" / "example-agent.md"
    assert agent_file.exists()
    content = agent_file.read_text()
    assert "name: example-agent" in content
    assert "description:" in content
