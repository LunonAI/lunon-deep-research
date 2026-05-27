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
    """The sensitivity sub-section is the chapter's distinctive the reference
    pattern — pin the heading-anchor + ±Npp protocol-neutral form.

    Greptile PR #47 round-6: the rule previously hardcoded `±10pp`,
    contradicting the user-prompt block whenever the plan specified a
    non-default perturbation (e.g. `perturbation_pp=5`). The system
    rule now uses `±Npp` (matching the heading-anchor hint on the same
    line); the exact N is interpolated by the user-prompt directive.
    Pin both `sensitivity` lowercase substring AND the `±Npp`
    placeholder, plus a NEGATIVE assertion that the hardcoded `±10pp`
    is NOT in the system rule (the user-prompt block has the real
    value).
    """
    rule = wr._TIER_RANKING_RULE
    assert "sensitivity" in rule.lower()
    assert "±Npp" in rule, f"rule must use protocol-neutral ±Npp; got: {rule[:1500]}"
    # The literal ±10pp must not leak back as a hardcoded contradiction
    # against a non-default `perturbation_pp` interpolation.
    assert "±10pp" not in rule, (
        f"rule must not hardcode ±10pp — the user-prompt block interpolates "
        f"the actual perturbation value, so a literal here creates two "
        f"conflicting instructions in the same LLM call. Got: {rule[:1500]}"
    )


def test_tier_ranking_rule_names_computational_not_narrative():
    """The COMPUTATIONAL-vs-narrative rule prevents the Lunon-specific
    failure mode of producing a prose-only sensitivity section."""
    rule = wr._TIER_RANKING_RULE
    assert "COMPUTATIONAL" in rule or "computational" in rule.lower()


def test_tier_ranking_rule_installed_in_writer_system_for_compare():
    """The rule must be reachable through `writer_system()` for compare
    archetype (one of the two emitting archetypes per architect schema)
    when the `has_tier_ranking` gate fires."""
    sys_prompt = wr.writer_system(
        archetype="compare",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Tier Ranking"],
        has_tier_ranking=True,
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
        has_tier_ranking=True,
    )
    assert "TIER RANKING + SENSITIVITY CHECK" in sys_prompt


def test_tier_ranking_rule_follows_mermaid_directive():
    """Ordering: rule appears after _MERMAID_DIRECTIVE in middle_block."""
    sys_prompt = wr.writer_system(
        archetype="compare",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Tier Ranking"],
        has_tier_ranking=True,
    )
    mermaid_pos = sys_prompt.find("SEMANTIC DIAGRAM DIRECTIVE")
    tr_pos = sys_prompt.find("TIER RANKING + SENSITIVITY CHECK")
    assert mermaid_pos >= 0 and tr_pos >= 0
    assert mermaid_pos < tr_pos


# ---------- Conditional gating on `has_tier_ranking` (PR #47 round-5 preempt) ----------


def test_tier_ranking_rule_installed_when_has_tier_ranking_true():
    """Explicit positive case for the gate: passing `has_tier_ranking=True`
    must include `_TIER_RANKING_RULE` in the system prompt. Mirrors the
    `has_stakeholder_chapter` / `has_limitations_chapter` precedent.
    """
    sys_prompt = wr.writer_system(
        archetype="compare",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Tier Ranking"],
        has_tier_ranking=True,
    )
    assert "TIER RANKING + SENSITIVITY CHECK" in sys_prompt, (
        f"writer_system with has_tier_ranking=True missing _TIER_RANKING_RULE; got prompt-head: {sys_prompt[:600]}"
    )


def test_tier_ranking_rule_absent_when_has_tier_ranking_false():
    """Explicit negative case: passing `has_tier_ranking=False` must
    NOT include the ~700-char rule. For the (majority of) tasks where
    the architect didn't populate `tier_ranking` (non-compare/predict,
    or compare/predict with <5 entities / <4 dimensions), the rule is
    pure prompt noise and burns context for no signal.
    """
    sys_prompt = wr.writer_system(
        archetype="compare",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body"],
        has_tier_ranking=False,
    )
    assert "TIER RANKING + SENSITIVITY CHECK" not in sys_prompt, (
        f"writer_system with has_tier_ranking=False unexpectedly included "
        f"_TIER_RANKING_RULE; got prompt-head: {sys_prompt[:600]}"
    )


def test_tier_ranking_rule_absent_when_has_tier_ranking_default():
    """Back-compat: a caller that doesn't thread the flag at all must
    also NOT receive the rule (default value is False). Pin the
    default behavior so a future signature change can't silently
    flip it.
    """
    sys_prompt = wr.writer_system(
        archetype="compare",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body"],
    )
    assert "TIER RANKING + SENSITIVITY CHECK" not in sys_prompt
