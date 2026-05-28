"""PR-B-safe: the whole-article refiner must skip drafts it physically cannot
return within the output budget (a guaranteed min-ratio revert that still bills
the full input + ~3.5min). Observed on the id=91 smoke: $0.96 + 207s for a
no-op on a 65k-word article.
"""

from deep_research.pipeline import refiner


def test_skips_when_draft_exceeds_output_budget(monkeypatch):
    """A draft whose 0.70-pruned size still exceeds the output budget is skipped
    WITHOUT an LLM call (guaranteed revert)."""
    called = {"n": 0}

    def fake_call(*a, **k):  # pragma: no cover - must not run
        called["n"] += 1
        return "x"

    monkeypatch.setattr(refiner.llm, "call", fake_call)
    # 0.70 * est_out > _MAX_OUT_TOKENS  →  len > _MAX_OUT_TOKENS * _TOK / 0.70
    huge = "word " * 60000  # ~300k chars → ~75k out-tokens
    out = refiner.refine(huge, archetype="list-all", language="en")
    assert out["applied"] is False
    assert "exceeds rewrite output budget" in out["reason"]
    assert out["article"] == huge  # unchanged passthrough
    assert called["n"] == 0  # never paid for the doomed call


def test_runs_when_draft_fits(monkeypatch):
    """A draft that fits is refined normally (guard does not over-trigger)."""
    captured = {}

    def fake_call(role, user, **k):
        captured["role"] = role
        return "refined body that is long enough to clear the min-ratio floor " * 20

    monkeypatch.setattr(refiner.llm, "call", fake_call)
    draft = "original body that is long enough to clear the min-ratio floor " * 20
    out = refiner.refine(draft, archetype="list-all", language="en")
    assert captured["role"] == "refiner"
    assert out["applied"] is True


def test_skip_threshold_ties_to_revert_ratio(monkeypatch):
    """Guard fires only when even a maximal 0.70 prune can't fit — never on a
    draft that could prune-to-fit."""
    monkeypatch.setattr(refiner.llm, "call", lambda *a, **k: "x " * 100)
    # Just BELOW the skip threshold: est_out * 0.70 < budget → must NOT skip.
    fits_chars = int(refiner._MAX_OUT_TOKENS * refiner._TOK / refiner._REVERT_RATIO) - 8000
    out = refiner.refine("a" * fits_chars, archetype="trend", language="en")
    assert "exceeds rewrite output budget" not in out["reason"]
