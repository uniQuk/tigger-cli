import json
import pathlib
from tigger.types import Message, ToolCallRecord
from tigger.sessions import save_message, load_session, list_sessions, new_session_id, _message_to_dict, _message_from_dict, project_id, project_session_dir


def test_message_round_trip():
    m = Message(role="user", content="hello")
    d = _message_to_dict(m)
    m2 = _message_from_dict(d)
    assert m2.role == "user"
    assert m2.content == "hello"


def test_message_with_tool_calls_round_trip():
    tc = ToolCallRecord(call_id="c1", name="bash", args={"cmd": "ls"})
    m = Message(role="assistant", content="", tool_calls=[tc])
    d = _message_to_dict(m)
    m2 = _message_from_dict(d)
    assert len(m2.tool_calls) == 1
    assert m2.tool_calls[0].name == "bash"


def test_message_with_tool_id_round_trip():
    m = Message(role="tool", content="result", tool_call_id="c1", name="bash")
    d = _message_to_dict(m)
    m2 = _message_from_dict(d)
    assert m2.tool_call_id == "c1"
    assert m2.name == "bash"


def test_save_and_load(tmp_path):
    save_message(tmp_path, "test-session", Message(role="user", content="hello"))
    save_message(tmp_path, "test-session", Message(role="assistant", content="hi"))
    msgs = load_session(tmp_path / "test-session.jsonl")
    assert len(msgs) == 2
    assert msgs[0].content == "hello"
    assert msgs[1].content == "hi"


def test_load_handles_corrupt_lines(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"role":"user","content":"ok"}\nnot json\n{"role":"assistant","content":"fine"}\n')
    msgs = load_session(path)
    assert len(msgs) == 2


def test_list_sessions_sorted(tmp_path):
    (tmp_path / "20260101-120000.jsonl").write_text('{"role":"user","content":"a"}\n')
    (tmp_path / "20260102-120000.jsonl").write_text('{"role":"user","content":"b"}\n{"role":"assistant","content":"c"}\n')
    sessions = list_sessions(tmp_path)
    assert len(sessions) == 2
    assert sessions[0].timestamp == "20260102-120000"
    assert sessions[0].message_count == 2


def test_list_sessions_empty(tmp_path):
    assert list_sessions(tmp_path) == []


def test_list_sessions_missing_dir():
    assert list_sessions(pathlib.Path("/nonexistent")) == []


def test_new_session_id_format():
    sid = new_session_id()
    assert len(sid) == 15  # YYYYMMDD-HHMMSS
    assert "-" in sid


def test_project_id_stable():
    p = pathlib.Path("/tmp/my-project")
    assert project_id(p) == project_id(p)


def test_project_id_different_paths():
    a = project_id(pathlib.Path("/tmp/project-a"))
    b = project_id(pathlib.Path("/tmp/project-b"))
    assert a != b


def test_project_id_readable():
    pid = project_id(pathlib.Path("/home/user/cool-app"))
    assert pid.startswith("cool-app-")


def test_project_id_special_chars():
    pid = project_id(pathlib.Path("/home/user/my project (v2)"))
    # Should not contain spaces or parens — only safe chars
    assert " " not in pid
    assert "(" not in pid
    assert ")" not in pid


def test_project_session_dir(tmp_path):
    global_dir = tmp_path / "global"
    project = pathlib.Path("/tmp/my-project")
    result = project_session_dir(global_dir, project)
    assert result.parent == global_dir / "sessions"
    assert result.name == project_id(project)
