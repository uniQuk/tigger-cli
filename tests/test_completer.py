from newcli.completer import NewcliCompleter
from newcli.skills import SkillDef
from newcli.hooks import HookRegistry
from prompt_toolkit.document import Document


def _completer(extra_skills: list[SkillDef] | None = None) -> NewcliCompleter:
    commands = {"clear": None, "tokens": None, "help": None, "mode": None, "permission": None}
    skills = [
        SkillDef(name="how", triggers=["/how"], tools=[], context="inline", body=""),
    ]
    if extra_skills:
        skills.extend(extra_skills)
    return NewcliCompleter(commands, skills, HookRegistry())


def _completions(completer: NewcliCompleter, text: str) -> list[str]:
    doc = Document(text, cursor_position=len(text))
    return [c.text for c in completer.get_completions(doc, None)]


def test_completer_no_activation_without_slash():
    results = _completions(_completer(), "how")
    assert results == []


def test_completer_no_activation_empty():
    results = _completions(_completer(), "")
    assert results == []


def test_completer_matches_command_prefix():
    results = _completions(_completer(), "/cl")
    assert "/clear" in results


def test_completer_matches_skill_prefix():
    results = _completions(_completer(), "/ho")
    assert "/how" in results


def test_completer_substring_match():
    c = _completer(extra_skills=[
        SkillDef(
            name="architecture-diagram",
            triggers=["/architecture-diagram"],
            tools=[],
            context="inline",
            body="",
        ),
    ])
    results = _completions(c, "/rchi")
    assert "/architecture-diagram" in results


def test_completer_slash_alone_shows_all():
    results = _completions(_completer(), "/")
    assert "/clear" in results
    assert "/how" in results


def test_completer_case_insensitive():
    results = _completions(_completer(), "/CL")
    assert "/clear" in results


def test_completer_no_duplicates():
    results = _completions(_completer(), "/")
    assert len(results) == len(set(results))
