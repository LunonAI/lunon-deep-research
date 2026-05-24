"""Unit tests for deep_research.pipeline.architect (P2-Option-A-#1).

Covers the post-Wave-2.5-#1 schema additions:
- depth_seeds backfill (pre-#1 plans without the field get an empty list)
- outline_audit telemetry (shortfalls vs the 8-12/3-6/2-4 bounds)
- query specialist_role attachment (existing behavior, must not regress)
- back-compat: an empty plan still normalizes without crashing
"""

from deep_research.pipeline import architect


def _bare_plan():
    """Minimal plan-shaped dict with one section, one subsection, no seeds."""
    return {
        "report_title": "T",
        "report_toc": [
            {
                "id": "S1",
                "title": "Sec 1",
                "subsections": [{"id": "S1.1", "title": "Sub 1.1"}],
                "depth_target": "broad",
            }
        ],
        "queries": [{"id": "Q1", "text": "q", "type": "factual"}],
        "acceptance_criteria": [],
    }


def test_normalize_backfills_missing_depth_seeds():
    """Pre-#1 plans without depth_seeds get an empty list so writer.outline_units
    can iterate without a `None` check."""
    plan = _bare_plan()
    architect._normalize(plan)
    sub = plan["report_toc"][0]["subsections"][0]
    assert sub["depth_seeds"] == []


def test_normalize_preserves_existing_depth_seeds():
    """A plan that already supplies depth_seeds is left alone — no rewrite,
    no shadowing of writer-meaningful values."""
    plan = _bare_plan()
    plan["report_toc"][0]["subsections"][0]["depth_seeds"] = [
        "Pegasus Cloth evolution V1→V2",
        "Mu's Crystal Wall damage ratio",
    ]
    architect._normalize(plan)
    assert plan["report_toc"][0]["subsections"][0]["depth_seeds"] == [
        "Pegasus Cloth evolution V1→V2",
        "Mu's Crystal Wall damage ratio",
    ]


def test_normalize_records_shortfall_when_outline_too_shallow():
    """The 8-12 top-section bound: a 1-section plan records a shortfall in
    _outline_audit (no fail-loud, just observability)."""
    plan = _bare_plan()
    architect._normalize(plan)
    audit = plan["_outline_audit"]
    assert audit["n_top_sections"] == 1
    assert any("top_sections=1<" in s for s in audit["shortfalls"])
    assert audit["subsections_missing_seeds"] == 1


def test_absent_field_and_explicit_empty_seeds_produce_identical_audit():
    """Greptile PR #20 issue 2: a pre-#1 plan with absent depth_seeds field
    and a post-#1 plan with explicit `"depth_seeds": []` are writer-observably
    identical (both surface an empty list to the writer), so their audit
    counters must agree. Previously the absent case bumped
    subsections_missing_seeds but skipped the seed-count shortfall check,
    while the explicit-empty case did the opposite — making audits across
    plan vintages incomparable."""
    plan_absent = {
        "report_toc": [
            {
                "id": "S1",
                "title": "Sec 1",
                "subsections": [{"id": "S1.1", "title": "Sub 1.1"}],
                "depth_target": "broad",
            }
        ],
        "queries": [],
        "acceptance_criteria": [],
    }
    plan_explicit = {
        "report_toc": [
            {
                "id": "S1",
                "title": "Sec 1",
                "subsections": [{"id": "S1.1", "title": "Sub 1.1", "depth_seeds": []}],
                "depth_target": "broad",
            }
        ],
        "queries": [],
        "acceptance_criteria": [],
    }
    architect._normalize(plan_absent)
    architect._normalize(plan_explicit)
    a = plan_absent["_outline_audit"]
    e = plan_explicit["_outline_audit"]
    assert a["subsections_missing_seeds"] == e["subsections_missing_seeds"] == 1
    assert a["n_seeds_total"] == e["n_seeds_total"] == 0
    # Both must surface the same seeds=0<MIN shortfall — the audit is
    # comparable across plan vintages.
    assert a["shortfalls"] == e["shortfalls"]


