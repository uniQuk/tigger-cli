"""Declarative hook system: markdown files with YAML frontmatter."""
from __future__ import annotations

import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import Callable

from tigger.skills import _parse_blocks
from tigger.types import RunContext, ToolCallRecord, ToolEndEvent

# ---------------------------------------------------------------------------
# New declarative hook system
# ---------------------------------------------------------------------------

VALID_EVENTS = {"PreToolUse", "PostToolUse", "SessionStart"}
VALID_ACTIONS = {"block", "warn", "allow"}


@dataclass
class HookDef:
    name: str
    event: str                          # PreToolUse | PostToolUse | SessionStart
    matcher: str = ".*"                 # regex matched against tool_name or session source
    action: str = "warn"                # block | warn | allow
    body: str = ""                      # message shown on warn/block
    enabled: bool = True
    source_path: pathlib.Path | None = None


@dataclass
class HookResult:
    blocked: bool = False
    messages: list[str] = field(default_factory=list)


def load_hooks_dir(hooks_dir: pathlib.Path) -> list[HookDef]:
    """Load hooks from a directory. Each .md file is one hook."""
    if not hooks_dir.exists() or not hooks_dir.is_dir():
        return []
    hooks = []
    for entry in sorted(hooks_dir.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        blocks = _parse_blocks(entry.read_text())
        if not blocks:
            continue
        b = blocks[0]
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
        hooks.append(HookDef(
            name=name,
            event=event,
            matcher=fm.get("matcher", ".*"),
            action=action,
            body=b["body"],
            enabled=fm.get("enabled", True),
            source_path=entry,
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
        if hook.action == "block":
            result.blocked = True
            if hook.body:
                result.messages.append(hook.body)
        elif hook.action == "warn":
            if hook.body:
                result.messages.append(hook.body)
        # "allow" is a no-op
    return result


# ---------------------------------------------------------------------------
# Legacy hook API — kept for backward compatibility during transition.
# Unit 3 will remove these and update loop.py to use evaluate_hooks.
# ---------------------------------------------------------------------------

BeforeFn = Callable[[ToolCallRecord, RunContext], ToolCallRecord]
AfterFn = Callable[[ToolEndEvent, RunContext], ToolEndEvent]


@dataclass
class HookRegistry:
    before: dict[str, list[BeforeFn]] = field(default_factory=dict)
    after: dict[str, list[AfterFn]] = field(default_factory=dict)


_REGISTRY = HookRegistry()


def on_before(*tool_names: str):
    def decorator(fn: BeforeFn) -> BeforeFn:
        for name in tool_names:
            _REGISTRY.before.setdefault(name, []).append(fn)
        return fn
    return decorator


def on_after(*tool_names: str):
    def decorator(fn: AfterFn) -> AfterFn:
        for name in tool_names:
            _REGISTRY.after.setdefault(name, []).append(fn)
        return fn
    return decorator


def run_before(call: ToolCallRecord, ctx: RunContext, registry: HookRegistry) -> ToolCallRecord:
    for fn in registry.before.get(call.name, []) + registry.before.get("*", []):
        call = fn(call, ctx)
    return call


def run_after(event: ToolEndEvent, ctx: RunContext, registry: HookRegistry) -> ToolEndEvent:
    for fn in registry.after.get(event.name, []) + registry.after.get("*", []):
        event = fn(event, ctx)
    return event


def load_hooks(path: pathlib.Path, *, require_consent: bool = True) -> HookRegistry:
    """Import *path* (legacy hooks.py format). Returns populated registry."""
    import importlib.util
    global _REGISTRY
    _REGISTRY = HookRegistry()
    if not path.exists():
        return _REGISTRY
    if require_consent:
        print(f"[hooks] Found hooks file: {path}")
        try:
            answer = input("  Load and execute project hooks? [y/N] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            answer = "n"
        if answer != "y":
            print("[hooks] Skipped — hooks not loaded.")
            return _REGISTRY
    spec = importlib.util.spec_from_file_location("_user_hooks", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        print(f"[hooks] Warning: failed to load {path}: {exc}")
    return _REGISTRY
