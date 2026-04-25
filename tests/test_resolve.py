from __future__ import annotations
import pathlib
import textwrap
import pytest
from tigger.resolve import resolve_file, resolve_skills, resolve_agents, resolve_modes, is_global_config, seed_global


def _make_skill(base_dir: pathlib.Path, name: str, body: str = "Body.") -> None:
    """Create a minimal skill directory with SKILL.md."""
    skill_dir = base_dir / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        ---
        {body}
    """))


def _make_agent_file(base_dir: pathlib.Path, name: str, body: str = "Agent body.") -> None:
    """Create a minimal agent .md file in an agents/ directory."""
    agents_dir = base_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{name}.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: {name} agent
        tools: [read]
        ---
        {body}
    """))


def _make_mode_file(base_dir: pathlib.Path, name: str, body: str = "") -> None:
    """Create a minimal mode .md file in a modes/ directory."""
    modes_dir = base_dir / "modes"
    modes_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\n---\n"
    if body:
        content += body + "\n"
    (modes_dir / f"{name}.md").write_text(content)


def _make_flat_agents(base_dir: pathlib.Path, name: str) -> None:
    """Create a flat agents.md file with one agent."""
    (base_dir / "agents.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        system_prompt: Flat format prompt for {name}.
        tools: [read]
        ---
        Ignored body.
    """))


# --- resolve_file ---

def test_resolve_file_project_wins(tmp_path):
    project = tmp_path / "project"
    global_ = tmp_path / "global"
    for d in (project, global_):
        d.mkdir()
        (d / "system.md").write_text(f"from {d.name}")
    result = resolve_file("system.md", project, global_)
    assert result == project / "system.md"


def test_resolve_file_falls_back_to_global(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    global_ = tmp_path / "global"
    global_.mkdir()
    (global_ / "system.md").write_text("global")
    result = resolve_file("system.md", project, global_)
    assert result == global_ / "system.md"


def test_resolve_file_falls_back_to_bundled(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "system.md").write_text("bundled")
    result = resolve_file("system.md", project, None, bundled)
    assert result == bundled / "system.md"


def test_resolve_file_returns_none_when_missing(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    result = resolve_file("system.md", project, None)
    assert result is None


def test_resolve_file_none_dirs(tmp_path):
    result = resolve_file("system.md", None, None)
    assert result is None


def test_resolve_file_none_project_uses_global(tmp_path):
    global_ = tmp_path / "global"
    global_.mkdir()
    (global_ / "hooks.py").write_text("# hooks")
    result = resolve_file("hooks.py", None, global_)
    assert result == global_ / "hooks.py"


# --- resolve_skills ---

def test_resolve_skills_merges_tiers(tmp_path):
    project = tmp_path / "project"
    global_ = tmp_path / "global"
    internal = tmp_path / "internal"
    _make_skill(project, "user-skill")
    _make_skill(global_, "global-skill")
    _make_skill(internal, "internal-skill")
    skills = resolve_skills(project, global_, internal)
    names = {s.name for s in skills}
    assert names == {"user-skill", "global-skill", "internal-skill"}


def test_resolve_skills_project_shadows_global(tmp_path):
    project = tmp_path / "project"
    global_ = tmp_path / "global"
    _make_skill(project, "debug", body="Project debug.")
    _make_skill(global_, "debug", body="Global debug.")
    skills = resolve_skills(project, global_, tmp_path / "empty")
    assert len(skills) == 1
    assert skills[0].name == "debug"
    assert "Project debug" in skills[0].body


def test_resolve_skills_project_shadows_internal(tmp_path):
    project = tmp_path / "project"
    internal = tmp_path / "internal"
    _make_skill(project, "_debug", body="Custom debug.")
    _make_skill(internal, "_debug", body="Internal debug.")
    skills = resolve_skills(project, None, internal)
    assert len(skills) == 1
    assert "Custom debug" in skills[0].body


def test_resolve_skills_internal_detected_by_name(tmp_path):
    internal = tmp_path / "internal"
    _make_skill(internal, "_debug")
    skills = resolve_skills(None, None, internal)
    assert len(skills) == 1
    assert skills[0].name.startswith("_")


def test_resolve_skills_global_not_internal(tmp_path):
    global_ = tmp_path / "global"
    _make_skill(global_, "my-skill")
    skills = resolve_skills(None, global_, tmp_path / "empty")
    assert len(skills) == 1
    assert not skills[0].name.startswith("_")


def test_resolve_skills_only_one_tier(tmp_path):
    global_ = tmp_path / "global"
    _make_skill(global_, "only-skill")
    skills = resolve_skills(None, global_, tmp_path / "no-internal")
    assert len(skills) == 1
    assert skills[0].name == "only-skill"


def test_resolve_skills_empty_dirs(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    skills = resolve_skills(project, None, tmp_path / "no-internal")
    assert skills == []


def test_resolve_skills_none_dirs(tmp_path):
    skills = resolve_skills(None, None, tmp_path / "no-internal")
    assert skills == []


# --- resolve_agents ---

def test_resolve_agents_merges_tiers(tmp_path):
    project = tmp_path / "project"
    global_ = tmp_path / "global"
    internal = tmp_path / "internal"
    _make_agent_file(project, "user-agent")
    _make_agent_file(global_, "global-agent")
    _make_agent_file(internal, "internal-agent")
    agents = resolve_agents(project, global_, internal)
    names = {a.name for a in agents}
    assert names == {"user-agent", "global-agent", "internal-agent"}


def test_resolve_agents_project_shadows_internal(tmp_path):
    project = tmp_path / "project"
    internal = tmp_path / "internal"
    _make_agent_file(project, "_test-engineer", body="Custom version.")
    _make_agent_file(internal, "_test-engineer", body="Internal version.")
    agents = resolve_agents(project, None, internal)
    assert len(agents) == 1
    assert "Custom version" in agents[0].system_prompt


def test_resolve_agents_internal_detected_by_name(tmp_path):
    internal = tmp_path / "internal"
    _make_agent_file(internal, "_test-engineer")
    agents = resolve_agents(None, None, internal)
    assert len(agents) == 1
    assert agents[0].name.startswith("_")


def test_resolve_agents_directory_shadows_flat_within_tier(tmp_path):
    """Within a tier, directory agents win over flat agents.md on name collision."""
    tier = tmp_path / "tier"
    _make_agent_file(tier, "my-agent", body="From directory.")
    _make_flat_agents(tier, "my-agent")
    agents = resolve_agents(tier, None, tmp_path / "empty")
    assert len(agents) == 1
    assert "From directory" in agents[0].system_prompt


def test_resolve_agents_empty_dirs(tmp_path):
    agents = resolve_agents(None, None, tmp_path / "no-internal")
    assert agents == []


# --- is_global_config ---

def test_is_global_config_true(tmp_path, monkeypatch):
    monkeypatch.setattr("tigger.resolve.home_config_dir", lambda: tmp_path / ".tigger")
    cfg = tmp_path / ".tigger" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.touch()
    assert is_global_config(cfg) is True


def test_is_global_config_false(tmp_path, monkeypatch):
    monkeypatch.setattr("tigger.resolve.home_config_dir", lambda: tmp_path / ".tigger")
    cfg = tmp_path / "project" / ".tigger" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.touch()
    assert is_global_config(cfg) is False


# --- seed_global ---

def test_seed_global_copies_skills_and_agents(tmp_path):
    internal = tmp_path / "internal"
    _make_skill(internal, "_debug")
    _make_agent_file(internal, "_test-engineer")
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    result = seed_global(global_dir, internal)
    assert result is True
    assert (global_dir / "skills" / "_debug" / "SKILL.md").exists()
    assert (global_dir / "agents" / "_test-engineer.md").exists()


def test_seed_global_skips_existing(tmp_path):
    internal = tmp_path / "internal"
    _make_skill(internal, "_debug")
    global_dir = tmp_path / "global"
    # Pre-populate with custom content
    custom_dir = global_dir / "skills" / "_debug"
    custom_dir.mkdir(parents=True)
    (custom_dir / "SKILL.md").write_text("my custom debug")
    result = seed_global(global_dir, internal)
    assert result is False
    # Custom content preserved
    assert (global_dir / "skills" / "_debug" / "SKILL.md").read_text() == "my custom debug"


def test_seed_global_skips_prefixed_if_non_prefixed_exists(tmp_path):
    """If user has debug/ from a prior seed, don't also create _debug/."""
    internal = tmp_path / "internal"
    _make_skill(internal, "_debug")
    _make_agent_file(internal, "_test-engineer")
    global_dir = tmp_path / "global"
    # Pre-populate with non-prefixed versions (prior seed)
    custom_dir = global_dir / "skills" / "debug"
    custom_dir.mkdir(parents=True)
    (custom_dir / "SKILL.md").write_text("old debug")
    agents_dir = global_dir / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "test-engineer.md").write_text("old agent")
    result = seed_global(global_dir, internal)
    assert result is False
    assert not (global_dir / "skills" / "_debug").exists()
    assert not (global_dir / "agents" / "_test-engineer.md").exists()


