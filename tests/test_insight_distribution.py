"""Wave 2 §3.2 (2026-05-26): per-archetype distributional coverage for
the four `_INSIGHT_MIN` elements.

Pre-Wave-2 the rule said "every leaf must close with AT LEAST ONE of
(a)-(d)". The 2026-05-26 id=91 smoke showed this enabled path-of-least-
resistance failure: writer over-fired EASY elements (contrarian 1.77×
over, quant 2.44× over) and under-fired the HARD one (forward-looking
0.14× short — 7× below the reference's per-1000-word density).

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
    + spell out the percentage targets per element. Pre-Wave-2 it said
    'pick ONE of (a)-(d)' which let the writer choose the easy element
    on every leaf."""
    assert "DISTRIBUTIONAL COVERAGE" in _INSIGHT_MIN, _INSIGHT_MIN[:500]
    # All four target percentages must appear in the rule.
    assert "≥30%" in _INSIGHT_MIN  # forward-looking default
    assert "≥20%" in _INSIGHT_MIN  # contrarian / quant / alternative default


def test_insight_min_rule_documents_per_archetype_bias():
    """The rule must describe the per-archetype bias so a reader of the
    system prompt understands why the distribution targets differ across
    archetypes (predict/trend bias forward-looking; list-all/compare
    bias alternative)."""
    assert "PER-ARCHETYPE BIAS" in _INSIGHT_MIN
    assert "predict" in _INSIGHT_MIN.lower()
    assert "list-all" in _INSIGHT_MIN.lower() or "compare" in _INSIGHT_MIN.lower()


def test_insight_distribution_default_keys_complete():
    """The default distribution dict must carry all four element keys
    so callers (writer-prompt mirror + compliance scorer) can always
    look up every element without KeyError fallback noise."""
    expected_keys = {
        "forward_looking_min",
        "contrarian_min",
        "quant_min",
        "alternative_min",
    }
    assert set(_INSIGHT_DISTRIBUTION_DEFAULT.keys()) == expected_keys


def test_insight_distribution_for_predict_biases_forward_looking_up():
    """predict / trend / recommend are forward-looking-by-mission. The
    (a) target must be UP to ≥50%, biasing OUT of (b) and (d)."""
    for archetype in ("predict", "trend", "recommend"):
        d = insight_distribution(archetype)
        assert d["forward_looking_min"] >= 50, f"{archetype}: forward_looking_min should be ≥50%"
        # (c) quant stays at ≥20 for quantified anchors.
        assert d["quant_min"] >= 20, f"{archetype}: quant_min should stay at ≥20%"


def test_insight_distribution_for_list_all_biases_alternative_up():
    """list-all / compare are entity-enumerated archetypes — most
    leaves are inherently comparisons across the matrix. Bias (d) UP
    to ≥30% while keeping (a) at ≥30% so the forward-looking gap
    doesn't reopen."""
    for archetype in ("list-all", "compare"):
        d = insight_distribution(archetype)
        assert d["alternative_min"] >= 30, f"{archetype}: alternative_min should be ≥30%"
        assert d["forward_looking_min"] >= 30, f"{archetype}: forward_looking_min should be ≥30%"


def test_insight_distribution_for_explain_mechanism_is_balanced():
    """explain-mechanism uses the balanced 30/20/20/20 default."""
    d = insight_distribution("explain-mechanism")
    assert d == _INSIGHT_DISTRIBUTION_DEFAULT


def test_insight_distribution_unknown_archetype_falls_back_to_default():
    """Unknown archetype → default balanced distribution. No KeyError."""
    d = insight_distribution("some-future-archetype")
    assert d == _INSIGHT_DISTRIBUTION_DEFAULT
    d2 = insight_distribution(None)
    assert d2 == _INSIGHT_DISTRIBUTION_DEFAULT


def test_insight_distribution_writer_prompt_mirrors_targets():
    """The writer.write_section user prompt must include the per-
    archetype distribution targets so the writer sees the numbers
    upfront (where its attention lands, not just in the system prompt)."""
    from deep_research.pipeline.writer import _insight_distribution_block

    # predict archetype: forward-looking aim ≥50%
    block = _insight_distribution_block("predict")
    assert "INSIGHT DISTRIBUTION" in block
    assert "≥50%" in block
    # list-all archetype: alternative aim ≥30%
    block_la = _insight_distribution_block("list-all")
    assert "INSIGHT DISTRIBUTION" in block_la
    assert "≥30%" in block_la
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
