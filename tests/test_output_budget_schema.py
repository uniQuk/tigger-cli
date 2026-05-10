"""Schema-level tests for the per-skill output budget feature (Unit 1).

Covers SkillDef parsing of the `output_budget` frontmatter field and
Config loading of `output_budget_default`.
"""
from __future__ import annotations

import json
import pathlib

from tigger.config import load_config
from tigger.skills import load_skills_dir, parse_output_budget
from tigger.types import Config, RunContext


# ── parse_output_budget ────────────────────────────────────────────────────

def test_parse_output_budget_missing_returns_none():
    assert parse_output_budget(None) is None


def test_parse_output_budget_integer():
    assert parse_output_budget(2048) == 2048


def test_parse_output_budget_explicit_zero():
    """Distinct from missing: explicit 0 means 'disable the gate'."""
    assert parse_output_budget(0) == 0


def test_parse_output_budget_unbounded_lowercase():
    assert parse_output_budget("unbounded") is None


def test_parse_output_budget_unbounded_uppercase():
    assert parse_output_budget("UNBOUNDED") is None


def test_parse_output_budget_unbounded_mixed_case():
    assert parse_output_budget("Unbounded") is None


def test_parse_output_budget_numeric_string():
    assert parse_output_budget("4096") == 4096


def test_parse_output_budget_garbage_falls_back():
    """Don't crash skill load on malformed values; just disable the gate."""
    assert parse_output_budget("garbage") is None
    assert parse_output_budget(["list"]) is None
    assert parse_output_budget(True) is None  # YAML true is not a budget


# ── SkillDef via load_skills_dir ───────────────────────────────────────────

def _write_skill(root: pathlib.Path, name: str, frontmatter: str) -> None:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\n{frontmatter}---\n# {name}\nbody\n")


def test_skill_with_output_budget_parses(tmp_path):
    _write_skill(tmp_path, "small", "name: small\noutput_budget: 2048\n")
    skills = load_skills_dir(tmp_path)
    assert len(skills) == 1
    assert skills[0].output_budget == 2048


def test_skill_without_output_budget_parses(tmp_path):
    _write_skill(tmp_path, "no_budget", "name: no_budget\n")
    skills = load_skills_dir(tmp_path)
    assert len(skills) == 1
    assert skills[0].output_budget is None


def test_skill_with_unbounded_parses_to_none(tmp_path):
    _write_skill(tmp_path, "unbnd", "name: unbnd\noutput_budget: unbounded\n")
    skills = load_skills_dir(tmp_path)
    assert len(skills) == 1
    assert skills[0].output_budget is None


def test_skill_with_explicit_zero_disables(tmp_path):
    _write_skill(tmp_path, "off", "name: off\noutput_budget: 0\n")
    skills = load_skills_dir(tmp_path)
    assert len(skills) == 1
    assert skills[0].output_budget == 0


# ── Config.output_budget_default ───────────────────────────────────────────

def test_config_default_when_missing(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "default_provider": "p",
        "providers": {"p": {"base_url": "http://x", "api_key": "k", "models": ["m"]}},
    }))
    config = load_config(cfg_path)
    assert config.output_budget_default == 0


def test_config_default_from_json(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "default_provider": "p",
        "providers": {"p": {"base_url": "http://x", "api_key": "k", "models": ["m"]}},
        "output_budget_default": 4096,
    }))
    config = load_config(cfg_path)
    assert config.output_budget_default == 4096


# ── RunContext.output_budget ───────────────────────────────────────────────

def test_run_context_default_output_budget_is_none():
    cfg = Config(base_url="http://x", model="m")
    ctx = RunContext(config=cfg, messages=[], system_prompt="")
    assert ctx.output_budget is None


def test_run_context_explicit_output_budget():
    cfg = Config(base_url="http://x", model="m")
    ctx = RunContext(config=cfg, messages=[], system_prompt="", output_budget=2048)
    assert ctx.output_budget == 2048
