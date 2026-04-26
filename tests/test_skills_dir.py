import pathlib
import textwrap
import pytest
from tigger.skills import load_skills_dir, SkillDef


def _make_skill(
    tmp_path: pathlib.Path,
    folder_name: str,
    skill_md: str,
    refs: dict[str, str] | None = None,
    assets: dict[str, str] | None = None,
) -> pathlib.Path:
    """Create a skill folder under tmp_path. Returns the folder path."""
    folder = tmp_path / folder_name
    folder.mkdir()
    (folder / "SKILL.md").write_text(skill_md)
    if refs:
        (folder / "references").mkdir()
        for fname, content in refs.items():
            (folder / "references" / fname).write_text(content)
    if assets:
        (folder / "assets").mkdir()
        for fname, content in assets.items():
            (folder / "assets" / fname).write_text(content)
    return folder


_BASIC = textwrap.dedent("""\
    ---
    name: my-skill
    ---
    Do the thing with $ARGUMENTS.
""")

_WITH_TRIGGER = textwrap.dedent("""\
    ---
    name: my-skill
    triggers: [/ms]
    ---
    Do the thing with $ARGUMENTS.
""")

_WITH_TOOLS = textwrap.dedent("""\
    ---
    name: my-skill
    tools: [read, grep]
    ---
    Body.
""")


def test_load_skills_dir_basic(tmp_path):
    _make_skill(tmp_path, "my-skill", _BASIC)
    skills = load_skills_dir(tmp_path)
    assert len(skills) == 1
    assert skills[0].name == "my-skill"
    assert "Do the thing" in skills[0].body


def test_load_skills_dir_default_trigger_is_folder_name(tmp_path):
    _make_skill(tmp_path, "my-skill", _BASIC)
    skills = load_skills_dir(tmp_path)
    assert skills[0].triggers == ["/my-skill"]


def test_load_skills_dir_explicit_trigger_overrides(tmp_path):
    _make_skill(tmp_path, "my-skill", _WITH_TRIGGER)
    skills = load_skills_dir(tmp_path)
    assert skills[0].triggers == ["/ms"]


def test_load_skills_dir_references_loaded(tmp_path):
    _make_skill(
        tmp_path, "my-skill", _BASIC,
        refs={"a.md": "Reference A content", "b.md": "Reference B content"},
    )
    skills = load_skills_dir(tmp_path)
    assert len(skills[0].references) == 2
    assert ("a.md", "Reference A content") in skills[0].references
    assert ("b.md", "Reference B content") in skills[0].references


def test_load_skills_dir_references_sorted(tmp_path):
    _make_skill(
        tmp_path, "my-skill", _BASIC,
        refs={"z.md": "Z", "a.md": "A"},
    )
    skills = load_skills_dir(tmp_path)
    # sorted by filename: a.md first, z.md second
    assert skills[0].references[0] == ("a.md", "A")
    assert skills[0].references[1] == ("z.md", "Z")


def test_load_skills_dir_assets_path_set(tmp_path):
    _make_skill(
        tmp_path, "my-skill", _BASIC,
        assets={"template.html": "<html/>"},
    )
    skills = load_skills_dir(tmp_path)
    assert skills[0].assets is not None
    assert (skills[0].assets / "template.html").exists()


def test_load_skills_dir_no_assets_is_none(tmp_path):
    _make_skill(tmp_path, "my-skill", _BASIC)
    skills = load_skills_dir(tmp_path)
    assert skills[0].assets is None


def test_load_skills_dir_skips_folder_without_skill_md(tmp_path):
    (tmp_path / "not-a-skill").mkdir()
    (tmp_path / "not-a-skill" / "README.md").write_text("nothing")
    skills = load_skills_dir(tmp_path)
    assert skills == []


def test_load_skills_dir_skips_non_directories(tmp_path):
    _make_skill(tmp_path, "good-skill", _BASIC)
    (tmp_path / "stray_file.txt").write_text("ignored")
    skills = load_skills_dir(tmp_path)
    assert len(skills) == 1


def test_load_skills_dir_missing_name_skipped(tmp_path):
    bad_md = "---\ndescription: no name here\n---\nBody."
    _make_skill(tmp_path, "nameless", bad_md)
    skills = load_skills_dir(tmp_path)
    assert skills == []


def test_load_skills_dir_folder_field_set(tmp_path):
    _make_skill(tmp_path, "my-skill", _BASIC)
    skills = load_skills_dir(tmp_path)
    assert skills[0].folder == tmp_path / "my-skill"


def test_load_skills_dir_empty_dir(tmp_path):
    assert load_skills_dir(tmp_path) == []


def test_load_skills_dir_nonexistent(tmp_path):
    assert load_skills_dir(tmp_path / "no-such-dir") == []


def test_render_auto_injects_references_by_default(tmp_path):
    # References are loaded and auto-injected into render() output by default.
    _make_skill(
        tmp_path, "my-skill", _BASIC,
        refs={"ref.md": "Important reference context"},
    )
    skills = load_skills_dir(tmp_path)
    assert ("ref.md", "Important reference context") in skills[0].references
    rendered = skills[0].render("/my-skill do this")
    assert "## Reference: ref.md" in rendered
    assert "Important reference context" in rendered
    assert "Do the thing" in rendered
    assert "do this" in rendered
    assert "$ARGUMENTS" not in rendered


_WITH_NO_INJECT = textwrap.dedent("""\
    ---
    name: my-skill
    inject_references: false
    ---
    Do the thing with $ARGUMENTS.
""")


def test_render_inject_references_false_skips_injection(tmp_path):
    _make_skill(
        tmp_path, "my-skill", _WITH_NO_INJECT,
        refs={"ref.md": "Important reference context"},
    )
    skills = load_skills_dir(tmp_path)
    assert skills[0].inject_references is False
    rendered = skills[0].render("/my-skill do this")
    assert "Important reference context" not in rendered
    assert "Do the thing" in rendered
    assert "do this" in rendered


def test_render_no_references_unchanged(tmp_path):
    _make_skill(tmp_path, "my-skill", _BASIC)
    skills = load_skills_dir(tmp_path)
    rendered = skills[0].render("/my-skill hello")
    assert "Do the thing with hello." in rendered
    assert "Skill folder:" in rendered
    assert str((tmp_path / "my-skill").resolve()) in rendered


_NO_ARGS_PLACEHOLDER = textwrap.dedent("""\
    ---
    name: my-skill
    ---
    You are an expert. Follow these instructions carefully.
""")


def test_render_no_placeholder_appends_args(tmp_path):
    # Skills without $ARGUMENTS get the user's request appended after ---
    _make_skill(tmp_path, "my-skill", _NO_ARGS_PLACEHOLDER)
    skills = load_skills_dir(tmp_path)
    rendered = skills[0].render("/my-skill explain the loop")
    assert "You are an expert" in rendered
    assert "explain the loop" in rendered
    assert "---" in rendered


def test_render_no_placeholder_no_args_returns_body(tmp_path):
    # If no args and no placeholder, body is preserved (location header may be prepended).
    _make_skill(tmp_path, "my-skill", _NO_ARGS_PLACEHOLDER)
    skills = load_skills_dir(tmp_path)
    rendered = skills[0].render("/my-skill")
    assert "You are an expert. Follow these instructions carefully." in rendered
