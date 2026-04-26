import json
import pathlib
import pytest
from tigger.types import TrustLevel
from tigger.trust import is_trusted, write_trusted, check_trust


def test_is_trusted_returns_false_when_file_missing(tmp_path):
    result = is_trusted(tmp_path, tmp_path / "trusted_paths.json")
    assert result is False


def test_is_trusted_exact_match(tmp_path):
    tf = tmp_path / "trusted_paths.json"
    tf.write_text(json.dumps([str(tmp_path)]))
    assert is_trusted(tmp_path, tf) is True


def test_is_trusted_parent_match(tmp_path):
    sub = tmp_path / "project" / "subdir"
    sub.mkdir(parents=True)
    tf = tmp_path / "trusted_paths.json"
    tf.write_text(json.dumps([str(tmp_path)]))
    assert is_trusted(sub, tf) is True


def test_is_trusted_sibling_not_matched(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    target = tmp_path / "project"
    target.mkdir()
    tf = tmp_path / "trusted_paths.json"
    tf.write_text(json.dumps([str(other)]))
    assert is_trusted(target, tf) is False


def test_write_trusted_creates_file(tmp_path):
    tf = tmp_path / "trusted_paths.json"
    write_trusted(tmp_path / "proj", tf)
    data = json.loads(tf.read_text())
    assert str((tmp_path / "proj").resolve()) in data


def test_write_trusted_no_duplicates(tmp_path):
    tf = tmp_path / "trusted_paths.json"
    write_trusted(tmp_path, tf)
    write_trusted(tmp_path, tf)
    data = json.loads(tf.read_text())
    assert data.count(str(tmp_path.resolve())) == 1


def test_write_trusted_appends_to_existing(tmp_path):
    tf = tmp_path / "trusted_paths.json"
    tf.write_text(json.dumps(["/existing"]))
    write_trusted(tmp_path / "new", tf)
    data = json.loads(tf.read_text())
    assert "/existing" in data
    assert str((tmp_path / "new").resolve()) in data


def test_check_trust_returns_always_when_trusted(tmp_path):
    tf = tmp_path / "trusted_paths.json"
    tf.write_text(json.dumps([str(tmp_path)]))
    result = check_trust(tmp_path, trusted_file=tf)
    assert result == TrustLevel.ALWAYS


def test_check_trust_returns_none_when_not_trusted(tmp_path):
    tf = tmp_path / "trusted_paths.json"
    result = check_trust(tmp_path / "unknown", trusted_file=tf)
    assert result is None


def test_is_trusted_handles_corrupt_file(tmp_path, capsys):
    """F019/F020 regression: a truncated trust file must not crash startup."""
    tf = tmp_path / "trusted_paths.json"
    tf.write_text("{not valid json")
    result = is_trusted(tmp_path, tf)
    assert result is False
    captured = capsys.readouterr()
    assert "corrupt" in captured.err
    assert str(tf) in captured.err


def test_is_trusted_handles_empty_file(tmp_path, capsys):
    tf = tmp_path / "trusted_paths.json"
    tf.write_text("")
    result = is_trusted(tmp_path, tf)
    assert result is False
    captured = capsys.readouterr()
    assert "corrupt" in captured.err
