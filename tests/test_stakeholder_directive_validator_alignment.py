"""P3-W6.b (2026-05-27): writer-directive ↔ validator alignment check.

The W6.b directive's non-overlap discipline must produce output that
PASSES the validator's pairwise Jaccard < 0.20 audit (which has been
ACTIVE since PR #42). Pre-W6.b the validator was alone; this test
proves the directive + validator form a closed loop.

We can't actually run the writer LLM in unit tests, so we exercise
the loop with synthetic article output that follows the directive's
prose contract (disjoint per-stakeholder bodies, named addressees,
content-directive specificity) and assert the validator scores it
ok=True.
"""

from deep_research.pipeline import validation


def _disjoint_article(stakeholders: list[tuple[str, str]]) -> str:
    """Build a synthetic stakeholder chapter following the W6.b
    directive's contract: each addressee's body is content-disjoint
    from siblings (no shared 4-grams), naming the stakeholder's
    specific decision context."""
    sections = ["## 7 Strategic Recommendations\n", "Opening paragraph.\n"]
    for sid, (_, label) in enumerate(stakeholders, 1):
        body_map = {
            "For Investors": (
                "Investors should pursue ARR-positive Series-B picks in semiconductor "
                "manufacturing and avoid analog hardware. Diversify across architectures. "
                "Track the policy timeline for export controls."
            ),
            "For Policymakers": (
                "Policymakers should incentivize quantum-safe cryptography standards "
                "and fund domestic foundry capacity. Coordinate with allies on chip-"
                "fab subsidies. Mandate PQC migration deadlines for federal systems."
            ),
            "For Industry": (
                "Industry leaders should partner with academic groups on benchmark "
                "datasets. Allocate engineering hires toward integration teams. "
                "Adopt open-source toolchains to reduce vendor lock-in."
            ),
            "For Researchers": (
                "Researchers should focus efforts on error-correction asymptotics "
                "and noise modeling. Publish in venues with reproducible artifacts. "
                "Collaborate cross-institutionally on shared substrate benchmarks."
            ),
            "For Practitioners": (
                "Practitioners should pilot hybrid classical-quantum workflows on "
                "non-critical workloads. Train cross-functional staff on circuit-"
                "design tooling. Document failure modes for the broader community."
            ),
        }
        body = body_map.get(label, f"Generic advice for {label}.")
        sections.append(f"### 7.{sid} {label}\n\n{body}\n")
    return "\n".join(sections)


def _overlapping_article(stakeholders: list[tuple[str, str]]) -> str:
    """Build a synthetic stakeholder chapter that VIOLATES the W6.b
    non-overlap discipline (every body has 80%+ shared content) so the
    validator MUST flag it."""
    common_body = (
        "Pursue ARR-positive Series-B picks in semiconductor manufacturing and "
        "avoid early-stage analog hardware. Diversify across architectures. "
        "Track the policy timeline for export controls. Coordinate with allies."
    )
    sections = ["## 7 Strategic Recommendations\n"]
    for sid, (_, label) in enumerate(stakeholders, 1):
        sections.append(f"### 7.{sid} {label}\n\n{common_body}\n")
    return "\n".join(sections)


def _sc(stakeholders: list[tuple[str, str]]):
    return {
        "title": "Strategic Recommendations",
        "stakeholders": [{"id": sid, "label": label, "content_directive": ""} for sid, label in stakeholders],
    }


def test_directive_compliant_article_passes_validator():
    """An article that follows the W6.b directive's non-overlap contract
    (disjoint per-stakeholder bodies) passes `_validate_stakeholder_overlap`
    with zero pairs above the 0.20 Jaccard threshold."""
    stakeholders = [
        ("S7.1", "For Investors"),
        ("S7.2", "For Policymakers"),
        ("S7.3", "For Industry"),
        ("S7.4", "For Researchers"),
    ]
    article = _disjoint_article(stakeholders)
    audit = validation._validate_stakeholder_overlap(article, _sc(stakeholders))
    assert audit is not None
    assert audit["n_stakeholders_audited"] == 4
    assert audit["overlap_pairs"] == [], (
        f"directive-compliant article should produce zero overlap_pairs; got: {audit['overlap_pairs']}"
    )
    assert audit["max_pair_overlap"] < 0.20, (
        f"directive-compliant article max overlap should be < 0.20; got: {audit['max_pair_overlap']}"
    )


def test_directive_violating_article_flagged_by_validator():
    """A counter-test: an article that VIOLATES the non-overlap rule
    (identical bodies across stakeholders) is flagged. Proves the
    validator is actually firing — otherwise the alignment test above
    would be trivially passing on a no-op validator."""
    stakeholders = [
        ("S7.1", "For Investors"),
        ("S7.2", "For Policymakers"),
        ("S7.3", "For Industry"),
    ]
    article = _overlapping_article(stakeholders)
    audit = validation._validate_stakeholder_overlap(article, _sc(stakeholders))
    assert audit is not None
    assert len(audit["overlap_pairs"]) >= 1, f"identical-body article must produce ≥1 flagged pair; got: {audit}"
    assert audit["max_pair_overlap"] > 0.20


def test_directive_compliant_3_stakeholders_passes():
    """3 stakeholders (the lower bound). Verify the alignment holds at
    the architect's 3-stakeholder minimum (per architect.py:213)."""
    stakeholders = [
        ("S7.1", "For Investors"),
        ("S7.2", "For Policymakers"),
        ("S7.3", "For Researchers"),
    ]
    article = _disjoint_article(stakeholders)
    audit = validation._validate_stakeholder_overlap(article, _sc(stakeholders))
    assert audit is not None
    assert audit["overlap_pairs"] == []


def test_directive_compliant_5_stakeholders_passes():
    """5 stakeholders (the upper bound). Alignment holds at the
    architect's 5-stakeholder maximum."""
    stakeholders = [
        ("S7.1", "For Investors"),
        ("S7.2", "For Policymakers"),
        ("S7.3", "For Industry"),
        ("S7.4", "For Researchers"),
        ("S7.5", "For Practitioners"),
    ]
    article = _disjoint_article(stakeholders)
    audit = validation._validate_stakeholder_overlap(article, _sc(stakeholders))
    assert audit is not None
    assert audit["overlap_pairs"] == []
    assert audit["n_stakeholders_audited"] == 5
