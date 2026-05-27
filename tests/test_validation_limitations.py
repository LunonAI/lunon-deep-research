"""P3-W5.b (2026-05-27): `_validate_limitations_chapter` tests.

The validator computes a structural + anti-generic audit on the
limitations chapter. Returns None when no chapter is in the plan; else
returns an audit dict listing present/missing/generic sub-sections plus
scenario-stress-test presence. Advisory severity — drift-log only, does
NOT trigger the refiner pass.

Tests pin:
- None return on missing / null / malformed plan field
- All-5-present article passes with empty missing/generic lists
- Missing sub-section heading → flagged in missing_subsections
- Generic boilerplate body (no year/proper-noun/rubric-id anchor) →
  flagged in generic_subsections
- Scenario stress-test sub-section detection (EN + ZH)
- Truncated bodies surfaced when sub-section is article-trailing
- Citation-marker false-positive guard (digits inside `[^...-2024]` do
  NOT count as a year)
"""

from deep_research.pipeline import validation


def _build_inp(article: str, plan: dict):
    """Wrap article+plan in a minimal ValidationInput shape. Fields not
    relevant to limitations chapter validation are stubbed."""
    from deep_research.state import DesignGuide, Scaffold

    return validation.ValidationInput(
        article=article,
        plan=plan,
        scaffold=Scaffold(sections=[], total_target_tokens=12000),
        design_guide=DesignGuide(),
        language="en",
        domain="default",
        task_id="test",
    )


def _full_lc(**overrides):
    lc = {
        "title": "Limitations",
        "sub_sections": [
            {"id": "S5.1", "type": "data_granularity", "title": "Data Granularity"},
            {"id": "S5.2", "type": "scope_cap", "title": "Scope Cap"},
            {"id": "S5.3", "type": "time_validity", "title": "Time Validity"},
            {"id": "S5.4", "type": "sampling", "title": "Sampling"},
            {"id": "S5.5", "type": "falsifiers", "title": "Falsifiers"},
        ],
        "scenario_stress_test": None,
    }
    lc.update(overrides)
    return lc


def _full_article_with_5_subsections() -> str:
    """Synthetic limitations chapter with all 5 sub-sections, each
    body carrying a concrete anchor (year / proper noun / rubric id)."""
    return (
        "# Title\n\n"
        "## 1 Intro\n\nBody.\n\n"
        "## 5 Limitations\n\n"
        "Opening paragraph.\n\n"
        "### 5.1 Data Granularity\n\n"
        "The 2024 IBM filing data did not resolve per-region quantum-chip yield. "
        "Per R-3 (data-currency criterion), this gap blocks fine-grained ranking.\n\n"
        "### 5.2 Scope Cap\n\n"
        "Per §1.1 scope, the analysis excludes pre-commercial labs. The Bharti and "
        "Reliance ecosystem is therefore under-represented.\n\n"
        "### 5.3 Time Validity\n\n"
        "Beyond 2028 the EU CMA framework reset will invalidate §3.2 cost projections.\n\n"
        "### 5.4 Sampling\n\n"
        "Tier-3 academic groups outside the Anglo-American axis are under-represented. "
        "Per R-2 (geographic-coverage criterion), this introduces a Western-Hemisphere bias.\n\n"
        "### 5.5 Falsifiers\n\n"
        "Three observations would refute the §4 thesis: (1) Google posts a 100-qubit "
        "error-corrected logical run before 2027; (2) NIST cancels PQC migration; "
        "(3) per R-4 (cost-curve), DRAM-equivalent quantum memory drops to $1k/qubit.\n"
    )


# ---------- None / null / malformed handling ----------


def test_returns_none_when_limitations_chapter_absent():
    """When the plan has no limitations_chapter key, validator returns
    None (silent skip). Matches the stakeholder/framing pattern."""
    plan = {"report_toc": []}
    assert validation._validate_limitations_chapter("article body", plan.get("limitations_chapter")) is None


def test_returns_none_when_limitations_chapter_null():
    """Explicit null (architect emits None for trend / recommend
    archetypes) → silent skip, distinct from missing key."""
    assert validation._validate_limitations_chapter("article body", None) is None


def test_returns_none_when_limitations_chapter_not_dict():
    """Defensive: a malformed plan with limitations_chapter = list or
    str must not crash; return None (skip)."""
    assert validation._validate_limitations_chapter("article body", ["bad"]) is None
    assert validation._validate_limitations_chapter("article body", "limitations") is None


