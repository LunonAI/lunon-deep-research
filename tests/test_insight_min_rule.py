"""Pin the post-#3 _INSIGHT_MIN rule structure (P2-Option-A-#3).

The previous _INSIGHT_MIN actively SUPPRESSED forward-looking content for
list-all/compare/explain-mechanism archetypes — a calibration that survived
from the post-W9 over-correction and was directly counter to the +0.154 raw
Insight gap observed against the high-scoring corpus. These tests pin the
new Insight-positive rule structure so a future refactor can't silently
re-introduce the suppression framing.
"""

from deep_research.writing_rules import _INSIGHT_MIN, writer_system


def test_insight_rule_drops_archetype_suppression():
    """The old rule said 'Do NOT add forward-looking projections... UNLESS
    the prompt explicitly asks for prediction OR the task archetype is
    predict, recommend, or trend.' Make sure that suppression-by-archetype
    framing is gone — Insight density is now required across ALL archetypes."""
    assert "Do NOT add forward-looking" not in _INSIGHT_MIN
    assert "UNLESS the prompt explicitly asks for prediction" not in _INSIGHT_MIN
    assert "For all other archetypes" not in _INSIGHT_MIN
    # The new rule's title is the new contract.
    assert "INSIGHT DENSITY — REQUIRED CLOSE-OF-LEAF" in _INSIGHT_MIN


def test_insight_rule_specifies_four_close_elements():
    """Every H4 leaf must close with one of the four named payoff types."""
    for element in (
        "FORWARD-LOOKING IMPLICATION",
        "NAMED CONTRARIAN FRAMING",
        "QUANTIFIED PROJECTION OR CONFIDENCE RANGE",
        "NAMED-ALTERNATIVE COMPARISON",
    ):
        assert element in _INSIGHT_MIN, f"missing required leaf-close element: {element}"


def test_insight_rule_keeps_grounding_requirement():
    """Insight elements must stay evidence-backed — free speculation hurts."""
    assert "GROUNDING RULE" in _INSIGHT_MIN
    assert "evidence-backed" in _INSIGHT_MIN
    assert "hurts more than absent insight" in _INSIGHT_MIN


def test_insight_rule_rejects_formulaic_insertion():
    """The rule must call out generic 'looking ahead'-style padding as
    forbidden — the leaf should pick a different depth_seed if the evidence
    doesn't support a substantive payoff."""
    assert "AVOID FORMULAIC INSERTION" in _INSIGHT_MIN
    assert "do NOT bolt a generic" in _INSIGHT_MIN
    assert "pick a different depth_seed" in _INSIGHT_MIN


def test_writer_system_includes_new_insight_rule_for_every_archetype():
    """Wired through writer_system() — the rule appears regardless of which
    archetype the caller passes. (Old rule was always included too, just
    with conditional content that suppressed for some archetypes; new rule
    is universal in both wiring AND content.)"""
    sample_toc_titles = ["A", "B"]
    for archetype in (
        "list-all",
        "compare",
        "explain-mechanism",
        "predict",
        "recommend",
        "trend",
    ):
        sys = writer_system(archetype, "default", "en", sample_toc_titles, task_id=None)
        assert "INSIGHT DENSITY — REQUIRED CLOSE-OF-LEAF" in sys, (
            f"archetype={archetype} did not get the new Insight rule"
        )
        assert "Do NOT add forward-looking" not in sys, f"archetype={archetype} still carries the old suppression text"
