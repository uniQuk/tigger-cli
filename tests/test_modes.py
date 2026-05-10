from __future__ import annotations
import pathlib
import textwrap
from tigger.skills import load_modes_dir


def _make_mode(
    modes_dir: pathlib.Path,
    filename: str,
    content: str,
) -> pathlib.Path:
    """Create a mode .md file in modes_dir. Returns the file path."""
    modes_dir.mkdir(exist_ok=True)
    path = modes_dir / filename
    path.write_text(content)
    return path


_ACT = textwrap.dedent("""\
    ---
    name: act
    ---
""")

_PLAN = textwrap.dedent("""\
    ---
    name: plan
    ---
    You are in plan mode. Present a plan before acting.
""")

_NO_NAME = textwrap.dedent("""\
    ---
    description: Mode without explicit name
    ---
    Custom mode body.
""")


def test_load_modes_dir_basic(tmp_path):
    _make_mode(tmp_path, "act.md", _ACT)
    _make_mode(tmp_path, "plan.md", _PLAN)
    modes = load_modes_dir(tmp_path)
    assert len(modes) == 2
    assert modes[0].name == "act"
    assert modes[0].body == ""
    assert modes[1].name == "plan"
    assert "plan mode" in modes[1].body


def test_load_modes_dir_name_defaults_to_stem(tmp_path):
    _make_mode(tmp_path, "custom.md", _NO_NAME)
    modes = load_modes_dir(tmp_path)
    assert len(modes) == 1
    assert modes[0].name == "custom"
    assert modes[0].body == "Custom mode body."


def test_load_modes_dir_source_path(tmp_path):
    path = _make_mode(tmp_path, "act.md", _ACT)
    modes = load_modes_dir(tmp_path)
    assert modes[0].source_path == path


def test_load_modes_dir_ignores_non_md(tmp_path):
    _make_mode(tmp_path, "act.md", _ACT)
    (tmp_path / "README.txt").write_text("not a mode")
    (tmp_path / "notes.py").write_text("not a mode")
    modes = load_modes_dir(tmp_path)
    assert len(modes) == 1


def test_load_modes_dir_nonexistent(tmp_path):
    assert load_modes_dir(tmp_path / "no-such-dir") == []


def test_load_modes_dir_empty(tmp_path):
    assert load_modes_dir(tmp_path) == []


def test_load_modes_dir_skips_invalid_frontmatter(tmp_path):
    (tmp_path / "bad.md").write_text("No frontmatter here.")
    modes = load_modes_dir(tmp_path)
    assert modes == []


def test_load_modes_dir_body_with_hr_preserved(tmp_path):
    _make_mode(tmp_path, "custom.md", textwrap.dedent("""\
        ---
        name: custom
        ---
        Before the rule.

        ---

        After the rule.
    """))
    modes = load_modes_dir(tmp_path)
    assert len(modes) == 1
    assert "---" in modes[0].body
    assert "Before the rule." in modes[0].body
    assert "After the rule." in modes[0].body


def test_load_modes_dir_sorted_alphabetically(tmp_path):
    _make_mode(tmp_path, "zeta.md", textwrap.dedent("""\
        ---
        name: zeta
        ---
        Zeta mode.
    """))
    _make_mode(tmp_path, "alpha.md", textwrap.dedent("""\
        ---
        name: alpha
        ---
        Alpha mode.
    """))
    modes = load_modes_dir(tmp_path)
    assert modes[0].name == "alpha"
    assert modes[1].name == "zeta"


def test_load_internal_modes():
    """Verify the bundled internal modes parse correctly."""
    internal_modes = pathlib.Path(__file__).parent.parent / "src" / "tigger" / "internal" / "modes"
    modes = load_modes_dir(internal_modes)
    names = {m.name for m in modes}
    assert "act" in names
    assert "plan" in names
    act = next(m for m in modes if m.name == "act")
    plan = next(m for m in modes if m.name == "plan")
    assert act.body == ""
    assert len(plan.body) > 0
