"""Tests for tigger.parsing — YAML frontmatter helpers."""
from tigger.parsing import parse_blocks, parse_single


def test_parse_blocks_returns_empty_for_empty_input():
    assert parse_blocks("") == []


def test_parse_blocks_recovers_from_invalid_yaml(capsys):
    """F008 regression: a malformed frontmatter block warns to stderr and is skipped,
    rather than silently swallowing the error or aborting the entire parse."""
    text = (
        "---\n"
        "name: bad: : :\n"  # invalid YAML
        "---\n"
        "body1\n"
        "---\n"
        "name: good\n"
        "---\n"
        "body2\n"
    )
    blocks = parse_blocks(text, source="my-skills.md")
    # The good block still loads.
    assert any(b["fm"].get("name") == "good" for b in blocks)
    captured = capsys.readouterr()
    assert "my-skills.md" in captured.err
    assert "YAML frontmatter error" in captured.err


def test_parse_single_recovers_from_invalid_yaml(capsys):
    text = "---\nname: bad: : :\n---\nbody"
    result = parse_single(text, source="agent.md")
    assert result is None
    captured = capsys.readouterr()
    assert "agent.md" in captured.err


def test_parse_single_no_frontmatter_returns_none():
    assert parse_single("just body, no fence") is None


def test_parse_blocks_clean_input_emits_no_warnings(capsys):
    text = "---\nname: ok\n---\nbody\n"
    parse_blocks(text)
    assert capsys.readouterr().err == ""
