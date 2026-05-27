"""Wave 2 §3.2 (2026-05-26): per-archetype distributional coverage for
the four `_INSIGHT_MIN` elements.

Pre-Wave-2 the rule said "every leaf must close with AT LEAST ONE of
(a)-(d)". The 2026-05-26 id=91 smoke showed this enabled path-of-least-
resistance failure: writer over-fired EASY elements (contrarian 1.77×
over, quant 2.44× over) and under-fired the HARD one (forward-looking
0.14× short — 7× below Qianfan's per-1000-word density).

Wave 2 §3.2 changes the rule to require DISTRIBUTIONAL coverage across
the section's leaves (≥X% per element) and adds per-archetype bias:
  - predict / trend / recommend: ≥50% forward-looking (the archetype's mission)
  - list-all / compare: ≥30% named-alternative (the archetype's structure)
  - explain-mechanism: balanced 30/20/20/20 default

Distribution targets are surfaced via `insight_distribution(archetype)`
+ mirrored to the writer.write_section user prompt as an explicit
percentage block the writer can self-check against.
"""

from deep_research.writing_rules import (
    _INSIGHT_DISTRIBUTION_BY_ARCHETYPE,
    _INSIGHT_DISTRIBUTION_DEFAULT,
    _INSIGHT_MIN,
    insight_distribution,
)


def test_insight_min_rule_describes_distributional_coverage():
    """The system-prompt rule must explicitly say DISTRIBUTIONAL COVERAGE
    so the writer knows the rule shape (not 'pick ONE of (a)-(d)').

    Greptile PR #30 round-2 follow-up: previously this test asserted
    hardcoded `≥30%` / `≥20%` percentages, but those values lived in
    BOTH the system prompt (this constant) AND the user prompt (via
    `_insight_distribution_block`), creating a stale source of truth
    that contradicted per-archetype calibration. The numbers now live
    EXCLUSIVELY in the user prompt; the system prompt explains the
    coverage CONCEPT + per-archetype bias LOGIC and defers to the
    user prompt for exact percentages."""
    assert "DISTRIBUTIONAL COVERAGE" in _INSIGHT_MIN, _INSIGHT_MIN[:500]
    # The TARGET DISTRIBUTION block must explicitly defer to the
    # user-prompt block for exact percentages (no more hardcoded floors).
    assert "INSIGHT DISTRIBUTION FOR THIS SECTION" in _INSIGHT_MIN
    # The four elements must still be enumerated (their definitions
    # haven't moved — only the percentage targets did).
    for element in (
        "FORWARD-LOOKING IMPLICATION",
        "NAMED CONTRARIAN FRAMING",
        "QUANTIFIED PROJECTION OR CONFIDENCE RANGE",
        "NAMED-ALTERNATIVE COMPARISON",
    ):
        assert element in _INSIGHT_MIN, f"missing element: {element}"


def test_insight_min_rule_documents_per_archetype_bias():
    """The rule must describe the per-archetype bias so a reader of the
    system prompt understands why the distribution targets differ across
    archetypes (predict/trend bias forward-looking; list-all/compare
    bias alternative)."""
    assert "PER-ARCHETYPE BIAS" in _INSIGHT_MIN
    assert "predict" in _INSIGHT_MIN.lower()
    assert "list-all" in _INSIGHT_MIN.lower() or "compare" in _INSIGHT_MIN.lower()


def test_insight_distribution_default_keys_complete():
    """The default distribution dict must carry all SIX element keys
    so callers (writer-prompt mirror + compliance scorer) can always
    look up every element without KeyError fallback noise.

    Wave 3 PR 2: extended from 4 keys to 6 (added causal_chain_min +
    problem_tradeoff_min) to cover RACE Insight criteria 2 + 3."""
    expected_keys = {
        "forward_looking_min",
        "contrarian_min",
        "quant_min",
        "alternative_min",
        "causal_chain_min",
        "problem_tradeoff_min",
    }
    assert set(_INSIGHT_DISTRIBUTION_DEFAULT.keys()) == expected_keys


