"""Unit tests for P3-W5 — limitations chapter architect contract.

the reference corpus pattern (6/11 articles): predict / compare / explain-
mechanism / list-all archetypes end with an engineering-grade limitations
chapter enumerating 5 dimensions (data granularity, scope cap, time
validity, sampling, falsifiers). q3 §8.5 (predict) adds a 3-scenario
stress test that recomputes the article's main ranking.
"""

from deep_research.pipeline import architect


def _bare_plan_with_limitations(archetype="predict", **lc_overrides):
    lc = {
        "title": "Limitations and Future Research",
        "sub_sections": [
            {"id": "S9.1", "type": "data_granularity", "title": "Data granularity", "content_directive": "..."},
            {"id": "S9.2", "type": "scope_cap", "title": "Scope cap", "content_directive": "..."},
            {"id": "S9.3", "type": "time_validity", "title": "Time validity", "content_directive": "..."},
            {"id": "S9.4", "type": "sampling", "title": "Sampling", "content_directive": "..."},
            {"id": "S9.5", "type": "falsifiers", "title": "Falsifiers", "content_directive": "..."},
        ],
        "scenario_stress_test": {
            "scenarios": ["base", "optimistic", "pessimistic"],
            "recompute_target": "tier_ranking",
            "directive": "recompute the §8.1 ranking under each scenario; report rank stability.",
        }
        if archetype == "predict"
        else None,
    }
    lc.update(lc_overrides)
    return {
        "report_title": "T",
        "report_toc": [{"id": "S1", "title": "Sec", "subsections": [], "depth_target": "broad"}],
        "queries": [{"id": f"Q{i}", "text": "q", "type": "factual"} for i in range(50)],
        "acceptance_criteria": [],
        "limitations_chapter": lc,
    }


def test_limitations_constants_pinned():
    """Sub-section types + required-archetype set pinned (drift = contract drift)."""
    assert architect._LIMITATIONS_SUBSECTION_TYPES == (
        "data_granularity",
        "scope_cap",
        "time_validity",
        "sampling",
        "falsifiers",
    )
    assert architect._LIMITATIONS_REQUIRED_ARCHETYPES == frozenset(
        {"predict", "compare", "explain-mechanism", "list-all"}
    )
    assert architect._LIMITATIONS_STRESS_TEST_ARCHETYPES == frozenset({"predict"})


def test_normalize_predict_with_complete_limitations_no_shortfall():
    plan = _bare_plan_with_limitations(archetype="predict")
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    lc_shortfalls = [s for s in audit["shortfalls"] if "limitations" in s]
    assert lc_shortfalls == [], f"got {lc_shortfalls}"


def test_normalize_missing_limitations_for_required_archetype_emits_shortfall():
    plan = _bare_plan_with_limitations()
    plan.pop("limitations_chapter")
    architect._normalize(plan, archetype="explain-mechanism")
    audit = plan["_outline_audit"]
    assert any("limitations_chapter=missing" in s for s in audit["shortfalls"])
    lc = plan["limitations_chapter"]
    assert isinstance(lc, dict)
    assert lc["sub_sections"] == []


def test_normalize_missing_limitations_for_predict_suppresses_stress_test_shortfall():
    """predict + entirely absent limitations_chapter: only the `missing`
    shortfall fires — the stress-test shortfall must be suppressed by the
    `lc_was_missing` guard (otherwise consumers would see two shortfalls
    for one root cause and might trigger a spurious stress-test retry).

    Greptile PR #41 round-2: the same gate applies to the sub-section
    audit keys. When the chapter is entirely absent, NONE of the three
    per-chapter audit keys (`sub_section_types`, `missing_sub_section_
    types`, `has_stress_test`) should be in audit — otherwise the keys
    are indistinguishable from "chapter present but all 5 sub-types
    missing," and a targeted-retry consumer could fire 5 sub-section
    retries + 1 stress-test retry for a single root cause.
    """
    plan = _bare_plan_with_limitations()
    plan.pop("limitations_chapter")
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    lc_shortfalls = [s for s in audit["shortfalls"] if "limitations" in s]
    assert lc_shortfalls == ["limitations_chapter=missing(required-for-archetype)"], (
        f"expected only the missing-chapter shortfall, got {lc_shortfalls}"
    )
    # All three per-chapter audit keys must be absent when chapter was absent.
    assert "limitations_chapter_has_stress_test" not in audit
    assert "limitations_chapter_sub_section_types" not in audit
    assert "limitations_chapter_missing_sub_section_types" not in audit
    # Backfill: empty-dict shape, ready for the writer to fail-soft on.
    lc = plan["limitations_chapter"]
    assert isinstance(lc, dict)
    assert lc["sub_sections"] == []
    assert lc.get("scenario_stress_test") is None


