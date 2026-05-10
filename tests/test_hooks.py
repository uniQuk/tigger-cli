"""Tests for the declarative hook system."""
from __future__ import annotations
import pathlib
import textwrap
from tigger.hooks import HookDef, load_hooks_dir, evaluate_hooks
from tigger.types import Config, RunContext


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


# --- args_match ---

class TestArgsMatch:
    def test_args_match_fires_on_match(self):
        hook = HookDef(name="rm", event="PreToolUse", matcher="bash",
                       action="block", body="No rm!", args_match={"command": "rm"})
        ctx = {"tool_name": "bash", "tool_args": {"command": "rm -rf /"}}
        result = evaluate_hooks("PreToolUse", ctx, [hook])
        assert result.blocked is True

    def test_args_match_skips_on_no_match(self):
        hook = HookDef(name="rm", event="PreToolUse", matcher="bash",
                       action="block", body="No rm!", args_match={"command": "rm"})
        ctx = {"tool_name": "bash", "tool_args": {"command": "echo hello"}}
        result = evaluate_hooks("PreToolUse", ctx, [hook])
        assert result.blocked is False

    def test_no_args_match_backward_compat(self):
        hook = HookDef(name="b", event="PreToolUse", matcher="bash",
                       action="block", body="Blocked!")
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [hook])
        assert result.blocked is True

    def test_missing_arg_key_skips(self):
        hook = HookDef(name="x", event="PreToolUse", matcher="bash",
                       action="block", body="No!", args_match={"nonexistent": ".*"})
        ctx = {"tool_name": "bash", "tool_args": {"command": "ls"}}
        result = evaluate_hooks("PreToolUse", ctx, [hook])
        assert result.blocked is False

    def test_wildcard_arg_matches_any(self):
        hook = HookDef(name="any", event="PreToolUse", matcher="bash",
                       action="warn", body="Logged", args_match={"command": ".*"})
        ctx = {"tool_name": "bash", "tool_args": {"command": "anything"}}
        result = evaluate_hooks("PreToolUse", ctx, [hook])
        assert "Logged" in result.messages

    def test_invalid_arg_regex_skips(self, capsys):
        hook = HookDef(name="bad", event="PreToolUse", matcher="bash",
                       action="block", body="Bad", args_match={"command": "[invalid"})
        ctx = {"tool_name": "bash", "tool_args": {"command": "ls"}}
        result = evaluate_hooks("PreToolUse", ctx, [hook])
        assert result.blocked is False

    def test_none_arg_value_skips(self):
        hook = HookDef(name="n", event="PreToolUse", matcher="bash",
                       action="block", body="No!", args_match={"command": ".*"})
        ctx = {"tool_name": "bash", "tool_args": {"command": None}}
        result = evaluate_hooks("PreToolUse", ctx, [hook])
        assert result.blocked is False

    def test_multiple_args_match_all_must_match(self):
        hook = HookDef(name="m", event="PreToolUse", matcher="bash",
                       action="block", body="No!",
                       args_match={"command": "rm", "path": "/etc"})
        ctx_both = {"tool_name": "bash", "tool_args": {"command": "rm -f", "path": "/etc/hosts"}}
        assert evaluate_hooks("PreToolUse", ctx_both, [hook]).blocked is True
        ctx_one = {"tool_name": "bash", "tool_args": {"command": "rm -f", "path": "/tmp/x"}}
        assert evaluate_hooks("PreToolUse", ctx_one, [hook]).blocked is False

    def test_args_match_loaded_from_frontmatter(self, tmp_path):
        content = textwrap.dedent("""\
            ---
            name: block-rm
            event: PreToolUse
            matcher: bash
            action: block
            args_match:
              command: "rm"
            ---
            Dangerous rm command.
        """)
        _make_hook(tmp_path, "block-rm.md", content)
        hooks = load_hooks_dir(tmp_path)
        assert hooks[0].args_match == {"command": "rm"}


# --- feedback ---