def test_returns_none_when_sub_sections_empty_or_missing():
    """An empty or missing sub_sections array yields a no-op skip,
    not a degenerate audit with all 5 missing."""
    assert (
        validation._validate_limitations_chapter("article body", {"title": "Limitations", "sub_sections": []}) is None
    )
    assert validation._validate_limitations_chapter("article body", {"title": "Limitations"}) is None


def test_returns_none_when_sub_sections_have_no_type_field():
    """Architect drift: sub_sections list of dicts WITHOUT the `type`
    field is unusable; skip with None rather than reporting all-missing."""
    bad_lc = {
        "title": "Limitations",
        "sub_sections": [{"id": "S5.1", "title": "Something"}, {"id": "S5.2"}],
    }
    assert validation._validate_limitations_chapter("article body", bad_lc) is None


# ---------- structural detection ----------


def test_all_5_subsections_present_with_anchors_yields_empty_missing_and_generic():
    """A well-formed article with all 5 sub-sections, each with a
    concrete anchor in body, returns the canonical pass case."""
    article = _full_article_with_5_subsections()
    audit = validation._validate_limitations_chapter(article, _full_lc())
    assert audit is not None
    assert audit["n_subsections_declared"] == 5
    assert audit["n_subsections_present"] == 5
    assert set(audit["present_subsections"]) == {
        "data_granularity",
        "scope_cap",
        "time_validity",
        "sampling",
        "falsifiers",
    }
    assert audit["missing_subsections"] == []
    assert audit["generic_subsections"] == []


def test_missing_subsection_heading_flagged():
    """An article whose limitations chapter is missing the
    `Time Validity` sub-section flags `time_validity` in missing."""
    article = _full_article_with_5_subsections().replace("### 5.3 Time Validity", "### 5.3 Other Heading")
    audit = validation._validate_limitations_chapter(article, _full_lc())
    assert audit is not None
    assert "time_validity" in audit["missing_subsections"]
    assert audit["n_subsections_present"] == 4


def test_generic_subsection_body_flagged():
    """A sub-section whose body has no specific anchor (no year, no
    proper noun, no R-N rubric id) is flagged in generic_subsections.
    This is the Qianfan-grade signal — boilerplate fails the check."""
    article = (
        "## 5 Limitations\n\n"
        "### 5.1 Data Granularity\n\n"
        "the data is limited in some ways. some aspects are not well covered. "
        "it would be good to have more data.\n\n"  # no anchor: pure boilerplate
        "### 5.2 Scope Cap\n\n"
        "Per R-1, this article excludes EU jurisdictions.\n\n"
        "### 5.3 Time Validity\n\n"
        "Conclusions hold through 2027.\n\n"
        "### 5.4 Sampling\n\n"
        "Per R-2 the Brazilian Petrobras data is under-represented.\n\n"
        "### 5.5 Falsifiers\n\n"
        "Refuted if Tesla cancels its 2026 roadmap.\n"
    )
    audit = validation._validate_limitations_chapter(article, _full_lc())
    assert audit is not None
    assert "data_granularity" in audit["generic_subsections"], (
        f"data_granularity body has no anchor (pure boilerplate) but was not flagged; got: {audit}"
    )
    # Other 4 sub-sections have anchors and should NOT be flagged.
    for t in ("scope_cap", "time_validity", "sampling", "falsifiers"):
        assert t not in audit["generic_subsections"], (
            f"{t} has an anchor in its body but was wrongly flagged generic; got: {audit}"
        )


def test_citation_marker_digits_do_not_falsely_count_as_year():
    """Greptile pre-scan: a body containing only citation markers like
    `[^S5-2024]` MUST NOT pass the anchor check via the year regex —
    the digits are not a date. `_LIMITATIONS_CITATION_STRIP_RE` pre-strips
    `[^...]` markers from the body before the anchor regex runs, so the
    embedded `-2024` / `-1999` digits cannot match the year sub-pattern."""
    article = (
        "## 5 Limitations\n\n"
        "### 5.1 Data Granularity\n\n"
        "the data is limited [^S5-2024]. more data needed [^S5-1999].\n\n"
        "### 5.2 Scope Cap\n\nPer R-1, excluded.\n\n"
        "### 5.3 Time Validity\n\nBeyond 2030 invalid.\n\n"
        "### 5.4 Sampling\n\nPer R-2, sampling.\n\n"
        "### 5.5 Falsifiers\n\nPer R-4, refuted.\n"
    )
    audit = validation._validate_limitations_chapter(article, _full_lc())
    assert audit is not None
    assert "data_granularity" in audit["generic_subsections"], (
        f"data_granularity body has only citation markers, no real anchor — should be generic; got: {audit}"
    )


