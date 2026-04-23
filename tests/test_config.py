import json
import tempfile
import pathlib
import warnings
import pytest
from tigger.config import load_config, derive_provider_name, switch_model, write_config
from tigger.types import Config, ModelConfig, ProviderConfig


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


# --- derive_provider_name tests ---

def test_derive_provider_name_ip():
    assert derive_provider_name("http://192.168.2.122:1234/v1") == "192.168.2.122"


def test_derive_provider_name_openai():
    assert derive_provider_name("https://api.openai.com/v1") == "openai"


def test_derive_provider_name_localhost():
    assert derive_provider_name("http://localhost:1234/v1") == "localhost"


def test_derive_provider_name_custom_domain():
    assert derive_provider_name("https://my-llm.example.org/v1") == "my-llm.example"


# --- switch_model tests ---

def test_switch_model_changes_active():
    pc1 = ProviderConfig(name="a", base_url="http://a/v1", api_key="ka", models=["m1"])
    pc2 = ProviderConfig(name="b", base_url="http://b/v1", api_key="kb", models=["m2", "m3"])
    cfg = Config(base_url="http://a/v1", model="m1", api_key="ka",
                 providers={"a": pc1, "b": pc2}, active_provider="a")
    new = switch_model(cfg, "b", "m3")
    assert new.active_provider == "b"
    assert new.model == "m3"
    assert new.base_url == "http://b/v1"
    assert new.model == "m3"
    assert new.api_key == "kb"


def test_switch_model_preserves_other_fields():
    pc = ProviderConfig(name="a", base_url="http://a/v1", api_key="k", models=["m"])
    cfg = Config(base_url="http://a/v1", model="m", api_key="k",
                 providers={"a": pc}, active_provider="a",
                 context_limit=64000, temperature=0.5)
    new = switch_model(cfg, "a", "m")
    assert new.context_limit == 64000
    assert new.temperature == 0.5


# --- load_config provider tests ---

def test_load_old_format_creates_provider():
    p = _write({"base_url": "http://192.168.2.122:1234/v1", "model": "qwen3",
                "api_key": "sk-test"})
    cfg = load_config(p)
    assert len(cfg.providers) == 1
    assert cfg.active_provider == "192.168.2.122"
    assert cfg.model == "qwen3"
    assert cfg.base_url == "http://192.168.2.122:1234/v1"
    assert cfg.model == "qwen3"
    assert cfg.api_key == "sk-test"
    prov = cfg.providers["192.168.2.122"]
    assert prov.models == ["qwen3"]


def test_load_new_format():
    data = {
        "default_provider": "local",
        "default_model": "qwen3",
        "providers": {
            "local": {
                "base_url": "http://localhost:1234/v1",
                "api_key": "local",
                "models": ["qwen3", "llama"]
            },
            "cloud": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-cloud",
                "models": ["gpt-4o"]
            }
        }
    }
    p = _write(data)
    cfg = load_config(p)
    assert len(cfg.providers) == 2
    assert cfg.active_provider == "local"
    assert cfg.model == "qwen3"
    assert cfg.base_url == "http://localhost:1234/v1"
    assert cfg.api_key == "local"
    assert cfg.providers["cloud"].models == ["gpt-4o"]


def test_load_new_format_defaults_to_first_provider():
    data = {
        "providers": {
            "only": {
                "base_url": "http://x/v1",
                "api_key": "k",
                "models": ["m1"]
            }
        }
    }
    p = _write(data)
    cfg = load_config(p)
    assert cfg.active_provider == "only"
    assert cfg.model == "m1"


# --- write_config tests ---

def test_write_config_round_trips(tmp_path):
    pc = ProviderConfig(name="loc", base_url="http://x/v1", api_key="k", models=["m1", "m2"])
    cfg = Config(base_url="http://x/v1", model="m1", api_key="k",
                 providers={"loc": pc}, active_provider="loc")
    out = tmp_path / "config.json"
    write_config(out, cfg)
    reloaded = load_config(out)
    assert reloaded.active_provider == "loc"
    assert reloaded.model == "m1"
    assert reloaded.providers["loc"].models == ["m1", "m2"]


def test_write_config_creates_parent_dirs(tmp_path):
    pc = ProviderConfig(name="x", base_url="http://x/v1", api_key="k", models=["m"])
    cfg = Config(base_url="http://x/v1", model="m", api_key="k",
                 providers={"x": pc}, active_provider="x")
    out = tmp_path / "sub" / "dir" / "config.json"
    write_config(out, cfg)
    assert out.exists()


# --- Per-model config (dict-style models) tests ---

def test_load_config_dict_models():
    data = {
        "providers": {
            "local": {
                "base_url": "http://localhost/v1",
                "api_key": "local",
                "models": {
                    "qwen3": {"temperature": 0.3, "max_tokens": 4096},
                    "llama": {}
                }
            }
        }
    }
    p = _write(data)
    cfg = load_config(p)
    prov = cfg.providers["local"]
    assert isinstance(prov.models, dict)
    assert prov.model_names == ["qwen3", "llama"]
    assert prov.models["qwen3"].temperature == 0.3
    assert prov.models["qwen3"].max_tokens == 4096
    assert prov.models["llama"].temperature is None


def test_load_config_list_models_still_works():
    data = {
        "providers": {
            "local": {
                "base_url": "http://localhost/v1",
                "api_key": "local",
                "models": ["qwen3", "llama"]
            }
        }
    }
    p = _write(data)
    cfg = load_config(p)
    prov = cfg.providers["local"]
    assert isinstance(prov.models, list)
    assert prov.models == ["qwen3", "llama"]


def test_switch_model_merges_overrides():
    models = {
        "hot": ModelConfig(temperature=1.0, max_tokens=8192, context_limit=64000),
        "cold": ModelConfig(temperature=0.1),
    }
    pc = ProviderConfig(name="p", base_url="http://x/v1", api_key="k", models=models)
    cfg = Config(base_url="http://x/v1", model="hot", api_key="k",
                 providers={"p": pc}, active_provider="p",
                 temperature=0.7, max_tokens=2048, context_limit=8192)
    new = switch_model(cfg, "p", "hot")
    assert new.temperature == 1.0
    assert new.max_tokens == 8192
    assert new.context_limit == 64000


def test_switch_model_no_override_uses_global():
    models = {"m1": ModelConfig(temperature=0.9)}
    pc = ProviderConfig(name="p", base_url="http://x/v1", api_key="k", models=models)
    cfg = Config(base_url="http://x/v1", model="m1", api_key="k",
                 providers={"p": pc}, active_provider="p",
                 temperature=0.7, max_tokens=2048)
    # Switch to a model not in the dict — should keep globals
    new = switch_model(cfg, "p", "m_unknown")
    assert new.temperature == 0.7
    assert new.max_tokens == 2048


def test_write_config_preserves_dict_models(tmp_path):
    models = {
        "qwen3": ModelConfig(temperature=0.3, context_limit=32000),
        "llama": ModelConfig(),
    }
    pc = ProviderConfig(name="loc", base_url="http://x/v1", api_key="k", models=models)
    cfg = Config(base_url="http://x/v1", model="qwen3", api_key="k",
                 providers={"loc": pc}, active_provider="loc")
    out = tmp_path / "config.json"
    write_config(out, cfg)
    reloaded = load_config(out)
    prov = reloaded.providers["loc"]
    assert isinstance(prov.models, dict)
    assert prov.model_names == ["qwen3", "llama"]
    assert prov.models["qwen3"].temperature == 0.3
    assert prov.models["qwen3"].context_limit == 32000
    assert prov.models["llama"].temperature is None
