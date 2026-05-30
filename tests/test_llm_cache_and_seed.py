"""B1 + B3 (audit 2026-05-30): llm-dispatch prompt-cache auto-enable and the
honest anthropic seed contract.

These assert request *structure* — which kwargs the dispatcher forwards to each
client — never model output. Prompt caching is output-invariant (the model sees
identical tokens), and the seed guard is a contract check, so neither depends on
a live model.
"""

import pytest

from deep_research import llm

# Prefix-only synthetic model ids: `_provider()` routes purely on the prefix
# (gpt-* -> openai, claude* -> anthropic) and `raw_call` is stubbed below, so the
# id is just a routing token — it never reaches a network or a real model.
_PROVIDER_MODEL = {"anthropic_client": "claude-test", "openai_client": "gpt-test"}


def _capture(monkeypatch, which, role):
    """Stub `which`.raw_call to record forwarded kwargs, and pin `role` to a model
    that routes to `which` (via the DR_ROLE_* override) so the assertion can't be
    silently broken by a future role->provider remap in config — which would
    reroute the call to an unstubbed client and surface as a confusing KeyError on
    the empty `cap` rather than a clear failure.
    """
    monkeypatch.setenv(f"DR_ROLE_{role.upper()}", _PROVIDER_MODEL[which])
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
    # architect pinned to a claude-* model (anthropic); a >=min-size system auto-caches.
    cap = _capture(monkeypatch, "anthropic_client", "architect")
    llm.call("architect", "u", system="x" * (llm._CACHE_SYSTEM_MIN_CHARS + 1))
    assert cap["cache_system"] is True


def test_small_system_not_cached_on_anthropic(monkeypatch):
    cap = _capture(monkeypatch, "anthropic_client", "architect")
    llm.call("architect", "u", system="short system prompt")
    assert cap["cache_system"] is False


def test_writer_always_caches_regardless_of_size(monkeypatch):
    cap = _capture(monkeypatch, "anthropic_client", "writer")
    llm.call("writer", "u", system="short")
    assert cap["cache_system"] is True


def test_explicit_cache_override_respected(monkeypatch):
    cap = _capture(monkeypatch, "anthropic_client", "architect")
    llm.call("architect", "u", system="x" * (llm._CACHE_SYSTEM_MIN_CHARS + 1), cache_system=False)
    assert cap["cache_system"] is False


# ---- B3: honest seed contract -------------------------------------------


def test_seed_raises_on_anthropic(monkeypatch):
    _capture(monkeypatch, "anthropic_client", "architect")
    with pytest.raises(ValueError, match="seed"):
        llm.call("architect", "u", system="s", seed=123)


def test_no_seed_is_fine_on_anthropic(monkeypatch):
    cap = _capture(monkeypatch, "anthropic_client", "architect")
    llm.call("architect", "u", system="s")  # seed defaults to None
    assert cap["model"].startswith("claude")


def test_seed_forwarded_on_openai(monkeypatch):
    cap = _capture(monkeypatch, "openai_client", "intent")  # intent pinned to a gpt-* model -> openai
    llm.call("intent", "u", seed=7)
    assert cap["seed"] == 7
