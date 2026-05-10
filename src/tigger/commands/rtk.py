from __future__ import annotations

import dataclasses
import shutil
import subprocess

from tigger.hooks import RTK_HOOK_NAME, set_hook_enabled
from tigger.types import RunContext


def _rtk_available() -> bool:
    return shutil.which("rtk") is not None


def _run_rtk(*args: str) -> None:
    from tigger.ui import console

    if not _rtk_available():
        console.print(
            "[red]rtk binary not found in PATH.[/red] "
            "[dim]Install from[/dim] https://github.com/rtk-ai/rtk"
        )
        return
    result = subprocess.run(
        ["rtk", *args], capture_output=True, text=True, timeout=10,
    )
    out = result.stdout or result.stderr or "(no output)"
    # Pass rtk's own output through verbatim — it has its own formatting.
    console.print(out, highlight=False, markup=False)


def cmd_rtk(args: str, ctx: RunContext, hook_defs: list | None = None) -> None:
    from tigger.ui import console

    parts = args.strip().split()
    sub = parts[0].lower() if parts else ""

    if sub == "on":
        if not _rtk_available():
            console.print(
                "[red]rtk binary not found in PATH.[/red] "
                "[dim]Install from[/dim] https://github.com/rtk-ai/rtk"
            )
            return
        ctx.config = dataclasses.replace(ctx.config, rtk=True)
        set_hook_enabled(hook_defs, RTK_HOOK_NAME, True)
        console.print(
            "[dim]✓ RTK enabled[/dim] [dim]— bash commands will be proxied through rtk.[/dim]"
        )
        return

    if sub == "off":
        ctx.config = dataclasses.replace(ctx.config, rtk=False)
        set_hook_enabled(hook_defs, RTK_HOOK_NAME, False)
        console.print(
            "[dim]✓ RTK disabled[/dim] [dim]— bash commands run directly.[/dim]"
        )
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
    yes_no = lambda b: "[green]yes[/green]" if b else "[red]no[/red]"
    console.print()
    console.print("[bold]RTK[/bold]")
    console.print(f"  [dim]installed:[/dim] {yes_no(installed)}")
    console.print(f"  [dim]enabled:[/dim]   {yes_no(enabled)}")
    if not installed:
        console.print()
        console.print(
            "  [dim]Install RTK for 60-90% token savings on shell commands.[/dim]"
        )
        console.print("  [cyan]https://github.com/rtk-ai/rtk[/cyan]")
    elif not enabled:
        console.print()
        console.print(
            "  [dim]RTK is installed but not enabled. Run[/dim] [cyan]/rtk on[/cyan] [dim]to enable.[/dim]"
        )
    console.print()
    console.print(
        "  [cyan]/rtk on|off[/cyan]          [dim]Toggle RTK proxy[/dim]"
    )
    console.print(
        "  [cyan]/rtk gain[/cyan]            [dim]Show project token savings[/dim]"
    )
    console.print(
        "  [cyan]/rtk gain --history[/cyan]  [dim]Per-command savings history[/dim]"
    )
    console.print(
        "  [cyan]/rtk gain --graph[/cyan]    [dim]Daily savings graph[/dim]"
    )
