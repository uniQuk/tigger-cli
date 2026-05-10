import datetime
from tigger.types import Config, Message, TextChunk
from tigger.compaction import (
    maybe_compact, persist_summary, load_recent_summary,
)


def _cfg(**kw):
    return Config(base_url="http://x", model="m", **kw)


def _msg(role, content):
    return Message(role=role, content=content)


def _tool_msg(content):
    return Message(role="tool", content=content, tool_call_id="c1", name="bash")


def _fake_provider(system, messages, tools, cfg):
    yield TextChunk(content="<state_snapshot>test summary</state_snapshot>")


# ── persist_summary ──────────────────────────────────────────────────────

def test_persist_summary_creates_file(tmp_path):
    summaries_dir = tmp_path / "summaries"
    path = persist_summary("hello world", summaries_dir)
    assert path.exists()
    assert path.read_text() == "hello world"
    assert path.parent == summaries_dir


def test_persist_summary_naming_format(tmp_path):
    summaries_dir = tmp_path / "summaries"
    path = persist_summary("content", summaries_dir)
    # Filename should match YYYY-MM-DD-HHMMSS.md
    stem = path.stem
    # Parse should succeed without error
    datetime.datetime.strptime(stem, "%Y-%m-%d-%H%M%S")
    assert path.suffix == ".md"


def test_persist_summary_creates_parent_dirs(tmp_path):
    summaries_dir = tmp_path / "deep" / "nested" / "summaries"
    path = persist_summary("content", summaries_dir)
    assert path.exists()


# ── load_recent_summary ─────────────────────────────────────────────────

def test_load_recent_summary_returns_content(tmp_path):
    summaries_dir = tmp_path / "summaries"
    persist_summary("recent summary", summaries_dir)
    result = load_recent_summary(summaries_dir)
    assert result == "recent summary"


def test_load_recent_summary_no_dir(tmp_path):
    result = load_recent_summary(tmp_path / "nonexistent")
    assert result is None


def test_load_recent_summary_empty_dir(tmp_path):
    summaries_dir = tmp_path / "summaries"
    summaries_dir.mkdir()
    result = load_recent_summary(summaries_dir)
    assert result is None


def test_load_recent_summary_ignores_old_files(tmp_path):
    summaries_dir = tmp_path / "summaries"
    summaries_dir.mkdir(parents=True)
    # Create a file with a timestamp 48 hours ago
    old_ts = datetime.datetime.now() - datetime.timedelta(hours=48)
    old_name = old_ts.strftime("%Y-%m-%d-%H%M%S") + ".md"
    (summaries_dir / old_name).write_text("old summary")
    result = load_recent_summary(summaries_dir)
    assert result is None


def test_load_recent_summary_picks_most_recent(tmp_path):
    summaries_dir = tmp_path / "summaries"
    summaries_dir.mkdir(parents=True)
    # Create two files: one recent, one slightly older (but still within 24h)
    now = datetime.datetime.now()
    older = now - datetime.timedelta(hours=1)
    older_name = older.strftime("%Y-%m-%d-%H%M%S") + ".md"
    newer_name = now.strftime("%Y-%m-%d-%H%M%S") + ".md"
    (summaries_dir / older_name).write_text("older")
    (summaries_dir / newer_name).write_text("newer")
    result = load_recent_summary(summaries_dir)
    assert result == "newer"


# ── maybe_compact persists summary ──────────────────────────────────────

def test_maybe_compact_persists_summary_on_summarize(tmp_path):
    summaries_dir = tmp_path / "summaries"
    cfg = _cfg(context_limit=100)
    msgs = [_tool_msg("x" * 300) for _ in range(8)]
    result, cr = maybe_compact(msgs, cfg, _fake_provider, summaries_dir=summaries_dir)
    assert cr.summarized > 0
    files = list(summaries_dir.glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "test summary" in content


def test_maybe_compact_no_persist_without_summaries_dir():
    cfg = _cfg(context_limit=100)
    msgs = [_tool_msg("x" * 300) for _ in range(8)]
    # summaries_dir=None (default) — should not raise
    result, cr = maybe_compact(msgs, cfg, _fake_provider)
    assert cr.summarized > 0


def test_maybe_compact_no_persist_when_no_summarization(tmp_path):
    summaries_dir = tmp_path / "summaries"
    cfg = _cfg(context_limit=8192)
    msgs = [_msg("user", "short")]
    result, cr = maybe_compact(msgs, cfg, None, summaries_dir=summaries_dir)
    assert cr.summarized == 0
    assert not summaries_dir.exists()


# ── Startup injection ───────────────────────────────────────────────────

def test_startup_injects_recent_summary(tmp_path):
    """load_recent_summary content should be usable as system prompt prefix."""
    summaries_dir = tmp_path / "summaries"
    persist_summary("session context here", summaries_dir)
    summary = load_recent_summary(summaries_dir)
    assert summary is not None
    system = f"[Previous session context]\n{summary}\n\nBase system prompt"
    assert system.startswith("[Previous session context]")
    assert "session context here" in system
    assert "Base system prompt" in system


def test_startup_no_injection_for_old_summary(tmp_path):
    """Old summaries (>24h) should not be injected."""
    summaries_dir = tmp_path / "summaries"
    summaries_dir.mkdir(parents=True)
    old_ts = datetime.datetime.now() - datetime.timedelta(hours=25)
    old_name = old_ts.strftime("%Y-%m-%d-%H%M%S") + ".md"
    (summaries_dir / old_name).write_text("stale context")
    summary = load_recent_summary(summaries_dir)
    assert summary is None
    # System prompt should remain unmodified
    system = "Base system prompt"
    if summary:
        system = f"[Previous session context]\n{summary}\n\n{system}"
    assert system == "Base system prompt"
