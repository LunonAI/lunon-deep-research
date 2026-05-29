"""P3-W7.b (2026-05-27): `_validate_tier_ranking` tests.

The validator computes a structural + precision + sensitivity audit on
the tier_ranking chapter. Advisory severity — drift-log only.

Pre-strip note: footnote markers like `[^S7-2.45]` and §-refs like
`§7.45` are stripped before the 2-decimal/3+-decimal regex runs, so
their internal digits don't false-positive the precision check.
"""

from deep_research.pipeline import validation
from deep_research.state import DesignGuide, Scaffold


def _full_tr(**overrides):
    tr = {
        "title": "Tier Ranking",
        "scoring_formula": "S_final = Σ(weight_i × dim_i)",
        "weights": {"R-1": 0.4, "R-2": 0.35, "R-3": 0.25},
        "tiers": [
            {"name": "Tier 1", "threshold": ">=8.0"},
            {"name": "Tier 2", "threshold": ">=6.0"},
            {"name": "Tier 3", "threshold": "<6.0"},
        ],
        "sensitivity_check": {"perturbation_pp": 10, "report": "rank_stability"},
    }
    tr.update(overrides)
    return tr


def _well_formed_article() -> str:
    """An article with a proper tier_ranking chapter: scoring table
    with 2-decimal cells AND a sensitivity sub-section."""
    return (
        "# Title\n\n"
        "## 1 Intro\n\nBody.\n\n"
        "## 7 Tier Ranking\n\n"
        "Using S_final = Σ(weight_i × dim_i), each entity is scored per "
        "§1.2 rubric items R-1, R-2, R-3.\n\n"
        "| Entity | R-1 | R-2 | R-3 | S_final | Tier |\n"
        "|---|---|---|---|---|---|\n"
        "| A | 8.50 | 7.20 | 9.10 | 8.20 | Tier 1 |\n"
        "| B | 6.30 | 6.10 | 5.40 | 6.05 | Tier 2 |\n"
        "| C | 4.50 | 4.20 | 3.80 | 4.20 | Tier 3 |\n\n"
        "### 7.1 Sensitivity Check\n\n"
        "Under ±10pp perturbation on R-1, 2 entities change tier. The "
        "most-sensitive weight is R-1.\n\n"
        "| Scenario | A | B | C |\n"
        "|---|---|---|---|\n"
        "| Base | T1 | T2 | T3 |\n"
        "| R-1 -10pp | T2 | T2 | T3 |\n"
        "| R-1 +10pp | T1 | T1 | T3 |\n"
    )


# ---------- None / null / malformed handling ----------


def test_returns_none_when_tier_ranking_absent():
    plan = {"report_toc": []}
    assert validation._validate_tier_ranking("body", plan) is None


def test_returns_none_when_tier_ranking_null():
    plan = {"tier_ranking": None}
    assert validation._validate_tier_ranking("body", plan) is None


def test_returns_none_when_weights_not_dict():
    tr = _full_tr(weights=[("R-1", 0.5)])
    assert validation._validate_tier_ranking("body", {"tier_ranking": tr}) is None


def test_returns_none_when_tiers_not_list():
    tr = _full_tr(tiers="not a list")
    assert validation._validate_tier_ranking("body", {"tier_ranking": tr}) is None


def test_returns_none_when_weights_empty():
    tr = _full_tr(weights={})
    assert validation._validate_tier_ranking("body", {"tier_ranking": tr}) is None


# ---------- bool-subclass-of-int filter ----------


def test_bool_weights_filtered_out():
    """Greptile pre-scan: bool is a subclass of int. Filter must
    explicitly exclude bool to prevent `True`/`False` from being
    counted as numeric weights."""
    tr = _full_tr(weights={"R-1": True, "R-2": False, "R-3": 0.5})
    audit = validation._validate_tier_ranking(_well_formed_article(), {"tier_ranking": tr})
    assert audit is not None
    # Only R-3 is numeric (not bool); n_weights = 1
    assert audit["n_weights"] == 1, f"bool weights should be filtered out; got n_weights={audit['n_weights']}"


# ---------- structural detection ----------


