from __future__ import annotations
import json
import pathlib
from newcli.types import Config

_VALID_PERMISSION_MODES = {"auto", "manual", "accept-all"}


def load_config(path: pathlib.Path) -> Config:
    """Load config.json at *path* and return a validated frozen Config."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open() as f:
        data = json.load(f)

    if "base_url" not in data:
        raise ValueError("config.json missing required field: base_url")
    if "model" not in data:
        raise ValueError("config.json missing required field: model")

    mode = data.get("permission_mode", "auto")
    if mode not in _VALID_PERMISSION_MODES:
        raise ValueError(
            f"permission_mode must be one of {_VALID_PERMISSION_MODES}, got {mode!r}"
        )

    return Config(
        base_url=data["base_url"],
        model=data["model"],
        api_key=data.get("api_key", "local"),
        context_limit=data.get("context_limit", 8192),
        max_tokens=data.get("max_tokens", 2048),
        temperature=data.get("temperature", 0.7),
        permission_mode=mode,
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
