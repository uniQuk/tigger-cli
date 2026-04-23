from __future__ import annotations
import importlib.util, pathlib
from dataclasses import dataclass, field
from typing import Callable
from tigger.types import ToolCallRecord, ToolEndEvent, RunContext

BeforeFn = Callable[[ToolCallRecord, RunContext], ToolCallRecord]
AfterFn  = Callable[[ToolEndEvent,   RunContext], ToolEndEvent]


@dataclass
class HookRegistry:
    before: dict[str, list[BeforeFn]] = field(default_factory=dict)
    after:  dict[str, list[AfterFn]]  = field(default_factory=dict)


# Module-level singleton used by the decorator API.
# load_hooks() resets this before importing user code so each call is clean.
_REGISTRY = HookRegistry()


def on_before(*tool_names: str):
    """Decorator: register a before-hook for one or more tool names (or '*')."""
    def decorator(fn: BeforeFn) -> BeforeFn:
        for name in tool_names:
            _REGISTRY.before.setdefault(name, []).append(fn)
        return fn
    return decorator


def on_after(*tool_names: str):
    """Decorator: register an after-hook for one or more tool names (or '*')."""
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


def load_hooks(path: pathlib.Path) -> HookRegistry:
    """Import *path* (causing @on_before/@on_after decorators to fire) and return the registry."""
    global _REGISTRY
    _REGISTRY = HookRegistry()          # reset so previous loads don't accumulate

    if not path.exists():
        return _REGISTRY

    spec = importlib.util.spec_from_file_location("_user_hooks", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        print(f"[hooks] Warning: failed to load {path}: {exc}")

    return _REGISTRY
