"""P3-W5.b (2026-05-27): _LIMITATIONS_RULE installation tests.

The `_LIMITATIONS_RULE` constant in writing_rules.py is the system-prompt
anchor for the 5-sub-section limitations chapter discipline. It must be:
  (a) Present as a string constant naming all 5 sub-section types.
  (b) Installed in `middle_block` so `writer_system()` includes it.
  (c) Reinforcing — not contradicting — the writer.py user-prompt
      `limitations_block` directive (the system-prompt summary + the
      user-prompt structured payload together form the contract).

Tests pin: constant presence, all 5 types named, middle_block install,
and ordering relative to peer P3 rules.
"""

from deep_research import writing_rules as wr


def test_limitations_rule_string_present():
    """`_LIMITATIONS_RULE` constant exists and is a non-empty string."""
    assert hasattr(wr, "_LIMITATIONS_RULE"), "_LIMITATIONS_RULE constant missing from writing_rules module"
    assert isinstance(wr._LIMITATIONS_RULE, str), f"_LIMITATIONS_RULE must be str; got {type(wr._LIMITATIONS_RULE)}"
    assert len(wr._LIMITATIONS_RULE) > 200, (
        f"_LIMITATIONS_RULE looks suspiciously short (only {len(wr._LIMITATIONS_RULE)} chars); "
        f"the 5-sub-section discipline + falsification quality bar should yield 800+ chars"
    )


def test_limitations_rule_names_all_5_subsection_types():
    """All 5 canonical sub-section types must be named in the rule so
    the writer LLM gets the verbatim list from the system prompt. This
    is the regression bar against a future refactor that drops one type
    (silently producing 4-sub-section limitations chapters)."""
    rule = wr._LIMITATIONS_RULE
    for t in ("Data granularity", "Scope cap", "Time validity", "Sampling", "Falsifiers"):
        assert t in rule, f"sub-section type `{t}` missing from _LIMITATIONS_RULE; got: {rule[:600]}"


def test_limitations_rule_names_falsification_quality_bar():
    """The 'every sentence must point to a concrete, checkable gap' /
    anti-boilerplate clause is the reference-grade signal — this is what
    distinguishes the chapter from Lunon's pre-W5 generic limitations
    paragraph. Pin the keywords."""
    rule = wr._LIMITATIONS_RULE
    # The rule must include some signal about specificity / forbidding
    # generic boilerplate.
    has_specific = "concrete" in rule.lower() or "specific" in rule.lower()
    has_forbidden = "forbid" in rule.lower() or "avoid" in rule.lower() or "boilerplate" in rule.lower()
    assert has_specific, f"_LIMITATIONS_RULE missing specificity signal; got: {rule[:800]}"
    assert has_forbidden, f"_LIMITATIONS_RULE missing anti-boilerplate signal; got: {rule[:800]}"


def test_limitations_rule_names_scenario_stress_test_for_predict():
    """The scenario stress-test sub-section is the predict-archetype
    feature; the rule must mention it conditionally so the writer LLM
    knows to emit the 6th sub-section when tier_ranking is present."""
    rule = wr._LIMITATIONS_RULE
    assert "scenario stress test" in rule.lower() or "stress test" in rule.lower(), (
        f"_LIMITATIONS_RULE missing scenario-stress-test signal for predict archetype; got: {rule[:1500]}"
    )
    # Should also reference the recompute target indirectly (tier_ranking).
    assert "tier" in rule.lower() or "rank" in rule.lower(), (
        f"_LIMITATIONS_RULE scenario block missing tier/ranking signal; got: {rule[:1500]}"
    )


def test_limitations_rule_installed_in_writer_system_for_predict():
    """The rule must be reachable through `writer_system()` so the
    writer LLM sees it in the system prompt. Calling writer_system
    for an archetype that has the limitations chapter (predict) must
    surface the rule somewhere in the assembled string."""
    sys_prompt = wr.writer_system(
        archetype="predict",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Limitations"],
    )
    assert "Limitations Chapter".upper() in sys_prompt.upper() or "LIMITATIONS CHAPTER STRUCTURE" in sys_prompt, (
        f"writer_system for predict archetype missing _LIMITATIONS_RULE; "
        f"writer LLM will not see the system-level structural contract. "
        f"Got prompt-head: {sys_prompt[:600]}..."
    )


def test_limitations_rule_installed_in_writer_system_for_trend():
    """The rule is included via middle_block for ALL archetypes — the
    architect-side gating decides whether the chapter is in the plan
    or not; the writer always carries the system-level rule so it's
    ready when the chapter IS present. (Pre-W5.b regression bar: a
    refactor that gated the rule by archetype in writer_system would
    create an asymmetry with the architect that limitations is
    archetype-gated — but only the architect makes that decision.)"""
    sys_prompt = wr.writer_system(
        archetype="trend",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body"],
    )
    # Rule should still be present (the architect decides if the chapter
    # is in the plan; the rule is a no-op when the chapter is null).
    assert "LIMITATIONS CHAPTER STRUCTURE" in sys_prompt, (
        f"writer_system unexpectedly omits _LIMITATIONS_RULE for trend archetype; "
        f"the rule must always be present so any future architect change that "
        f"emits limitations_chapter for trend tasks doesn't lose the system-level "
        f"directive. Got prompt-head: {sys_prompt[:600]}..."
    )


def test_limitations_rule_follows_mermaid_directive_in_middle_block():
    """Ordering invariant in `middle_block`: `_MERMAID_DIRECTIVE` comes
    before `_LIMITATIONS_RULE`. The two are independent so order doesn't
    affect semantics, but pinning the order keeps the system prompt
    structurally stable across PRs — a future refactor that moves rules
    out of band order would risk reshuffling the entire middle_block
    and confuse Greptile diffs."""
    sys_prompt = wr.writer_system(
        archetype="predict",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Limitations"],
    )
    mermaid_pos = sys_prompt.find("SEMANTIC DIAGRAM DIRECTIVE")
    lim_pos = sys_prompt.find("LIMITATIONS CHAPTER STRUCTURE")
    assert mermaid_pos >= 0 and lim_pos >= 0
    assert mermaid_pos < lim_pos, (
        f"_LIMITATIONS_RULE must follow _MERMAID_DIRECTIVE in middle_block "
        f"to maintain stable system-prompt ordering; got mermaid={mermaid_pos}, lim={lim_pos}"
    )