def test_normalize_records_shortfall_when_outline_over_bounds():
    """The upper bounds: too many subsections or seeds also record shortfalls
    (Greptile PR #20 issue 1). Without this an architect that emits 10
    subs/section or 8 seeds/sub silently passes the audit even though the
    output structurally deviates from the corpus calibration."""
    plan = {
        "report_toc": [
            {
                "id": "S1",
                "title": "Sec",
                "subsections": [
                    {"id": f"S1.{i + 1}", "title": "x", "depth_seeds": []}
                    # 10 subsections > _SUBSECTIONS_MAX (6).
                    for i in range(10)
                ]
                + [{"id": "S1.over", "title": "x", "depth_seeds": ["a"] * 8}],
                "depth_target": "broad",
            }
        ],
        "queries": [],
        "acceptance_criteria": [],
    }
    architect._normalize(plan)
    audit = plan["_outline_audit"]
    # Both upper-bound shortfalls must surface.
    assert any(s.endswith(f">{architect._SUBSECTIONS_MAX}") for s in audit["shortfalls"]), audit
    assert any(s.endswith(f">{architect._SEEDS_MAX}") for s in audit["shortfalls"]), audit


def test_normalize_records_no_shortfall_when_outline_meets_bounds():
    """A plan that hits the 8-12 / 3-6 / 2-4 bounds records zero shortfalls."""
    plan = {
        "report_toc": [
            {
                "id": f"S{i + 1}",
                "title": f"Sec {i + 1}",
                "subsections": [
                    {
                        "id": f"S{i + 1}.{j + 1}",
                        "title": f"Sub {i + 1}.{j + 1}",
                        "depth_seeds": [f"seed {k + 1}" for k in range(2)],
                    }
                    for j in range(3)
                ],
                "depth_target": "deep",
            }
            for i in range(8)
        ],
        "queries": [],
        "acceptance_criteria": [],
    }
    architect._normalize(plan)
    audit = plan["_outline_audit"]
    assert audit["n_top_sections"] == 8
    assert audit["n_subsections_total"] == 24
    assert audit["n_seeds_total"] == 48
    assert audit["shortfalls"] == []
    assert audit["subsections_missing_seeds"] == 0


def test_normalize_attaches_specialist_role():
    """Pre-existing behavior: every query gets a specialist_role for downstream
    dispatch. Must not regress."""
    plan = _bare_plan()
    plan["queries"] = [
        {"id": "Q1", "text": "q1", "type": "factual"},
        {"id": "Q2", "text": "q2", "type": "comparative"},
        {"id": "Q3", "text": "q3", "type": "GARBAGE_TYPE"},
    ]
    architect._normalize(plan)
    assert plan["queries"][0]["specialist_role"] == "evidence_gatherer"
    assert plan["queries"][1]["specialist_role"] == "comparator"
    # Unknown type falls back to factual.
    assert plan["queries"][2]["type"] == "factual"
    assert plan["queries"][2]["specialist_role"] == "evidence_gatherer"


def test_format_retry_feedback_includes_all_shortfalls():
    """The feedback string must list every specific bound violation so the
    architect knows exactly what to fix on retry."""
    audit = {
        "n_top_sections": 5,
        "n_subsections_total": 12,
        "n_seeds_total": 18,
        "shortfalls": ["top_sections=5<8", "S1.subs=2<3", "S2.1.seeds=1<2"],
    }
    feedback = architect._format_retry_feedback(audit)
    for s in audit["shortfalls"]:
        assert s in feedback, f"shortfall {s!r} missing from feedback"
    # Header and instruction must be present.
    assert "SHORTFALL FEEDBACK" in feedback
    assert "REGENERATE the FULL plan" in feedback
    # Summary line must surface the audit counts the architect needs to see.
    assert "5 top sections" in feedback


