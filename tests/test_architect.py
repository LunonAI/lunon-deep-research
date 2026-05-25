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
    """A plan that hits the 8-12 / 3-6 / 2-4 bounds AND the 48-64 query band
    records zero shortfalls. (Greptile PR #22 follow-up added the
    query-count check; this test now exercises the queries band too.)"""
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
        # 48 queries — at the lower edge of the post-#4 48-64 HARD RULE band.
        "queries": [{"id": f"Q{i + 1}", "text": f"q{i + 1}", "type": "factual"} for i in range(48)],
        "acceptance_criteria": [],
    }
    architect._normalize(plan)
    audit = plan["_outline_audit"]
    assert audit["n_top_sections"] == 8
    assert audit["n_subsections_total"] == 24
    assert audit["n_seeds_total"] == 48
    assert audit["n_queries"] == 48
    assert audit["shortfalls"] == []
    assert audit["subsections_missing_seeds"] == 0


def test_normalize_records_shortfall_when_query_count_below_band():
    """Greptile PR #22 follow-up: the 48-64 HARD RULE on queries must surface
    as an `_outline_audit` shortfall when the LLM falls back to the pre-#4
    24-32 range (or anything below 48). Without this, a regression that
    silently halves the evidence volume per specialist would only be
    visible by counting findings downstream — too late."""
    plan = {
        "report_toc": [
            {"id": "S1", "title": "Sec", "subsections": [{"id": "S1.1", "title": "Sub", "depth_seeds": ["a", "b"]}]}
        ],
        # 24 queries — the pre-#4 floor; well below the new 48 lower bound.
        "queries": [{"id": f"Q{i + 1}", "text": "q", "type": "factual"} for i in range(24)],
        "acceptance_criteria": [],
    }
    architect._normalize(plan)
    audit = plan["_outline_audit"]
    assert audit["n_queries"] == 24
    assert any(f"queries=24<{architect._QUERIES_MIN}" in s for s in audit["shortfalls"]), audit


def test_normalize_records_shortfall_when_query_count_above_band():
    """Symmetric upper bound: 65+ queries also record a shortfall, matching
    the over-band tracking for top_sections / subsections / seeds."""
    plan = {
        "report_toc": [
            {"id": "S1", "title": "Sec", "subsections": [{"id": "S1.1", "title": "Sub", "depth_seeds": ["a", "b"]}]}
        ],
        # 80 queries — above the 64 upper bound.
        "queries": [{"id": f"Q{i + 1}", "text": "q", "type": "factual"} for i in range(80)],
        "acceptance_criteria": [],
    }
    architect._normalize(plan)
    audit = plan["_outline_audit"]
    assert audit["n_queries"] == 80
    assert any(f"queries=80>{architect._QUERIES_MAX}" in s for s in audit["shortfalls"]), audit


def test_audit_n_queries_present_for_empty_plan():
    """Defensive: empty plan still produces n_queries=0 in the audit (and a
    queries<MIN shortfall), so downstream readers can rely on the field
    being present."""
    plan: dict = {}
    architect._normalize(plan)
    audit = plan["_outline_audit"]
    assert audit["n_queries"] == 0
    assert any("queries=0<" in s for s in audit["shortfalls"]), audit


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
