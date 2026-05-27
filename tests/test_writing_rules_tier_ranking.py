"""P3-W7.b (2026-05-27): `_TIER_RANKING_RULE` installation tests."""

from deep_research import writing_rules as wr


def test_tier_ranking_rule_string_present():
    """Constant exists and is non-empty."""
    assert hasattr(wr, "_TIER_RANKING_RULE")
    assert isinstance(wr._TIER_RANKING_RULE, str)
    assert len(wr._TIER_RANKING_RULE) > 300, f"_TIER_RANKING_RULE too short ({len(wr._TIER_RANKING_RULE)} chars)"


def test_tier_ranking_rule_names_scoring_formula():
    """The rule must show the canonical scoring formula form so the
    writer has a template to mirror."""
    rule = wr._TIER_RANKING_RULE
    assert "S_final" in rule, f"rule missing S_final formula; got: {rule[:600]}"


def test_tier_ranking_rule_names_2_decimal_precision():
    """The 2-decimal precision rule is the most-mistakable signal."""
    rule = wr._TIER_RANKING_RULE
    assert "2 DECIMAL PLACES" in rule or "2 decimal" in rule.lower()
    # Should include both forbidden forms (1-decimal AND 3-decimal)
    assert "7.5" in rule, f"rule should give 1-decimal counter-example; got: {rule[:1500]}"
    assert "7.452" in rule, f"rule should give 3-decimal counter-example; got: {rule[:1500]}"


def test_tier_ranking_rule_names_sensitivity_check():
    """The sensitivity sub-section is the chapter's distinctive Qianfan
    pattern — pin the ±10pp signal."""
    rule = wr._TIER_RANKING_RULE
    assert "sensitivity" in rule.lower()
    assert "±10pp" in rule or "±10 pp" in rule or "10pp" in rule


def test_tier_ranking_rule_names_computational_not_narrative():
    """The COMPUTATIONAL-vs-narrative rule prevents the Lunon-specific
    failure mode of producing a prose-only sensitivity section."""
    rule = wr._TIER_RANKING_RULE
    assert "COMPUTATIONAL" in rule or "computational" in rule.lower()


def test_tier_ranking_rule_installed_in_writer_system_for_compare():
    """The rule must be reachable through `writer_system()` for compare
    archetype (one of the two emitting archetypes per architect schema)."""
    sys_prompt = wr.writer_system(
        archetype="compare",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Tier Ranking"],
    )
    assert "TIER RANKING + SENSITIVITY CHECK" in sys_prompt, (
        f"writer_system for compare missing _TIER_RANKING_RULE; got prompt-head: {sys_prompt[:600]}..."
    )


def test_tier_ranking_rule_installed_in_writer_system_for_predict():
    """Predict is the second emitting archetype."""
    sys_prompt = wr.writer_system(
        archetype="predict",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Tier Ranking"],
    )
    assert "TIER RANKING + SENSITIVITY CHECK" in sys_prompt


def test_tier_ranking_rule_follows_mermaid_directive():
    """Ordering: rule appears after _MERMAID_DIRECTIVE in middle_block."""
    sys_prompt = wr.writer_system(
        archetype="compare",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Tier Ranking"],
    )
    mermaid_pos = sys_prompt.find("SEMANTIC DIAGRAM DIRECTIVE")
    tr_pos = sys_prompt.find("TIER RANKING + SENSITIVITY CHECK")
    assert mermaid_pos >= 0 and tr_pos >= 0
    assert mermaid_pos < tr_pos
