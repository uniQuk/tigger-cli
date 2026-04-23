import pathlib, tempfile, datetime
from tigger.memory import read_memory, append_memory, format_for_prompt

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
