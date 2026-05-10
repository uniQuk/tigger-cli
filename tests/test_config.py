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


def test_loader_defaults_match_dataclass():
    """Loader fallbacks must agree with Config dataclass defaults (single source)."""
    p = _write({"base_url": "http://x", "model": "m"})
    cfg = load_config(p)
    direct = Config(base_url="http://x", model="m")
    assert cfg.context_limit == direct.context_limit == 128000
    assert cfg.max_tokens == direct.max_tokens == 0
    assert cfg.max_depth == direct.max_depth == 4
    assert cfg.max_retries == direct.max_retries == 2
    assert cfg.temperature == direct.temperature == 0.7


def test_user_context_override_wins():
    p = _write({"base_url": "http://x", "model": "m", "context_limit": 8192})
    cfg = load_config(p)
    assert cfg.context_limit == 8192


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


def test_config_mode_defaults_to_act():
    p = _write({"base_url": "http://x", "model": "m"})
    cfg = load_config(p)
    assert cfg.mode == "act"


def test_mode_ask_silently_maps_to_act():
    p = _write({"base_url": "http://x", "model": "m", "mode": "ask"})
    cfg = load_config(p)
    assert cfg.mode == "act"


def test_unknown_mode_accepted_for_deferred_validation():
    """Unknown mode names are accepted by load_config; validated at startup."""
    p = _write({"base_url": "http://x", "model": "m", "mode": "custom"})
    cfg = load_config(p)
    assert cfg.mode == "custom"


# --- derive_provider_name tests ---

def test_derive_provider_name_ip():
    assert derive_provider_name("http://192.0.2.100:1234/v1") == "192.0.2.100"


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
    p = _write({"base_url": "http://192.0.2.100:1234/v1", "model": "qwen3",
                "api_key": "sk-test"})
    cfg = load_config(p)
    assert len(cfg.providers) == 1
    assert cfg.active_provider == "192.0.2.100"
    assert cfg.model == "qwen3"
    assert cfg.base_url == "http://192.0.2.100:1234/v1"
    assert cfg.model == "qwen3"
    assert cfg.api_key == "sk-test"
    prov = cfg.providers["192.0.2.100"]
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


def test_per_model_chat_template_kwargs_does_not_inherit_global():
    """Iter-5: a dict-format model entry without `chat_template_kwargs`
    must NOT inherit the global default. The global key may carry
    Qwen-only flags (enable_thinking / preserve_thinking) that a gemma
    or llama jinja template will reject with UndefinedValue."""
    p = _write({
        "default_provider": "local",
        "default_model": "gemma",
        "providers": {
            "local": {
                "base_url": "http://x",
                "models": {
                    "qwen": {"chat_template_kwargs": {"enable_thinking": True}},
                    "gemma": {"temperature": 1.0},
                },
            },
        },
        "chat_template_kwargs": {"enable_thinking": True, "preserve_thinking": True},
    })
    cfg = load_config(p)
    # gemma is the active model; per-model has no chat_template_kwargs,
    # so the active config carries an empty dict — NOT the global Qwen kwargs.
    assert cfg.chat_template_kwargs == {}
    # And switching to qwen brings ITS per-model kwargs in.
    cfg2 = switch_model(cfg, "local", "qwen")
    assert cfg2.chat_template_kwargs == {"enable_thinking": True}


def test_system_prompt_extra_loads():
    """`system_prompt_extra` round-trips through load_config."""
    p = _write({
        "base_url": "http://x", "model": "m",
        "system_prompt_extra": "Extra rule: speak only in haiku.",
    })
    cfg = load_config(p)
    assert cfg.system_prompt_extra == "Extra rule: speak only in haiku."


def test_system_prompt_extra_absent_is_none():
    """Missing `system_prompt_extra` keeps None (signals 'no addition')."""
    p = _write({"base_url": "http://x", "model": "m"})
    cfg = load_config(p)
    assert cfg.system_prompt_extra is None


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


