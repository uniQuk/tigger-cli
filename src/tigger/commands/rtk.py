from __future__ import annotations
import dataclasses
import shutil
import subprocess
from tigger.types import RunContext


def _rtk_available() -> bool:
    return shutil.which("rtk") is not None


def cmd_rtk(args: str, ctx: RunContext) -> None:
    arg = args.strip().lower()

    if arg == "on":
        if not _rtk_available():
            print("rtk binary not found in PATH. Install from https://github.com/rtk-ai/rtk")
            return
        ctx.config = dataclasses.replace(ctx.config, rtk=True)
        print("RTK enabled — bash commands will be proxied through rtk.")
        return

    if arg == "off":
        ctx.config = dataclasses.replace(ctx.config, rtk=False)
        print("RTK disabled — bash commands run directly.")
        return

    if arg == "gain":
        if not _rtk_available():
            print("rtk binary not found in PATH.")
            return
        result = subprocess.run(
            ["rtk", "gain"], capture_output=True, text=True, timeout=10,
        )
        print(result.stdout or result.stderr or "(no output)")
        return

    if arg == "gain --history":
        if not _rtk_available():
            print("rtk binary not found in PATH.")
            return
        result = subprocess.run(
            ["rtk", "gain", "--history"], capture_output=True, text=True, timeout=10,
        )
        print(result.stdout or result.stderr or "(no output)")
        return

    # Default: show status
    installed = _rtk_available()
    enabled = ctx.config.rtk
    print(f"  installed: {'yes' if installed else 'no'}")
    print(f"  enabled:   {'yes' if enabled else 'no'}")
    if not installed:
        print(f"\n  Install RTK for 60-90% token savings on shell commands.")
        print(f"  https://github.com/rtk-ai/rtk")
    elif not enabled:
        print(f"\n  RTK is installed but not enabled. Run /rtk on to enable.")
    print(f"\n  /rtk on|off     Toggle RTK proxy")
    print(f"  /rtk gain       Show token savings")
