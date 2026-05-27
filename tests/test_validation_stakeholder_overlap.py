"""Unit tests for P3-W6 — `_validate_stakeholder_overlap`.

Pairwise Jaccard 4-gram overlap audit on stakeholder sub-sections.
Threshold 0.20 — Qianfan's stakeholder sub-sections in q23/q3/q14 are
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
    assert out["n_stakeholders"] == 3
    assert out["max_pair_overlap"] < 0.20, f"got max overlap {out['max_pair_overlap']}: {out}"
    assert out["overlap_pairs"] == []


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
    """Stakeholder whose label isn't in the article: counts as empty body
    (n-gram set empty, contributes nothing to pairwise overlap)."""
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


def test_returns_required_keys():
    sc = {"stakeholders": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
    out = _validate_stakeholder_overlap("## A\n\ntext\n\n## B\n\ntext\n", sc)
    # Greptile PR #42 round-2 added `short_pairs` so the audit surfaces when
    # an n-gram fallback was needed (4 → 3 → 2 grams) for short bodies.
    expected = {"n_stakeholders", "max_pair_overlap", "overlap_pairs", "short_pairs"}
    assert set(out.keys()) == expected


def test_short_bodies_fall_back_to_bigrams_when_4gram_empty():
    """Greptile PR #42 round-2 issue #3: a short body like "Reduce risk"
    has 2 words → empty 4-gram and 3-gram sets. Previously the pair was
    silently skipped (false-negative). Now the audit falls back to
    bigrams (n=2) so even terse stakeholder directives are compared,
    and the fact that fallback fired is recorded in `short_pairs`."""
    article = (
        "## Recommendations\n\n"
        "### For Investors\n\nReduce risk now\n\n"  # 3 words → no 4-grams, no 3-grams (3<3 false), needs bigrams
        "### For Policymakers\n\nReduce risk now\n"
    )
    sc = {
        "stakeholders": [
            {"id": "investors", "label": "For Investors"},
            {"id": "policymakers", "label": "For Policymakers"},
        ]
    }
    out = _validate_stakeholder_overlap(article, sc)
    # Identical 3-word bodies → bigram fallback fires; bigrams identical → jaccard 1.0.
    assert out["max_pair_overlap"] > 0.20, f"identical short bodies not detected: {out}"
    assert any(t[0] == "investors" and t[1] == "policymakers" for t in out["overlap_pairs"])
    # short_pairs records that n<4 was needed; investors+policymakers used n=3 (3 words → 1 trigram).
    assert out["short_pairs"], f"short_pairs should record fallback firing: {out}"
    assert out["short_pairs"][0][0] == "investors"
    assert out["short_pairs"][0][1] == "policymakers"
    assert out["short_pairs"][0][2] in (2, 3), f"expected n_used in 2..3, got {out['short_pairs'][0]}"


def test_short_bodies_disjoint_at_bigram_level_not_flagged():
    """Symmetric coverage: short non-overlapping bodies should NOT be
    flagged even though they triggered fallback. short_pairs still
    records the fallback (diagnostic), but overlap_pairs stays empty."""
    article = (
        "## Recommendations\n\n"
        "### For Investors\n\nReduce risk\n\n"
        "### For Policymakers\n\nIncrease funding\n"
    )
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
