from __future__ import annotations

import json
import pathlib
import urllib.parse
import warnings

from tigger._constants import CONFIG_DIR, home_config_dir
from tigger.types import (
    DEFAULT_CONTEXT_LIMIT,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_READ_TIMEOUT,
    DEFAULT_TEMPERATURE,
    Config,
    ModelConfig,
    ProviderConfig,
)
import os

_PERM_RENAME: dict[str, str] = {"manual": "ask", "auto": "allow", "accept-all": "bypass"}
_VALID_PERMISSION_MODES = {"ask", "allow", "bypass"}
_MODE_RENAME: dict[str, str] = {"ask": "act"}


def derive_provider_name(base_url: str) -> str:
    """Derive a short provider name from a base URL's hostname."""
    hostname = urllib.parse.urlparse(base_url).hostname or base_url
    if hostname.startswith("api."):
        hostname = hostname[4:]
    if hostname.endswith(".com"):
        hostname = hostname[:-4]
    if hostname.endswith(".org"):
        hostname = hostname[:-4]
    return hostname


def switch_model(config: Config, provider_name: str, model_name: str) -> Config:
    """Return a new Config with the active provider and model switched."""
    import dataclasses
    provider = config.providers[provider_name]
    overrides = {}
    if isinstance(provider.models, dict) and model_name in provider.models:
        mcfg = provider.models[model_name]
        if mcfg.temperature is not None:
            overrides["temperature"] = mcfg.temperature
        if mcfg.max_tokens is not None:
            overrides["max_tokens"] = mcfg.max_tokens
        if mcfg.context_limit is not None:
            overrides["context_limit"] = mcfg.context_limit
    return dataclasses.replace(
        config,
        active_provider=provider_name,
        model=model_name,
        base_url=provider.base_url,
        api_key=provider.api_key,
        **overrides,
    )


def load_config(path: pathlib.Path) -> Config:
    """Load config.json at *path* and return a validated frozen Config."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open() as f:
        data = json.load(f)

    perm = data.get("permission_mode", "allow")
    if perm in _PERM_RENAME:
        new_perm = _PERM_RENAME[perm]
        warnings.warn(
            f"permission_mode {perm!r} is deprecated; use {new_perm!r} instead",
            DeprecationWarning,
            stacklevel=2,
        )
        perm = new_perm
    if perm not in _VALID_PERMISSION_MODES:
        raise ValueError(
            f"permission_mode must be one of {_VALID_PERMISSION_MODES}, got {perm!r}"
        )

    mode = data.get("mode", "act")
    if mode in _MODE_RENAME:
        mode = _MODE_RENAME[mode]

    # --- Provider loading ---
    if "providers" in data:
        # New multi-provider format
        providers = {}
        for name, prov_data in data["providers"].items():
            raw_models = prov_data.get("models", [])
            if isinstance(raw_models, list):
                models = raw_models
            elif isinstance(raw_models, dict):
                models = {}
                for mname, mcfg in raw_models.items():
                    if isinstance(mcfg, dict):
                        models[mname] = ModelConfig(
                            temperature=mcfg.get("temperature"),
                            max_tokens=mcfg.get("max_tokens"),
                            context_limit=mcfg.get("context_limit"),
                            top_p=mcfg.get("top_p"),
                            thinking=mcfg.get("thinking"),
                        )
                    else:
                        models[mname] = ModelConfig()
            else:
                models = []
            providers[name] = ProviderConfig(
                name=name,
                base_url=prov_data["base_url"],
                api_key=prov_data.get("api_key", "local"),
                models=models,
            )
        if not providers:
            raise ValueError("config.json 'providers' is empty")
        active_provider = data.get("default_provider", next(iter(providers)))
        if active_provider not in providers:
            raise ValueError(f"default_provider {active_provider!r} not found in providers")
        prov_model_names = providers[active_provider].model_names
        if not prov_model_names and "default_model" not in data:
            raise ValueError(f"provider {active_provider!r} has no models and no default_model set")
        dm = data.get("default_model")
        active_model = prov_model_names[0] if dm is None else dm
        active_prov = providers[active_provider]
    else:
        # Old flat format — backward compat migration
        if "base_url" not in data:
            raise ValueError("config.json missing required field: base_url")
        model_name = data.get("model") or data.get("models")
        if not model_name:
            raise ValueError("config.json missing required field: model")
        if isinstance(model_name, list):
            model_name = model_name[0]
        prov_name = derive_provider_name(data["base_url"])
        api_key = data.get("api_key", "local")
        active_prov = ProviderConfig(
            name=prov_name,
            base_url=data["base_url"],
            api_key=api_key,
            models=[model_name],
        )
        providers = {prov_name: active_prov}
        active_provider = prov_name
        active_model = model_name

    return Config(
        base_url=active_prov.base_url,
        model=active_model,
        api_key=active_prov.api_key,
        providers=providers,
        active_provider=active_provider,
        context_limit=data.get("context_limit", DEFAULT_CONTEXT_LIMIT),
        max_tokens=data.get("max_tokens", DEFAULT_MAX_TOKENS),
        temperature=data.get("temperature", DEFAULT_TEMPERATURE),
        permission_mode=perm,
        mode=mode,
        max_depth=data.get("max_depth", DEFAULT_MAX_DEPTH),
        max_retries=data.get("max_retries", DEFAULT_MAX_RETRIES),
        bash_safe_prefixes=data.get("bash_safe_prefixes", []),
        rtk=data.get("rtk", False),
        read_timeout=_resolve_read_timeout(data.get("read_timeout")),
    )


def _resolve_read_timeout(value: object) -> int:
    """Env var TIGGER_READ_TIMEOUT overrides config; config overrides default."""
    env = os.environ.get("TIGGER_READ_TIMEOUT")
    if env:
        try:
            return int(env)
        except ValueError:
            warnings.warn(
                f"TIGGER_READ_TIMEOUT={env!r} is not an integer; using default",
                stacklevel=2,
            )
    if isinstance(value, int) and value >= 0:
        return value
    return DEFAULT_READ_TIMEOUT


def find_config(start: pathlib.Path) -> pathlib.Path | None:
    """Walk up from *start* looking for .tigger/config.json, fallback to ~/.tigger/."""
    current = start.resolve()
    while True:
        candidate = current / CONFIG_DIR / "config.json"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    global_cfg = home_config_dir() / "config.json"
    return global_cfg if global_cfg.exists() else None


def write_config(path: pathlib.Path, config: Config) -> None:
    """Serialize *config* to JSON at *path* in the new providers format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    providers_data = {}
    for name, prov in config.providers.items():
        providers_data[name] = {
            "base_url": prov.base_url,
            "api_key": prov.api_key,
        }
        if isinstance(prov.models, dict):
            models_data = {}
            for mname, mcfg in prov.models.items():
                cfg_dict = {}
                for f in ("temperature", "max_tokens", "context_limit", "top_p", "thinking"):
                    val = getattr(mcfg, f)
                    if val is not None:
                        cfg_dict[f] = val
                models_data[mname] = cfg_dict
            providers_data[name]["models"] = models_data
        else:
            providers_data[name]["models"] = prov.models
    data = {
        "default_provider": config.active_provider,
        "default_model": config.model,
        "providers": providers_data,
        "context_limit": config.context_limit,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "permission_mode": config.permission_mode,
        "mode": config.mode,
        "max_depth": config.max_depth,
        "max_retries": config.max_retries,
        "bash_safe_prefixes": config.bash_safe_prefixes,
        "rtk": config.rtk,
        "read_timeout": config.read_timeout,
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
