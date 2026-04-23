import pathlib
import tempfile
from tigger.input_processing import expand_file_refs


def test_expand_single_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = expand_file_refs(f"@{f}")
    assert "hello world" in result
    assert "Contents of" in result


def test_expand_preserves_surrounding_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("content")
    result = expand_file_refs(f"explain @{f} please")
    assert "explain" in result
    assert "please" in result
    assert "content" in result


def test_expand_nonexistent_file(capsys):
    result = expand_file_refs("@nonexistent.txt")
    assert result == "@nonexistent.txt"
    out = capsys.readouterr().out
    assert "Warning" in out


def test_expand_large_file_truncated(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "big.txt"
    f.write_text("x" * 60000)
    result = expand_file_refs(f"@{f}")
    assert len(result) < 55000  # truncated
    out = capsys.readouterr().out
    assert "truncating" in out


def test_expand_at_alone_not_expanded():
    result = expand_file_refs("@ foo")
    assert result == "@ foo"


def test_expand_multiple_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("aaa")
    f2.write_text("bbb")
    result = expand_file_refs(f"@{f1} and @{f2}")
    assert "aaa" in result
    assert "bbb" in result
