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
    forbidden. When evidence genuinely doesn't support any of (a)-(d), the
    writer must state the leaf's bounded scope — NOT drop/skip the leaf
    (which would trip the validation node's sections_present hard-fail) and
    NOT swap depth_seeds (the writer doesn't have authority over the
    outline; the architect does)."""
    assert "AVOID FORMULAIC INSERTION" in _INSIGHT_MIN
    assert "do NOT bolt a generic" in _INSIGHT_MIN
    # Pin the no-drop guidance (Greptile PR #21 follow-up): an earlier draft
    # told the writer to "pick a different depth_seed", which the writer
    # cannot do at write time and which risks dropping H4 leaves entirely.
    assert "Do NOT drop or skip the H4 leaf" in _INSIGHT_MIN
    assert "bounded scope" in _INSIGHT_MIN
    # And the old, ambiguous "pick a different depth_seed" phrasing must
    # stay out — re-introducing it would re-introduce the drop-leaf risk.
    assert "pick a different depth_seed" not in _INSIGHT_MIN


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


def test_writer_system_keeps_insight_rule_when_dedup_suppressed():
    """Greptile PR #21 follow-up: pin that `_INSIGHT_MIN` lives OUTSIDE the
    `include_dedup` branch. The previous test passed `task_id=None`, which
    means `include_dedup=True` for every archetype (the auto-suppress path
    requires task_id), so it could not catch a refactor that mistakenly
    nested `_INSIGHT_MIN` inside the dedup conditional. This test forces
    `suppress_dedup=True` so dedup IS omitted and asserts Insight survives —
    closing the coverage gap Greptile flagged."""
    sample_toc_titles = ["A", "B"]
    for archetype in (
        "list-all",
        "compare",
        "explain-mechanism",
        "predict",
        "recommend",
        "trend",
    ):
        sys = writer_system(
            archetype,
            "default",
            "en",
            sample_toc_titles,
            task_id=None,
            suppress_dedup=True,
        )
        # Insight rule MUST still appear — that's the whole point of the pin.
        assert "INSIGHT DENSITY — REQUIRED CLOSE-OF-LEAF" in sys, (
            f"archetype={archetype} lost the Insight rule when dedup was suppressed — "
            f"_INSIGHT_MIN must not be nested under the include_dedup branch"
        )
        # And sanity: the dedup rule IS gone (so we know the suppression
        # actually took effect; otherwise the test would pass vacuously).
        assert "CROSS-SECTION NON-REDUNDANCY" not in sys, (
            f"archetype={archetype} kept _DEDUP_RULE despite suppress_dedup=True"
        )
