import pathlib
import tempfile
from tigger.input_processing import expand_file_refs


def test_expand_single_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = expand_file_refs("@test.txt")
    assert "hello world" in result
    assert "Contents of" in result


def test_expand_preserves_surrounding_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("content")
    result = expand_file_refs("explain @test.txt please")
    assert "explain" in result
    assert "please" in result
    assert "content" in result


def test_expand_nonexistent_file(capsys):
    result = expand_file_refs("@nonexistent.txt")
    assert result == "@nonexistent.txt"
    out = capsys.readouterr().err
    assert "Warning" in out


def test_expand_large_file_truncated(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "big.txt"
    f.write_text("x" * 60000)
    result = expand_file_refs("@big.txt")
    assert len(result) < 55000  # truncated
    out = capsys.readouterr().err
    assert "truncating" in out


def test_expand_at_alone_not_expanded():
    result = expand_file_refs("@ foo")
    assert result == "@ foo"


def test_expand_multiple_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("aaa")
    (tmp_path / "b.txt").write_text("bbb")
    result = expand_file_refs("@a.txt and @b.txt")
    assert "aaa" in result
    assert "bbb" in result


def test_expand_rejects_absolute_path(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("secret")
    result = expand_file_refs(f"@{f}")
    assert "secret" not in result
    out = capsys.readouterr().err
    assert "must be relative" in out


def test_expand_rejects_home_path(capsys):
    result = expand_file_refs("@~/.ssh/id_rsa")
    assert "id_rsa" not in result or "@~/.ssh/id_rsa" == result
    out = capsys.readouterr().err
    assert "must be relative" in out


def test_expand_rejects_directory(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "subdir").mkdir()
    result = expand_file_refs("@subdir")
    assert result == "@subdir"
    out = capsys.readouterr().err
    assert "not directories" in out


def test_expand_rejects_parent_traversal(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Create a file outside workspace
    parent_file = tmp_path.parent / "secret.txt"
    try:
        parent_file.write_text("leaked")
        result = expand_file_refs("@../secret.txt")
        assert "leaked" not in result
    finally:
        parent_file.unlink(missing_ok=True)


def test_expand_warnings_stay_off_stdout(tmp_path, capsys, monkeypatch):
    """F036 regression: warnings must go to stderr so they don't pollute REPL stdout."""
    monkeypatch.chdir(tmp_path)
    expand_file_refs("@/nope/absolute")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "must be relative" in captured.err