def test_seed_global_adds_new_skills_alongside_existing(tmp_path):
    internal = tmp_path / "internal"
    _make_skill(internal, "_debug")
    _make_skill(internal, "_commit")
    global_dir = tmp_path / "global"
    # Pre-populate _debug only
    custom_dir = global_dir / "skills" / "_debug"
    custom_dir.mkdir(parents=True)
    (custom_dir / "SKILL.md").write_text("my custom debug")
    result = seed_global(global_dir, internal)
    assert result is True  # _commit was new
    assert (global_dir / "skills" / "_debug" / "SKILL.md").read_text() == "my custom debug"
    assert (global_dir / "skills" / "_commit" / "SKILL.md").exists()


def test_seed_global_no_internal_dir(tmp_path):
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    result = seed_global(global_dir, tmp_path / "nonexistent")
    assert result is False


def test_seed_global_idempotent(tmp_path):
    internal = tmp_path / "internal"
    _make_skill(internal, "_debug")
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    seed_global(global_dir, internal)
    # Second call should be a no-op
    result = seed_global(global_dir, internal)
    assert result is False


# --- resolve_modes ---

def test_resolve_modes_merges_tiers(tmp_path):
    project = tmp_path / "project"
    global_ = tmp_path / "global"
    internal = tmp_path / "internal"
    _make_mode_file(project, "custom", body="Custom mode.")
    _make_mode_file(global_, "plan", body="Global plan.")
    _make_mode_file(internal, "act")
    modes = resolve_modes(project, global_, internal)
    names = {m.name for m in modes}
    assert names == {"custom", "plan", "act"}


