"""Tests for the declarative hook system."""
from __future__ import annotations
import pathlib
import textwrap
from tigger.hooks import (
    HookDef, HookResult, load_hooks_dir, evaluate_hooks,
    # Legacy API — kept for backward compat tests
    HookRegistry, run_before, run_after, load_hooks,
)
from tigger.types import ToolCallRecord, ToolEndEvent, Config, RunContext


def _ctx():
    cfg = Config(base_url="http://x", model="m")
    return RunContext(config=cfg, messages=[], system_prompt="")


def _make_hook(hooks_dir: pathlib.Path, filename: str, content: str) -> pathlib.Path:
    hooks_dir.mkdir(parents=True, exist_ok=True)
    path = hooks_dir / filename
    path.write_text(content)
    return path


_BLOCK_RM = textwrap.dedent("""\
    ---
    name: block-rm
    event: PreToolUse
    matcher: bash
    action: block
    ---
    Dangerous rm command detected.
""")

_WARN_WRITE = textwrap.dedent("""\
    ---
    name: warn-write
    event: PostToolUse
    matcher: write|edit
    action: warn
    ---
    File modified. Review changes.
""")

_DISABLED = textwrap.dedent("""\
    ---
    name: disabled-hook
    event: PreToolUse
    matcher: bash
    action: block
    enabled: false
    ---
    Should not fire.
""")

_MINIMAL = textwrap.dedent("""\
    ---
    name: minimal
    event: PreToolUse
    ---
    Minimal hook.
""")

_SESSION = textwrap.dedent("""\
    ---
    name: setup
    event: SessionStart
    action: warn
    ---
    Welcome!
""")


# --- load_hooks_dir ---

class TestLoadHooksDir:
    def test_basic_load(self, tmp_path):
        _make_hook(tmp_path, "block-rm.md", _BLOCK_RM)
        hooks = load_hooks_dir(tmp_path)
        assert len(hooks) == 1
        assert hooks[0].name == "block-rm"
        assert hooks[0].event == "PreToolUse"
        assert hooks[0].matcher == "bash"
        assert hooks[0].action == "block"
        assert "Dangerous rm" in hooks[0].body

    def test_multiple_sorted(self, tmp_path):
        _make_hook(tmp_path, "warn.md", _WARN_WRITE)
        _make_hook(tmp_path, "block.md", _BLOCK_RM)
        hooks = load_hooks_dir(tmp_path)
        assert len(hooks) == 2
        assert hooks[0].name == "block-rm"  # block.md sorts first

    def test_name_defaults_to_stem(self, tmp_path):
        content = "---\nevent: PreToolUse\n---\nBody."
        _make_hook(tmp_path, "my-hook.md", content)
        hooks = load_hooks_dir(tmp_path)
        assert hooks[0].name == "my-hook"

    def test_matcher_defaults_to_all(self, tmp_path):
        _make_hook(tmp_path, "minimal.md", _MINIMAL)
        assert load_hooks_dir(tmp_path)[0].matcher == ".*"

    def test_enabled_defaults_true(self, tmp_path):
        _make_hook(tmp_path, "minimal.md", _MINIMAL)
        assert load_hooks_dir(tmp_path)[0].enabled is True

    def test_enabled_false_parsed(self, tmp_path):
        _make_hook(tmp_path, "disabled.md", _DISABLED)
        assert load_hooks_dir(tmp_path)[0].enabled is False

    def test_ignores_non_md(self, tmp_path):
        _make_hook(tmp_path, "hook.md", _BLOCK_RM)
        (tmp_path / "notes.txt").write_text("not a hook")
        assert len(load_hooks_dir(tmp_path)) == 1

    def test_skips_invalid_event(self, tmp_path):
        _make_hook(tmp_path, "bad.md", "---\nname: bad\naction: block\n---\nNo event.")
        assert load_hooks_dir(tmp_path) == []

    def test_empty_dir(self, tmp_path):
        assert load_hooks_dir(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path):
        assert load_hooks_dir(tmp_path / "nope") == []

    def test_source_path_set(self, tmp_path):
        _make_hook(tmp_path, "hook.md", _BLOCK_RM)
        assert load_hooks_dir(tmp_path)[0].source_path == tmp_path / "hook.md"


# --- evaluate_hooks ---

