"""L6 + L7 (2026-05-29): pin the skim-layer (readability) and meta-causal
synthesis (insight) contract additions surfaced by the reference head-to-head.
"""

from deep_research import writing_rules as wr
from deep_research.pipeline import architect


def _writer_sys(arch="explain-mechanism"):
    return wr.writer_system(arch, domain="default", language="zh", toc_titles=["A", "B"])


def test_l6_skim_layer_in_writer_system():
    sysd = _writer_sys()
    assert "SKIM-LAYER" in sysd
    assert "load-bearing claim" in sysd  # bold the key claim per paragraph
    assert "recap-then-preview" in sysd
    # preserves Lunon's concise asset — no nominalization padding
    assert "nominalization" in sysd.lower() or "stay CONCISE" in sysd


def test_l7_metacausal_in_architect_system():
    s = architect._SYSTEM
    assert "META-CAUSAL SYNTHESIS" in s
    assert "coupling paths" in s and "maturity tiers" in s
    assert "external-domain calibration" in s


def test_l3_expand_every_entity_and_l4_deliverable_rules_present():
    s = architect._SYSTEM
    assert "EXPAND EVERY ENTITY" in s
    assert "is NOT a substitute" in s  # a §1 matrix row != a body expansion
    assert "DELIVERABLE DECOMPOSITION" in s


def test_l2_numeric_spine_in_prompts():
    """L2: quantitative reports must pin ONE headline figure reused verbatim
    across chapters (id44 emitted 3 contradictory totals)."""
    from deep_research import writing_rules as wr
    from deep_research.pipeline import architect

    assert "L2 NUMERIC SPINE" in architect._SYSTEM
    assert "NUMERIC SPINE" in wr.writer_system("trend", domain="default", language="zh", toc_titles=["A"])