def test_normalize_missing_limitations_for_explain_mechanism_omits_subsection_audit():
    """Greptile PR #41 round-2: same gate must apply for non-predict
    required archetypes. explain-mechanism doesn't have stress-test
    requirements, so we specifically verify the sub-section audit keys
    are omitted (the `has_stress_test` key is irrelevant here)."""
    plan = _bare_plan_with_limitations()
    plan.pop("limitations_chapter")
    architect._normalize(plan, archetype="explain-mechanism")
    audit = plan["_outline_audit"]
    # Single missing-chapter shortfall, no derived sub-section shortfalls.
    lc_shortfalls = [s for s in audit["shortfalls"] if "limitations" in s]
    assert lc_shortfalls == ["limitations_chapter=missing(required-for-archetype)"], (
        f"unexpected derived shortfalls: {lc_shortfalls}"
    )
    # Per-chapter audit keys must NOT be present.
    assert "limitations_chapter_sub_section_types" not in audit
    assert "limitations_chapter_missing_sub_section_types" not in audit
    # has_stress_test is gated on predict archetype AND not-missing — both
    # conditions fail here, so it's also absent.
    assert "limitations_chapter_has_stress_test" not in audit


def test_normalize_trend_no_limitations_no_shortfall():
    """trend archetype is NOT in required set; missing limitations is fine."""
    plan = _bare_plan_with_limitations()
    plan.pop("limitations_chapter")
    architect._normalize(plan, archetype="trend")
    audit = plan["_outline_audit"]
    lc_shortfalls = [s for s in audit["shortfalls"] if "limitations_chapter=missing" in s]
    assert lc_shortfalls == []


def test_normalize_recommend_no_limitations_no_shortfall():
    """recommend archetype is NOT in required set."""
    plan = _bare_plan_with_limitations()
    plan.pop("limitations_chapter")
    architect._normalize(plan, archetype="recommend")
    audit = plan["_outline_audit"]
    lc_shortfalls = [s for s in audit["shortfalls"] if "limitations_chapter=missing" in s]
    assert lc_shortfalls == []


def test_normalize_records_limitations_sub_section_types():
    plan = _bare_plan_with_limitations()
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert audit["limitations_chapter_sub_section_types"] == list(architect._LIMITATIONS_SUBSECTION_TYPES)
    assert audit["limitations_chapter_missing_sub_section_types"] == []


def test_normalize_flags_missing_limitations_sub_section_type():
    """Drop one sub-section type → audit records the missing type."""
    plan = _bare_plan_with_limitations()
    # Drop the "falsifiers" sub-section
    plan["limitations_chapter"]["sub_sections"] = plan["limitations_chapter"]["sub_sections"][:-1]
    architect._normalize(plan, archetype="compare")
    audit = plan["_outline_audit"]
    assert "falsifiers" in audit["limitations_chapter_missing_sub_section_types"]
    assert any("falsifiers" in s for s in audit["shortfalls"])


def test_normalize_predict_with_missing_stress_test_emits_shortfall():
    """predict archetype requires scenario_stress_test. The shortfall
    string interpolates the actual archetype so targeted-retry
    consumers can route on it (see also
    `test_stress_test_shortfall_string_interpolates_archetype` for the
    Greptile PR #41 round-3 future-proofing pin)."""
    plan = _bare_plan_with_limitations()
    plan["limitations_chapter"]["scenario_stress_test"] = None
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert audit["limitations_chapter_has_stress_test"] is False
    assert "limitations_chapter.scenario_stress_test=missing(required-for-predict)" in audit["shortfalls"], (
        f"expected parameterized shortfall, got {audit['shortfalls']}"
    )


