"""round 10 (2026-06-03): OpenRouter throughput routing.

The Nemotron specialist extracts (~14k-token output) were auto-routed to slow
providers (DeepInfra pin falling back to DekaLLM/Nebius) and timing out at the
1000s specialist cap → structured findings discarded, run degraded to crude
snippets AND ate the timeout. Default routing now sorts by THROUGHPUT (fastest
provider), overriding the legacy fixed-provider pin.
"""

import importlib

from deep_research import _env
from deep_research.clients import openrouter_client as oc


def _cfg(provider, *, sort, pinned, monkeypatch):
    monkeypatch.setattr(oc, "_SORT", sort)
    monkeypatch.setattr(oc, "_PINNED", pinned)
    return oc._provider_config(provider)


def test_default_uses_throughput_sort_over_pin(monkeypatch):
    # the fix: throughput sort takes precedence over a slow fixed pin (DeepInfra)
    cfg = _cfg(None, sort="throughput", pinned="DeepInfra", monkeypatch=monkeypatch)
    assert cfg == {"allow_fallbacks": True, "sort": "throughput"}
    assert "order" not in cfg  # the slow DeepInfra pin is NOT used


def test_empty_string_is_throughput_sorted(monkeypatch):
    cfg = _cfg("", sort="throughput", pinned="DeepInfra", monkeypatch=monkeypatch)
    assert cfg == {"allow_fallbacks": True, "sort": "throughput"}


def test_strict_per_call_pin_has_no_sort(monkeypatch):
    # explicit per-call pin (repro experiments) — strict, no fallback, no sort
    cfg = _cfg("Together", sort="throughput", pinned="DeepInfra", monkeypatch=monkeypatch)
    assert cfg == {"allow_fallbacks": False, "order": ["Together"]}


def test_sort_off_restores_legacy_pin(monkeypatch):
    # DR_OPENROUTER_SORT=off (→ _SORT="") falls back to the _PINNED order
    cfg = _cfg(None, sort="", pinned="DeepInfra", monkeypatch=monkeypatch)
    assert cfg == {"allow_fallbacks": True, "order": ["DeepInfra"]}


def test_sort_default_is_throughput_when_env_unset(monkeypatch):
    # An unset DR_OPENROUTER_SORT must still default routing ON (throughput).
    # Patch the real env BEFORE the reload — monkeypatching oc.get is futile
    # because importlib.reload re-runs `from .._env import get`, rebinding
    # oc.get to the live function before _SORT is computed. get() reads the
    # .env ENV map first, then os.environ, so neutralise BOTH sources to make
    # the test hermetic regardless of the host/CI environment.
    original_sort = oc._SORT
    monkeypatch.setitem(_env.ENV, "DR_OPENROUTER_SORT", "")
    monkeypatch.delenv("DR_OPENROUTER_SORT", raising=False)
    importlib.reload(oc)
    try:
        assert oc._SORT == "throughput"
    finally:
        # Restore the recomputed module global directly. A second
        # importlib.reload here would run while monkeypatch is STILL active
        # (teardown fires only after the test returns), recomputing _SORT from
        # the patched env and leaving it stale on hosts that set
        # DR_OPENROUTER_SORT. Direct restore is env-independent.
        oc._SORT = original_sort
