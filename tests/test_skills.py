import textwrap, pathlib, tempfile
from tigger.skills import (
    load_skills,
    load_agents,
    match_skill,
    warn_on_command_collisions,
    SkillDef,
    AgentDef,
)

SKILLS_MD = textwrap.dedent("""
    ---
    name: review
    triggers: [/review]
    tools: [read, grep, glob]
    context: inline
    ---
    Review the code at $ARGUMENTS. Check for logic errors.

    ---
    name: refactor
    triggers: [/refactor]
    tools: [read, edit, bash]
    context: fork
    ---
    Refactor $ARGUMENTS. Preserve behavior.
""").strip()

AGENTS_MD = textwrap.dedent("""
    ---
    name: reviewer
    system_prompt: |
      You are a careful code reviewer.
    tools: [read, grep, glob]
    model: null
    ---
""").strip()

def _write(content: str) -> pathlib.Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
    f.write(content)
    f.close()
    return pathlib.Path(f.name)

def test_load_skills_count():
    skills = load_skills(_write(SKILLS_MD))
    assert len(skills) == 2

def test_skill_fields():
    skills = load_skills(_write(SKILLS_MD))
    review = next(s for s in skills if s.name == "review")
    assert review.context == "inline"
    assert "read" in review.tools
    assert "/review" in review.triggers

def test_skill_render_substitutes_arguments():
    skills = load_skills(_write(SKILLS_MD))
    review = next(s for s in skills if s.name == "review")
    rendered = review.render("/review src/main.py")
    assert "src/main.py" in rendered
    assert "$ARGUMENTS" not in rendered

def test_match_skill_by_slash():
    skills = load_skills(_write(SKILLS_MD))
    matched = match_skill("/review src/foo.py", skills)
    assert matched is not None and matched.name == "review"

def test_match_skill_no_match():
    skills = load_skills(_write(SKILLS_MD))
    assert match_skill("just a question", skills) is None

def test_load_skills_missing_file():
    assert load_skills(pathlib.Path("/no/skills.md")) == []

def test_load_agents():
    agents = load_agents(_write(AGENTS_MD))
    assert len(agents) == 1
    assert agents[0].name == "reviewer"
    assert "reviewer" in agents[0].system_prompt.lower()

def test_load_agents_missing_file():
    assert load_agents(pathlib.Path("/no/agents.md")) == []


# --- trigger boundary regression tests for F002 ---

SHORT_TRIGGER_MD = textwrap.dedent("""
    ---
    name: m_skill
    triggers: [/m]
    tools: []
    context: inline
    ---
    body
""").strip()


def test_short_trigger_does_not_shadow_longer_command():
    """F002 regression: skill with trigger /m must not match /memory."""
    skills = load_skills(_write(SHORT_TRIGGER_MD))
    assert match_skill("/memory", skills) is None
    assert match_skill("/memory list", skills) is None


def test_short_trigger_matches_exact():
    skills = load_skills(_write(SHORT_TRIGGER_MD))
    assert match_skill("/m", skills) is not None


def test_short_trigger_matches_with_args():
    skills = load_skills(_write(SHORT_TRIGGER_MD))
    assert match_skill("/m foo bar", skills) is not None


def test_trigger_does_not_match_unrelated_prefix():
    skills = load_skills(_write(SKILLS_MD))
    # /reviewer should not match /review trigger.
    assert match_skill("/reviewer", skills) is None


def test_warn_on_command_collisions_emits_for_collision(capsys):
    skills = load_skills(_write(textwrap.dedent("""
        ---
        name: memory_clone
        triggers: [/memory]
        tools: []
        context: inline
        ---
        body
    """).strip()))
    warnings = warn_on_command_collisions(skills, ["memory", "model"])
    assert len(warnings) == 1
    assert "/memory" in warnings[0]
    captured = capsys.readouterr()
    # Iter 70: routed through ui.console (stdout) for theming.
    assert "/memory" in (captured.out + captured.err)


def test_warn_on_command_collisions_silent_when_no_collision(capsys):
    skills = load_skills(_write(SKILLS_MD))
    warnings = warn_on_command_collisions(skills, ["memory", "model"])
    assert warnings == []
    captured = capsys.readouterr()
    # Iter 70: warnings now route through ui.console (stdout). Clean inputs
    # should emit nothing on either stream.
    assert captured.out == ""
    assert captured.err == ""
