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

# Sampling fields that ModelConfig can override on the active Config.
_OVERRIDE_FIELDS = (
    "temperature", "max_tokens", "context_limit", "top_p", "top_k",
    "min_p", "presence_penalty", "frequency_penalty",
    "repetition_penalty", "chat_template_kwargs", "disable_tools",
)
# All fields the JSON model entry may set; superset of override fields plus identity.
_MODEL_CONFIG_FIELDS = ("model", "name", *_OVERRIDE_FIELDS, "thinking")


def _model_config_from_dict(raw: dict) -> ModelConfig:
    """Build a ModelConfig from a JSON model entry, accepting `repeat_penalty` alias."""
    kwargs = {f: raw.get(f) for f in _MODEL_CONFIG_FIELDS}
    if kwargs["repetition_penalty"] is None:
        kwargs["repetition_penalty"] = raw.get("repeat_penalty")
    return ModelConfig(**kwargs)


def _resolve_active_model(
    provider: ProviderConfig, model_name: str
) -> tuple[str, str, dict]:
    """Return (wire_id, display_name, overrides) for *model_name* in *provider*."""
    wire_id = model_name
    display_name = model_name
    overrides: dict = {}
    if isinstance(provider.models, dict) and model_name in provider.models:
        mcfg = provider.models[model_name]
        if mcfg.model:
            wire_id = mcfg.model
        if mcfg.name:
            display_name = mcfg.name
        for f in _OVERRIDE_FIELDS:
            val = getattr(mcfg, f)
            if val is not None:
                overrides[f] = val
        # `chat_template_kwargs` is per-model authoritative in dict-format
        # providers — the global default carries Qwen-style flags
        # (enable_thinking / preserve_thinking) that a gemma or llama
        # jinja template will reject ("Cannot call something that is not
        # a function: got UndefinedValue"). A per-model entry without
        # this field means "no template kwargs", not "inherit global".
        overrides.setdefault("chat_template_kwargs", mcfg.chat_template_kwargs or {})
        # `disable_tools` is per-model authoritative for the same reason
        # in reverse: switching from a chat-only model (gemma, True) to a
        # tools-capable one (qwen, unset) must reset to False rather than
        # bleeding the previous model's True through the override fall-through.
        overrides.setdefault("disable_tools", bool(mcfg.disable_tools))
    return wire_id, display_name, overrides


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
    wire_id, display_name, overrides = _resolve_active_model(provider, model_name)
    return dataclasses.replace(
        config,
        active_provider=provider_name,
        model=wire_id,
        model_slug=model_name,
        model_name=display_name,
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
                    models[mname] = _model_config_from_dict(mcfg) if isinstance(mcfg, dict) else ModelConfig()
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

    wire_id, display_name, overrides = _resolve_active_model(active_prov, active_model)
    # Per-model overrides win over top-level config; top-level wins over defaults.
    def pick(field: str, default):
        if field in overrides:
            return overrides[field]
        return data.get(field, default)

    return Config(
        base_url=active_prov.base_url,
        model=wire_id,
        model_slug=active_model,
        model_name=display_name,
        api_key=active_prov.api_key,
        providers=providers,
        active_provider=active_provider,
        context_limit=pick("context_limit", DEFAULT_CONTEXT_LIMIT),
        max_tokens=pick("max_tokens", DEFAULT_MAX_TOKENS),
        temperature=pick("temperature", DEFAULT_TEMPERATURE),
        permission_mode=perm,
        mode=mode,
        max_depth=data.get("max_depth", DEFAULT_MAX_DEPTH),
        max_retries=data.get("max_retries", DEFAULT_MAX_RETRIES),
        bash_safe_prefixes=data.get("bash_safe_prefixes", []),
        output_budget_default=data.get("output_budget_default", 0),
        rtk=data.get("rtk", False),
        read_timeout=_resolve_read_timeout(data.get("read_timeout")),
        top_p=pick("top_p", None),
        top_k=pick("top_k", None),
        min_p=pick("min_p", None),
        presence_penalty=pick("presence_penalty", None),
        frequency_penalty=pick("frequency_penalty", None),
        repetition_penalty=overrides.get(
            "repetition_penalty",
            data.get("repetition_penalty", data.get("repeat_penalty")),
        ),
        chat_template_kwargs=pick("chat_template_kwargs", {}) or {},
        disable_tools=bool(pick("disable_tools", False)),
        system_prompt_extra=data.get("system_prompt_extra") or None,
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
    """Serialize *config* to JSON at *path*, preserving keys we don't own.

    Reads the existing file (if any) and overwrites only the fields tigger
    manages. Unknown top-level keys, unknown per-provider keys, and unknown
    per-model keys are preserved verbatim — protects hand-edited fields like
    top-level sampler defaults (top_p, top_k, min_p, repetition_penalty,
    presence_penalty, chat_template_kwargs) and any custom annotations from
    being silently dropped on save.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                existing = loaded
        except (json.JSONDecodeError, OSError):
            existing = {}

    existing_providers = existing.get("providers")
    if not isinstance(existing_providers, dict):
        existing_providers = {}

    providers_data: dict = {}
    for name, prov in config.providers.items():
        existing_prov = existing_providers.get(name)
        if not isinstance(existing_prov, dict):
            existing_prov = {}
        prov_data = dict(existing_prov)
        prov_data["base_url"] = prov.base_url
        prov_data["api_key"] = prov.api_key
        if isinstance(prov.models, dict):
            existing_models = existing_prov.get("models")
            if not isinstance(existing_models, dict):
                existing_models = {}
            models_data: dict = {}
            for mname, mcfg in prov.models.items():
                existing_model = existing_models.get(mname)
                if not isinstance(existing_model, dict):
                    existing_model = {}
                cfg_dict = dict(existing_model)
                for f in _MODEL_CONFIG_FIELDS:
                    val = getattr(mcfg, f)
                    if val is not None:
                        cfg_dict[f] = val
                models_data[mname] = cfg_dict
            prov_data["models"] = models_data
        else:
            prov_data["models"] = prov.models
        providers_data[name] = prov_data

    data = dict(existing)
    data["default_provider"] = config.active_provider
    data["default_model"] = config.model_slug or config.model
    data["providers"] = providers_data
    data["context_limit"] = config.context_limit
    data["max_tokens"] = config.max_tokens
    data["temperature"] = config.temperature
    data["permission_mode"] = config.permission_mode
    data["mode"] = config.mode
    data["max_depth"] = config.max_depth
    data["max_retries"] = config.max_retries
    data["bash_safe_prefixes"] = config.bash_safe_prefixes
    data["rtk"] = config.rtk
    data["read_timeout"] = config.read_timeout

    path.write_text(json.dumps(data, indent=2) + "\n")