def test_insight_distribution_for_predict_biases_forward_looking_up():
    """predict is forward-by-mission. Wave 3 PR-0 fresh-corpus
    recalibration (id=3 observed 76%) raised the target from 45 to 70.
    recommend was over-targeting in Wave 2 (40 vs observed 30) and was
    walked back to 25. trend stayed close (Wave 2 had 45; Wave 3 set
    35 per observed 40). The test enforces predict's UP move; the
    weaker forward-targets for trend/recommend are pinned in their
    own per-archetype tests."""
    d_predict = insight_distribution("predict")
    assert d_predict["forward_looking_min"] >= 60, (
        f"predict: forward_looking_min should be ≥60% (Wave 3 PR-0 calibration target ≥70); got {d_predict['forward_looking_min']}"
    )


def test_insight_distribution_for_list_all_biases_alternative_up():
    """list-all / compare are entity-enumerated archetypes — most
    leaves are inherently comparisons across the matrix. Wave 3 PR-0
    fresh-corpus recalibration: list-all observed alt 76% (target
    raised to 60), compare observed alt 22% (target DROPPED from 47
    to 15 — was way over-targeting). The test pins list-all's
    high-alternative bias; compare's lower bias is pinned in its own
    per-archetype test."""
    d = insight_distribution("list-all")
    assert d["alternative_min"] >= 55, (
        f"list-all: alternative_min should be ≥55% (Q observed 76); got {d['alternative_min']}"
    )
    assert d["forward_looking_min"] >= 45, (
        f"list-all: forward_looking_min should be ≥45% (Q observed 62); got {d['forward_looking_min']}"
    )


def test_insight_distribution_for_explain_mechanism_corpus_calibrated():
    """explain-mechanism uses Wave 3 PR-0 fresh-corpus targets:
    fwd 15 / contr 3 / quant 3 / alt 25. Derived from 4-task Qianfan
    mean (19 / 4 / 6 / 32). Notably LOW on contrarian/quant — Qianfan
    explains with alternatives, not contrarian framing or heavy
    quantification.

    Greptile PR #34 round-1 follow-up: causal_chain target lowered
    from 25 → 3 after tightening the detector to require ≥2 chain
    markers per leaf (the prior broad detector inflated Qianfan rates
    by counting bare 'enables/produces/due to/subsequently' as chain
    hits). Under the strict detector, Qianfan explain-mech rate is
    4% mean — target set to 3 as a measurable floor."""
    d = insight_distribution("explain-mechanism")
    # Alternative remains the dominant of the original 4 for explain-mech.
    assert d["alternative_min"] >= 20, (
        f"alt_min should be ≥20% (Wave 3 calibration target 25); got {d['alternative_min']}"
    )
    # Contrarian/quant remain minimal.
    assert d["contrarian_min"] <= 15
    assert d["quant_min"] <= 10
    # Wave 3 PR 2 (Greptile PR #34 round-1): causal_chain is the central
    # RACE 2 element for this archetype, but the strict detector
    # threshold is low (Q observed 4% mean under the tightened regex).
    # Floor set to 3 so a writer producing any genuine multi-link
    # chains clears it.
    assert 1 <= d["causal_chain_min"] <= 10, (
        f"causal_chain_min should be 1-10% for explain-mechanism under strict detector (target 3); got {d['causal_chain_min']}"
    )


def test_insight_distribution_for_predict_has_nonzero_causal_chain_target():
    """Wave 3 PR 2: predict was originally targeted at 45% causal_chain
    (Q broad-detector rate 57%). Greptile PR #34 round-1 follow-up:
    after tightening to require ≥2 chain markers, Q strict-rate dropped
    to 3% on id=3. Target lowered to 2 — a measurable floor that
    surfaces a deficit if Lunon's predict articles construct zero
    chains, but doesn't impose an impossible bar."""
    d = insight_distribution("predict")
    assert 1 <= d["causal_chain_min"] <= 10, (
        f"predict: causal_chain_min should be 1-10% under strict detector; got {d['causal_chain_min']}"
    )


