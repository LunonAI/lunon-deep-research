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
    assert "INSIGHT DENSITY" in _INSIGHT_MIN


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
    # Wave 2 §3.2 widened "H4 leaf" to "leaf" because flat archetypes
    # (list-all / compare per the Wave 2 §1.2 outline preset) have NO
    # H4 — their leaves are H2 body sections. The no-drop guidance
    # still applies to all archetypes.
    assert "Do NOT drop or skip the leaf" in _INSIGHT_MIN or "Do NOT drop or skip the H4 leaf" in _INSIGHT_MIN
    assert "bounded scope" in _INSIGHT_MIN
    # And the old, ambiguous "pick a different depth_seed" phrasing must
    # stay out — re-introducing it would re-introduce the drop-leaf risk.
    assert "pick a different depth_seed" not in _INSIGHT_MIN


def test_insight_rule_has_one_element_per_paragraph_reconciliation():
    """P3b-opt2: the insight rule must reconcile with the PER-ENTITY prose
    form by forbidding multi-mode stacking in a single paragraph, and the
    old stacking-permission ('Multiple elements can apply to ONE leaf —
    that's fine') must be GONE (it green-lit the 'internally unstable'
    stacking the RACE judge penalizes)."""
    assert "ONE INSIGHT ELEMENT PER PARAGRAPH" in _INSIGHT_MIN
    assert "NEVER stack" in _INSIGHT_MIN
    assert "internally" in _INSIGHT_MIN and "unstable" in _INSIGHT_MIN
    assert "BANDS" in _INSIGHT_MIN
    # the old permissive sentence is amended away
    assert "that's fine" not in _INSIGHT_MIN


def test_emdash_restraint_rule_in_writer_system():
    """P3b-opt2: the em-dash restraint clause is wired into every section's
    system prompt (the deterministic clamp is the backstop; the directive
    states the reference trend so the writer doesn't over-produce)."""
    sys = writer_system("list-all", "default", "en", ["A", "B"], task_id=None)
    assert "EM-DASH RESTRAINT" in sys
    assert "12 per 1,000 words" in sys


def test_insight_element_f_requires_resolution_clause():
    """P3b-D1: element (f) PROBLEM-TRADEOFF now requires an explicit
    resolution clause — a bare unresolved tension doesn't count (our weakest
    RACE-Insight sub-criterion)."""
    assert "RESOLUTION CLAUSE REQUIRED" in _INSIGHT_MIN
    assert "Where one might expect" in _INSIGHT_MIN
    assert "does NOT satisfy" in _INSIGHT_MIN


def test_chapter_synthesis_rule_in_writer_system():
    """P3b-D1: the end-of-chapter SYNTHESIS directive (highest-Insight move)
    is wired into the system prompt for every archetype, with the word cap,
    the no-new-entity constraint, the flat-report reshape, and the optional
    'what remains unresolved' closer."""
    for arche in ("list-all", "compare", "explain-mechanism", "predict"):
        sys = writer_system(arche, "default", "en", ["A", "B"], task_id=None)
        assert "END-OF-CHAPTER SYNTHESIS" in sys, f"missing for {arche}"
        assert "profiles NO new entity" in sys
        assert "180 words" in sys
        assert "RE-ALLOCATE" in sys
        assert "FLAT reports" in sys  # list-all reshape path
        assert "What remains unresolved" in sys  # technique 4 (per-chapter limits)


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
        assert "INSIGHT DENSITY" in sys, f"archetype={archetype} did not get the new Insight rule"
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
        assert "INSIGHT DENSITY" in sys, (
            f"archetype={archetype} lost the Insight rule when dedup was suppressed — "
            f"_INSIGHT_MIN must not be nested under the include_dedup branch"
        )
        # And sanity: the dedup rule IS gone (so we know the suppression
        # actually took effect; otherwise the test would pass vacuously).
        assert "CROSS-SECTION NON-REDUNDANCY" not in sys, (
            f"archetype={archetype} kept _DEDUP_RULE despite suppress_dedup=True"
        )
