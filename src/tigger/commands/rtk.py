from __future__ import annotations

import dataclasses
import shutil
import subprocess

from tigger.hooks import RTK_HOOK_NAME, set_hook_enabled
from tigger.types import RunContext


def _rtk_available() -> bool:
    return shutil.which("rtk") is not None


def _run_rtk(*args: str) -> None:
    if not _rtk_available():
        print("rtk binary not found in PATH. Install from https://github.com/rtk-ai/rtk")
        return
    result = subprocess.run(
        ["rtk", *args], capture_output=True, text=True, timeout=10,
    )
    print(result.stdout or result.stderr or "(no output)")


def cmd_rtk(args: str, ctx: RunContext, hook_defs: list | None = None) -> None:
    parts = args.strip().split()
    sub = parts[0].lower() if parts else ""

    if sub == "on":
        if not _rtk_available():
            print("rtk binary not found in PATH. Install from https://github.com/rtk-ai/rtk")
            return
        ctx.config = dataclasses.replace(ctx.config, rtk=True)
        set_hook_enabled(hook_defs, RTK_HOOK_NAME, True)
        print("RTK enabled — bash commands will be proxied through rtk.")
        return

    if sub == "off":
        ctx.config = dataclasses.replace(ctx.config, rtk=False)
        set_hook_enabled(hook_defs, RTK_HOOK_NAME, False)
        print("RTK disabled — bash commands run directly.")
        return

    if sub == "gain":
        # Pass remaining flags through to rtk gain (e.g. --history, --project, --graph)
        # Always include --project to scope to current workspace
        extra = parts[1:]
        if "--project" not in extra and "-p" not in extra:
            extra.insert(0, "--project")
        _run_rtk("gain", *extra)
        return

    # Default: show status
    installed = _rtk_available()
    enabled = ctx.config.rtk
    print(f"  installed: {'yes' if installed else 'no'}")
    print(f"  enabled:   {'yes' if enabled else 'no'}")
    if not installed:
        print("\n  Install RTK for 60-90% token savings on shell commands.")
        print("  https://github.com/rtk-ai/rtk")
    elif not enabled:
        print("\n  RTK is installed but not enabled. Run /rtk on to enable.")
    print("\n  /rtk on|off          Toggle RTK proxy")
    print("  /rtk gain            Show project token savings")
    print("  /rtk gain --history  Per-command savings history")
    print("  /rtk gain --graph    Daily savings graph")