def test_insight_distribution_for_compare_was_recalibrated_down_on_alternative():
    """Wave 3 PR-0 fresh-corpus calibration corrected a major Wave 2
    miscalibration: compare's alternative_min was 47 (extrapolated
    from list-all) but Qianfan compare observed only 22%. Target
    walked back to 15 to avoid forcing Lunon to over-fire on the
    alternative element."""
    d = insight_distribution("compare")
    assert d["alternative_min"] <= 25, (
        f"compare: alternative_min should be ≤25% post-Wave-3 (Q observed 22; was over-targeted at 47 in Wave 2); got {d['alternative_min']}"
    )


def test_insight_distribution_for_recommend_biases_alternative_up():
    """Wave 3 PR 2 calibration: recommend is the only archetype where
    Qianfan systematically compares options across explicit alternatives
    (observed 48%). Target raised from Wave 2's 15 to 40."""
    d = insight_distribution("recommend")
    assert d["alternative_min"] >= 35, (
        f"recommend: alternative_min should be ≥35% (Wave 3 target 40); got {d['alternative_min']}"
    )


def test_insight_distribution_unknown_archetype_falls_back_to_default():
    """Unknown archetype → default balanced distribution. No KeyError."""
    d = insight_distribution("some-future-archetype")
    assert d == _INSIGHT_DISTRIBUTION_DEFAULT
    d2 = insight_distribution(None)
    assert d2 == _INSIGHT_DISTRIBUTION_DEFAULT


def test_insight_distribution_returns_fresh_copy_for_known_archetype():
    """Greptile PR #30 follow-up: caller mutation of the returned dict
    must NOT corrupt the module-level `_INSIGHT_DISTRIBUTION_BY_ARCHETYPE`
    constant. Pre-fix the known-archetype path returned the actual stored
    dict object (mutable reference) — a caller doing
    `d = insight_distribution('predict'); d['forward_looking_min'] = 99`
    would silently corrupt the default for every subsequent call."""
    # Snapshot the pre-call canonical value.
    original = dict(_INSIGHT_DISTRIBUTION_BY_ARCHETYPE["predict"])
    d = insight_distribution("predict")
    # Mutate the returned dict.
    d["forward_looking_min"] = 999
    # The module-level constant must be UNTOUCHED.
    assert _INSIGHT_DISTRIBUTION_BY_ARCHETYPE["predict"] == original, (
        "insight_distribution returned a mutable reference — caller mutation "
        "corrupted the module-level constant. Wrap return in dict(...)."
    )
    # And subsequent calls must return the original (uncorrupted) value.
    d2 = insight_distribution("predict")
    assert d2["forward_looking_min"] == original["forward_looking_min"]


def test_insight_distribution_returns_fresh_copy_for_unknown_archetype():
    """Symmetric guard: unknown-archetype path must also return a fresh
    copy (this was the pre-fix behaviour but pinning so the
    `dict(...)` wrapper isn't accidentally removed in a refactor)."""
    original = dict(_INSIGHT_DISTRIBUTION_DEFAULT)
    d = insight_distribution("unknown-archetype")
    d["forward_looking_min"] = 999
    # The module-level default must be UNTOUCHED.
    assert _INSIGHT_DISTRIBUTION_DEFAULT == original


