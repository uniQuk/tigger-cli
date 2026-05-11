"""Perf-instrumentation tests for `loop.run` (R7, R8)."""
from __future__ import annotations

import pathlib

from tigger.loop import run
from tigger.tools import ToolRegistry
from tigger.types import (
    AssistantMessage,
    Config,
    RunContext,
    TextChunk,
    ToolCallRecord,
)


def _ctx() -> RunContext:
    cfg = Config(base_url="http://x", model="m", permission_mode="bypass")
    return RunContext(config=cfg, messages=[], system_prompt="sys")


def _two_turn_provider(*, in_tokens: list[int], out_tokens: list[int]):
    """Provider that issues a tool call on turn 1 then stops on turn 2."""
    state = {"turn": 0}

    def fake(system, messages, tools, config):
        i = state["turn"]
        state["turn"] += 1
        yield TextChunk(content="")
        if i == 0:
            yield AssistantMessage(
                content="",
                tool_calls=[ToolCallRecord("c1", "noop", {})],
                input_tokens=in_tokens[0],
                output_tokens=out_tokens[0],
                finish_reason="tool_calls",
            )
        else:
            yield AssistantMessage(
                content="done",
                tool_calls=[],
                input_tokens=in_tokens[1] if len(in_tokens) > 1 else 0,
                output_tokens=out_tokens[1] if len(out_tokens) > 1 else 0,
                finish_reason="stop",
            )

    return fake


def _noop_registry() -> ToolRegistry:
    from tigger.types import ToolDef

    reg = ToolRegistry()
    reg.register(ToolDef(
        name="noop",
        description="",
        parameters={"type": "object", "properties": {}},
        func=lambda args: "ok",
    ))
    return reg


def _read_perf(path: pathlib.Path) -> tuple[list[str], list[list[str]]]:
    lines = path.read_text().strip().splitlines()
    header = lines[0].split("\t")
    rows = [line.split("\t") for line in lines[1:]]
    return header, rows


def test_perf_header_includes_new_columns(tmp_path, monkeypatch):
    perf_file = tmp_path / "perf.tsv"
    monkeypatch.setenv("TIGGER_PERF", str(perf_file))
    list(run(
        "hi",
        _ctx(),
        _noop_registry(),
        provider_fn=_two_turn_provider(in_tokens=[100, 110], out_tokens=[5, 3]),
    ))
    header, rows = _read_perf(perf_file)
    assert header[-4:] == [
        "delta_chars",
        "tokens_per_sec",
        "cache_hit_estimate",
        "apparent_prefill_tok_per_s",
    ]
    assert len(rows) == 2
    # Every row has the same number of columns as the header.
    assert all(len(r) == len(header) for r in rows)


def test_perf_apparent_prefill_signals_cache_hit(tmp_path, monkeypatch):
    """`apparent_prefill_tok_per_s` = local_tokens / wall — when the host
    served the prefix from KV cache, wall is decode-bound and this number
    far exceeds the model's known decode rate. Works across single-shot
    `--once` runs, unlike cache_hit_estimate which needs a prior turn."""
    perf_file = tmp_path / "perf.tsv"
    monkeypatch.setenv("TIGGER_PERF", str(perf_file))

    # Force a fast turn: 5000-token prompt served in 1s ⇒ apparent_prefill
    # = 5000 tok/s (a cache-hit signature on any local 27b-class model).
    import tigger.loop as loop_mod
    real_mono = loop_mod.time.monotonic
    counter = {"n": 0}

    def fake_mono() -> float:
        counter["n"] += 1
        # turn_start, compact_start, compact_end, then turn end at +1s.
        return real_mono() + (1.0 if counter["n"] >= 4 else 0.0)

    monkeypatch.setattr(loop_mod.time, "monotonic", fake_mono)
    list(run(
        "hi",
        _ctx(),
        _noop_registry(),
        provider_fn=_two_turn_provider(in_tokens=[5000, 5000], out_tokens=[10, 10]),
    ))
    header, rows = _read_perf(perf_file)
    apparent_idx = header.index("apparent_prefill_tok_per_s")
    # ~5000 tok / ~1s ⇒ far above any local decode rate (max ~50 tok/s).
    assert float(rows[0][apparent_idx]) >= 1000.0


def test_cache_likely_hit_signal_fires_when_apparent_prefill_high(
    tmp_path, monkeypatch, capsys,
):
    """Iter-35: emit `[perf] cache likely hit` when apparent_prefill_tok_per_s
    exceeds 100 tok/s — empirically impossible without prefix caching on
    local hardware."""
    perf_file = tmp_path / "perf.tsv"
    monkeypatch.setenv("TIGGER_PERF", str(perf_file))

    import tigger.loop as loop_mod
    real_mono = loop_mod.time.monotonic
    counter = {"n": 0}

    def fake_mono() -> float:
        counter["n"] += 1
        return real_mono() + (1.0 if counter["n"] >= 4 else 0.0)

    monkeypatch.setattr(loop_mod.time, "monotonic", fake_mono)
    list(run(
        "hi",
        _ctx(),
        _noop_registry(),
        provider_fn=_two_turn_provider(in_tokens=[5000, 5000], out_tokens=[10, 10]),
    ))
    captured = capsys.readouterr()
    assert "cache likely hit" in captured.err
    assert "apparent_prefill=" in captured.err


