from __future__ import annotations
import pathlib
import textwrap
from tigger.skills import load_agents_dir, load_agents, AgentDef


def _make_agent(
    agents_dir: pathlib.Path,
    filename: str,
    content: str,
) -> pathlib.Path:
    """Create an agent .md file in agents_dir. Returns the file path."""
    agents_dir.mkdir(exist_ok=True)
    path = agents_dir / filename
    path.write_text(content)
    return path


_BASIC = textwrap.dedent("""\
    ---
    name: test-agent
    description: A test agent for verification
    tools:
      - read
      - grep
    model: inherit
    ---
    You are a test agent. Follow instructions carefully.
""")

_NO_NAME = textwrap.dedent("""\
    ---
    description: Agent without explicit name
    tools: [read]
    ---
    Body content.
""")

_MINIMAL = textwrap.dedent("""\
    ---
    name: minimal
    ---
    Minimal agent body.
""")


def test_load_agents_dir_basic(tmp_path):
    _make_agent(tmp_path, "test-agent.md", _BASIC)
    agents = load_agents_dir(tmp_path)
    assert len(agents) == 1
    assert agents[0].name == "test-agent"
    assert agents[0].description == "A test agent for verification"
    assert agents[0].tools == ["read", "grep"]
    assert agents[0].model == "inherit"
    assert "You are a test agent" in agents[0].system_prompt


def test_load_agents_dir_system_prompt_from_body(tmp_path):
    _make_agent(tmp_path, "test-agent.md", _BASIC)
    agents = load_agents_dir(tmp_path)
    assert agents[0].system_prompt == "You are a test agent. Follow instructions carefully."


def test_load_agents_dir_multiple_sorted(tmp_path):
    _make_agent(tmp_path, "beta.md", textwrap.dedent("""\
        ---
        name: beta
        ---
        Beta agent.
    """))
    _make_agent(tmp_path, "alpha.md", textwrap.dedent("""\
        ---
        name: alpha
        ---
        Alpha agent.
    """))
    agents = load_agents_dir(tmp_path)
    assert len(agents) == 2
    assert agents[0].name == "alpha"
    assert agents[1].name == "beta"


def test_load_agents_dir_name_defaults_to_filename_stem(tmp_path):
    _make_agent(tmp_path, "my-agent.md", _NO_NAME)
    agents = load_agents_dir(tmp_path)
    assert len(agents) == 1
    assert agents[0].name == "my-agent"


def test_load_agents_dir_description_parsed(tmp_path):
    _make_agent(tmp_path, "test-agent.md", _BASIC)
    agents = load_agents_dir(tmp_path)
    assert agents[0].description == "A test agent for verification"


def test_load_agents_dir_description_defaults_empty(tmp_path):
    _make_agent(tmp_path, "minimal.md", _MINIMAL)
    agents = load_agents_dir(tmp_path)
    assert agents[0].description == ""


def test_load_agents_dir_ignores_non_md_files(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    _make_agent(tmp_path, "test-agent.md", _BASIC)
    (tmp_path / "README.txt").write_text("not an agent")
    (tmp_path / "notes.py").write_text("not an agent")
    agents = load_agents_dir(tmp_path)
    assert len(agents) == 1


def test_load_agents_dir_skips_directories(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    _make_agent(tmp_path, "test-agent.md", _BASIC)
    (tmp_path / "subdir").mkdir()
    agents = load_agents_dir(tmp_path)
    assert len(agents) == 1


def test_load_agents_dir_skips_md_without_frontmatter(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "bad.md").write_text("No frontmatter here, just text.")
    agents = load_agents_dir(tmp_path)
    assert agents == []


def test_load_agents_dir_empty_directory(tmp_path):
    assert load_agents_dir(tmp_path) == []


def test_load_agents_dir_nonexistent(tmp_path):
    assert load_agents_dir(tmp_path / "no-such-dir") == []


def test_load_agents_dir_minimal_agent(tmp_path):
    _make_agent(tmp_path, "minimal.md", _MINIMAL)
    agents = load_agents_dir(tmp_path)
    assert len(agents) == 1
    assert agents[0].name == "minimal"
    assert agents[0].tools == []
    assert agents[0].model is None
    assert agents[0].description == ""


def test_load_agents_flat_format_still_works(tmp_path):
    """Existing flat agents.md format continues to load correctly."""
    flat_file = tmp_path / "agents.md"
    flat_file.write_text(textwrap.dedent("""\
        ---
        name: old-agent
        system_prompt: You are an old-style agent.
        tools: [read, grep]
        ---
        Body is ignored in flat format.
    """))
    agents = load_agents(flat_file)
    assert len(agents) == 1
    assert agents[0].name == "old-agent"
    assert agents[0].system_prompt == "You are an old-style agent."


def test_agent_def_no_internal_field():
    agent = AgentDef(name="test", system_prompt="prompt", tools=[])
    assert not hasattr(agent, "internal")


def test_skill_def_no_internal_field():
    from tigger.skills import SkillDef
    skill = SkillDef(name="test", triggers=[], tools=[], context="inline", body="body")
    assert not hasattr(skill, "internal")
