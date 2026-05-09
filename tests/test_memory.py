import pathlib, tempfile, datetime
from tigger.memory import read_memory, append_memory, format_for_prompt, search_memory, delete_memory, clear_memory

def _tmp() -> pathlib.Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
    f.close()
    return pathlib.Path(f.name)

def test_read_empty_file():
    p = _tmp()
    assert read_memory(p) == []

def test_append_and_read():
    p = _tmp()
    append_memory(p, "use pytest")
    lines = read_memory(p)
    assert len(lines) == 1
    assert "use pytest" in lines[0]

def test_append_adds_date():
    p = _tmp()
    append_memory(p, "api at localhost")
    lines = read_memory(p)
    today = datetime.date.today().isoformat()
    assert today in lines[0]

def test_read_returns_last_50():
    p = _tmp()
    for i in range(60):
        append_memory(p, f"note {i}")
    lines = read_memory(p)
    assert len(lines) == 50
    assert "note 59" in lines[-1]

def test_format_for_prompt_empty():
    assert format_for_prompt([]) == ""

def test_format_for_prompt():
    lines = ["[2026-04-22] use pytest", "[2026-04-22] api at localhost"]
    prompt = format_for_prompt(lines)
    assert "## Memory" in prompt
    assert "use pytest" in prompt

def test_read_missing_file():
    assert read_memory(pathlib.Path("/no/memory.md")) == []

# --- search_memory ---

def test_search_memory_finds_matching():
    p = _tmp()
    append_memory(p, "use pytest")
    append_memory(p, "api at localhost")
    append_memory(p, "pytest is great")
    results = search_memory(p, "pytest")
    assert len(results) == 2
    assert results[0][0] == 1
    assert results[1][0] == 3
    assert "pytest" in results[0][1]

def test_search_memory_case_insensitive():
    p = _tmp()
    append_memory(p, "Use PyTest")
    results = search_memory(p, "pytest")
    assert len(results) == 1

def test_search_memory_no_match():
    p = _tmp()
    append_memory(p, "use pytest")
    results = search_memory(p, "nomatch")
    assert results == []

def test_search_memory_empty_file():
    p = _tmp()
    results = search_memory(p, "anything")
    assert results == []

# --- delete_memory ---

def test_delete_memory_removes_entry():
    p = _tmp()
    for i in range(5):
        append_memory(p, f"note {i}")
    ok = delete_memory(p, 3)
    assert ok is True
    lines = read_memory(p)
    assert len(lines) == 4
    assert all("note 2" not in l for l in lines)

def test_delete_memory_invalid_index_too_high():
    p = _tmp()
    for i in range(5):
        append_memory(p, f"note {i}")
    ok = delete_memory(p, 99)
    assert ok is False
    assert len(read_memory(p)) == 5

def test_delete_memory_invalid_index_zero():
    p = _tmp()
    append_memory(p, "note")
    assert delete_memory(p, 0) is False

def test_delete_memory_invalid_index_negative():
    p = _tmp()
    append_memory(p, "note")
    assert delete_memory(p, -1) is False

# --- clear_memory ---

def test_clear_memory():
    p = _tmp()
    for i in range(5):
        append_memory(p, f"note {i}")
    clear_memory(p)
    assert read_memory(p) == []

def test_clear_memory_empty_file():
    p = _tmp()
    clear_memory(p)  # should not raise
    assert read_memory(p) == []

# --- cmd_memory subcommands ---

def _make_ctx():
    """Minimal RunContext stub for cmd_memory tests."""
    from types import SimpleNamespace
    return SimpleNamespace()

def test_cmd_memory_search(capsys):
    from tigger.commands.memory import cmd_memory
    p = _tmp()
    append_memory(p, "use pytest")
    append_memory(p, "api at localhost")
    cmd_memory("search pytest", _make_ctx(), p)
    out = capsys.readouterr().out
    # New format prefixes the line index with "1." instead of "[1]"
    assert "1." in out
    assert "pytest" in out
    assert "localhost" not in out

def test_cmd_memory_search_no_query(capsys):
    from tigger.commands.memory import cmd_memory
    p = _tmp()
    cmd_memory("search", _make_ctx(), p)
    out = capsys.readouterr().out
    assert "Usage" in out

def test_cmd_memory_search_no_match(capsys):
    from tigger.commands.memory import cmd_memory
    p = _tmp()
    append_memory(p, "use pytest")
    cmd_memory("search nomatch", _make_ctx(), p)
    out = capsys.readouterr().out
    assert "No matches" in out

def test_cmd_memory_delete(capsys):
    from tigger.commands.memory import cmd_memory
    p = _tmp()
    for i in range(3):
        append_memory(p, f"note {i}")
    cmd_memory("delete 2", _make_ctx(), p)
    out = capsys.readouterr().out
    assert "Deleted" in out
    assert len(read_memory(p)) == 2

def test_cmd_memory_delete_invalid(capsys):
    from tigger.commands.memory import cmd_memory
    p = _tmp()
    append_memory(p, "note")
    cmd_memory("delete 99", _make_ctx(), p)
    out = capsys.readouterr().out
    assert "Invalid index" in out

def test_cmd_memory_clear(capsys):
    from tigger.commands.memory import cmd_memory
    p = _tmp()
    append_memory(p, "note")
    cmd_memory("clear", _make_ctx(), p)
    out = capsys.readouterr().out
    assert "cleared" in out.lower()
    assert read_memory(p) == []

def test_cmd_memory_list_default(capsys):
    from tigger.commands.memory import cmd_memory
    p = _tmp()
    append_memory(p, "use pytest")
    cmd_memory("", _make_ctx(), p)
    out = capsys.readouterr().out
    assert "pytest" in out