class TestEvaluateHooks:
    def test_block(self):
        hook = HookDef(name="b", event="PreToolUse", matcher="bash",
                       action="block", body="Blocked!")
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [hook])
        assert result.blocked is True
        assert "Blocked!" in result.messages

    def test_non_matching_skipped(self):
        hook = HookDef(name="b", event="PreToolUse", matcher="bash",
                       action="block", body="Blocked!")
        result = evaluate_hooks("PreToolUse", {"tool_name": "read"}, [hook])
        assert result.blocked is False
        assert result.messages == []

    def test_warn_no_block(self):
        hook = HookDef(name="w", event="PreToolUse", matcher=".*",
                       action="warn", body="Careful!")
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [hook])
        assert result.blocked is False
        assert "Careful!" in result.messages

    def test_allow_silent(self):
        hook = HookDef(name="a", event="PreToolUse", matcher=".*",
                       action="allow", body="Ignored")
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [hook])
        assert result.blocked is False
        assert result.messages == []

    def test_multiple_one_blocks(self):
        hooks = [
            HookDef(name="w", event="PreToolUse", matcher="bash",
                    action="warn", body="Warning!"),
            HookDef(name="b", event="PreToolUse", matcher="bash",
                    action="block", body="Blocked!"),
        ]
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, hooks)
        assert result.blocked is True
        assert len(result.messages) == 2

    def test_disabled_skipped(self):
        hook = HookDef(name="d", event="PreToolUse", matcher=".*",
                       action="block", body="Nope", enabled=False)
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [hook])
        assert result.blocked is False

    def test_session_start(self):
        hook = HookDef(name="s", event="SessionStart",
                       action="warn", body="Welcome!")
        result = evaluate_hooks("SessionStart", {}, [hook])
        assert "Welcome!" in result.messages

    def test_no_hooks(self):
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [])
        assert result.blocked is False
        assert result.messages == []

    def test_wildcard_matcher(self):
        hook = HookDef(name="all", event="PreToolUse", matcher=".*",
                       action="warn", body="Logged")
        result = evaluate_hooks("PreToolUse", {"tool_name": "anything"}, [hook])
        assert "Logged" in result.messages

    def test_regex_matcher(self):
        hook = HookDef(name="w", event="PreToolUse", matcher="write|edit",
                       action="warn", body="Write op")
        assert evaluate_hooks("PreToolUse", {"tool_name": "write"}, [hook]).messages
        assert evaluate_hooks("PreToolUse", {"tool_name": "edit"}, [hook]).messages
        assert not evaluate_hooks("PreToolUse", {"tool_name": "read"}, [hook]).messages

    def test_invalid_regex_skipped(self, capsys):
        hook = HookDef(name="bad", event="PreToolUse", matcher="[invalid",
                       action="block", body="Bad")
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [hook])
        assert result.blocked is False

    def test_wrong_event_skipped(self):
        hook = HookDef(name="post", event="PostToolUse", matcher=".*",
                       action="block", body="Post!")
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [hook])
        assert result.blocked is False

    def test_empty_body_no_message(self):
        hook = HookDef(name="silent", event="PreToolUse", matcher="bash",
                       action="block", body="")
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [hook])
        assert result.blocked is True
        assert result.messages == []


# --- Legacy API (backward compat during transition) ---

class TestLegacyAPI:
    def test_run_before_modifies_call(self):
        reg = HookRegistry()
        reg.before.setdefault("read", []).append(
            lambda call, ctx: ToolCallRecord(call.call_id, call.name, {"path": "/modified"})
        )
        call = ToolCallRecord("c1", "read", {"path": "/original"})
        result = run_before(call, _ctx(), reg)
        assert result.args["path"] == "/modified"

    def test_run_after_modifies_event(self):
        reg = HookRegistry()
        reg.after.setdefault("bash", []).append(
            lambda e, ctx: ToolEndEvent(e.call_id, e.name, "overridden")
        )
        ev = ToolEndEvent("c1", "bash", "original")
        result = run_after(ev, _ctx(), reg)
        assert result.output == "overridden"

    def test_load_hooks_missing_returns_empty(self):
        reg = load_hooks(pathlib.Path("/no/such/hooks.py"), require_consent=False)
        assert reg.before == {} and reg.after == {}
