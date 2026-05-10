import pathlib
import textwrap
from tigger.skills import load_skills_dir


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


_WITH_OVERRIDES = textwrap.dedent("""\
    ---
    name: my-skill
    stop_after_write: true
    chat_template_kwargs:
      enable_thinking: false
      another_flag: 42
    ---
    body
""")


def test_load_stop_after_write_and_chat_template_kwargs(tmp_path):
    _make_skill(tmp_path, "my-skill", _WITH_OVERRIDES)
    skills = load_skills_dir(tmp_path)
    assert len(skills) == 1
    s = skills[0]
    assert s.stop_after_write is True
    assert s.chat_template_kwargs == {"enable_thinking": False, "another_flag": 42}


def test_chat_template_kwargs_defaults_to_none(tmp_path):
    _make_skill(tmp_path, "my-skill", _BASIC)
    skills = load_skills_dir(tmp_path)
    assert skills[0].chat_template_kwargs is None
    assert skills[0].stop_after_write is False


_BAD_KWARGS = textwrap.dedent("""\
    ---
    name: my-skill
    chat_template_kwargs: "not a dict"
    stop_after_write: nope
    ---
    body
""")


def test_invalid_overrides_fall_back_silently(tmp_path):
    _make_skill(tmp_path, "my-skill", _BAD_KWARGS)
    skills = load_skills_dir(tmp_path)
    # Loader survives garbage values rather than crashing the session.
    assert skills[0].chat_template_kwargs is None
    assert skills[0].stop_after_write is False


_PORTABLE_HTML_ARTIFACT = textwrap.dedent("""\
    ---
    name: architecture-diagram
    ---
    Create professional, standalone HTML files with SVG graphics.

    ## Output

    Always produce a single self-contained `.html` file with inline SVG.
""")


def test_portable_html_artifact_skill_gets_fast_runtime_defaults(tmp_path):
    _make_skill(tmp_path, "architecture-diagram", _PORTABLE_HTML_ARTIFACT)
    skills = load_skills_dir(tmp_path)
    s = skills[0]
    assert s.context == "fork"
    assert s.tools == ["read", "glob", "write", "edit", "analyze"]
    assert s.output_budget == 32768
    assert s.stop_after_write is False
    assert s.chat_template_kwargs == {
        "enable_thinking": False,
        "preserve_thinking": False,
    }


_EXPLICIT_INLINE_ARTIFACT = textwrap.dedent("""\
    ---
    name: architecture-diagram
    context: inline
    tools: [read]
    output_budget: 100
    stop_after_write: false
    chat_template_kwargs:
      enable_thinking: true
    ---
    Create professional, standalone HTML files with SVG graphics.
    Always produce a single self-contained `.html` file with inline SVG.
""")


def test_explicit_artifact_frontmatter_beats_fast_runtime_defaults(tmp_path):
    _make_skill(tmp_path, "architecture-diagram", _EXPLICIT_INLINE_ARTIFACT)
    skills = load_skills_dir(tmp_path)
    s = skills[0]
    assert s.context == "inline"
    assert s.tools == ["read"]
    assert s.output_budget == 100
    assert s.stop_after_write is False
    assert s.chat_template_kwargs == {"enable_thinking": True}
