from __future__ import annotations

import dataclasses
import pathlib
import re

from tigger.config import switch_model, write_config
from tigger.types import ProviderConfig, RunContext


def cmd_provider(args: str, ctx: RunContext, config_path: pathlib.Path) -> None:
    from tigger.ui import console

    subcmd = args.strip().lower()
    if subcmd != "add":
        console.print("[dim]Usage:[/dim] /provider add")
        return
    _provider_add(ctx, config_path)


def _provider_add(ctx: RunContext, config_path: pathlib.Path) -> None:
    from tigger.ui import console

    existing = list(ctx.config.providers.keys())
    hint = f" (or existing: {', '.join(existing)})" if existing else ""
    name = input(f"  Provider name{hint}: ").strip()

    if not name or not re.match(r'^[a-zA-Z0-9._-]+$', name):
        console.print(
            "[red]Invalid provider name.[/red] "
            "[dim]Use alphanumeric characters, hyphens, dots.[/dim]"
        )
        return

    if name in ctx.config.providers:
        # Add model to existing provider
        model = input("  Model name: ").strip()
        if not model:
            console.print("[dim]Cancelled — no model name given.[/dim]")
            return
        prov = ctx.config.providers[name]
        if model in prov.model_names:
            console.print(
                f"[red]Model[/red] {model!r} "
                f"[red]already exists in provider[/red] {name!r}."
            )
            return
        if isinstance(prov.models, dict):
            new_models = dict(prov.models)
            from tigger.types import ModelConfig
            new_models[model] = ModelConfig()
        else:
            new_models = list(prov.models) + [model]
        new_prov = dataclasses.replace(prov, models=new_models)
        new_providers = dict(ctx.config.providers)
        new_providers[name] = new_prov
        ctx.config = dataclasses.replace(ctx.config, providers=new_providers)
        write_config(config_path, ctx.config)
        console.print(
            f"[dim]✓ Added model[/dim] [cyan]{model}[/cyan] "
            f"[dim]to provider[/dim] [magenta]{name}[/magenta]"
        )
    else:
        # New provider
        base_url = input("  Base URL: ").strip()
        if not base_url.startswith(("http://", "https://")):
            console.print(
                "[red]Base URL must start with[/red] http:// [red]or[/red] https://"
            )
            return
        api_key = input("  API key (Enter for 'local'): ").strip() or "local"
        model = input("  Model name: ").strip()
        if not model:
            console.print("[dim]Cancelled — no model name given.[/dim]")
            return

        new_prov = ProviderConfig(name=name, base_url=base_url,
                                  api_key=api_key, models=[model])
        new_providers = dict(ctx.config.providers)
        new_providers[name] = new_prov
        ctx.config = dataclasses.replace(ctx.config, providers=new_providers)
        write_config(config_path, ctx.config)
        console.print(
            f"[dim]✓ Added provider[/dim] [magenta]{name}[/magenta] "
            f"[dim]with model[/dim] [cyan]{model}[/cyan]"
        )

        try:
            switch = input("  Switch to it now? [Y/n]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return
        if switch in ("y", ""):
            ctx.config = switch_model(ctx.config, name, model)
            console.print(
                f"[dim]✓ Switched to[/dim] [cyan]{name}/{model}[/cyan]"
            )
