import pathlib, tempfile, textwrap
from newcli.types import ToolCallRecord, ToolEndEvent, Config, RunContext
from newcli.hooks import HookRegistry, run_before, run_after, load_hooks

def _ctx():
    cfg = Config(base_url="http://x", model="m")
    return RunContext(config=cfg, messages=[], system_prompt="")

def test_run_before_modifies_call():
    reg = HookRegistry()
    reg.before.setdefault("read", []).append(
        lambda call, ctx: ToolCallRecord(call.call_id, call.name, {"path": "/modified"})
    )
    call = ToolCallRecord("c1", "read", {"path": "/original"})
    result = run_before(call, _ctx(), reg)
    assert result.args["path"] == "/modified"

def test_run_after_modifies_event():
    reg = HookRegistry()
    reg.after.setdefault("bash", []).append(
        lambda e, ctx: ToolEndEvent(e.call_id, e.name, "overridden")
    )
    ev = ToolEndEvent("c1", "bash", "original")
    result = run_after(ev, _ctx(), reg)
    assert result.output == "overridden"

def test_wildcard_before_hook():
    reg = HookRegistry()
    log = []
    reg.before.setdefault("*", []).append(lambda c, ctx: (log.append(c.name), c)[1])
    call = ToolCallRecord("c1", "read", {})
    run_before(call, _ctx(), reg)
    assert "read" in log

def test_wildcard_after_hook():
    reg = HookRegistry()
    log = []
    reg.after.setdefault("*", []).append(lambda e, ctx: (log.append(e.name), e)[1])
    run_after(ToolEndEvent("c1", "bash", "out"), _ctx(), reg)
    assert "bash" in log

def test_multiple_hooks_chain():
    reg = HookRegistry()
    reg.before.setdefault("write", []).extend([
        lambda c, ctx: ToolCallRecord(c.call_id, c.name, {**c.args, "step": 1}),
        lambda c, ctx: ToolCallRecord(c.call_id, c.name, {**c.args, "step": 2}),
    ])
    call = ToolCallRecord("c1", "write", {})
    result = run_before(call, _ctx(), reg)
    assert result.args["step"] == 2

def test_load_hooks_from_file():
    src = textwrap.dedent("""
        from newcli.hooks import on_before
        @on_before("read")
        def my_hook(call, ctx):
            return call
    """)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(src)
        p = pathlib.Path(f.name)
    reg = load_hooks(p)
    assert "read" in reg.before

def test_load_hooks_missing_file_returns_empty():
    reg = load_hooks(pathlib.Path("/no/such/hooks.py"))
    assert reg.before == {} and reg.after == {}