def test_write_config_preserves_unknown_top_level_keys(tmp_path):
    """Hand-edited top-level keys (sampler defaults, custom annotations) must
    survive a save. Tigger only owns the fields it explicitly serializes;
    everything else is round-tripped verbatim."""
    out = tmp_path / "config.json"
    out.write_text(json.dumps({
        "providers": {
            "loc": {
                "base_url": "http://x/v1",
                "api_key": "k",
                "models": {"m1": {"temperature": 0.5}},
            },
        },
        "default_provider": "loc",
        "default_model": "m1",
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "repetition_penalty": 1.0,
        "presence_penalty": 0.0,
        "chat_template_kwargs": {"enable_thinking": True},
        "system_prompt_extra": "be concise",
        "custom_user_field": "annotation",
    }))
    cfg = load_config(out)
    write_config(out, cfg)
    after = json.loads(out.read_text())
    assert after["top_p"] == 0.95
    assert after["top_k"] == 20
    assert after["min_p"] == 0.0
    assert after["repetition_penalty"] == 1.0
    assert after["presence_penalty"] == 0.0
    assert after["chat_template_kwargs"] == {"enable_thinking": True}
    assert after["system_prompt_extra"] == "be concise"
    assert after["custom_user_field"] == "annotation"


def test_write_config_preserves_unknown_per_model_keys(tmp_path):
    """Per-model keys we don't recognize (custom annotations, future fields)
    survive verbatim through save."""
    out = tmp_path / "config.json"
    out.write_text(json.dumps({
        "providers": {
            "loc": {
                "base_url": "http://x/v1",
                "api_key": "k",
                "models": {
                    "m1": {
                        "temperature": 0.5,
                        "notes": "user-tuned for code review",
                        "future_sampler_param": 42,
                    },
                },
            },
        },
        "default_provider": "loc",
        "default_model": "m1",
    }))
    cfg = load_config(out)
    write_config(out, cfg)
    after = json.loads(out.read_text())
    m = after["providers"]["loc"]["models"]["m1"]
    assert m["notes"] == "user-tuned for code review"
    assert m["future_sampler_param"] == 42
    assert m["temperature"] == 0.5


def test_disable_tools_per_model_loads_and_switches():
    """A model with `disable_tools: true` resolves into Config.disable_tools=True;
    switching to a model without the flag returns to default False."""
    p = _write({
        "default_provider": "loc",
        "default_model": "gemma",
        "providers": {
            "loc": {
                "base_url": "http://x",
                "models": {
                    "gemma": {"temperature": 1.0, "disable_tools": True},
                    "qwen": {"temperature": 0.7},
                },
            },
        },
    })
    cfg = load_config(p)
    assert cfg.disable_tools is True
    cfg2 = switch_model(cfg, "loc", "qwen")
    assert cfg2.disable_tools is False


def test_disable_tools_round_trips_through_write_config(tmp_path):
    """`disable_tools` on a per-model entry survives write_config -> load_config."""
    out = tmp_path / "config.json"
    out.write_text(json.dumps({
        "providers": {
            "loc": {
                "base_url": "http://x/v1",
                "api_key": "k",
                "models": {"gemma": {"disable_tools": True}},
            },
        },
        "default_provider": "loc",
        "default_model": "gemma",
    }))
    cfg = load_config(out)
    write_config(out, cfg)
    reloaded = load_config(out)
    assert reloaded.disable_tools is True
    assert reloaded.providers["loc"].models["gemma"].disable_tools is True


def test_write_config_updates_default_model(tmp_path):
    """Switching the active model and saving updates `default_model` so the
    next session picks up where the user left off."""
    out = tmp_path / "config.json"
    out.write_text(json.dumps({
        "providers": {
            "loc": {
                "base_url": "http://x/v1",
                "api_key": "k",
                "models": {"a": {}, "b": {}},
            },
        },
        "default_provider": "loc",
        "default_model": "a",
    }))
    cfg = load_config(out)
    cfg = switch_model(cfg, "loc", "b")
    write_config(out, cfg)
    after = json.loads(out.read_text())
    assert after["default_model"] == "b"
    assert after["default_provider"] == "loc"
