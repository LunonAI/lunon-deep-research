"""Unit tests for P3-W2 — §1 framing chapter architect contract.

Qianfan-verified corpus-wide pattern (10/11 articles): every article opens
with a 5-9% length framing chapter that publishes (a) scope, (b) rubric,
(c) roadmap, (d) vocabulary. Lunon's pre-W2 §1 was substantive content but
never published a downstream contract. P3-W2 adds the `framing_chapter`
artifact to the architect plan + audit + writer-side surfacing.

These tests pin: required vs optional archetype gating; default backfill;
sub-section-type validation; vocabulary + rubric bounds; back-compat with
plans that omit framing_chapter.
"""

from deep_research.pipeline import architect


def _bare_plan_with_framing(**fc_overrides):
    fc = {
        "title": "Research Framework",
        "sub_sections": [
            {"id": "S1.1", "type": "scope", "title": "Scope", "content_directive": "..."},
            {"id": "S1.2", "type": "rubric", "title": "Rubric", "content_directive": "..."},
            {"id": "S1.3", "type": "roadmap", "title": "Roadmap", "content_directive": "..."},
            {"id": "S1.4", "type": "vocabulary", "title": "Vocabulary", "content_directive": "..."},
        ],
        "published_vocabulary": ["axiom1", "axiom2", "axiom3", "axiom4", "axiom5"],
        "published_rubric_items": [
            {"id": "R-1", "label": "Quality", "weight": 0.25},
            {"id": "R-2", "label": "Speed", "weight": 0.25},
            {"id": "R-3", "label": "Cost", "weight": 0.25},
            {"id": "R-4", "label": "Reach", "weight": 0.25},
        ],
    }
    fc.update(fc_overrides)
    return {
        "report_title": "T",
        "report_toc": [{"id": "S1", "title": "Sec", "subsections": [], "depth_target": "broad"}],
        "queries": [{"id": f"Q{i}", "text": "q", "type": "factual"} for i in range(50)],
        "acceptance_criteria": [],
        "framing_chapter": fc,
    }


def test_framing_chapter_constants_match_spec():
    """Pin the constants — these are referenced in the audit + retry
    feedback + compliance scorer. Drift in either direction is a contract
    change."""
    assert architect._FRAMING_VOCABULARY_MIN == 5
    assert architect._FRAMING_VOCABULARY_MAX == 10
    assert architect._FRAMING_RUBRIC_MIN == 4
    assert architect._FRAMING_RUBRIC_MAX == 6
    assert architect._FRAMING_SUBSECTION_TYPES == ("scope", "rubric", "roadmap", "vocabulary")


def test_framing_chapter_required_archetypes_pinned():
    """compare, explain-mechanism, predict, recommend require a framing
    chapter. trend is optional (single-axis trend tasks don't benefit from a
    methodology preamble). G11-A: list-all is EXCLUDED — the fresh #1 corpus
    (q91/q89) carries no §0.x framing for roster prompts."""
    expected = {"compare", "explain-mechanism", "predict", "recommend"}
    assert architect._FRAMING_CHAPTER_REQUIRED_ARCHETYPES == frozenset(expected)
    assert "list-all" not in architect._FRAMING_CHAPTER_REQUIRED_ARCHETYPES


def test_framing_chapter_rubric_required_archetypes_pinned():
    """compare, predict, recommend produce a non-empty rubric (they're
    evaluation-archetype; the rubric is referenced downstream)."""
    expected = {"compare", "predict", "recommend"}
    assert architect._FRAMING_RUBRIC_REQUIRED_ARCHETYPES == frozenset(expected)


def test_normalize_required_archetype_with_complete_framing():
    """Happy path: predict archetype with a complete framing chapter →
    no framing-chapter shortfalls."""
    plan = _bare_plan_with_framing()
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    fc_shortfalls = [s for s in audit["shortfalls"] if "framing_chapter" in s]
    assert fc_shortfalls == [], f"got unexpected framing shortfalls: {fc_shortfalls}"


def test_normalize_required_archetype_missing_framing_emits_shortfall():
    """Required archetype with NO framing_chapter field → backfill +
    `framing_chapter=missing(required-for-archetype)` shortfall fires."""
    plan = _bare_plan_with_framing()
    plan.pop("framing_chapter")
    architect._normalize(plan, archetype="explain-mechanism")
    audit = plan["_outline_audit"]
    assert any("framing_chapter=missing" in s for s in audit["shortfalls"]), f"got {audit['shortfalls']}"
    # Backfill produces an empty-but-shaped framing chapter so the writer
    # doesn't crash on `fc["sub_sections"]`.
    fc = plan["framing_chapter"]
    assert isinstance(fc, dict)
    assert fc["sub_sections"] == []
    assert fc["published_vocabulary"] == []
    assert fc["published_rubric_items"] == []


def test_normalize_trend_archetype_no_framing_no_shortfall():
    """trend archetype is NOT in _FRAMING_CHAPTER_REQUIRED_ARCHETYPES.
    Missing framing chapter shouldn't fire a shortfall for trend tasks."""
    plan = _bare_plan_with_framing()
    plan.pop("framing_chapter")
    architect._normalize(plan, archetype="trend")
    audit = plan["_outline_audit"]
    fc_shortfalls = [s for s in audit["shortfalls"] if "framing_chapter=missing" in s]
    assert fc_shortfalls == [], f"trend should not require framing: {audit['shortfalls']}"


