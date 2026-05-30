"""E1 (audit 2026-05-30): a degraded inner-scorer must stay fail-soft but must
NOT launder a scorer outage into a synthetic 10/10 pass.

Before this fix, score_section returned min_score=10.0 when the scorer LLM call
raised, so a transient outage shipped every affected section at a perfect score
— invisible except in drift logs. The fix keeps ok=True (still ships, doesn't
burn the inner-loop budget) but reports min_score=None (UNVALIDATED).
"""

from deep_research.pipeline import inner_loop


def test_degraded_scorer_is_unvalidated_not_perfect(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("scorer outage")

    monkeypatch.setattr(inner_loop.llm, "call_json", boom)
    r = inner_loop.score_section("body", {"criterions": {}}, "en", "Title")
    assert r["degraded"] is True
    assert r["ok"] is True  # fail-soft: section still ships
    assert r["min_score"] is None  # but NOT a fake 10/10
    assert r["fail"] == []


def test_healthy_scorer_unaffected(monkeypatch):
    def healthy(*a, **k):
        return {"scores": [{"dimension": "d", "criterion": "c", "score": 7, "rationale": "ok"}]}

    monkeypatch.setattr(inner_loop.llm, "call_json", healthy)
    spec = {"criterions": {"d": [{"criterion": "c", "explanation": "e"}]}}
    r = inner_loop.score_section("body", spec, "en", "Title")
    assert not r.get("degraded")
    assert r["ok"] is True
    assert r["min_score"] == 7.0


def test_healthy_scorer_below_threshold_fails(monkeypatch):
    def low(*a, **k):
        return {"scores": [{"dimension": "d", "criterion": "c", "score": 3, "rationale": "thin"}]}

    monkeypatch.setattr(inner_loop.llm, "call_json", low)
    spec = {"criterions": {"d": [{"criterion": "c"}]}}
    r = inner_loop.score_section("body", spec, "en", "Title")
    assert not r.get("degraded")
    assert r["ok"] is False  # genuine low score still blocks, unlike a degraded pass
    assert r["min_score"] == 3.0