class TestFeedback:
    def test_block_produces_feedback(self):
        hook = HookDef(name="no-rm", event="PreToolUse", matcher="bash",
                       action="block", body="Blocked!")
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [hook])
        assert len(result.feedback) == 1
        assert "[hook: no-rm]" in result.feedback[0]
        assert "Blocked!" in result.feedback[0]

    def test_warn_produces_feedback(self):
        hook = HookDef(name="careful", event="PreToolUse", matcher="bash",
                       action="warn", body="Be careful!")
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [hook])
        assert len(result.feedback) == 1
        assert "[hook: careful]" in result.feedback[0]

    def test_allow_no_feedback(self):
        hook = HookDef(name="ok", event="PreToolUse", matcher="bash",
                       action="allow", body="Ignored")
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [hook])
        assert result.feedback == []

    def test_no_body_no_feedback(self):
        hook = HookDef(name="silent", event="PreToolUse", matcher="bash",
                       action="block", body="")
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, [hook])
        assert result.blocked is True
        assert result.feedback == []

    def test_block_with_args_match_produces_feedback(self):
        hook = HookDef(name="no-rm", event="PreToolUse", matcher="bash",
                       action="block", body="No rm!",
                       args_match={"command": "rm"})
        ctx = {"tool_name": "bash", "tool_args": {"command": "rm -rf /"}}
        result = evaluate_hooks("PreToolUse", ctx, [hook])
        assert result.blocked is True
        assert "[hook: no-rm]" in result.feedback[0]

    def test_multiple_hooks_multiple_feedback(self):
        hooks = [
            HookDef(name="w1", event="PreToolUse", matcher="bash",
                    action="warn", body="Warning 1"),
            HookDef(name="w2", event="PreToolUse", matcher="bash",
                    action="warn", body="Warning 2"),
        ]
        result = evaluate_hooks("PreToolUse", {"tool_name": "bash"}, hooks)
        assert len(result.feedback) == 2


# --- transform action ---

class TestTransformAction:
    def test_transform_rewrites_arg(self):
        hook = HookDef(name="rtk", event="PreToolUse", matcher="bash",
                       action="transform", body="command: rtk {command}")
        ctx = {"tool_name": "bash", "tool_args": {"command": "git status"}}
        result = evaluate_hooks("PreToolUse", ctx, [hook])
        assert ctx["tool_args"]["command"] == "rtk git status"
        assert result.transformed is True

    def test_transform_with_args_match(self):
        hook = HookDef(name="rtk", event="PreToolUse", matcher="bash",
                       action="transform", body="command: rtk {command}",
                       args_match={"command": "^(?!rtk )"})
        ctx_no_prefix = {"tool_name": "bash", "tool_args": {"command": "git status"}}
        evaluate_hooks("PreToolUse", ctx_no_prefix, [hook])
        assert ctx_no_prefix["tool_args"]["command"] == "rtk git status"
        ctx_has_prefix = {"tool_name": "bash", "tool_args": {"command": "rtk git status"}}
        evaluate_hooks("PreToolUse", ctx_has_prefix, [hook])
        assert ctx_has_prefix["tool_args"]["command"] == "rtk git status"  # not double-prefixed

    def test_transform_missing_key_fails_open(self, capsys):
        hook = HookDef(name="bad", event="PreToolUse", matcher="bash",
                       action="transform", body="command: prefix {nonexistent}")
        ctx = {"tool_name": "bash", "tool_args": {"command": "ls"}}
        evaluate_hooks("PreToolUse", ctx, [hook])
        assert ctx["tool_args"]["command"] == "ls"  # unchanged

    def test_transform_malformed_body_line(self, capsys):
        hook = HookDef(name="bad", event="PreToolUse", matcher="bash",
                       action="transform", body="no separator here")
        ctx = {"tool_name": "bash", "tool_args": {"command": "ls"}}
        evaluate_hooks("PreToolUse", ctx, [hook])
        assert ctx["tool_args"]["command"] == "ls"  # unchanged

    def test_two_transforms_second_skipped(self, capsys):
        hooks = [
            HookDef(name="first", event="PreToolUse", matcher="bash",
                    action="transform", body="command: first {command}"),
            HookDef(name="second", event="PreToolUse", matcher="bash",
                    action="transform", body="command: second {command}"),
        ]
        ctx = {"tool_name": "bash", "tool_args": {"command": "ls"}}
        evaluate_hooks("PreToolUse", ctx, [hooks[0], hooks[1]])
        assert ctx["tool_args"]["command"] == "first ls"

    def test_transform_coexists_with_warn(self):
        hooks = [
            HookDef(name="t", event="PreToolUse", matcher="bash",
                    action="transform", body="command: rtk {command}"),
            HookDef(name="w", event="PreToolUse", matcher="bash",
                    action="warn", body="Logged"),
        ]
        ctx = {"tool_name": "bash", "tool_args": {"command": "git status"}}
        result = evaluate_hooks("PreToolUse", ctx, hooks)
        assert ctx["tool_args"]["command"] == "rtk git status"
        assert "Logged" in result.messages