def test_cache_likely_hit_suppressed_when_prefill_dominant(
    tmp_path, monkeypatch, capsys,
):
    """Iter-49: when prefill-dominant fires AND apparent_prefill > 100
    (partial-warm cases), the cache-likely-hit line is suppressed — the
    prefill-dominant warning already carries the apparent_prefill rate,
    so emitting both reads as a contradiction."""
    perf_file = tmp_path / "perf.tsv"
    monkeypatch.setenv("TIGGER_PERF", str(perf_file))

    import tigger.loop as loop_mod
    real_mono = loop_mod.time.monotonic
    counter = {"n": 0}

    def fake_mono() -> float:
        counter["n"] += 1
        # Monotonic offset grows by 30s per call, so each turn's wall is ~90s
        # (4 monotonic calls per turn). With in=15000 and out=3:
        #   wall/out = 90/3 = 30 > 1.5 → prefill-dominant fires.
        #   apparent_prefill = 15000/90 ≈ 167 > 100 → cache-likely-hit
        #   threshold met. Both conditions true; only prefill-dominant should
        #   print after the iter-49 suppression rule.
        return real_mono() + counter["n"] * 30.0

    monkeypatch.setattr(loop_mod.time, "monotonic", fake_mono)
    list(run(
        "hi",
        _ctx(),
        _noop_registry(),
        provider_fn=_two_turn_provider(in_tokens=[15000, 15000], out_tokens=[3, 3]),
    ))
    captured = capsys.readouterr()
    assert "prefill-dominant" in captured.err
    assert "cache likely hit" not in captured.err


def test_cache_likely_hit_signal_silent_on_cold_prefill(
    tmp_path, monkeypatch, capsys,
):
    """Cold-prefill scenario: 500-token prompt taking ~90s wall ⇒
    apparent_prefill ≈ 5.6 tok/s, well below the 100 threshold. Signal
    must NOT fire on either of the two turns."""
    perf_file = tmp_path / "perf.tsv"
    monkeypatch.setenv("TIGGER_PERF", str(perf_file))

    import tigger.loop as loop_mod
    real_mono = loop_mod.time.monotonic
    counter = {"n": 0}

    def fake_mono() -> float:
        counter["n"] += 1
        # Advance 30s on every call so every wall spans ~90s — emulates a
        # cold-prefill regime where wall is dominated by prompt processing.
        return real_mono() + 30.0 * counter["n"]

    monkeypatch.setattr(loop_mod.time, "monotonic", fake_mono)
    list(run(
        "hi",
        _ctx(),
        _noop_registry(),
        provider_fn=_two_turn_provider(in_tokens=[500, 500], out_tokens=[10, 10]),
    ))
    captured = capsys.readouterr()
    assert "cache likely hit" not in captured.err


def test_perf_first_turn_cache_hit_zero(tmp_path, monkeypatch):
    perf_file = tmp_path / "perf.tsv"
    monkeypatch.setenv("TIGGER_PERF", str(perf_file))
    list(run(
        "hi",
        _ctx(),
        _noop_registry(),
        provider_fn=_two_turn_provider(in_tokens=[100, 110], out_tokens=[5, 3]),
    ))
    header, rows = _read_perf(perf_file)
    cache_idx = header.index("cache_hit_estimate")
    delta_idx = header.index("delta_chars")
    chars_idx = header.index("prompt_chars")
    # Turn 1: no prior turn, cache_hit_estimate must be 0.
    assert float(rows[0][cache_idx]) == 0.0
    # delta_chars on turn 1 equals the full prompt_chars.
    assert int(rows[0][delta_idx]) == int(rows[0][chars_idx])


def test_perf_zero_output_does_not_divide_by_zero(tmp_path, monkeypatch):
    perf_file = tmp_path / "perf.tsv"
    monkeypatch.setenv("TIGGER_PERF", str(perf_file))
    list(run(
        "hi",
        _ctx(),
        _noop_registry(),
        provider_fn=_two_turn_provider(in_tokens=[100, 110], out_tokens=[0, 0]),
    ))
    header, rows = _read_perf(perf_file)
    tps_idx = header.index("tokens_per_sec")
    # Should be 0.00 — no exception raised.
    assert float(rows[0][tps_idx]) == 0.0


def test_perf_warning_fires_on_prefill_dominant_turn(tmp_path, monkeypatch, capsys):
    """A turn with high wall/output ratio AND small delta_chars should warn."""
    perf_file = tmp_path / "perf.tsv"
    monkeypatch.setenv("TIGGER_PERF", str(perf_file))

    # Force a slow turn: patch time.monotonic to advance 10s per call after start.
    import tigger.loop as loop_mod

    real_mono = loop_mod.time.monotonic
    counter = {"n": 0}

    def slow_mono():
        counter["n"] += 1
        # First two calls: turn_start, compact_start. Subsequent: simulate 10s passed.
        if counter["n"] <= 2:
            return 0.0
        return 10.0

    monkeypatch.setattr(loop_mod.time, "monotonic", slow_mono)

    list(run(
        "hi",
        _ctx(),
        _noop_registry(),
        provider_fn=_two_turn_provider(in_tokens=[100, 110], out_tokens=[3, 3]),
    ))

    captured = capsys.readouterr()
    monkeypatch.setattr(loop_mod.time, "monotonic", real_mono)
    # At least one turn should have triggered the warning.
    assert "prefill-dominant" in captured.err
    # Iter 48: the warning carries the apparent_prefill rate so the user
    # can see how cold the cache was when it fired.
    assert "apparent_prefill=" in captured.err
