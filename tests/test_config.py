import json
import tempfile
import pathlib
import warnings
import pytest
from newcli.config import load_config
from newcli.types import Config


def _write(data: dict) -> pathlib.Path:
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    json.dump(data, f)
    f.close()
    return pathlib.Path(f.name)


def test_load_minimal():
    p = _write({"base_url": "http://localhost:11434/v1", "model": "qwen3"})
    cfg = load_config(p)
    assert isinstance(cfg, Config)
    assert cfg.base_url == "http://localhost:11434/v1"
    assert cfg.model == "qwen3"
    assert cfg.api_key == "local"           # default applied


def test_load_overrides_defaults():
    p = _write({"base_url": "http://x", "model": "m",
                "permission_mode": "bypass", "max_depth": 2})
    cfg = load_config(p)
    assert cfg.permission_mode == "bypass"
    assert cfg.max_depth == 2


def test_missing_required_fields():
    p = _write({"model": "qwen3"})          # no base_url
    with pytest.raises(ValueError, match="base_url"):
        load_config(p)


def test_invalid_permission_mode():
    p = _write({"base_url": "http://x", "model": "m", "permission_mode": "yolo"})
    with pytest.raises(ValueError, match="permission_mode"):
        load_config(p)


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_config(pathlib.Path("/no/such/config.json"))


def test_old_permission_names_map_to_new():
    mapping = {"manual": "ask", "auto": "allow", "accept-all": "bypass"}
    for old, new in mapping.items():
        p = _write({"base_url": "http://x", "model": "m", "permission_mode": old})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = load_config(p)
        assert cfg.permission_mode == new, f"{old} should map to {new}"
        assert any("deprecated" in str(x.message).lower() for x in w)


def test_new_permission_names_accepted():
    for name in ("ask", "allow", "bypass"):
        p = _write({"base_url": "http://x", "model": "m", "permission_mode": name})
        cfg = load_config(p)
        assert cfg.permission_mode == name


def test_config_loads_mode_field():
    p = _write({"base_url": "http://x", "model": "m", "mode": "plan"})
    cfg = load_config(p)
    assert cfg.mode == "plan"


def test_config_mode_defaults_to_ask():
    p = _write({"base_url": "http://x", "model": "m"})
    cfg = load_config(p)
    assert cfg.mode == "ask"


def test_invalid_mode_raises():
    p = _write({"base_url": "http://x", "model": "m", "mode": "yolo"})
    with pytest.raises(ValueError, match="mode"):
        load_config(p)
