from newcli.types import ToolDef
from newcli.permissions import check


def _tool(name="bash", read_only=False, safe=False):
    return ToolDef(name=name, description="", parameters={},
                   func=lambda a: "", read_only=read_only, safe=safe)


def test_read_only_always_permitted():
    t = _tool(read_only=True)
    for mode in ("auto", "manual", "accept-all"):
        assert check(t, mode, {}, bash_safe_prefixes=[]) is True


def test_accept_all_permits_everything():
    t = _tool()
    assert check(t, "accept-all", {}, bash_safe_prefixes=[]) is True


def test_safe_tool_auto_permitted():
    t = _tool(safe=True)
    assert check(t, "auto", {}, bash_safe_prefixes=[]) is True


def test_safe_tool_manual_not_permitted():
    t = _tool(safe=True)
    assert check(t, "manual", {}, bash_safe_prefixes=[]) is False


def test_bash_safe_prefix_auto():
    t = _tool(name="bash")
    prefixes = ["git log", "ls"]
    assert check(t, "auto", {"command": "git log --oneline"}, bash_safe_prefixes=prefixes) is True
    assert check(t, "auto", {"command": "rm -rf /"}, bash_safe_prefixes=prefixes) is False


def test_unknown_tool_manual_denied():
    t = _tool(name="write")
    assert check(t, "manual", {}, bash_safe_prefixes=[]) is False


def test_unknown_tool_auto_denied():
    t = _tool(name="write")
    assert check(t, "auto", {}, bash_safe_prefixes=[]) is False