def _build_good_plan_obj():
    """Plan that passes every bound — used as a 'retry succeeded' response."""
    return {
        "report_toc": [
            {
                "id": f"S{i + 1}",
                "title": f"Sec {i + 1}",
                "subsections": [
                    {
                        "id": f"S{i + 1}.{j + 1}",
                        "title": f"Sub {i + 1}.{j + 1}",
                        "depth_seeds": ["seed a", "seed b"],
                    }
                    for j in range(3)
                ],
                "depth_target": "broad",
            }
            for i in range(9)
        ],
        "queries": [],
        "acceptance_criteria": [],
    }


def _build_shallow_plan_obj():
    """Plan with too few top sections — should trigger the retry."""
    return {
        "report_toc": [
            {
                "id": "S1",
                "title": "Only",
                "subsections": [{"id": "S1.1", "title": "Lonely"}],
                "depth_target": "broad",
            }
        ],
        "queries": [],
        "acceptance_criteria": [],
    }


def test_build_skips_retry_when_first_plan_meets_bounds(monkeypatch):
    """A first plan that passes the audit should NOT trigger a second
    architect call — the retry is only for fail-soft enforcement."""
    calls: list[str] = []

    def fake_call_json(*_args, note: str = "", **_kw):
        calls.append(note)
        return _build_good_plan_obj()

    monkeypatch.setattr(architect.llm, "call_json", fake_call_json)
    plan = architect.build("p", "en", "compare", [], {}, [])
    assert calls == ["architect"], f"unexpected calls: {calls}"
    assert plan["_outline_audit"]["retry_attempted"] is False


def test_build_triggers_retry_when_first_plan_has_shortfalls(monkeypatch):
    """A shallow first plan must trigger the retry call. The retry's plan
    (when better) replaces the original."""
    calls: list[str] = []
    responses = iter([_build_shallow_plan_obj(), _build_good_plan_obj()])

    def fake_call_json(*_args, note: str = "", **_kw):
        calls.append(note)
        return next(responses)

    monkeypatch.setattr(architect.llm, "call_json", fake_call_json)
    plan = architect.build("p", "en", "compare", [], {}, [])
    assert calls == ["architect", "architect.retry"], f"unexpected calls: {calls}"
    assert plan["_outline_audit"]["retry_attempted"] is True
    # Retry succeeded — final plan should be the deep one.
    assert plan["_outline_audit"]["n_top_sections"] == 9
    assert plan["_outline_audit"]["shortfalls"] == []
    # The original shortfalls are preserved for diagnostics so a dev-run
    # reader can see what the retry fixed.
    assert plan["_outline_audit"]["pre_retry_shortfalls"], "pre_retry_shortfalls should be populated"


def test_build_keeps_original_when_retry_makes_things_worse(monkeypatch):
    """Defensive: if the retry returns a plan with MORE shortfalls than the
    original (LLM mis-cooperating), keep the original. The retry should
    never make output worse than the first try."""
    # First plan: 1 top section (shortfall: top_sections=1<8).
    # Retry plan: 0 top sections (even more shortfalls including subsections=0).
    worse = {"report_toc": [], "queries": [], "acceptance_criteria": []}
    responses = iter([_build_shallow_plan_obj(), worse])

    def fake_call_json(*_args, **_kw):
        return next(responses)

    monkeypatch.setattr(architect.llm, "call_json", fake_call_json)
    plan = architect.build("p", "en", "compare", [], {}, [])
    # We kept the original shallow plan (1 top section), not the worse retry.
    assert plan["_outline_audit"]["n_top_sections"] == 1
    assert plan["_outline_audit"].get("retry_rejected_for_more_shortfalls") is True


def test_normalize_handles_empty_plan():
    """Defensive: an empty plan dict (e.g. LLM returned `{}` somehow) should
    normalize without crashing — sets defaults so downstream nodes see a
    consistent shape."""
    plan: dict = {}
    architect._normalize(plan)
    assert plan["report_toc"] == []
    assert plan["queries"] == []
    assert plan["acceptance_criteria"] == []
    assert plan["_outline_audit"]["n_top_sections"] == 0