def test_normalize_audit_records_sub_section_types():
    """Audit must surface the list of sub-section types so dev-run
    analysers can spot when one was dropped."""
    plan = _bare_plan_with_framing()
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert audit["framing_chapter_sub_section_types"] == ["scope", "rubric", "roadmap", "vocabulary"]
    assert audit["framing_chapter_missing_sub_section_types"] == []


def test_normalize_flags_missing_sub_section_type():
    """Drop one of the 4 required types — shortfall fires."""
    plan = _bare_plan_with_framing()
    plan["framing_chapter"]["sub_sections"] = [
        {"id": "S1.1", "type": "scope", "title": "Scope", "content_directive": "..."},
        {"id": "S1.2", "type": "vocabulary", "title": "Vocab", "content_directive": "..."},
        # rubric + roadmap missing
    ]
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    missing = audit["framing_chapter_missing_sub_section_types"]
    assert "rubric" in missing
    assert "roadmap" in missing
    assert any("missing_sub_section_types" in s for s in audit["shortfalls"])


def test_normalize_flags_vocabulary_below_floor():
    """Vocabulary < 5 fires shortfall."""
    plan = _bare_plan_with_framing(published_vocabulary=["a", "b"])
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert any("framing_chapter.vocabulary=2<5" in s for s in audit["shortfalls"]), f"got {audit['shortfalls']}"


def test_normalize_flags_vocabulary_above_ceiling():
    """Vocabulary > 10 fires shortfall."""
    plan = _bare_plan_with_framing(published_vocabulary=[f"term{i}" for i in range(15)])
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert any("framing_chapter.vocabulary=15>10" in s for s in audit["shortfalls"]), f"got {audit['shortfalls']}"


def test_normalize_flags_rubric_below_floor_for_compare():
    """compare requires rubric ≥4. Test with 2 items → shortfall."""
    plan = _bare_plan_with_framing(
        published_rubric_items=[
            {"id": "R-1", "label": "L1", "weight": 0.5},
            {"id": "R-2", "label": "L2", "weight": 0.5},
        ]
    )
    architect._normalize(plan, archetype="compare")
    audit = plan["_outline_audit"]
    assert any("framing_chapter.rubric=2<4" in s for s in audit["shortfalls"]), f"got {audit['shortfalls']}"


def test_normalize_skips_rubric_check_for_explain_mechanism():
    """explain-mechanism is in REQUIRED archetypes but NOT in
    RUBRIC_REQUIRED_ARCHETYPES — rubric count shortfalls suppressed."""
    plan = _bare_plan_with_framing(published_rubric_items=[])  # 0 rubric items
    architect._normalize(plan, archetype="explain-mechanism")
    audit = plan["_outline_audit"]
    rubric_sf = [s for s in audit["shortfalls"] if "framing_chapter.rubric" in s]
    assert rubric_sf == [], f"explain-mechanism should not require rubric; got {rubric_sf}"


def test_normalize_records_vocabulary_and_rubric_counts():
    """Audit surfaces the actual counts for drift telemetry."""
    plan = _bare_plan_with_framing()
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert audit["framing_chapter_vocabulary_count"] == 5
    assert audit["framing_chapter_rubric_count"] == 4


def test_normalize_handles_malformed_field_types():
    """If the architect emits framing_chapter with non-list sub_sections
    or vocabulary, normalize handles gracefully (coerces to empty list)."""
    plan = _bare_plan_with_framing()
    plan["framing_chapter"]["sub_sections"] = "not a list"
    plan["framing_chapter"]["published_vocabulary"] = None
    plan["framing_chapter"]["published_rubric_items"] = {"not": "a list"}
    architect._normalize(plan, archetype="predict")
    fc = plan["framing_chapter"]
    # All malformed fields coerced to empty lists.
    assert fc["sub_sections"] == []
    assert fc["published_vocabulary"] == []
    assert fc["published_rubric_items"] == []


def test_normalize_unknown_archetype_no_framing_audit():
    """An unknown / empty archetype doesn't trigger the framing-chapter
    audit path at all."""
    plan = _bare_plan_with_framing()
    plan.pop("framing_chapter")
    architect._normalize(plan, archetype=None)
    audit = plan["_outline_audit"]
    fc_shortfalls = [s for s in audit["shortfalls"] if "framing_chapter" in s]
    assert fc_shortfalls == [], f"unknown archetype should not require framing: {fc_shortfalls}"


def test_normalize_preserves_pre_p3_w2_plan_shape():
    """Back-compat: a plan that doesn't include framing_chapter for a
    NON-required archetype (e.g. trend) still works."""
    plan = _bare_plan_with_framing()
    plan.pop("framing_chapter")
    architect._normalize(plan, archetype="trend")
    audit = plan["_outline_audit"]
    # No framing-chapter audit fields when archetype doesn't require it
    # — clean by absence.
    assert "framing_chapter_sub_section_types" not in audit