def test_insight_min_system_prompt_carries_no_hardcoded_percentages():
    """Greptile PR #30 round-2 follow-up: `_INSIGHT_MIN` (system prompt)
    must NOT carry hardcoded distribution percentages that contradict
    the per-archetype calibrated values in `_INSIGHT_DISTRIBUTION_BY_
    ARCHETYPE`. Pre-fix the system prompt said 'AIM ≥30% / ≥20% / ≥20%
    / ≥20%' as a uniform floor, while the user prompt (via
    `_insight_distribution_block`) interpolated per-archetype values
    that for list-all gave ≥10% contrarian and for explain-mechanism
    gave ≥1% quant. A writer would anchor on the higher system-prompt
    floor and over-fire the elements §3.2 was meant to suppress.

    Fix: the system prompt now defers explicitly to the user-prompt
    block for exact percentages, and only the LOGIC (which archetype
    biases which element up/down) is documented in the system prompt.
    Pin the no-hardcoded-percentages invariant so a future refactor
    can't accidentally re-introduce the duplicated source of truth."""
    from deep_research.writing_rules import _INSIGHT_MIN

    # The system prompt must NOT carry the old uniform-floor numbers
    # that contradicted the per-archetype calibration.
    assert "AIM ≥30%" not in _INSIGHT_MIN, "stale '≥30%' hardcoded floor — should defer to user prompt"
    assert "AIM ≥20%" not in _INSIGHT_MIN, "stale '≥20%' hardcoded floor — should defer to user prompt"
    # The system prompt must NOT carry the old per-archetype-specific
    # numbers either (they're in the user-prompt block now).
    assert "bias the (a) share UP to ≥50%" not in _INSIGHT_MIN
    assert "bias (d) UP to ≥30%" not in _INSIGHT_MIN
    assert "balanced 30/20/20/20" not in _INSIGHT_MIN
    # And the system prompt MUST point the writer to the user-prompt
    # block as the source of truth for exact targets.
    assert "INSIGHT DISTRIBUTION FOR THIS SECTION" in _INSIGHT_MIN
    assert "DEFER TO THAT BLOCK" in _INSIGHT_MIN or "single source of truth" in _INSIGHT_MIN
    # The LOGIC (WHY targets differ per archetype) MUST still be present
    # so the writer understands the rationale, just without specific
    # numbers.
    assert "PER-ARCHETYPE BIAS LOGIC" in _INSIGHT_MIN
    # All three bias narratives present so the writer understands the
    # archetype-shape mapping conceptually.
    assert "forward-looking-by-mission" in _INSIGHT_MIN
    assert "entity-enumerated" in _INSIGHT_MIN


def test_insight_distribution_writer_prompt_mirrors_targets():
    """The writer.write_section user prompt must include the per-
    archetype distribution targets so the writer sees the numbers
    upfront (where its attention lands, not just in the system prompt).

    Wave 3 PR 2: writer block now lists all SIX elements (added
    causal_chain + problem_tradeoff). Targets updated per PR-0 fresh-
    corpus recalibration (predict's forward target jumped 45 → 70).
    Greptile PR #34 round-1 follow-up: causal_chain targets lowered
    across all archetypes after the detector was tightened to require
    ≥2 chain markers per leaf."""
    from deep_research.pipeline.writer import _insight_distribution_block

    # predict archetype: Wave 3 calibration set forward_looking_min=70
    # (Q observed 76% on id=3). causal_chain_min was 45 in the original
    # Wave 3 PR 2; Greptile follow-up dropped it to 2 after the strict
    # detector showed Q at 3%.
    block = _insight_distribution_block("predict")
    assert "INSIGHT DISTRIBUTION" in block
    assert "≥70%" in block, "predict's recalibrated forward_looking target should appear"
    # list-all archetype: Wave 3 set alternative_min=60 (Q observed 76%).
    block_la = _insight_distribution_block("list-all")
    assert "INSIGHT DISTRIBUTION" in block_la
    assert "≥60%" in block_la, "list-all's recalibrated alternative target should appear"
    # The 6-element naming must include the 2 new elements verbatim so
    # the writer sees what (e) and (f) are.
    assert "(e) CAUSAL CHAIN" in block
    assert "(f) PROBLEM-TRADEOFF" in block
    # Per-element percentage strings must appear for ALL six elements
    # on this archetype (predict targets fwd 70 / contr 5 / quant 25 /
    # alt 35 / causal 2 / problem 5).
    for pct in ("≥70%", "≥5%", "≥25%", "≥35%", "≥2%"):
        assert pct in block, f"predict: missing target string {pct!r}"
    # The compliance scorer reference must be there so the writer
    # knows the targets are MEASURED downstream.
    assert "p2_writer_compliance.py" in block
    assert "drift" in block.lower() or "scorer" in block.lower()


def test_insight_distribution_archetype_table_covers_all_known_archetypes():
    """Pin the set of archetypes that have per-archetype overrides so
    a future archetype-list change doesn't silently drop an override.
    Unknown archetypes fall through to default, which is fine — but a
    KNOWN archetype losing its tuned distribution is a regression."""
    expected_overrides = {
        "predict",
        "trend",
        "recommend",
        "list-all",
        "compare",
        "explain-mechanism",
    }
    assert set(_INSIGHT_DISTRIBUTION_BY_ARCHETYPE.keys()) == expected_overrides
