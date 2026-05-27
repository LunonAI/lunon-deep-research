"""Unit tests for P3-W6 — `_validate_stakeholder_overlap`.

Pairwise Jaccard 4-gram overlap audit on stakeholder sub-sections.
Threshold 0.20 — the reference's stakeholder sub-sections in q23/q3/q14 are
nearly content-disjoint.
"""

from deep_research.pipeline.validation import _validate_stakeholder_overlap


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
    expected = {"n_stakeholders", "max_pair_overlap", "overlap_pairs"}
    assert set(out.keys()) == expected