def test_resolve_modes_project_shadows_global(tmp_path):
    project = tmp_path / "project"
    global_ = tmp_path / "global"
    _make_mode_file(project, "plan", body="Project plan.")
    _make_mode_file(global_, "plan", body="Global plan.")
    modes = resolve_modes(project, global_, tmp_path / "empty")
    assert len(modes) == 1
    assert "Project plan" in modes[0].body


def test_resolve_modes_empty_dirs(tmp_path):
    modes = resolve_modes(None, None, tmp_path / "no-internal")
    assert modes == []


# --- seed_global (modes) ---

def test_seed_global_copies_modes(tmp_path):
    internal = tmp_path / "internal"
    _make_mode_file(internal, "act")
    _make_mode_file(internal, "plan", body="Plan mode.")
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    result = seed_global(global_dir, internal)
    assert result is True
    assert (global_dir / "modes" / "act.md").exists()
    assert (global_dir / "modes" / "plan.md").exists()


def test_seed_global_skips_existing_modes(tmp_path):
    internal = tmp_path / "internal"
    _make_mode_file(internal, "plan", body="Internal plan.")
    global_dir = tmp_path / "global"
    modes_dir = global_dir / "modes"
    modes_dir.mkdir(parents=True)
    (modes_dir / "plan.md").write_text("my custom plan")
    result = seed_global(global_dir, internal)
    assert result is False
    assert (modes_dir / "plan.md").read_text() == "my custom plan"


def test_seed_global_skips_prefixed_mode_if_non_prefixed_exists(tmp_path):
    internal = tmp_path / "internal"
    _make_mode_file(internal, "_act")
    global_dir = tmp_path / "global"
    modes_dir = global_dir / "modes"
    modes_dir.mkdir(parents=True)
    (modes_dir / "act.md").write_text("existing act")
    result = seed_global(global_dir, internal)
    assert result is False
    assert not (modes_dir / "_act.md").exists()