def test_well_formed_article_passes_all_checks():
    """Canonical case: scoring table with 2-decimal cells + sensitivity
    sub-section → all green."""
    audit = validation._validate_tier_ranking(_well_formed_article(), {"tier_ranking": _full_tr()})
    assert audit is not None
    assert audit["n_weights"] == 3
    assert audit["n_tiers"] == 3
    assert audit["scoring_table_present"] is True
    assert audit["two_decimal_cells"] >= 12  # 3 entities × 4 score columns
    assert audit["three_plus_decimal_cells"] == 0
    assert audit["decimal_precision_ok"] is True
    assert audit["sensitivity_subsection_present"] is True


def test_scoring_table_absent_flagged():
    """An article where the writer rendered the chapter as prose only
    (no markdown table) flags scoring_table_present=False."""
    article = (
        "## 7 Tier Ranking\n\n"
        "Entity A scores 8.50 on R-1, 7.20 on R-2. Entity B scores 6.30 on R-1.\n"
        "### 7.1 Sensitivity Check\n\nUnder ±10pp, 2 entities shift.\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None
    assert audit["scoring_table_present"] is False


def test_1_decimal_precision_fails_decimal_check():
    """A scoring table with 1-decimal cells fails the 2-decimal check
    even if 2-decimal cells exist elsewhere. The decimal_precision_ok
    bar requires ZERO 3+-decimal cells AND ≥1 two-decimal cell. But
    1-decimal cells are allowed (they're just not COUNTED as 2-dec).
    To catch the 1-dec writer drift, we test that two_decimal_cells
    is below the threshold for a real table."""
    article = (
        "## 7 Tier Ranking\n\n"
        "| Entity | R-1 | S_final |\n|---|---|---|\n"
        "| A | 8.5 | 7.5 |\n"  # 1-decimal — won't match 2-dec regex
        "| B | 6.3 | 6.0 |\n"
        "### 7.1 Sensitivity Check\n\nUnder ±10pp.\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None
    # No 2-decimal cells found — precision NOT ok
    assert audit["two_decimal_cells"] == 0
    assert audit["decimal_precision_ok"] is False


def test_3_decimal_precision_fails_check():
    """A scoring table with 3+-decimal cells (e.g., 7.452) fails the
    2-decimal check — Qianfan corpus convention is strict 2 decimals."""
    article = (
        "## 7 Tier Ranking\n\n"
        "| Entity | R-1 | S_final |\n|---|---|---|\n"
        "| A | 8.452 | 7.213 |\n"  # 3-decimal — disallowed
        "| B | 6.30 | 6.05 |\n"
        "### 7.1 Sensitivity Check\n\nUnder ±10pp.\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None
    assert audit["three_plus_decimal_cells"] >= 1
    assert audit["decimal_precision_ok"] is False


def test_citation_marker_digits_dont_falsely_count_as_decimal():
    """Greptile pre-scan: a body containing only citation markers like
    `[^S7-2.45]` MUST NOT match the 2-decimal regex. Pre-strip
    `[^...]` so internal `2.45` digits don't false-positive."""
    article = (
        "## 7 Tier Ranking\n\n"
        "| Entity | R-1 |\n|---|---|\n"
        "| A [^S7-7.45] | text |\n"
        "| B [^S7-2.45] | text |\n"
        "### 7.1 Sensitivity\n\nUnder ±10pp.\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None
    # Citation-marker digits stripped → no 2-decimal cells found
    # (the "7.45" inside [^S7-7.45] doesn't count).
    assert audit["two_decimal_cells"] == 0


def test_section_ref_digits_dont_falsely_count_as_decimal():
    """Similar: `§7.45` is a section ref, not a score. Pre-strip."""
    article = (
        "## 7 Tier Ranking\n\n"
        "| Entity | R-1 |\n|---|---|\n"
        "| A | See §7.45 |\n"
        "| B | See §2.45 |\n"
        "### 7.1 Sensitivity\n\nUnder ±10pp.\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None
    assert audit["two_decimal_cells"] == 0


# ---------- sensitivity heading detection (4 forms) ----------


def test_sensitivity_heading_en_detected():
    """EN 'Sensitivity' heading."""
    article = "## 7 Tier Ranking\n\n| E | S |\n|---|---|\n| A | 8.50 |\n### 7.1 Sensitivity Check\n\nBody.\n"
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None and audit["sensitivity_subsection_present"] is True


def test_sensitivity_heading_zh_detected():
    """ZH '敏感性' heading."""
    article = "## 7 Tier Ranking\n\n| E | S |\n|---|---|\n| A | 8.50 |\n### 7.1 敏感性分析\n\nBody.\n"
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None and audit["sensitivity_subsection_present"] is True


def test_sensitivity_heading_pp_symbolic_detected():
    """Symbolic '±10pp' form."""
    article = "## 7 Tier Ranking\n\n| E | S |\n|---|---|\n| A | 8.50 |\n### 7.1 ±10pp Perturbation\n\nBody.\n"
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None and audit["sensitivity_subsection_present"] is True


def test_sensitivity_heading_zh_percentage_detected():
    """ZH '±10个百分点' form."""
    article = "## 7 Tier Ranking\n\n| E | S |\n|---|---|\n| A | 8.50 |\n### 7.1 ±10个百分点扰动\n\nBody.\n"
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None and audit["sensitivity_subsection_present"] is True


def test_sensitivity_heading_absent_flagged():
    """An article with NO sensitivity sub-section flags False."""
    article = "## 7 Tier Ranking\n\n| E | S |\n|---|---|\n| A | 8.50 |\n### 7.1 Conclusion\n\nWrap-up.\n"
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None and audit["sensitivity_subsection_present"] is False


# ---------- cross-PR rubric consistency ----------


def test_rubric_mismatch_keys_flagged_when_framing_present():
    """Cross-PR consistency: tier_ranking.weights keys NOT in
    framing_chapter.published_rubric_items are flagged in
    `rubric_mismatch_keys`."""
    tr = _full_tr(weights={"R-1": 0.4, "R-2": 0.35, "R-4": 0.25})  # R-4 not in framing
    fc = {
        "title": "Framework",
        "sub_sections": [],
        "published_vocabulary": [],
        "published_rubric_items": [
            {"id": "R-1", "label": "X", "weight": 0.5},
            {"id": "R-2", "label": "Y", "weight": 0.5},
            {"id": "R-3", "label": "Z", "weight": 0.0},
        ],
    }
    audit = validation._validate_tier_ranking(_well_formed_article(), {"tier_ranking": tr, "framing_chapter": fc})
    assert audit is not None
    assert audit["rubric_mismatch_keys"] == ["R-4"], (
        f"R-4 (not in framing rubric) should be flagged; got: {audit['rubric_mismatch_keys']}"
    )


def test_rubric_mismatch_keys_empty_when_aligned():
    """When all tier_ranking weights align with framing rubric ids,
    `rubric_mismatch_keys` is empty."""
    tr = _full_tr()  # R-1, R-2, R-3
    fc = {
        "title": "Framework",
        "sub_sections": [],
        "published_vocabulary": [],
        "published_rubric_items": [
            {"id": "R-1", "label": "X", "weight": 0.4},
            {"id": "R-2", "label": "Y", "weight": 0.35},
            {"id": "R-3", "label": "Z", "weight": 0.25},
        ],
    }
    audit = validation._validate_tier_ranking(_well_formed_article(), {"tier_ranking": tr, "framing_chapter": fc})
    assert audit is not None
    assert audit["rubric_mismatch_keys"] == []


def test_rubric_mismatch_keys_empty_when_no_framing_chapter():
    """When framing_chapter is absent, the cross-PR check is skipped —
    `rubric_mismatch_keys` is empty (no false positives on plans
    without a framing chapter)."""
    tr = _full_tr()
    audit = validation._validate_tier_ranking(_well_formed_article(), {"tier_ranking": tr})
    assert audit is not None
    assert audit["rubric_mismatch_keys"] == []


# ---------- Chapter-boundary heading-level coverage (Greptile PR #47 round-2) ----------


def test_h3_tier_ranking_chapter_does_not_absorb_h3_siblings():
    r"""Greptile PR #47 round-2: chapter-start regex accepts `#{1,3}`
    so an H3 chapter `### 7.3 Tier Ranking` is a legitimate entry
    point. Pre-fix, chapter-end was bounded at `#{1,2}` only — so an
    H3 chapter would bleed past its H3 siblings (`### 7.4 …`,
    `### 7.5 …`), and tables / sensitivity headings in those siblings
    would register as if they belonged to tier_ranking. Post-fix,
    chapter-end is bounded at the SAME hash-count as chapter-start,
    so an H3 chapter ends at the next H1/H2/H3.

    Fixture: an H3 tier_ranking chapter with NO table and NO
    sensitivity sub-section, followed by an H3 sibling chapter that
    contains both. Pre-fix: `scoring_table_present=True` and
    `sensitivity_subsection_present=True` (sibling content absorbed).
    Post-fix: both False (sibling content correctly excluded).
    """
    article = (
        "# Title\n\n"
        "## 7 Outer Section\n\n"
        "### 7.3 Tier Ranking\n\n"  # H3 chapter with empty body
        "The methodology is described in the next section.\n\n"
        "### 7.4 Methodology Notes\n\n"  # sibling at SAME H3 level
        "| Entity | R-1 | R-2 | S_final |\n"
        "|---|---|---|---|\n"
        "| A | 8.50 | 7.20 | 7.85 |\n\n"
        "#### 7.4.1 Sensitivity Analysis Subnote\n\n"
        "Under ±10pp perturbation, all tiers hold.\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None
    # Sibling's table must NOT be attributed to the empty H3 chapter.
    assert audit["scoring_table_present"] is False, f"H3 chapter absorbed sibling H3 section's table: {audit}"
    # Sibling's sensitivity heading must NOT be attributed either.
    assert audit["sensitivity_subsection_present"] is False, f"H3 chapter absorbed sibling sensitivity heading: {audit}"
    # And no decimal cells should leak from the sibling.
    assert audit["two_decimal_cells"] == 0


def test_h3_tier_ranking_chapter_keeps_own_h4_sensitivity_subsection():
    """Complement to the above: when an H3 chapter has its OWN H4
    sensitivity sub-section (the level-deeper-than-chapter form), it
    must STAY in the scanned region — proportional bounding means
    end-at-same-level, so deeper sub-sections survive.
    """
    article = (
        "# Title\n\n"
        "## 7 Outer\n\n"
        "### 7.3 Tier Ranking\n\n"
        "Per §1.2 rubric R-1, R-2, R-3:\n\n"
        "| Entity | R-1 | R-2 | R-3 | S_final |\n"
        "|---|---|---|---|---|\n"
        "| A | 8.50 | 7.20 | 9.10 | 8.20 |\n\n"
        "#### 7.3.1 Sensitivity Check\n\n"
        "Under ±10pp perturbation, no entity changes tier.\n\n"
        "### 7.4 Next Sibling\n\nUnrelated.\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None
    assert audit["scoring_table_present"] is True
    assert audit["sensitivity_subsection_present"] is True
    # Sibling content excluded.
    assert "Unrelated" not in str(audit)


# ---------- Title prefix-collision protection (Greptile PR #47 round-2) ----------


def test_chapter_title_does_not_match_longer_prefix_heading():
    """Greptile PR #47 round-2: applying the
    `regex-prefix-collision-no-end-anchor` pattern fix from PR #42
    round-7 to this validator. Title `"Tier Ranking"` must NOT
    silently match a heading like `## 7 Tier Ranking Considerations`
    — without an end anchor, `re.escape(title)` would, and the wrong
    chapter's body would be extracted.

    Fixture: an article with NO `## N Tier Ranking` heading but with
    a `## 7 Tier Ranking Considerations` heading containing a full
    scoring table. Pre-fix: the longer heading would match,
    `scoring_table_present=True` for a chapter the writer never
    actually rendered. Post-fix: no match, chapter_body is empty,
    audit reports an all-zero structural result.
    """
    article = (
        "# Title\n\n"
        "## 7 Tier Ranking Considerations\n\n"  # longer; must NOT match
        "Some discussion about tier-ranking methodology.\n\n"
        "| Entity | R-1 | R-2 | S_final |\n"
        "|---|---|---|---|\n"
        "| A | 8.50 | 7.20 | 7.85 |\n\n"
        "### 7.1 Sensitivity Analysis\n\n"
        "±10pp perturbation discussion.\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None
    # The longer heading must NOT have been used as the chapter anchor —
    # so the table / sensitivity heading inside it stay out of the audit.
    assert audit["scoring_table_present"] is False, f"prefix-collision: 'Tier Ranking' matched longer heading: {audit}"
    assert audit["sensitivity_subsection_present"] is False
    assert audit["two_decimal_cells"] == 0


def test_chapter_title_followed_by_known_terminators_still_matches():
    """Symmetric: the end-anchor accepts the title followed by a known
    heading terminator (`:`, `-`, `—`, `–`) — these are legitimate
    heading-extension separators, not prefix-collision sources.
    """
    for terminator in (":", " -", " —", " –"):
        article = (
            "# Title\n\n"
            f"## 7 Tier Ranking{terminator} Detailed Methodology\n\n"
            "Per §1.2 R-1, R-2, R-3:\n\n"
            "| Entity | R-1 | R-2 | S_final |\n"
            "|---|---|---|---|\n"
            "| A | 8.50 | 7.20 | 7.85 |\n\n"
            "### 7.1 Sensitivity Check\n\n"
            "±10pp.\n"
        )
        audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
        assert audit is not None
        assert audit["scoring_table_present"] is True, (
            f"title with terminator {terminator!r} should still match: {audit}"
        )


# ---------- Sensitivity heading anchor token set (Greptile PR #47 round-3) ----------


def test_sensitivity_heading_matches_each_documented_token():
    """The validator's sensitivity-heading regex MUST match each of the
    4 documented heading-anchor tokens: `sensitivity` (EN), `敏感性`
    (ZH), `±Npp` (symbolic-shorthand EN), `±N个百分点` (symbolic ZH).
    These four tokens are the contract surface — writer.py directive +
    `_TIER_RANKING_RULE` + the comment above the regex all enumerate
    exactly these four. Pin each individually so a future tightening
    of the regex can't silently drop one.
    """
    base_chapter = (
        "# Title\n\n"
        "## 7 Tier Ranking\n\n"
        "Per §1.2 R-1, R-2, R-3:\n\n"
        "| Entity | R-1 | S_final |\n|---|---|---|\n"
        "| A | 8.50 | 7.85 |\n\n"
        "{sensitivity_heading}\n\n"
        "Recompute under perturbation: A stays Tier 1.\n"
    )
    documented_tokens = (
        "### 7.1 Sensitivity Check",  # EN word
        "### 7.1 敏感性分析",  # ZH word
        "### 7.1 ±10pp Robustness",  # symbolic-shorthand EN
        "### 7.1 ±10个百分点扰动",  # symbolic-shorthand ZH
    )
    for heading in documented_tokens:
        article = base_chapter.format(sensitivity_heading=heading)
        audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
        assert audit is not None
        assert audit["sensitivity_subsection_present"] is True, (
            f"documented heading anchor `{heading}` failed to match: {audit}"
        )


def test_sensitivity_heading_does_not_match_undocumented_stress_test_form():
    """Greptile PR #47 round-3: the regex previously had an undocumented
    `stress\\s+test` alternation — not in the writer directive, not in
    `_TIER_RANKING_RULE`, not in the comment above the regex. A chapter
    with a `### Stress Test Analysis` heading but NO actual ±pp re-
    ranking content would have `sensitivity_subsection_present=True`
    logged in drift telemetry even though the required computational
    sub-section was absent — silent false-negative on the audit
    contract. Also conflicts terminology with the P3-W5 limitations
    chapter's `scenario_stress_test` sub-node (a different
    architectural concept).

    Post-fix, a "Stress Test"-only heading must NOT match — the writer
    is correctly steered toward the 4 documented forms.
    """
    article = (
        "# Title\n\n"
        "## 7 Tier Ranking\n\n"
        "Per §1.2 R-1, R-2, R-3:\n\n"
        "| Entity | R-1 | S_final |\n|---|---|---|\n"
        "| A | 8.50 | 7.85 |\n\n"
        "### 7.1 Stress Test Analysis\n\n"  # undocumented form
        "Some prose about stressing the model, but no ±pp recompute.\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit is not None
    assert audit["sensitivity_subsection_present"] is False, (
        f"undocumented `Stress Test` form leaked back into sensitivity match: {audit}"
    )


# ---------- G3 (2026-05-28): commitment-gate signals ----------


def test_audit_reports_entities_scored_present_when_populated():
    """G3: entities_scored populated → flag True (architect computed numeric
    scores, so the chapter MUST render a committed matrix)."""
    plan = {"tier_ranking": _full_tr(entities_scored=[{"name": "A", "s_final": 8.2}])}
    audit = validation._validate_tier_ranking(_well_formed_article(), plan)
    assert audit["entities_scored_present"] is True


def test_audit_reports_entities_scored_absent_for_qualitative_or_no_scores():
    """G3: no entities_scored (qualitative compare tiers, or the fail-soft
    no-scores path) → flag False, so the numeric-matrix requirement won't fire."""
    plan = {"tier_ranking": _full_tr()}
    audit = validation._validate_tier_ranking(_well_formed_article(), plan)
    assert audit["entities_scored_present"] is False


def test_audit_counts_deferral_tokens_inside_chapter():
    """G3: deferral/placeholder tokens in the ranking chapter are counted —
    待§N核实 / 未核实 / 占位 / 证据缺口."""
    article = (
        "# Title\n\n## 1 Intro\n\nBody.\n\n"
        "## 7 Tier Ranking\n\n"
        "| Team | S_final |\n|---|---|\n"
        "| A | 待§2核实 |\n| B | 未核实 |\n\n"
        "占位说明 and 证据缺口 remain to be filled.\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit["deferral_hits"] >= 4, audit


def test_audit_deferral_scoped_to_chapter_region():
    """G3: deferral tokens OUTSIDE the ranking chapter (e.g. a §1 roadmap)
    are NOT counted by deferral_hits — that case is caught instead by the
    'entities_scored_present but no committed matrix' failure."""
    article = (
        "# Title\n\n## 1 Intro\n\n占位 待核实 未核实 证据缺口 in the roadmap.\n\n"
        "## 7 Tier Ranking\n\n"
        "| Entity | S_final |\n|---|---|\n| A | 8.20 |\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit["deferral_hits"] == 0, audit


def test_audit_clean_committed_ranking_has_zero_deferral():
    """G3: a fully-committed numeric ranking has no deferral tokens."""
    audit = validation._validate_tier_ranking(_well_formed_article(), {"tier_ranking": _full_tr()})
    assert audit["deferral_hits"] == 0
    assert audit["scoring_table_present"] is True
    assert audit["two_decimal_cells"] >= 1


# ---------- Greptile PR #64 issue #3: `占位` negative lookahead ----------


def test_deferral_占位_substring_compounds_not_counted():
    """Greptile PR #64 issue #3: the bare `占位` alternation matched any
    occurrence of those two chars as a substring, including the unrelated
    compounds `占位置` ("occupy a position") and `占位费` ("site/booth fee").
    The negative lookahead `占位(?![置费])` excludes both while still counting
    the placeholder sense. Here the ranking chapter contains ONLY the two
    false-positive compounds, so deferral_hits must be 0."""
    article = (
        "# Title\n\n## 1 Intro\n\nBody.\n\n"
        "## 7 Tier Ranking\n\n"
        "| Entity | S_final |\n|---|---|\n| A | 8.20 |\n\n"
        "Entity A 占位置 in the front rank, and the 占位费 was already paid.\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit["deferral_hits"] == 0, audit


def test_deferral_real_占位_placeholder_still_counted():
    """Complement: a genuine `占位` placeholder (bare, and the common
    `占位符` form) IS still counted — the lookahead only excludes the
    `[置费]` compounds, so recall on the placeholder sense is unchanged."""
    article = (
        "# Title\n\n## 1 Intro\n\nBody.\n\n"
        "## 7 Tier Ranking\n\n"
        "| Entity | S_final |\n|---|---|\n| A | 占位 |\n| B | 占位符 |\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit["deferral_hits"] >= 2, audit


def test_deferral_other_tokens_recall_unchanged_after_lookahead():
    """Recall on the non-占位 tokens (待…核实 / 未核实 / 证据缺口) is
    unaffected by the `占位` lookahead change."""
    article = (
        "# Title\n\n## 1 Intro\n\nBody.\n\n"
        "## 7 Tier Ranking\n\n"
        "| Entity | S_final |\n|---|---|\n"
        "| A | 待§2核实 |\n| B | 未核实 |\n| C | 证据缺口 |\n"
    )
    audit = validation._validate_tier_ranking(article, {"tier_ranking": _full_tr()})
    assert audit["deferral_hits"] >= 3, audit


# ---------- Greptile PR #64 issue #2: run() promotion-to-failure integration ----------
#
# The five helper-level tests above verify the audit dict only. These drive the
# actual `run()` promotion blocks (~372-399 of validation.py) so a regression in
# the caller (wrong key, `>` vs `>=`, the two blocks swapped, or a missing
# entities_scored_present guard) is caught.


def _run_input(article: str, plan: dict, task_id: str = "t-tr"):
    return validation.ValidationInput(
        article=article,
        plan=plan,
        scaffold=Scaffold(sections=[]),
        design_guide=DesignGuide(),
        language="en",
        domain="default",
        task_id=task_id,
    )


def _uncommitted_deferred_article() -> str:
    """A tier_ranking chapter that renders a table SHAPE but every score
    cell is a deferral/placeholder token — no committed 2-decimal cell, and
    >2 deferral tokens. With entities_scored populated this must trip BOTH
    `tier_ranking_uncommitted` (a) and `tier_ranking_deferred` (b)."""
    return (
        "# Title\n\n## 1 Intro\n\nBody.\n\n"
        "## 7 Tier Ranking\n\n"
        "Per §1.2 rubric R-1, R-2, R-3 (scores deferred):\n\n"
        "| Entity | R-1 | R-2 | S_final |\n"
        "|---|---|---|---|\n"
        "| A | 待§2核实 | 未核实 | 占位 |\n"
        "| B | 证据缺口 | 未核实 | 占位 |\n\n"
        "Final scoring 待§2–§7完成.\n"
    )


def test_run_promotes_uncommitted_and_deferred_when_entities_scored():
    """Issue #2: with entities_scored populated and an uncommitted+deferred
    chapter, `run()` must surface BOTH hard failures in `failures`."""
    plan = {"tier_ranking": _full_tr(entities_scored=[{"name": "A", "s_final": 8.2}])}
    out = validation.run(_run_input(_uncommitted_deferred_article(), plan))
    checks = {f["check"] for f in out.failures}
    assert "tier_ranking_uncommitted" in checks, f"uncommitted not promoted: {out.failures}"
    assert "tier_ranking_deferred" in checks, f"deferred not promoted: {out.failures}"
    # Both promoted failures must be high severity (regen-looping signal).
    for f in out.failures:
        if f["check"] in ("tier_ranking_uncommitted", "tier_ranking_deferred"):
            assert f["severity"] == "high", f
    assert out.ok is False
    # The audit metadata is also recorded so a dev reader sees the signal.
    assert "tier_ranking" in out.counts


def test_run_does_not_promote_when_entities_scored_absent():
    """Issue #2 + Issue #1: the SAME uncommitted+deferred chapter, but with
    NO entities_scored (qualitative compare tiers / fail-soft no-scores
    path), must NOT trip either hard failure — both gates are guarded by
    entities_scored_present so the regenerator never loops on these."""
    plan = {"tier_ranking": _full_tr()}  # no entities_scored
    out = validation.run(_run_input(_uncommitted_deferred_article(), plan))
    checks = {f["check"] for f in out.failures}
    assert "tier_ranking_uncommitted" not in checks, f"uncommitted wrongly promoted: {out.failures}"
    assert "tier_ranking_deferred" not in checks, f"deferred wrongly promoted: {out.failures}"
    # Audit metadata is still recorded (the chapter was planned + rendered).
    assert "tier_ranking" in out.counts
    assert out.counts["tier_ranking"]["entities_scored_present"] is False


def test_run_does_not_promote_committed_clean_ranking():
    """Issue #2: a well-formed committed ranking (2-decimal table, no
    deferral) with entities_scored populated must NOT trip either gate —
    guards against an inverted condition that would fail clean articles."""
    plan = {"tier_ranking": _full_tr(entities_scored=[{"name": "A", "s_final": 8.2}])}
    out = validation.run(_run_input(_well_formed_article(), plan))
    checks = {f["check"] for f in out.failures}
    assert "tier_ranking_uncommitted" not in checks, f"clean ranking wrongly flagged uncommitted: {out.failures}"
    assert "tier_ranking_deferred" not in checks, f"clean ranking wrongly flagged deferred: {out.failures}"


def test_run_skips_tier_ranking_when_absent():
    """Issue #2: with no tier_ranking in the plan, neither gate fires and no
    tier_ranking metadata is recorded."""
    plan = {"acceptance_criteria": []}
    out = validation.run(_run_input("# Title\n\n## 1 Overview\n\nbody\n", plan))
    checks = {f["check"] for f in out.failures}
    assert "tier_ranking_uncommitted" not in checks
    assert "tier_ranking_deferred" not in checks
    assert "tier_ranking" not in out.counts
