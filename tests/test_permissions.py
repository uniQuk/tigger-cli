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


def test_unknown_tool_allow_denied():
    t = _tool(name="write")
    assert check(t, "allow", {}, bash_safe_prefixes=[]) is False