def test_stress_test_shortfall_string_interpolates_archetype(monkeypatch):
    """Greptile PR #41 round-3: the stress-test shortfall message must
    interpolate the current `archetype`, not hardcode "predict". This
    pin protects against a regression where a future addition to
    `_LIMITATIONS_STRESS_TEST_ARCHETYPES` would still emit
    "required-for-predict" for the new archetype — a misleading
    message that would make targeted-retry consumers treat the two
    archetypes identically.

    Setup: extend `_LIMITATIONS_STRESS_TEST_ARCHETYPES` to also cover
    "explain-mechanism". (`_LIMITATIONS_REQUIRED_ARCHETYPES` already
    contains "explain-mechanism", so the outer `lc_is_required` gate
    passes without an additional patch.) Emulate a chapter missing the
    stress test, then verify the shortfall names the actual archetype.
    """
    monkeypatch.setattr(
        architect,
        "_LIMITATIONS_STRESS_TEST_ARCHETYPES",
        frozenset({"predict", "explain-mechanism"}),
    )
    # Pre-condition the docstring relies on: explain-mechanism is already
    # in the required set, so no second monkeypatch is needed for the
    # outer `lc_is_required` gate to pass. If a future refactor drops
    # explain-mechanism from the required set, this test must be updated
    # to also patch `_LIMITATIONS_REQUIRED_ARCHETYPES`.
    assert "explain-mechanism" in architect._LIMITATIONS_REQUIRED_ARCHETYPES
    plan = _bare_plan_with_limitations(archetype="predict")
    plan["limitations_chapter"]["scenario_stress_test"] = None
    architect._normalize(plan, archetype="explain-mechanism")
    audit = plan["_outline_audit"]
    assert audit["limitations_chapter_has_stress_test"] is False
    assert "limitations_chapter.scenario_stress_test=missing(required-for-explain-mechanism)" in audit["shortfalls"], (
        f"shortfall did not interpolate {{archetype}}; got {audit['shortfalls']}"
    )
    # Crucially, the legacy hardcoded form must NOT appear.
    assert "limitations_chapter.scenario_stress_test=missing(required-for-predict)" not in audit["shortfalls"]


def test_normalize_compare_does_not_require_stress_test():
    """compare archetype has limitations but NOT scenario_stress_test."""
    plan = _bare_plan_with_limitations()
    plan["limitations_chapter"]["scenario_stress_test"] = None
    architect._normalize(plan, archetype="compare")
    audit = plan["_outline_audit"]
    # No stress-test field on audit (the check is gated on predict).
    assert "limitations_chapter_has_stress_test" not in audit
    stress_sf = [s for s in audit["shortfalls"] if "scenario_stress_test" in s]
    assert stress_sf == []


def test_normalize_handles_malformed_limitations_field_types():
    """sub_sections as non-list → coerced to empty list. Greptile PR #41
    round-4: also pins the audit-key writes and the shortfall append that
    follow the coercion. Because `lc_was_missing=False` (the chapter is
    present, just with a malformed `sub_sections`), the `not lc_was_missing`
    branch still runs and MUST:
      (1) write `limitations_chapter_sub_section_types=[]` (post-coercion);
      (2) write `limitations_chapter_missing_sub_section_types=[all 5]`;
      (3) append the combined missing-types shortfall;
      (4) for predict, write `limitations_chapter_has_stress_test=True`
          (the fixture's stress test is intact — only sub_sections was
          mangled) and NOT append a stress-test shortfall.
    A regression that silently dropped any of these writes would not be
    caught by a coercion-only assertion.
    """
    plan = _bare_plan_with_limitations()
    plan["limitations_chapter"]["sub_sections"] = "not a list"
    architect._normalize(plan, archetype="predict")
    lc = plan["limitations_chapter"]
    audit = plan["_outline_audit"]
    # (1) Coercion.
    assert lc["sub_sections"] == []
    # (2) Audit keys are written (not gated out — chapter was present).
    assert audit["limitations_chapter_sub_section_types"] == []
    assert audit["limitations_chapter_missing_sub_section_types"] == list(architect._LIMITATIONS_SUBSECTION_TYPES)
    # (3) Missing-types shortfall is appended (all 5 absent).
    expected_sf = "limitations_chapter.missing_sub_section_types=" + ",".join(architect._LIMITATIONS_SUBSECTION_TYPES)
    assert expected_sf in audit["shortfalls"], f"got {audit['shortfalls']}"
    # (4) Stress-test fixture is intact → True + no stress-test shortfall.
    assert audit["limitations_chapter_has_stress_test"] is True
    assert not any("scenario_stress_test=missing" in s for s in audit["shortfalls"])
    # And crucially: the chapter-missing shortfall must NOT fire here —
    # the chapter was present, just with one malformed field.
    assert not any(s.startswith("limitations_chapter=missing") for s in audit["shortfalls"])


def test_normalize_unknown_archetype_no_limitations_audit():
    plan = _bare_plan_with_limitations()
    plan.pop("limitations_chapter")
    architect._normalize(plan, archetype=None)
    audit = plan["_outline_audit"]
    assert "limitations_chapter_sub_section_types" not in audit
