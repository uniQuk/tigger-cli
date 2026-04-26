from tigger.types import ToolDef
from tigger.permissions import check


def _tool(name="bash", read_only=False):
    return ToolDef(name=name, description="", parameters={},
                   func=lambda a: "", read_only=read_only)


def test_read_only_always_permitted():
    t = _tool(read_only=True)
    for mode in ("allow", "ask", "bypass"):
        assert check(t, mode, {}, bash_safe_prefixes=[]) is True


def test_bypass_permits_everything():
    t = _tool()
    assert check(t, "bypass", {}, bash_safe_prefixes=[]) is True


def test_bash_safe_prefix_allow():
    t = _tool(name="bash")
    prefixes = ["git log", "ls"]
    assert check(t, "allow", {"command": "git log --oneline"}, bash_safe_prefixes=prefixes) is True
    assert check(t, "allow", {"command": "rm -rf /"}, bash_safe_prefixes=prefixes) is False


def test_unknown_tool_ask_denied():
    t = _tool(name="write")
    assert check(t, "ask", {}, bash_safe_prefixes=[]) is False


def test_write_tool_allow_approved():
    t = _tool(name="write")
    assert check(t, "allow", {}, bash_safe_prefixes=[]) is True


def test_unknown_tool_allow_denied():
    t = _tool(name="some_unknown_tool")
    assert check(t, "allow", {}, bash_safe_prefixes=[]) is False


# --- Shell metacharacter injection coverage ---

import pytest

_METACHARACTERS = [";", "|", "&", "`", "$", "\n", "\\", "(", ")", "{", "}", "<", ">"]


@pytest.mark.parametrize("char", _METACHARACTERS)
def test_shell_metachar_blocks_safe_prefix(char):
    """Each shell metacharacter individually blocks a command even with a safe prefix."""
    t = _tool(name="bash")
    cmd = f"git log {char} echo pwned"
    assert check(t, "allow", {"command": cmd}, bash_safe_prefixes=["git log"]) is False


def test_safe_prefix_no_metachar_passes():
    t = _tool(name="bash")
    assert check(t, "allow", {"command": "git log --oneline"}, bash_safe_prefixes=["git log"]) is True


def test_exact_safe_prefix_passes():
    t = _tool(name="bash")
    assert check(t, "allow", {"command": "git log"}, bash_safe_prefixes=["git log"]) is True


def test_empty_safe_prefixes_denies_all():
    t = _tool(name="bash")
    assert check(t, "allow", {"command": "ls"}, bash_safe_prefixes=[]) is False


# F038 regression: word-boundary check on safe prefix matching.

def test_safe_prefix_requires_word_boundary():
    t = _tool(name="bash")
    prefixes = ["git log"]
    # Exact match wins.
    assert check(t, "allow", {"command": "git log"}, bash_safe_prefixes=prefixes) is True
    # Followed by space-delimited args wins.
    assert check(t, "allow", {"command": "git log --oneline"}, bash_safe_prefixes=prefixes) is True
    # Same prefix, no word boundary — escalation attempt — must be rejected.
    assert check(t, "allow", {"command": "git logfoo --oneline"}, bash_safe_prefixes=prefixes) is False


def test_safe_prefix_metachar_guard_catches_chained_command():
    """Even a valid prefix on a word boundary must not allow shell chaining."""
    t = _tool(name="bash")
    prefixes = ["git log"]
    assert check(t, "allow", {"command": "git log; rm -rf /"}, bash_safe_prefixes=prefixes) is False
    assert check(t, "allow", {"command": "git log && touch x"}, bash_safe_prefixes=prefixes) is False


def test_safe_prefix_trailing_space_normalised():
    """Legacy configs with trailing-space prefixes (e.g. 'git ') keep working."""
    t = _tool(name="bash")
    prefixes = ["git "]
    assert check(t, "allow", {"command": "git status"}, bash_safe_prefixes=prefixes) is True
    assert check(t, "allow", {"command": "gitfoo"}, bash_safe_prefixes=prefixes) is False
