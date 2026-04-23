from __future__ import annotations
import json
import pathlib
import urllib.parse
import warnings
from newcli.types import Config, ProviderConfig

_PERM_RENAME: dict[str, str] = {"manual": "ask", "auto": "allow", "accept-all": "bypass"}
_VALID_PERMISSION_MODES = {"ask", "allow", "bypass"}
_VALID_MODES = {"ask", "plan"}


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
    return dataclasses.replace(
        config,
        active_provider=provider_name,
        active_model=model_name,
        base_url=provider.base_url,
        model=model_name,
        api_key=provider.api_key,
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

    mode = data.get("mode", "ask")
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {_VALID_MODES}, got {mode!r}")

    # --- Provider loading ---
    if "providers" in data:
        # New multi-provider format
        providers = {}
        for name, prov_data in data["providers"].items():
            providers[name] = ProviderConfig(
                name=name,
                base_url=prov_data["base_url"],
                api_key=prov_data.get("api_key", "local"),
                models=prov_data.get("models", []),
            )
        if not providers:
            raise ValueError("config.json 'providers' is empty")
        active_provider = data.get("default_provider", next(iter(providers)))
        if active_provider not in providers:
            raise ValueError(f"default_provider {active_provider!r} not found in providers")
        prov_models = providers[active_provider].models
        if not prov_models and "default_model" not in data:
            raise ValueError(f"provider {active_provider!r} has no models and no default_model set")
        active_model = data.get("default_model") or prov_models[0]
        active_prov = providers[active_provider]
    else:
        # Old flat format — backward compat migration
        if "base_url" not in data:
            raise ValueError("config.json missing required field: base_url")
        if "model" not in data:
            raise ValueError("config.json missing required field: model")
        prov_name = derive_provider_name(data["base_url"])
        api_key = data.get("api_key", "local")
        active_prov = ProviderConfig(
            name=prov_name,
            base_url=data["base_url"],
            api_key=api_key,
            models=[data["model"]],
        )
        providers = {prov_name: active_prov}
        active_provider = prov_name
        active_model = data["model"]

    return Config(
        base_url=active_prov.base_url,
        model=active_model,
        api_key=active_prov.api_key,
        providers=providers,
        active_provider=active_provider,
        active_model=active_model,
        context_limit=data.get("context_limit", 8192),
        max_tokens=data.get("max_tokens", 2048),
        temperature=data.get("temperature", 0.7),
        permission_mode=perm,
        mode=mode,
        max_depth=data.get("max_depth", 4),
        max_retries=data.get("max_retries", 2),
        bash_safe_prefixes=data.get("bash_safe_prefixes", []),
        prefer_text_tools=data.get("prefer_text_tools", False),
    )


def find_config(start: pathlib.Path) -> pathlib.Path | None:
    """Walk up from *start* looking for .ai/config.json, fallback to ~/.ai/."""
    current = start.resolve()
    while True:
        candidate = current / ".ai" / "config.json"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    global_cfg = pathlib.Path.home() / ".ai" / "config.json"
    return global_cfg if global_cfg.exists() else None


def write_config(path: pathlib.Path, config: Config) -> None:
    """Serialize *config* to JSON at *path* in the new providers format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    providers_data = {}
    for name, prov in config.providers.items():
        providers_data[name] = {
            "base_url": prov.base_url,
            "api_key": prov.api_key,
            "models": list(prov.models),
        }
    data = {
        "default_provider": config.active_provider,
        "default_model": config.active_model,
        "providers": providers_data,
        "context_limit": config.context_limit,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "permission_mode": config.permission_mode,
        "mode": config.mode,
        "max_depth": config.max_depth,
        "max_retries": config.max_retries,
        "bash_safe_prefixes": config.bash_safe_prefixes,
        "prefer_text_tools": config.prefer_text_tools,
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
