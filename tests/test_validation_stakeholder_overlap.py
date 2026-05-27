"""Unit tests for P3-W6 — `_validate_stakeholder_overlap`.

Pairwise Jaccard 4-gram overlap audit on stakeholder sub-sections.
Threshold 0.20 — the reference's stakeholder sub-sections in q23/q3/q14 are
nearly content-disjoint.
"""

from deep_research.pipeline import validation
from deep_research.pipeline.validation import _validate_stakeholder_overlap
from deep_research.state import DesignGuide, Scaffold


def test_returns_none_when_no_chapter():
    assert _validate_stakeholder_overlap("body", None) is None
    assert _validate_stakeholder_overlap("body", {}) is None


def test_returns_none_for_single_stakeholder():
    """Need ≥2 stakeholders to compute pairwise overlap."""
    sc = {"stakeholders": [{"id": "a", "label": "A"}]}
    assert _validate_stakeholder_overlap("body", sc) is None


def test_non_overlapping_stakeholders_pass():
    """Distinct content per stakeholder: max_pair_overlap < 0.20."""
    article = (
        "## Strategic Recommendations\n\n"
        "### For Investors\n\n"
        "Allocate capital to early-stage quantum hardware companies, "
        "prioritize portfolio diversification across superconducting and "
        "ion-trap approaches, hedge against patent disputes, and monitor "
        "DARPA QBI awards as third-party validation signals.\n\n"
        "### For Policymakers\n\n"
        "Coordinate export controls on cryogenic technology, fund university "
        "research at the QIS-CRAFT pilot programs, support international "
        "cooperation through the Quantum Flagship governance frameworks, "
        "and develop talent visas for foreign-trained researchers.\n\n"
        "### For Industry\n\n"
        "Build hybrid teams blending quantum theorists with classical engineers, "
        "establish error-correction R&D pipelines, partner with national labs "
        "for prototype validation, and invest in compiler/software tooling.\n"
    )
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
            {"id": "industry", "label": "For Industry"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    assert out is not None
    # Greptile PR #42 round-3: `n_stakeholders` renamed to
    # `n_stakeholders_audited` (the non-empty bodies that entered
    # comparison) so the audit can distinguish declared vs audited.
    assert out["n_stakeholders_declared"] == 3
    assert out["n_stakeholders_audited"] == 3
    assert out["max_pair_overlap"] < 0.20, f"got max overlap {out['max_pair_overlap']}: {out}"
    assert out["overlap_pairs"] == []
    assert out["missing_labels"] == []


def test_overlapping_stakeholders_flagged():
    """Two stakeholders with near-identical content: high Jaccard, flagged."""
    body = "Allocate capital to early-stage hardware companies and monitor patent disputes carefully."
    article = (
        "## Strategic Recommendations\n\n"
        f"### For Investors\n\n{body}\n\n"
        f"### For Policymakers\n\n{body}\n\n"  # IDENTICAL → max overlap = 1.0
    )
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    assert out["max_pair_overlap"] > 0.20
    assert any(t[0] == "investors" and t[1] == "policymakers" for t in out["overlap_pairs"])


def test_zh_uses_char_4grams():
    """ZH stakeholders: char 4-gram tokenization (no spaces)."""
    article = (
        "## 战略建议\n\n"
        "### 投资者\n\n"
        "推荐分散投资硬件公司，关注专利保护机制，监控政府资助信号变化。\n\n"
        "### 决策者\n\n"
        "协调出口管制，资助大学研究，支持国际合作框架，制定人才签证。\n"
    )
    sc = {
        "stakeholders": [
            {"id": "investor", "label": "投资者"},
            {"id": "policy", "label": "决策者"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    # Different content → low overlap.
    assert out["max_pair_overlap"] < 0.20, f"got {out}"


def test_missing_stakeholder_label_in_article_handled():
    """Stakeholder whose label isn't in the article: declared but not
    audited (excluded from pairwise overlap). Greptile PR #42 round-3
    surfaces this explicitly in `missing_labels` and `n_stakeholders_
    audited` so a reader of the audit output isn't misled."""
    article = "## Recommendations\n\n### For Investors\n\nInvestor advice here.\n"
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "absent", "label": "For Absent"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    # The absent stakeholder contributes empty body → no overlap pair fired.
    assert out["overlap_pairs"] == []
    assert out["n_stakeholders_declared"] == 2
    assert out["n_stakeholders_audited"] == 1, f"only the 1 found stakeholder should be audited; got {out}"
    assert out["missing_labels"] == ["absent"]


def test_returns_required_keys():
    sc = {"stakeholders": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
    out = _validate_stakeholder_overlap("## A\n\ntext\n\n## B\n\ntext\n", sc)
    # Greptile PR #42 round-2 added `short_pairs` so the audit surfaces when
    # an n-gram fallback was needed (4 → 3 → 2 grams) for short bodies.
    # Greptile PR #42 round-3 split `n_stakeholders` into
    # `n_stakeholders_declared` (plan total) and `n_stakeholders_audited`
    # (non-empty bodies actually compared) + added `missing_labels` to
    # surface plan entries whose label was not found in the article.
    expected = {
        "n_stakeholders_declared",
        "n_stakeholders_audited",
        "max_pair_overlap",
        "overlap_pairs",
        "short_pairs",
        "missing_labels",
    }
    assert set(out.keys()) == expected


def test_short_bodies_fall_back_to_bigrams_when_4gram_empty():
    """Greptile PR #42 round-2 issue #3: a short body like "Reduce risk"
    has 2 words → empty 4-gram and 3-gram sets. Previously the pair was
    silently skipped (false-negative). Now the audit falls back to
    bigrams (n=2) so even terse stakeholder directives are compared,
    and the fact that fallback fired is recorded in `short_pairs`.

    Greptile PR #42 round-4: this test previously used a 3-word body
    ("Reduce risk now") which made `_ngrams(text, 3)` return a single
    trigram (`3 < 3` is False, so the trigram path fired and bigram
    fallback never ran). The test name, docstring, and inline comment
    all claimed bigram fallback, while the assertion `in (2, 3)` only
    passed because it hedged on the n value. A genuine 2-word body
    forces the trigram set empty and exercises the actual bigram path
    the test claims to cover.
    """
    article = (
        "## Recommendations\n\n"
        "### For Investors\n\nReduce risk\n\n"  # 2 words → empty 4/3-grams, needs bigrams
        "### For Policymakers\n\nReduce risk\n"
    )
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    # Identical 2-word bodies → bigram fallback fires; bigrams identical → jaccard 1.0.
    assert out["max_pair_overlap"] > 0.20, f"identical short bodies not detected: {out}"
    assert any(t[0] == "investors" and t[1] == "policymakers" for t in out["overlap_pairs"])
    # short_pairs records bigram fallback (n_used = 2), exactly. No hedging.
    assert out["short_pairs"], f"short_pairs should record fallback firing: {out}"
    assert out["short_pairs"][0][0] == "investors"
    assert out["short_pairs"][0][1] == "policymakers"
    assert out["short_pairs"][0][2] == 2, (
        f"expected bigram fallback (n_used=2) for 2-word body, got {out['short_pairs'][0]}"
    )


def test_short_bodies_disjoint_at_bigram_level_not_flagged():
    """Symmetric coverage: short non-overlapping bodies should NOT be
    flagged even though they triggered fallback. short_pairs still
    records the fallback (diagnostic), but overlap_pairs stays empty."""
    article = "## Recommendations\n\n### For Investors\n\nReduce risk\n\n### For Policymakers\n\nIncrease funding\n"
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    assert out["overlap_pairs"] == [], f"disjoint short bodies wrongly flagged: {out}"
    # Bigram fallback fired (n_used=2) — visible in short_pairs.
    assert out["short_pairs"], f"short_pairs should record fallback firing: {out}"


def test_run_invokes_stakeholder_overlap_when_chapter_present():
    """Greptile PR #42 round-2 issue #1: `validation.run()` must actually
    call `_validate_stakeholder_overlap`. Previously it was dead code —
    defined after `run()` and never invoked from production. This test
    constructs a plan with an overlapping stakeholder_chapter, runs
    validation, and asserts the failure surfaces in `failures`."""
    body = "Allocate capital to early-stage hardware companies and monitor patent disputes carefully."
    article = (
        "# Title\n\n## 1 Overview\n\nOpening body content here.\n\n"
        "## 2 Strategic Recommendations\n\n"
        f"### For Investors\n\n{body}\n\n"
        f"### For Policymakers\n\n{body}\n"
    )
    plan = {
        "stakeholder_chapter": {
            "stakeholders": [
                {"id": "investors", "label": "For Investors"},
                {"id": "policymakers", "label": "For Policymakers"},
            ]
        }
    }
    inp = validation.ValidationInput(
        article=article,
        plan=plan,
        scaffold=Scaffold(sections=[]),
        design_guide=DesignGuide(),
        language="en",
        domain="default",
        task_id="t-test",
    )
    out = validation.run(inp)
    # The integration assertion: stakeholder_overlap counts AND failure both
    # present. Other checks may also fail (e.g., opening_template), so we
    # don't require `ok=False` to be solely from stakeholder_overlap; we
    # require the specific check to fire.
    assert "stakeholder_chapter" in out.counts, f"audit metadata missing: {out.counts}"
    overlap_failures = [f for f in out.failures if f["check"] == "stakeholder_overlap"]
    assert overlap_failures, f"stakeholder_overlap failure not surfaced: {out.failures}"


def test_run_skips_stakeholder_overlap_when_no_chapter():
    """When `plan` has no `stakeholder_chapter` (single-audience prompts),
    the audit must be silent — no metadata key, no failure entry, no
    crash. This is the path that ~half of all real tasks will take."""
    plan = {"acceptance_criteria": []}  # no stakeholder_chapter
    inp = validation.ValidationInput(
        article="# Title\n\n## 1 Overview\n\nbody\n",
        plan=plan,
        scaffold=Scaffold(sections=[]),
        design_guide=DesignGuide(),
        language="en",
        domain="default",
        task_id="t-no-sc",
    )
    out = validation.run(inp)
    assert "stakeholder_chapter" not in out.counts, f"unexpected audit metadata: {out.counts}"
    overlap_failures = [f for f in out.failures if f["check"] == "stakeholder_overlap"]
    assert overlap_failures == [], f"unexpected stakeholder_overlap failure: {out.failures}"


def test_run_records_stakeholder_overlap_metadata_when_clean():
    """When the chapter IS present but content is disjoint, metadata
    must still be recorded (counts["stakeholder_chapter"]) — so a
    dev-run reader can see "audit ran, found 0 overlaps" rather than
    "audit silently skipped." Distinguishes clean-pass from never-ran."""
    article = (
        "# Title\n\n## 1 Recs\n\n"
        "### For Investors\n\n"
        "Allocate capital to early-stage quantum hardware companies, "
        "prioritize portfolio diversification, hedge against patent disputes.\n\n"
        "### For Policymakers\n\n"
        "Coordinate export controls on cryogenic technology, fund university "
        "research programs and international cooperation frameworks.\n"
    )
    plan = {
        "stakeholder_chapter": {
            "stakeholders": [
                {"id": "investors", "label": "For Investors"},
                {"id": "policymakers", "label": "For Policymakers"},
            ]
        }
    }
    inp = validation.ValidationInput(
        article=article,
        plan=plan,
        scaffold=Scaffold(sections=[]),
        design_guide=DesignGuide(),
        language="en",
        domain="default",
        task_id="t-clean",
    )
    out = validation.run(inp)
    assert "stakeholder_chapter" in out.counts
    assert out.counts["stakeholder_chapter"]["overlap_pairs"] == []
    overlap_failures = [f for f in out.failures if f["check"] == "stakeholder_overlap"]
    assert overlap_failures == [], f"clean chapter wrongly flagged: {overlap_failures}"


# --------------------------------------------------------------------------
# Greptile PR #42 round-3 — heading-anchored body extraction must not be
# fooled by label appearing as cross-reference; audited count must
# distinguish from declared count.
# --------------------------------------------------------------------------


def test_label_as_cross_reference_does_not_pick_up_wrong_body():
    """Greptile PR #42 round-3 issue #1: pre-fix `str.find(label)` matched
    the FIRST occurrence of the label string anywhere in the article. If
    the label appears earlier as a cross-reference (e.g., '...see the
    For Investors section below...'), the extracted body spans from that
    line to the next heading — entirely the wrong section. The overlap
    audit then silently compares the wrong content and may falsely pass.

    Post-fix the regex anchors to a markdown heading line `#{2,4} ... label`
    only, so the cross-reference is ignored and the actual heading is used."""
    article = (
        "## Strategic Recommendations\n\n"
        "This chapter is split by audience. See the For Investors section below "
        "for capital-allocation guidance and the For Policymakers section for "
        "regulatory coordination guidance. Both sections must be read together "
        "because they share the same underlying analysis of patent disputes "
        "and export-control friction in the cryogenic supply chain.\n\n"
        "### For Investors\n\n"
        "Distinct investor-only advice: monitor DARPA QBI awards as third-party "
        "validation signals, hedge superconducting vs ion-trap exposure, prefer "
        "Series B/C entries over seed rounds, and track talent-poaching from "
        "the national-lab pipeline.\n\n"
        "### For Policymakers\n\n"
        "Distinct policymaker-only advice: coordinate the Wassenaar Arrangement "
        "updates with allies, fund the QIS-CRAFT pilot programs, develop talent "
        "visas matched to a 5-year horizon, and build international cooperation "
        "frameworks through the Quantum Flagship governance bodies.\n"
    )
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    # Pre-fix the extracted body for "For Investors" would have spanned
    # from the FIRST mention (in the cross-reference paragraph) to the
    # next `## `/`### ` heading — capturing the shared-analysis paragraph
    # PLUS the actual investor section + the policymaker section, which
    # would massively inflate overlap. Post-fix the body starts at the
    # actual `### For Investors` heading.
    assert out["max_pair_overlap"] < 0.20, (
        f"heading-anchor must skip the cross-reference; got max overlap {out['max_pair_overlap']}: {out}"
    )
    assert out["overlap_pairs"] == [], f"distinct sections wrongly flagged (heading anchor failed): {out}"


def test_label_in_other_section_body_does_not_pick_up_wrong_body():
    """Symmetric guard: the label appearing in ANOTHER section's body
    (not a heading) must not be mistaken for the section heading."""
    article = (
        "## Background\n\n"
        "Earlier studies referenced the For Investors framework first proposed "
        "by Smith (2024) as a reference design for capital-allocation cohorts. "
        "We adopt their taxonomy verbatim and extend it to the policymaker tier "
        "in the present analysis. Note the For Investors taxonomy uses five "
        "axes whereas our extension uses six.\n\n"
        "## Strategic Recommendations\n\n"
        "### For Investors\n\n"
        "Distinct investor advice: allocate to early-stage hardware companies, "
        "hedge approaches across superconducting and ion-trap, prefer late seed "
        "to early Series A, track DARPA awards as validation signals.\n\n"
        "### For Policymakers\n\n"
        "Distinct policymaker advice: coordinate Wassenaar updates, fund "
        "university research at QIS-CRAFT, develop talent visas, build "
        "international cooperation frameworks through Quantum Flagship.\n"
    )
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    assert out["overlap_pairs"] == [], f"distinct sections wrongly flagged (label-in-body mistaken for heading): {out}"


def test_label_in_heading_with_numbering_prefix_is_matched():
    """Headings frequently carry leading numbering (`### 8.3 For Investors`).
    The anchor must allow optional `\\d+(?:\\.\\d+)*\\s+` between hashes and
    label — otherwise numbered chapters silently miss the audit and the
    body falls back to empty (missing_labels)."""
    article = (
        "## 8 Strategic Recommendations\n\n"
        "### 8.1 For Investors\n\n"
        "Investor-only advice: allocate to hardware, hedge approaches, track DARPA awards.\n\n"
        "### 8.2 For Policymakers\n\n"
        "Policymaker-only advice: coordinate Wassenaar, fund QIS-CRAFT, develop talent visas.\n"
    )
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    assert out["n_stakeholders_audited"] == 2, f"numbered headings should still be matched; got {out}"
    assert out["missing_labels"] == []


def test_heading_label_match_is_case_insensitive():
    """Greptile PR #42 round-4: the writer LLM may de-capitalize headings
    mid-sentence (e.g. plan label `"For Investors"` → rendered as
    `### for investors`). Pre-fix the case-sensitive `re.search` returned
    None, the body was stored as `""`, and `"investors"` was added to
    `missing_labels` — a silent false-negative on the overlap audit.

    This test pins the fix: lowercase headings + a Title-Case heading +
    an UPPER-CASE heading must all match their plan-label counterparts,
    so every stakeholder enters the pairwise comparison and none lands
    in missing_labels.

    Also exercises that the case-insensitive match interoperates with
    the round-3 numbering-prefix tolerance (so a `### 8.1 for investors`
    still matches `For Investors`).

    Symmetric with `_validate_framing_chapter`'s vocabulary lookup
    (`body.lower().count(term.lower())`), which has been case-tolerant
    since round-1.
    """
    article = (
        "## 8 Strategic Recommendations\n\n"
        "### 8.1 for investors\n\n"  # lowercase + numbering prefix
        "Investor-only advice: allocate to hardware, hedge approaches.\n\n"
        "### For Policymakers\n\n"  # canonical Title-Case
        "Policymaker-only advice: coordinate Wassenaar, fund QIS-CRAFT.\n\n"
        "### FOR INDUSTRY\n\n"  # UPPER-CASE
        "Industry-only advice: hybrid teams, error-correction pipelines.\n"
    )
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
            {"id": "industry", "label": "For Industry"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    assert out["n_stakeholders_declared"] == 3
    assert out["n_stakeholders_audited"] == 3, (
        f"case-insensitive heading match should find all 3 stakeholders; got {out}"
    )
    assert out["missing_labels"] == [], f"no labels should be missing; got {out['missing_labels']}"


def test_n_stakeholders_declared_vs_audited_distinct_when_partial_missing():
    """The semantic gap Greptile flagged: 5 declared, 2 found → audited=2,
    not 5. Pre-fix `n_stakeholders=5` would mislead a reader to think all
    five entered the comparison."""
    article = (
        "## Recommendations\n\n"
        "### For Investors\n\nInvestor advice that is sufficiently long.\n\n"
        "### For Policymakers\n\nPolicymaker advice that is sufficiently long.\n"
    )
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
            {"id": "industry", "label": "For Industry"},
            {"id": "researchers", "label": "For Researchers"},
            {"id": "consumers", "label": "For Consumers"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    assert out["n_stakeholders_declared"] == 5
    assert out["n_stakeholders_audited"] == 2
    assert set(out["missing_labels"]) == {"industry", "researchers", "consumers"}


def test_body_extraction_stops_at_level1_heading():
    """Greptile PR #42 round-5 issue #2: pre-fix the `next_heading` regex
    matched only `#{2,4}` so a stakeholder block immediately followed by
    a level-1 chapter break (`# Appendix`, `# References`) would not see
    that boundary — the body would extend to the 5000-char cap, pulling
    in unrelated appendix/references content and inflating/deflating the
    Jaccard score for the trailing stakeholder. Post-fix `#{1,4}` catches
    level-1 breaks while still excluding `#####` deep headers.

    Setup: two stakeholders, the second followed by a level-1 `# Appendix`
    heading with prose that EXACTLY MATCHES the first stakeholder's body.
    Pre-fix, the policymaker body would absorb the appendix prose and
    Jaccard with investors would jump to ~1.0 (false positive). Post-fix
    the appendix prose is excluded and Jaccard stays low."""
    shared_prose = (
        "Capital allocation hedge ratio diversification governance compliance "
        "patent infrastructure cryogenic supply chain operations strategic "
        "planning advisory leadership."
    )
    article = (
        "## Strategic Recommendations\n\n"
        f"### For Investors\n\n{shared_prose}\n\n"
        "### For Policymakers\n\n"
        "Distinct policymaker-only advice: coordinate Wassenaar updates, "
        "fund QIS-CRAFT pilot programs, develop talent visas matched to a "
        "5-year horizon, build international cooperation frameworks.\n\n"
        f"# Appendix\n\n{shared_prose}\n\n"
        "More appendix material covering miscellaneous reference data.\n"
    )
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    # Post-fix: policymaker body stops at `# Appendix`, doesn't absorb
    # the shared_prose paragraph below it. Pairwise Jaccard stays low.
    assert out["max_pair_overlap"] < 0.20, (
        f"level-1 heading must terminate body extraction; got max overlap {out['max_pair_overlap']}: {out}"
    )
    assert out["overlap_pairs"] == [], f"distinct sections wrongly flagged (level-1 boundary missed): {out}"


def test_long_bodies_use_4grams_no_short_pair_entry():
    """When 4-grams are available for BOTH sides, no short_pairs entry —
    short_pairs is strictly a fallback indicator."""
    article = (
        "## Strategic Recommendations\n\n"
        "### For Investors\n\n"
        "Allocate capital to early-stage quantum hardware companies, "
        "prioritize portfolio diversification, hedge against patent disputes.\n\n"
        "### For Policymakers\n\n"
        "Coordinate export controls on cryogenic technology, fund university "
        "research, support international cooperation frameworks for AI.\n"
    )
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    # Long bodies → 4-grams plentiful → no fallback needed.
    assert out["short_pairs"] == [], f"unexpected short_pairs for long bodies: {out}"


def test_label_does_not_match_longer_heading_with_same_prefix():
    """Greptile PR #42 round-7 issue #2: pre-fix the heading regex had
    no end-of-label anchor, so a plan label `"For Industry"` silently
    matched `### For Industry Practitioners`. The extracted body would
    belong to the LONGER section, but `missing_labels` would NOT contain
    the stakeholder id and `n_stakeholders_audited` would count it as
    found — the audit looked complete while comparing the wrong content.
    Naive `(?!\\w)` does NOT fix this (the char after "Industry" is a
    space, which is non-word, so the lookahead passes). Post-fix the
    regex requires the label to be followed by end-of-line or a
    terminator punctuation (`:`, `-`, `—`, `–`).

    Setup: declare stakeholders ["For Industry", "For Investors"]; the
    article has ONLY `### For Industry Practitioners` and
    `### For Investors`. Pre-fix "For Industry" wrongly absorbed the
    Practitioners section. Post-fix it falls through to missing_labels."""
    article = (
        "## Strategic Recommendations\n\n"
        "### For Industry Practitioners\n\n"
        "Practitioners-only advice: build hybrid teams, prioritize "
        "compiler/software tooling, partner with national labs for "
        "prototype validation, invest in compiler infrastructure.\n\n"
        "### For Investors\n\n"
        "Investor-only advice: allocate to early-stage hardware, hedge "
        "approaches across superconducting and ion-trap, prefer late "
        "seed to early Series A, track DARPA awards as signals.\n"
    )
    sc = {
        "stakeholders": [
            {"id": "industry", "label": "For Industry"},
            {"id": "investors", "label": "For Investors"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    # "For Industry" must not match "For Industry Practitioners".
    assert "industry" in out["missing_labels"], (
        f"label `For Industry` should not match longer heading `For Industry Practitioners`; got {out}"
    )
    assert out["n_stakeholders_audited"] == 1, f"only `For Investors` actually exists as a heading; got {out}"


def test_label_matches_heading_with_trailing_colon():
    """Headings often carry a trailing colon (`### For Investors: Capital
    Allocation`). The post-round-7 anchor must accept this form so a
    real-world heading style isn't rejected by the new end-anchor."""
    article = (
        "## Strategic Recommendations\n\n"
        "### For Investors: Capital Allocation\n\n"
        "Investor advice with deep substantive content covering allocation, "
        "hedging, and DARPA award monitoring strategies.\n\n"
        "### For Policymakers — Regulatory Coordination\n\n"
        "Policymaker advice with Wassenaar updates, QIS-CRAFT funding, and "
        "talent visa development across a 5-year horizon for the workforce.\n"
    )
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    # Both stakeholders found despite trailing `:` and ` —` terminators.
    assert out["missing_labels"] == [], f"trailing punctuation (`:`, `—`) terminators should be accepted; got {out}"
    assert out["n_stakeholders_audited"] == 2
