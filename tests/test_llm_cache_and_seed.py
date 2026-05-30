"""B1 + B3 (audit 2026-05-30): llm-dispatch prompt-cache auto-enable and the
honest anthropic seed contract.

These assert request *structure* — which kwargs the dispatcher forwards to each
client — never model output. Prompt caching is output-invariant (the model sees
identical tokens), and the seed guard is a contract check, so neither depends on
a live model.
"""

import pytest

from deep_research import llm


def _capture(monkeypatch, which):
    cap = {}

    def fake(model, user, **kw):
        cap.update(kw)
        cap["model"] = model
        return "out", {}

    monkeypatch.setattr(getattr(llm, which), "raw_call", fake)
    return cap


# ---- B1: size-based system caching --------------------------------------


def test_should_cache_system_unit():
    assert llm._should_cache_system("writer", "tiny") is True  # writer always
    assert llm._should_cache_system("architect", "x" * llm._CACHE_SYSTEM_MIN_CHARS) is True
    assert llm._should_cache_system("architect", "x" * (llm._CACHE_SYSTEM_MIN_CHARS - 1)) is False
    assert llm._should_cache_system("scout", "x" * 200) is False
    assert llm._should_cache_system("architect", None) is False


def test_large_system_auto_caches_on_anthropic(monkeypatch):
    # architect routes to claude (anthropic); a >=min-size system auto-caches.
    cap = _capture(monkeypatch, "anthropic_client")
    llm.call("architect", "u", system="x" * (llm._CACHE_SYSTEM_MIN_CHARS + 1))
    assert cap["cache_system"] is True


def test_small_system_not_cached_on_anthropic(monkeypatch):
    cap = _capture(monkeypatch, "anthropic_client")
    llm.call("architect", "u", system="short system prompt")
    assert cap["cache_system"] is False


def test_writer_always_caches_regardless_of_size(monkeypatch):
    cap = _capture(monkeypatch, "anthropic_client")
    llm.call("writer", "u", system="short")
    assert cap["cache_system"] is True


def test_explicit_cache_override_respected(monkeypatch):
    cap = _capture(monkeypatch, "anthropic_client")
    llm.call("architect", "u", system="x" * (llm._CACHE_SYSTEM_MIN_CHARS + 1), cache_system=False)
    assert cap["cache_system"] is False


# ---- B3: honest seed contract -------------------------------------------


def test_seed_raises_on_anthropic(monkeypatch):
    _capture(monkeypatch, "anthropic_client")
    with pytest.raises(ValueError, match="seed"):
        llm.call("architect", "u", system="s", seed=123)


def test_no_seed_is_fine_on_anthropic(monkeypatch):
    cap = _capture(monkeypatch, "anthropic_client")
    llm.call("architect", "u", system="s")  # seed defaults to None
    assert cap["model"].startswith("claude")


def test_seed_forwarded_on_openai(monkeypatch):
    cap = _capture(monkeypatch, "openai_client")
    llm.call("intent", "u", seed=7)  # intent -> gpt-5.5 (openai)
    assert cap["seed"] == 7
