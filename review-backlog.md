# Architecture Review Backlog

Suggested improvements deferred from code review of `fix/architecture-review-fixes` (2026-04-25).

## 1. role=system provider compatibility

`summarize_old()` uses `role="system"` for compaction summaries. Some OpenAI-compatible local model servers may reject mid-conversation system messages. Consider a config option or fallback.

**File:** `src/tigger/compaction.py:107`

## 2. Add `__all__` to parsing.py and skills.py

Would clarify public API and help tooling distinguish public vs private symbols.

**Files:** `src/tigger/parsing.py`, `src/tigger/skills.py`

## 3. `.egg-info` in `_DEFAULT_EXCLUDES` never fires

Real directories are `package_name.egg-info`, so the exact-match check never triggers. Needs suffix matching:

```python
any(part.endswith(".egg-info") for part in ...)
```

**File:** `src/tigger/tools.py:14`

## 4. Add link-local SSRF test

Missing test coverage for `169.254.x.x` and `fe80::` addresses in `_is_private_or_local`.

```python
def test_ssrf_link_local():
    assert _is_private_or_local("169.254.1.1") is True
```

**File:** `tests/test_tools.py`
