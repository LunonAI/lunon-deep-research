"""Unit tests for P3-W6 — stakeholder chapter architect contract.

the reference pattern (6/11 articles): closing chapter splits recommendations
into 3-5 stakeholder addressee blocks with non-overlapping content.
The architect populates `stakeholder_chapter` when prompt signals a
plural audience.
"""

from deep_research.pipeline import architect


def _bare_plan_with_sc(stakeholders=None):
    sh = (
        stakeholders
        if stakeholders is not None
        else [
            {"id": "investors", "label": "For Investors", "content_directive": "..."},
            {"id": "policymakers", "label": "For Policymakers", "content_directive": "..."},
            {"id": "industry", "label": "For Industry Practitioners", "content_directive": "..."},
        ]
    )
    return {
        "report_title": "T",
        "report_toc": [{"id": "S1", "title": "S", "subsections": [], "depth_target": "broad"}],
        "queries": [{"id": f"Q{i}", "text": "q", "type": "factual"} for i in range(50)],
        "acceptance_criteria": [],
        "stakeholder_chapter": {
            "title": "Strategic Recommendations by Stakeholder",
            "stakeholders": sh,
        },
    }


def test_stakeholder_count_bounds_pinned():
    assert architect._STAKEHOLDER_COUNT_MIN == 3
    assert architect._STAKEHOLDER_COUNT_MAX == 5


def test_normalize_with_3_stakeholders_no_shortfall():
    plan = _bare_plan_with_sc()
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    sc_sf = [s for s in audit["shortfalls"] if "stakeholder_chapter" in s]
    assert sc_sf == [], f"got {sc_sf}"
    assert audit["stakeholder_chapter_count"] == 3


def test_normalize_below_min_count_emits_shortfall():
    plan = _bare_plan_with_sc(stakeholders=[{"id": "a", "label": "A", "content_directive": "..."}])
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert any("stakeholder_chapter.count=1<3" in s for s in audit["shortfalls"]), f"got {audit['shortfalls']}"


def test_normalize_above_max_count_emits_shortfall():
    sh = [{"id": f"s{i}", "label": f"S{i}", "content_directive": "..."} for i in range(7)]
    plan = _bare_plan_with_sc(stakeholders=sh)
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert any("stakeholder_chapter.count=7>5" in s for s in audit["shortfalls"])


def test_normalize_drops_malformed_stakeholders():
    """Entries missing `id` or not dict are filtered out."""
    sh = [
        {"id": "valid1", "label": "L1", "content_directive": "..."},
        {"label": "no-id"},  # missing id
        "not a dict",
        {"id": "valid2", "label": "L2", "content_directive": "..."},
        {"id": "valid3", "label": "L3", "content_directive": "..."},
    ]
    plan = _bare_plan_with_sc(stakeholders=sh)
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert audit["stakeholder_chapter_count"] == 3  # only valid1/2/3
    # 3 is at the floor — no shortfall.
    sc_sf = [s for s in audit["shortfalls"] if "stakeholder_chapter" in s]
    assert sc_sf == []


def test_normalize_missing_stakeholder_chapter_no_shortfall():
    """stakeholder_chapter is OPTIONAL — never required."""
    plan = _bare_plan_with_sc()
    plan.pop("stakeholder_chapter")
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    sc_sf = [s for s in audit["shortfalls"] if "stakeholder_chapter" in s]
    assert sc_sf == []


def test_prompt_signals_plural_audience_recognizes_investors_and_policymakers():
    assert architect._prompt_signals_plural_audience(
        "Provide recommendations for investors and policymakers on the future of clean energy."
    )


def test_prompt_signals_plural_audience_recognizes_recommendations_for_X():
    assert architect._prompt_signals_plural_audience(
        "What are the policy implications? Recommendations for industry stakeholders."
    )


def test_prompt_signals_plural_audience_recognizes_zh_patterns():
    assert architect._prompt_signals_plural_audience("面向多元主体提出战略建议")
    assert architect._prompt_signals_plural_audience("为投资者和决策者提供建议")


def test_prompt_signals_plural_audience_negative_cases():
    """Single-audience prompts should NOT trigger."""
    assert not architect._prompt_signals_plural_audience("Provide an overview of recent advances in quantum computing.")
    assert not architect._prompt_signals_plural_audience("分析最新的科技趋势")
    assert not architect._prompt_signals_plural_audience("")
    assert not architect._prompt_signals_plural_audience(None)
