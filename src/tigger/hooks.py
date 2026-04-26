"""Declarative hook system: markdown files with YAML frontmatter."""
from __future__ import annotations

import pathlib
import re
import sys
from dataclasses import dataclass, field

from tigger.parsing import parse_single

RTK_HOOK_NAME = "_rtk-rewrite"

VALID_EVENTS = {"PreToolUse", "PostToolUse", "SessionStart"}
VALID_ACTIONS = {"block", "warn", "allow", "transform"}


@dataclass
class HookDef:
    name: str
    event: str                          # PreToolUse | PostToolUse | SessionStart
    matcher: str = ".*"                 # regex matched against tool_name or session source
    action: str = "warn"                # block | warn | allow | transform
    body: str = ""                      # message shown on warn/block; key:template lines for transform
    enabled: bool = True
    source_path: pathlib.Path | None = None
    args_match: dict[str, str] = field(default_factory=dict)  # arg_name -> regex pattern


@dataclass
class HookResult:
    blocked: bool = False
    messages: list[str] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)
    transformed: bool = False


def load_hooks_dir(hooks_dir: pathlib.Path) -> list[HookDef]:
    """Load hooks from a directory. Each .md file is one hook."""
    if not hooks_dir.exists() or not hooks_dir.is_dir():
        return []
    hooks = []
    for entry in sorted(hooks_dir.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        b = parse_single(entry.read_text(), source=str(entry))
        if not b:
            continue
        fm = b["fm"]
        name = fm.get("name", entry.stem)
        event = fm.get("event", "")
        if event not in VALID_EVENTS:
            print(f"Warning: hook {entry.name} has invalid event {event!r}, skipping",
                  file=sys.stderr)
            continue
        action = fm.get("action", "warn")
        if action not in VALID_ACTIONS:
            action = "warn"
        raw_args_match = fm.get("args_match", {})
        args_match = {str(k): str(v) for k, v in raw_args_match.items()} if isinstance(raw_args_match, dict) else {}
        hooks.append(HookDef(
            name=name,
            event=event,
            matcher=fm.get("matcher", ".*"),
            action=action,
            body=b["body"],
            enabled=fm.get("enabled", True),
            source_path=entry,
            args_match=args_match,
        ))
    return hooks


def evaluate_hooks(event: str, context: dict, hooks: list[HookDef]) -> HookResult:
    """Evaluate all matching hooks for an event. Returns a HookResult.

    For PreToolUse, if any hook blocks, the tool call should be skipped.
    All matching hooks fire (additive merge — no shadowing).
    """
    result = HookResult()
    match_target = context.get("tool_name", "")
    for hook in hooks:
        if hook.event != event:
            continue
        if not hook.enabled:
            continue
        try:
            if not re.search(hook.matcher, match_target):
                continue
        except re.error:
            print(f"Warning: hook {hook.name!r} has invalid regex {hook.matcher!r}, skipping",
                  file=sys.stderr)
            continue
        # Check args_match conditions — all must match for hook to fire
        if hook.args_match:
            tool_args = context.get("tool_args", {})
            args_matched = True
            for arg_key, arg_pattern in hook.args_match.items():
                arg_val = tool_args.get(arg_key)
                if arg_val is None or not isinstance(arg_val, str):
                    args_matched = False
                    break
                try:
                    if not re.search(arg_pattern, arg_val):
                        args_matched = False
                        break
                except re.error:
                    print(f"Warning: hook {hook.name!r} has invalid args_match regex "
                          f"{arg_pattern!r} for key {arg_key!r}, skipping",
                          file=sys.stderr)
                    args_matched = False
                    break
            if not args_matched:
                continue
        if hook.action == "block":
            result.blocked = True
            if hook.body:
                result.messages.append(hook.body)
                result.feedback.append(f"[hook: {hook.name}]\n{hook.body}")
        elif hook.action == "warn":
            if hook.body:
                result.messages.append(hook.body)
                result.feedback.append(f"[hook: {hook.name}]\n{hook.body}")
        elif hook.action == "transform":
            if result.transformed:
                print(f"Warning: hook {hook.name!r} skipped — a transform already fired",
                      file=sys.stderr)
                continue
            # Lines mutate tool_args sequentially; caller re-validates permissions.
            tool_args = context.get("tool_args", {})
            for line in hook.body.splitlines():
                line = line.strip()
                if not line:
                    continue
                sep = line.find(": ")
                if sep < 0:
                    print(f"Warning: hook {hook.name!r} has malformed transform line {line!r}, "
                          "skipping line", file=sys.stderr)
                    continue
                key, template = line[:sep], line[sep + 2:]
                try:
                    tool_args[key] = template.format_map(tool_args)
                except (KeyError, ValueError) as exc:
                    print(f"Warning: hook {hook.name!r} transform failed for key {key!r}: {exc}",
                          file=sys.stderr)
            result.transformed = True
        # "allow" is a no-op
    return result


def set_hook_enabled(hooks: list[HookDef] | None, name: str, enabled: bool) -> None:
    """Find a hook by *name* and set its ``enabled`` flag."""
    if not hooks:
        return
    for h in hooks:
        if h.name == name:
            h.enabled = enabled
            return
