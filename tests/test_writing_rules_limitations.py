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
    assert len(wr._LIMITATIONS_RULE) > 800, (
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
    anti-boilerplate clause is the Qianfan-grade signal — this is what
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


def test_limitations_rule_installed_when_has_limitations_chapter_true():
    """Greptile PR #45 round-6 issue #2 (2026-05-27): the rule is
    gated on `has_limitations_chapter`. When the caller signals the
    plan carries the chapter (predict / compare / explain-mechanism /
    list-all), the rule must appear in the assembled system prompt."""
    sys_prompt = wr.writer_system(
        archetype="predict",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Limitations"],
        has_limitations_chapter=True,
    )
    assert "LIMITATIONS CHAPTER STRUCTURE" in sys_prompt, (
        f"writer_system with has_limitations_chapter=True missing _LIMITATIONS_RULE; "
        f"writer LLM will not see the system-level structural contract. "
        f"Got prompt-head: {sys_prompt[:600]}..."
    )


def test_limitations_rule_omitted_when_has_limitations_chapter_false():
    """Greptile PR #45 round-6 issue #2 (2026-05-27): when the caller
    signals the plan has NO limitations chapter (trend / recommend),
    the ~1300-char rule is pure prompt noise and must be omitted.
    Mirrors the `_STAKEHOLDER_RULE` gating precedent at
    `has_stakeholder_chapter`."""
    sys_prompt = wr.writer_system(
        archetype="trend",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body"],
        has_limitations_chapter=False,
    )
    assert "LIMITATIONS CHAPTER STRUCTURE" not in sys_prompt, (
        f"writer_system with has_limitations_chapter=False unexpectedly included "
        f"_LIMITATIONS_RULE; the rule should be gated like _STAKEHOLDER_RULE to "
        f"keep the system prompt lean on non-limitations archetypes. "
        f"Got prompt-head: {sys_prompt[:600]}..."
    )


def test_limitations_rule_defaults_omitted_when_flag_not_passed():
    """Back-compat: a caller that doesn't thread `has_limitations_chapter`
    gets the default `False`, which omits the rule. Mirrors the
    `has_stakeholder_chapter` default-False behaviour. The textual
    self-guard inside the rule ("required for predict / compare /
    explain-mechanism / list-all archetypes when `limitations_chapter`
    is in the plan") would still kick in if a future caller forgot
    the flag, preventing silent breakage."""
    sys_prompt = wr.writer_system(
        archetype="predict",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Limitations"],
    )
    assert "LIMITATIONS CHAPTER STRUCTURE" not in sys_prompt, (
        f"writer_system without explicit has_limitations_chapter flag should default "
        f"to omitting the rule. Got prompt-head: {sys_prompt[:600]}..."
    )


def test_limitations_rule_follows_mermaid_directive_in_middle_block():
    """Ordering invariant in `middle_block`: `_MERMAID_DIRECTIVE` comes
    before `_LIMITATIONS_RULE`. The two are independent so order doesn't
    affect semantics, but pinning the order keeps the system prompt
    structurally stable across PRs — a future refactor that moves rules
    out of band order would risk reshuffling the entire middle_block
    and confuse Greptile diffs. The assertion only fires when the rule
    is actually present (gated on `has_limitations_chapter=True`)."""
    sys_prompt = wr.writer_system(
        archetype="predict",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Limitations"],
        has_limitations_chapter=True,
    )
    mermaid_pos = sys_prompt.find("SEMANTIC DIAGRAM DIRECTIVE")
    lim_pos = sys_prompt.find("LIMITATIONS CHAPTER STRUCTURE")
    assert mermaid_pos >= 0 and lim_pos >= 0
    assert mermaid_pos < lim_pos, (
        f"_LIMITATIONS_RULE must follow _MERMAID_DIRECTIVE in middle_block "
        f"to maintain stable system-prompt ordering; got mermaid={mermaid_pos}, lim={lim_pos}"
    )
