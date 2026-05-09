import textwrap, pathlib, tempfile
from io import StringIO
from unittest.mock import patch

from tigger.commands.skills import cmd_skills
from tigger.skills import SkillDef, load_skills, load_skills_dir
from tigger.types import Config, RunContext, Message


def _ctx() -> RunContext:
    return RunContext(
        config=Config(base_url="http://localhost", model="test"),
        messages=[],
        system_prompt="",
    )


def _basic_skills() -> list[SkillDef]:
    return [
        SkillDef(
            name="review",
            triggers=["/review"],
            tools=["read", "grep"],
            context="inline",
            body="Review the code at $ARGUMENTS. Check for logic errors.",
        ),
        SkillDef(
            name="deploy",
            triggers=["/deploy"],
            tools=["bash"],
            context="fork",
            body="Deploy the service.",
        ),
    ]


def test_preview_shows_rendered_prompt(capsys):
    skills = _basic_skills()
    cmd_skills("preview review", _ctx(), skills=skills)
    out = capsys.readouterr().out
    assert "review" in out
    assert "triggers:" in out
    assert "context:" in out
    assert "tools:" in out
    # The rendered body should appear with $ARGUMENTS preserved as placeholder
    assert "Review the code at $ARGUMENTS" in out


def test_preview_not_found(capsys):
    skills = _basic_skills()
    cmd_skills("preview nonexistent", _ctx(), skills=skills)
    out = capsys.readouterr().out
    assert "Skill not found: nonexistent" in out
    assert "Available:" in out


def test_preview_no_name(capsys):
    skills = _basic_skills()
    cmd_skills("preview", _ctx(), skills=skills)
    out = capsys.readouterr().out
    assert "Usage:" in out


def test_preview_with_references(capsys):
    skill = SkillDef(
        name="guided",
        triggers=["/guided"],
        tools=["read"],
        context="inline",
        body="Follow the guide for $ARGUMENTS.",
        references=[("style.md", "Use consistent naming.")],
        inject_references=True,
    )
    cmd_skills("preview guided", _ctx(), skills=[skill])
    out = capsys.readouterr().out
    assert "references:" in out
    assert "style.md" in out
    # Reference content should be injected into the rendered output
    assert "Use consistent naming." in out


def test_preview_without_inject_references(capsys):
    skill = SkillDef(
        name="raw",
        triggers=["/raw"],
        tools=[],
        context="inline",
        body="Do the thing.",
        references=[("notes.md", "Some notes.")],
        inject_references=False,
    )
    cmd_skills("preview raw", _ctx(), skills=[skill])
    out = capsys.readouterr().out
    # Reference metadata shown but content NOT injected
    assert "notes.md" in out
    assert "Some notes." not in out


def test_preview_no_arguments_placeholder(capsys):
    """Skills without $ARGUMENTS get user input appended after ---."""
    skill = SkillDef(
        name="deploy",
        triggers=["/deploy"],
        tools=["bash"],
        context="fork",
        body="Deploy the service.",
    )
    cmd_skills("preview deploy", _ctx(), skills=[skill])
    out = capsys.readouterr().out
    assert "Deploy the service." in out


def test_list_still_works(capsys):
    """Calling /skills without subcommand still lists skills."""
    skills = _basic_skills()
    cmd_skills("", _ctx(), skills=skills)
    out = capsys.readouterr().out
    assert "review" in out
    assert "deploy" in out


def test_list_empty(capsys):
    cmd_skills("", _ctx(), skills=[])
    out = capsys.readouterr().out
    assert "No skills loaded." in out


def test_preview_from_skills_dir(capsys, tmp_path):
    """Integration: load from directory then preview."""
    skill_dir = tmp_path / "skills" / "checker"
    skill_dir.mkdir(parents=True)
    refs_dir = skill_dir / "references"
    refs_dir.mkdir()
    (refs_dir / "rules.md").write_text("Always lint first.")
    (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: checker
        tools: [bash]
        context: inline
        ---
        Check $ARGUMENTS against the rules.
    """))
    skills = load_skills_dir(tmp_path / "skills")
    assert len(skills) == 1
    cmd_skills("preview checker", _ctx(), skills=skills)
    out = capsys.readouterr().out
    assert "checker" in out
    assert "rules.md" in out
    assert "Always lint first." in out
    assert "Check $ARGUMENTS" in out