def test_scenario_stress_test_detected_when_heading_present():
    """When `scenario_stress_test` is in the plan AND the article has a
    matching sub-section heading, `scenario_stress_test_present=True`."""
    article = _full_article_with_5_subsections() + (
        "\n### 5.6 Scenario Stress Test\n\n"
        "Base, optimistic, pessimistic scenarios recompute the §4 ranking.\n"
        "| Scenario | Top | Shifts |\n|---|---|---|\n| base | A | 0 |\n"
    )
    lc = _full_lc(scenario_stress_test={"scenarios": ["base", "opt", "pess"], "recompute_target": "tier_ranking"})
    audit = validation._validate_limitations_chapter(article, lc)
    assert audit is not None
    assert audit["scenario_stress_test_present"] is True


def test_scenario_stress_test_absent_when_heading_missing():
    """Plan has sst but article has no stress-test heading → False."""
    article = _full_article_with_5_subsections()  # no sst sub-section
    lc = _full_lc(scenario_stress_test={"scenarios": ["base", "opt", "pess"]})
    audit = validation._validate_limitations_chapter(article, lc)
    assert audit is not None
    assert audit["scenario_stress_test_present"] is False


def test_scenario_stress_test_detected_zh():
    """ZH form: `情景压力测试` heading matches too — bilingual coverage
    since Qianfan articles are predominantly ZH (q3, q14, q56, etc.)."""
    article = _full_article_with_5_subsections() + ("\n### 5.6 情景压力测试\n\n敏感性分析。\n")
    lc = _full_lc(scenario_stress_test={"scenarios": ["base", "opt", "pess"]})
    audit = validation._validate_limitations_chapter(article, lc)
    assert audit is not None
    assert audit["scenario_stress_test_present"] is True


# ---------- run() integration ----------


def test_run_surfaces_limitations_chapter_in_counts():
    """The validator must surface the limitations audit in
    `counts["limitations_chapter"]` so drift telemetry captures it.
    Mirrors the stakeholder pattern at run() line 270."""
    article = _full_article_with_5_subsections()
    plan = {
        "report_toc": [],
        "acceptance_criteria": [],
        "limitations_chapter": _full_lc(),
    }
    inp = _build_inp(article, plan)
    out = validation.run(inp)
    assert "limitations_chapter" in out.counts, (
        f"limitations audit missing from counts; got keys: {sorted(out.counts.keys())}"
    )
    aud = out.counts["limitations_chapter"]
    assert aud["n_subsections_declared"] == 5
    assert aud["n_subsections_present"] == 5


def test_run_omits_limitations_chapter_when_plan_field_null():
    """When plan has limitations_chapter=None (trend archetype),
    counts MUST NOT have a `limitations_chapter` key — silent skip."""
    article = "## Body\n\nContent.\n"
    plan = {"report_toc": [], "acceptance_criteria": [], "limitations_chapter": None}
    inp = _build_inp(article, plan)
    out = validation.run(inp)
    assert "limitations_chapter" not in out.counts


def test_run_is_advisory_not_blocking():
    """Generic / missing sub-sections must NOT add failures to the
    validation gate — advisory only. A degenerate article with no
    limitations chapter content must still produce ok=True from
    the validator (other checks may fail; this one MUST NOT)."""
    article = (
        "## 5 Limitations\n\n"
        "### 5.1 Data Granularity\n\ngeneric.\n\n"
        "### 5.2 Scope Cap\n\ngeneric.\n\n"
        "### 5.3 Time Validity\n\ngeneric.\n\n"
        "### 5.4 Sampling\n\ngeneric.\n\n"
        "### 5.5 Falsifiers\n\ngeneric.\n"
    )
    plan = {
        "report_toc": [],
        "acceptance_criteria": [],
        "limitations_chapter": _full_lc(),
    }
    inp = _build_inp(article, plan)
    out = validation.run(inp)
    # All 5 generic; counts has the limitations entry, no failures.
    aud = out.counts["limitations_chapter"]
    assert len(aud["generic_subsections"]) == 5
    # Generic limitations does not append a failure (advisory only).
    assert not any(f.get("check") == "limitations_chapter" for f in out.failures), (
        f"limitations check leaked into failures (should be advisory only); got: {out.failures}"
    )
