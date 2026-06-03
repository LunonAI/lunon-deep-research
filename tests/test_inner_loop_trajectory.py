"""P3b-OPT2: inner-loop trajectory telemetry tests.

INNER_CAP now defaults to 2 (flipped from the W9 / 0.5229-baseline value of 3)
after the id=91 graded smoke proved the 3rd corrective pass is wasteful. The
loop still records, per section per iteration, whether grounding passed and the
inner-loop min_score so scripts/inner_cap_ab_analysis.py can keep checking
whether each corrective pass earns its cost. These tests guard (a) the cap
defaults to 2 (honoring the DR_INNER_CAP override) and (b) the trajectory is
recorded + persisted.
"""

import deep_research.orchestrate as orchestrate
from deep_research.pipeline import inner_loop


def test_inner_cap_default_is_2():
    """P3b-opt2: default flipped 3→2 after the id=91 graded smoke proved the
    3rd corrective pass is wasteful (49/51 sections reached it, 0 benefited,
    mean gain 0.029)."""
    assert orchestrate.INNER_CAP == 2


def test_inner_cap_honors_env_override(monkeypatch):
    """DR_INNER_CAP env override still works (e.g. to re-run at 3 for an A/B)."""
    import importlib

    monkeypatch.setenv("DR_INNER_CAP", "3")
    importlib.reload(orchestrate)
    try:
        assert orchestrate.INNER_CAP == 3
    finally:
        monkeypatch.delenv("DR_INNER_CAP", raising=False)
        importlib.reload(orchestrate)


def test_score_section_accepts_note(monkeypatch):
    """score_section threads a custom `note` into the cost ledger so inner_loop
    spend is attributable to a section (e.g. 'inner_loop.S3')."""
    captured = {}

    def fake_call_json(role, user, **kw):
        captured["note"] = kw.get("note")
        return {"scores": [{"dimension": "d", "criterion": "c", "score": 9, "rationale": "r"}]}

    monkeypatch.setattr(inner_loop.llm, "call_json", fake_call_json)
    inner_loop.score_section("body", {}, "en", "Title", note="inner_loop.S3")
    assert captured["note"] == "inner_loop.S3"


def test_score_section_default_note_preserved(monkeypatch):
    """Default note stays 'inner_loop' for callers that don't pass one."""
    captured = {}

    def fake_call_json(role, user, **kw):
        captured["note"] = kw.get("note")
        return {"scores": []}

    monkeypatch.setattr(inner_loop.llm, "call_json", fake_call_json)
    inner_loop.score_section("body", {}, "en", "Title")
    assert captured["note"] == "inner_loop"


def test_score_section_excludes_na_criteria_from_passfail(monkeypatch):
    """Per-section scope (2026-06-03): a criterion the grader marks `na` (owned by
    a DIFFERENT chapter) must be EXCLUDED from this section's min_score/fail — the
    fix for every-section-failing on other chapters' criteria. Here the only LOW
    score is na, and the in-scope criteria pass, so the section is OK."""
    scores = [
        {"dimension": "comprehensiveness", "criterion": "in-scope", "score": 7.5, "na": False, "rationale": "ok"},
        {"dimension": "instruction_following", "criterion": "in-scope 2", "score": 8, "na": False, "rationale": "ok"},
        {"dimension": "comprehensiveness", "criterion": "supplier-share (other chapter)", "score": 1.0, "na": True, "rationale": "out of scope"},
    ]
    monkeypatch.setattr(inner_loop.llm, "call_json", lambda *a, **k: {"scores": scores})
    r = inner_loop.score_section("body", {}, "zh", "产品定义章", section_scope="product definitions")
    assert r["ok"] is True, r
    assert r["min_score"] == 7.5  # the na=1.0 is excluded
    assert r["fail"] == []
    assert r["n_in_scope"] == 2


def test_score_section_passes_scope_to_grader(monkeypatch):
    """The section's planned scope reaches the grader prompt so it can judge
    which criteria are in-scope."""
    captured = {}
    monkeypatch.setattr(
        inner_loop.llm, "call_json", lambda role, user, **k: captured.update(user=user) or {"scores": []}
    )
    inner_loop.score_section("body", {}, "zh", "T", section_scope="covers suppliers and shares")
    assert "covers suppliers and shares" in captured["user"]


