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
    assert (ai_dir / "agents.md").exists()
    assert (ai_dir / "system.md").exists()
    assert (ai_dir / "hooks.py").exists()
    assert (ai_dir / "skills" / "SKILL.md").exists()
    out = capsys.readouterr().out
    assert "Created" in out


def test_init_skips_existing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ai_dir = tmp_path / CONFIG_DIR
    ai_dir.mkdir()
    (ai_dir / "agents.md").write_text("existing")
    cmd_init("", _ctx())
    assert (ai_dir / "agents.md").read_text() == "existing"
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
