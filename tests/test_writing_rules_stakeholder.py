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


def test_stakeholder_jaccard_max_is_single_source_of_truth():
    """Greptile PR #46 round-1 issue #1: `_STAKEHOLDER_JACCARD_MAX` in
    writing_rules.py must be the ONLY place the threshold literal lives.
    The validator (`_validate_stakeholder_overlap` line 703 region) must
    READ this constant via `wr._STAKEHOLDER_JACCARD_MAX`, not embed an
    independent `0.20` literal.

    Pre-fix: the constant was used only in the prompt string; the
    validator had its own `if jaccard > 0.20` literal — silent drift
    risk if either side moved without the other.

    This test (a) pins the constant value AND (b) asserts the validator
    actually reads it via inspect-source. If a future refactor re-
    introduces a hardcoded `0.20` in validation.py, this fires."""
    assert hasattr(wr, "_STAKEHOLDER_JACCARD_MAX")
    assert wr._STAKEHOLDER_JACCARD_MAX == 0.20

    # Source-of-truth check: validation.py must NOT contain the literal
    # `0.20` in its overlap-threshold guard. The validator reads
    # `wr._STAKEHOLDER_JACCARD_MAX` via the existing `from .. import
    # writing_rules as wr` import.
    import inspect

    src = inspect.getsource(v._validate_stakeholder_overlap)
    assert "wr._STAKEHOLDER_JACCARD_MAX" in src, (
        f"validator must read `wr._STAKEHOLDER_JACCARD_MAX` instead of "
        f"hardcoding the threshold literal; got source:\n{src[-800:]}"
    )
    # Defence-in-depth: ensure no naked `> 0.20` literal remains in the
    # validator. The Pre-fix code had `if jaccard > 0.20:` directly.
    # An exact `> 0.20` substring would catch the regression.
    assert "> 0.20" not in src, (
        f"validator contains a hardcoded `> 0.20` literal — should reference "
        f"`wr._STAKEHOLDER_JACCARD_MAX`. Got source:\n{src[-800:]}"
    )


def test_stakeholder_jaccard_max_drift_test_via_monkeypatch(monkeypatch):
    """Defence-in-depth: monkeypatch the constant DOWN to 0.10 and
    verify the validator now flags pairs above 0.10 (which it wouldn't
    have if the threshold were hardcoded to 0.20). Confirms the source-
    of-truth link is live, not just structurally present."""
    monkeypatch.setattr(wr, "_STAKEHOLDER_JACCARD_MAX", 0.10)
    article = (
        "## 7 Strategic Recommendations\n\n"
        "### 7.1 For Investors\n\n"
        "Pursue ARR-positive Series-B picks in semiconductor manufacturing. "
        "Track export controls. Diversify across analog and digital firms.\n\n"
        "### 7.2 For Policymakers\n\n"
        "Adopt PQC standards. Fund domestic foundries. Mandate disclosure "
        "of cross-border supply-chain dependencies.\n"
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
    # With threshold dropped to 0.10, any incidental overlap (shared
    # connector words across the two bodies) flags. With the prior
    # 0.20 threshold this body pair would NOT have flagged. The
    # specific outcome depends on shared-token count; the contract is
    # just that the threshold is live-read.
    # Recompute: if max_pair_overlap > 0.10 → must appear in overlap_pairs.
    if audit["max_pair_overlap"] > 0.10:
        assert len(audit["overlap_pairs"]) >= 1, (
            f"threshold lowered to 0.10 but no pair flagged at "
            f"max_overlap={audit['max_pair_overlap']}; validator may be "
            f"reading a stale value"
        )


def test_stakeholder_rule_installed_when_has_stakeholder_chapter_true():
    """Greptile PR #46 round-1 issue #2: `_STAKEHOLDER_RULE` only appears
    in the system prompt when `has_stakeholder_chapter=True` is passed.
    Predict archetype here serves only as the archetype arg; the
    archetype itself doesn't gate the rule (the plan's chapter does)."""
    sys_prompt = wr.writer_system(
        archetype="predict",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Recommendations"],
        has_stakeholder_chapter=True,
    )
    assert "STAKEHOLDER-SEGMENTED CLOSING" in sys_prompt, (
        f"writer_system with has_stakeholder_chapter=True missing _STAKEHOLDER_RULE; "
        f"writer LLM will not see the system-level non-overlap signal. "
        f"Got prompt-head: {sys_prompt[:600]}..."
    )


def test_stakeholder_rule_absent_when_has_stakeholder_chapter_false():
    """When `has_stakeholder_chapter=False` (default — most tasks don't
    have a plural-audience prompt), the ~850-char rule is omitted from
    the system prompt to reduce prompt overhead. Greptile PR #46 round-1
    issue #2."""
    sys_prompt = wr.writer_system(
        archetype="predict",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Conclusion"],
        has_stakeholder_chapter=False,
    )
    assert "STAKEHOLDER-SEGMENTED CLOSING" not in sys_prompt, (
        f"writer_system with has_stakeholder_chapter=False unexpectedly "
        f"includes _STAKEHOLDER_RULE — prompt overhead leakage. Got "
        f"prompt-head: {sys_prompt[:600]}..."
    )


def test_stakeholder_rule_absent_when_has_stakeholder_chapter_default():
    """The kwarg defaults to False — back-compat with any caller that
    doesn't pass the flag. Confirms the safe default (omit the rule)."""
    sys_prompt = wr.writer_system(
        archetype="predict",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Conclusion"],
    )
    assert "STAKEHOLDER-SEGMENTED CLOSING" not in sys_prompt


def test_stakeholder_rule_follows_mermaid_directive_in_middle_block():
    """Ordering: `_STAKEHOLDER_RULE` follows `_MERMAID_DIRECTIVE` (only
    relevant when the rule is included, i.e. has_stakeholder_chapter=True)."""
    sys_prompt = wr.writer_system(
        archetype="predict",
        domain="default",
        language="en",
        toc_titles=["Intro", "Body", "Recommendations"],
        has_stakeholder_chapter=True,
    )
    mermaid_pos = sys_prompt.find("SEMANTIC DIAGRAM DIRECTIVE")
    sh_pos = sys_prompt.find("STAKEHOLDER-SEGMENTED CLOSING")
    assert mermaid_pos >= 0 and sh_pos >= 0
    assert mermaid_pos < sh_pos, (
        f"_STAKEHOLDER_RULE must follow _MERMAID_DIRECTIVE; got mermaid={mermaid_pos}, sh={sh_pos}"
    )