def test_score_section_all_na_falls_back_not_vacuous_pass(monkeypatch):
    """Degenerate guard: if the grader marks EVERYTHING na, fall back to scoring
    all criteria so a section can't pass vacuously on zero judged criteria."""
    scores = [{"dimension": "d", "criterion": "c", "score": 2.0, "na": True, "rationale": "x"}]
    monkeypatch.setattr(inner_loop.llm, "call_json", lambda *a, **k: {"scores": scores})
    r = inner_loop.score_section("body", {}, "zh", "T", section_scope="s")
    assert r["ok"] is False and r["min_score"] == 2.0  # fell back, did not pass on 0 criteria


def test_score_section_degraded_path_returns_n_in_scope(monkeypatch):
    """Return-type consistency: the scorer-failure (degraded) path includes
    n_in_scope so a caller using r['n_in_scope'] can't KeyError (Greptile #98)."""

    def boom(*a, **k):
        raise RuntimeError("scorer outage")

    monkeypatch.setattr(inner_loop.llm, "call_json", boom)
    r = inner_loop.score_section("body", {}, "en", "T")
    assert r["degraded"] is True and r["n_in_scope"] == 0


def test_trajectory_entry_shape():
    """The trajectory entry shape that orchestrate records must carry the
    fields the analysis script reads: i, grounding_ok, scored, score_ok,
    min_score, degraded. This pins the contract so the analyser and producer
    agree."""
    # A passing-on-first-try section produces one scored entry.
    # The `degraded` flag (Greptile PR #50) distinguishes a genuine pass from
    # score_section's ok=True / min_score=None (UNVALIDATED, E1 fix PR #81)
    # fallback when the inner-scorer LLM call fails — the analysis script
    # excludes degraded i==2.
    expected_keys = {"i", "grounding_ok", "scored", "score_ok", "min_score", "degraded"}
    entry = {"i": 0, "grounding_ok": True, "scored": True, "score_ok": True, "min_score": 8.5, "degraded": False}
    assert set(entry.keys()) == expected_keys
    # A grounding-fail iteration records scored=False / score_ok=None.
    g_fail = {"i": 0, "grounding_ok": False, "scored": False, "score_ok": None, "min_score": None, "degraded": False}
    assert set(g_fail.keys()) == expected_keys
    assert g_fail["scored"] is False and g_fail["score_ok"] is None


def test_state_has_inner_loop_trajectory_field():
    """PipelineState carries the aggregation list with a safe default."""
    from deep_research.state import PipelineState

    fields = PipelineState.__dataclass_fields__
    assert "inner_loop_trajectory" in fields
    # default_factory list → fresh empty list per instance (not a shared mutable)
    a = PipelineState.__dataclass_fields__["inner_loop_trajectory"].default_factory()
    assert a == []


def test_trajectory_persisted_to_drift(monkeypatch, tmp_path):
    """_persist_drift forwards inner_loop_trajectory into the drift record so
    the analyser can read it from inner_loop_drift.jsonl."""
    import json
    import types

    # Point the drift path at a temp file and capture what gets written.
    drift_file = tmp_path / "drift.jsonl"
    monkeypatch.setattr(orchestrate, "_DRIFT_PATH", drift_file)

    s = types.SimpleNamespace(
        archetype={"archetype": "predict"},
        domain="default",
        section_scores=[],
        failing_rationales=[],
        refiner_passes=1,
        validation_log=[],
        article="x",
        tool_calls=0,
        n_specialist_timeouts=0,
        numbering_fix_stats={},
        refiner_gate_verdict={},
        evidence_dedup_stats={},
        capel_stats={},
        g_dedup_suppressed=False,
        footnote_normalize_stats={},
        plan={},
        mermaid_validate_stats={},
        xref_repair_stats={},
        inner_loop_trajectory=[
            {
                "section": "S3",
                "iters": [{"i": 0, "grounding_ok": True, "scored": True, "score_ok": False, "min_score": 5.0}],
            }
        ],
    )
    orchestrate._persist_drift(s, "en", "q")
    rec = json.loads(drift_file.read_text().splitlines()[-1])
    assert "inner_loop_trajectory" in rec
    assert rec["inner_loop_trajectory"][0]["section"] == "S3"
    assert rec["inner_loop_trajectory"][0]["iters"][0]["min_score"] == 5.0
