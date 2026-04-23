from __future__ import annotations
import dataclasses
import pathlib
import re
from tigger.types import RunContext, ProviderConfig
from tigger.config import switch_model, write_config


def cmd_provider(args: str, ctx: RunContext, config_path: pathlib.Path) -> None:
    subcmd = args.strip().lower()
    if subcmd != "add":
        print("Usage: /provider add")
        return
    _provider_add(ctx, config_path)


def _provider_add(ctx: RunContext, config_path: pathlib.Path) -> None:
    existing = list(ctx.config.providers.keys())
    hint = f" (or existing: {', '.join(existing)})" if existing else ""
    name = input(f"  Provider name{hint}: ").strip()

    if not name or not re.match(r'^[a-zA-Z0-9._-]+$', name):
        print("Invalid provider name. Use alphanumeric characters, hyphens, dots.")
        return

    if name in ctx.config.providers:
        # Add model to existing provider
        model = input("  Model name: ").strip()
        if not model:
            print("Cancelled — no model name given.")
            return
        prov = ctx.config.providers[name]
        if model in prov.models:
            print(f"Model {model!r} already exists in provider {name!r}.")
            return
        new_models = list(prov.models) + [model]
        new_prov = dataclasses.replace(prov, models=new_models)
        new_providers = dict(ctx.config.providers)
        new_providers[name] = new_prov
        ctx.config = dataclasses.replace(ctx.config, providers=new_providers)
        write_config(config_path, ctx.config)
        print(f"Added model {model!r} to provider {name!r}.")
    else:
        # New provider
        base_url = input("  Base URL: ").strip()
        if not base_url.startswith(("http://", "https://")):
            print("Base URL must start with http:// or https://")
            return
        api_key = input("  API key (Enter for 'local'): ").strip() or "local"
        model = input("  Model name: ").strip()
        if not model:
            print("Cancelled — no model name given.")
            return

        new_prov = ProviderConfig(name=name, base_url=base_url,
                                  api_key=api_key, models=[model])
        new_providers = dict(ctx.config.providers)
        new_providers[name] = new_prov
        ctx.config = dataclasses.replace(ctx.config, providers=new_providers)
        write_config(config_path, ctx.config)
        print(f"Added provider {name!r} with model {model!r}.")

        try:
            switch = input("  Switch to it now? [Y/n]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return
        if switch in ("y", ""):
            ctx.config = switch_model(ctx.config, name, model)
            print(f"Switched to {name}/{model}")
