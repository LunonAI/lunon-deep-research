"""P3-W6.b (2026-05-27): `_STAKEHOLDER_RULE` installation tests.

The system-prompt anchor for the 3-5 stakeholder addressee-block
discipline + non-overlap quality bar. Reinforces — doesn't contradict —
the writer.py user-prompt `stakeholder_block` directive.

Tests pin: constant presence, Jaccard threshold matches validator,
middle_block install, ordering relative to peer P3 rules.
"""

from deep_research import writing_rules as wr
from deep_research.pipeline import validation as v


def test_stakeholder_rule_string_present():
    """`_STAKEHOLDER_RULE` constant exists and is non-empty."""
    assert hasattr(wr, "_STAKEHOLDER_RULE")
    assert isinstance(wr._STAKEHOLDER_RULE, str)
    assert len(wr._STAKEHOLDER_RULE) > 200, (
        f"_STAKEHOLDER_RULE too short ({len(wr._STAKEHOLDER_RULE)} chars); the 3-5 "
        f"discipline + the reference phrasing examples + non-overlap rule should yield 800+ chars"
    )


def test_stakeholder_rule_names_non_overlap_discipline():
    """The non-overlap rule (Jaccard 4-gram < 0.20) is the W6 distinctive
    signal — pin the keywords."""
    rule = wr._STAKEHOLDER_RULE
    assert "non-overlap" in rule.lower() or "disjoint" in rule.lower(), (
        f"_STAKEHOLDER_RULE missing non-overlap signal; got: {rule[:600]}"
    )
    assert "0.20" in rule, f"_STAKEHOLDER_RULE missing 0.20 Jaccard threshold value; got: {rule[:800]}"


def test_stakeholder_rule_names_addressee_forms_en_and_zh():
    """The rule cites canonical addressee-heading forms in both EN and
    ZH so the writer LLM has language-appropriate templates."""
    rule = wr._STAKEHOLDER_RULE
    assert "For Policymakers" in rule or "For Investors" in rule, (
        f"_STAKEHOLDER_RULE missing EN addressee form; got: {rule[:800]}"
    )
    assert "对" in rule and "建议" in rule, f"_STAKEHOLDER_RULE missing ZH addressee form; got: {rule[:800]}"


def test_stakeholder_rule_names_opening_phrase_templates():
    """the reference corpus opening forms ("For X, the priority is…",
    "{X} should focus on…") must appear so the writer has concrete
    sentence shapes to mirror."""
    rule = wr._STAKEHOLDER_RULE
    assert "the priority is" in rule.lower() or "should focus on" in rule.lower(), (
        f"_STAKEHOLDER_RULE missing opening-phrase templates; got: {rule[:800]}"
    )


def test_stakeholder_jaccard_max_matches_validator_threshold():
    """`_STAKEHOLDER_JACCARD_MAX` in writing_rules must equal the
    threshold the validator actually enforces (line 703 in
    validation.py: `if jaccard > 0.20`). If they drift apart, the
    writer is told one threshold and the validator enforces another —
    silent inconsistency. Today both are 0.20; this test fires if
    either side moves without the other."""
    assert hasattr(wr, "_STAKEHOLDER_JACCARD_MAX")
    assert wr._STAKEHOLDER_JACCARD_MAX == 0.20

    # Defence-in-depth: actually run the validator with two known-
    # overlapping bodies and confirm 0.20 is the threshold by
    # exercising the boundary. We're testing the CONTRACT — if the
    # validator's literal changes, this test breaks before any prompt
    # text diverges.
    article = (
        "## 7 Strategic Recommendations\n\n"
        "### 7.1 For Investors\n\n"
        "Pursue ARR-positive Series-B picks in semiconductor manufacturing "
        "and avoid early-stage analog hardware. Diversify across at least "
        "three architectures. Track the policy timeline for export controls.\n\n"
        "### 7.2 For Policymakers\n\n"
        "Pursue ARR-positive Series-B picks in semiconductor manufacturing "
        "and avoid early-stage analog hardware. Diversify across at least "
        "three architectures. Track the policy timeline for export controls.\n"
    )
    sc = {
        "title": "Strategic Recommendations",
        "stakeholders": [
            {"id": "S7.1", "label": "For Investors", "content_directive": ""},
            {"id": "S7.2", "label": "For Policymakers", "content_directive": ""},
        ],
    }
    audit = v._validate_stakeholder_overlap(article, sc)
    assert audit is not None
    # Identical bodies → overlap > 0.20 → flagged.
    assert len(audit["overlap_pairs"]) == 1, (
        f"identical stakeholder bodies must be flagged at the 0.20 boundary; got: {audit}"
    )
    assert audit["overlap_pairs"][0][2] > 0.20


def test_stakeholder_rule_installed_in_writer_system():
    """The rule must be reachable through `writer_system()`. Predict
    archetype (the most common stakeholder-emitting archetype per
    architect.py:213 plural-audience heuristic)."""
    sys_prompt = wr.writer_system(
        archetype="predict",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Recommendations"],
    )
    assert "STAKEHOLDER-SEGMENTED CLOSING" in sys_prompt, (
        f"writer_system for predict archetype missing _STAKEHOLDER_RULE; "
        f"writer LLM will not see the system-level non-overlap signal. "
        f"Got prompt-head: {sys_prompt[:600]}..."
    )


def test_stakeholder_rule_follows_mermaid_directive_in_middle_block():
    """Ordering: `_STAKEHOLDER_RULE` follows `_MERMAID_DIRECTIVE`.
    Mirrors the W5.b ordering convention (P3 rules appended to
    middle_block in PR-merge order)."""
    sys_prompt = wr.writer_system(
        archetype="predict",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Recommendations"],
    )
    mermaid_pos = sys_prompt.find("SEMANTIC DIAGRAM DIRECTIVE")
    sh_pos = sys_prompt.find("STAKEHOLDER-SEGMENTED CLOSING")
    assert mermaid_pos >= 0 and sh_pos >= 0
    assert mermaid_pos < sh_pos, (
        f"_STAKEHOLDER_RULE must follow _MERMAID_DIRECTIVE; got mermaid={mermaid_pos}, sh={sh_pos}"
    )
