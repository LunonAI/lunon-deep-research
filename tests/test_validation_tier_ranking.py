"""P3-W7.b (2026-05-27): `_validate_tier_ranking` tests.

The validator computes a structural + precision + sensitivity audit on
the tier_ranking chapter. Advisory severity — drift-log only.

Pre-strip note: footnote markers like `[^S7-2.45]` and §-refs like
`§7.45` are stripped before the 2-decimal/3+-decimal regex runs, so
their internal digits don't false-positive the precision check.
"""

from deep_research.pipeline import validation


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
