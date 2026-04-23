import pathlib
import tempfile
from tigger.types import Config, RunContext, Message, TextChunk
from tigger.commands.summary import cmd_summary


def _cfg():
    return Config(base_url="http://x", model="m")


def _ctx_with_messages():
    cfg = _cfg()
    ctx = RunContext(config=cfg, messages=[
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi there"),
    ], system_prompt="")
    return ctx


def _fake_provider(system, messages, tools, cfg):
    yield TextChunk(content="## Overall Goal\nTest goal\n\n## Key Knowledge\nTest knowledge")


def test_summary_creates_file(tmp_path):
    ctx = _ctx_with_messages()
    cmd_summary("", ctx, tmp_path, _fake_provider)
    summaries = list((tmp_path / "summaries").iterdir())
    assert len(summaries) == 1
    content = summaries[0].read_text()
    assert "Overall Goal" in content


def test_summary_empty_session(capsys, tmp_path):
    cfg = _cfg()
    ctx = RunContext(config=cfg, messages=[], system_prompt="")
    cmd_summary("", ctx, tmp_path, _fake_provider)
    out = capsys.readouterr().out
    assert "No conversation" in out


def test_summary_prints_path(capsys, tmp_path):
    ctx = _ctx_with_messages()
    cmd_summary("", ctx, tmp_path, _fake_provider)
    out = capsys.readouterr().out
    assert "Summary saved to" in out


def test_summary_creates_dir(tmp_path):
    ctx = _ctx_with_messages()
    ai_dir = tmp_path / "new_tigger"
    cmd_summary("", ctx, ai_dir, _fake_provider)
    assert (ai_dir / "summaries").exists()
