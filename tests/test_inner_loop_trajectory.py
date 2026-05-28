"""P3b-OPT2 (2026-05-27): inner-loop trajectory telemetry tests.

INNER_CAP stays at 3 (the W9 / 0.5229-baseline value). This PR only OBSERVES
the loop — recording, per section per iteration, whether grounding passed and
the inner-loop min_score — so scripts/inner_cap_ab_analysis.py can decide
empirically whether the 2nd/3rd corrective pass earns its cost. These tests
guard (a) the cap is NOT changed and (b) the trajectory is recorded + persisted.
"""

import deep_research.orchestrate as orchestrate
from deep_research.pipeline import inner_loop


def test_inner_cap_unchanged_at_3():
    """Regression guard: this PR must NOT change INNER_CAP. The 0.5229
    leaderboard baseline ran at 3; we measure before we ever consider 2."""
    assert orchestrate.INNER_CAP == 3


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


def test_trajectory_entry_shape():
    """The trajectory entry shape that orchestrate records must carry the
    fields the analysis script reads: i, grounding_ok, scored, score_ok,
    min_score, degraded. This pins the contract so the analyser and producer
    agree."""
    # A passing-on-first-try section produces one scored entry.
    # The `degraded` flag (Greptile PR #50) distinguishes a genuine pass from
    # score_section's synthetic ok=True/min_score=10.0 fallback when the
    # inner-scorer LLM call fails — the analysis script excludes degraded i==2.
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
