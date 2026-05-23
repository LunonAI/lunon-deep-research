"""Unit tests for P2-Wave-2.5-D4-F7 reader-facing structure directives.

Verifies the priority-indicator + ranked-table + action-list directive
fires for list-all and recommend archetypes (the value-add scope) and
does NOT fire for compare / explain-mechanism / trend / predict (where
it would read as listicle-style padding).
"""

from deep_research import writing_rules as wr


def _sys(archetype: str, monkeypatch) -> str:
    monkeypatch.setenv("DR_CAPEL_G", "off")
    return wr.writer_system(archetype, "default", "en", ["A", "B"])


# --- F7 fires for list-all + recommend --------------------------------------


def test_list_all_archetype_gets_value_add_rule(monkeypatch):
    sys = _sys("list-all", monkeypatch)
    assert "READER-FACING STRUCTURE" in sys
    assert "PRIORITY INDICATORS" in sys
    assert "CLOSING ACTION LIST" in sys


def test_recommend_archetype_gets_value_add_rule(monkeypatch):
    sys = _sys("recommend", monkeypatch)
    assert "READER-FACING STRUCTURE" in sys
    assert "立即可执行的三项行动" in sys
    assert "Three Actions You Can Take This Week" in sys


# --- F7 quiet for other archetypes ------------------------------------------


def test_compare_does_not_get_value_add_rule(monkeypatch):
    sys = _sys("compare", monkeypatch)
    assert "READER-FACING STRUCTURE" not in sys


def test_explain_mechanism_does_not_get_value_add_rule(monkeypatch):
    sys = _sys("explain-mechanism", monkeypatch)
    assert "READER-FACING STRUCTURE" not in sys


def test_trend_does_not_get_value_add_rule(monkeypatch):
    sys = _sys("trend", monkeypatch)
    assert "READER-FACING STRUCTURE" not in sys


def test_predict_does_not_get_value_add_rule(monkeypatch):
    sys = _sys("predict", monkeypatch)
    assert "READER-FACING STRUCTURE" not in sys


# --- F7 content checks ------------------------------------------------------


def test_rule_names_reference_calibration_artifacts(monkeypatch):
    sys = _sys("list-all", monkeypatch)
    # Star-tier markers from the reference id=23.
    assert "★★★" in sys
    assert "★★" in sys
    # Numbered-ranked-table structure for TOP-N entities.
    assert "RANKED TABLES" in sys


def test_action_list_has_executable_criteria(monkeypatch):
    sys = _sys("recommend", monkeypatch)
    # The directive names what makes an action "executable" so the writer
    # can self-verify.
    assert "specific (names a resource" in sys
    assert "executable without further research" in sys
    assert "sourced to a named recommendation" in sys


def test_rule_anti_listicle_padding_clause(monkeypatch):
    sys = _sys("list-all", monkeypatch)
    # Defensive clause: do NOT add these to non-list-all/recommend archetypes
    # (the writer should already see this via the archetype gate; the line
    # in the rule body documents WHY for the LLM).
    assert "listicle-style padding" in sys


# --- refiner emphasis updates -----------------------------------------------


def test_refiner_emphasis_list_all_mentions_priority():
    """list-all refiner emphasis carries the priority-indicator guidance."""
    emph = wr.refiner_emphasis("list-all")
    assert "priority indicator" in emph or "★★★" in emph


def test_refiner_emphasis_list_all_mentions_actionable_list():
    """Greptile follow-up (PR #15): the refiner emphasis for list-all also
    references the conditional closing actionable list. Previously the test
    only checked the priority-indicator clause, so a regression that trimmed
    the Top-Picks language wouldn't surface."""
    emph = wr.refiner_emphasis("list-all")
    assert "Top Picks" in emph or "立即可执行的三项行动" in emph or "actionable list" in emph


def test_value_add_rule_makes_action_list_conditional():
    """Greptile follow-up (PR #15, round 1): the writer rule's CLOSING ACTION
    LIST must be CONDITIONAL on a decision-support function, matching the
    refiner emphasis. Previously the writer demanded the action list
    unconditionally while the refiner only added it 'when the question
    implies a decision support function' — purely enumerative list-all tasks
    (e.g. 'list all Nobel Chemistry laureates 2000-2020') would get an
    unwanted action list from the writer that the refiner wouldn't reinforce.

    Round 2 follow-up: same CONDITIONAL label applied to RANKED TABLES so
    item 2 is symmetric with item 3 — both items skip on purely enumerative
    tasks rather than letting RANKED TABLES manufacture a ranking criterion
    out of thin air."""
    rule = wr._VALUE_ADD_LIST_RECOMMEND_RULE
    # All three items (PRIORITY INDICATORS / RANKED TABLES / CLOSING ACTION
    # LIST) now carry the CONDITIONAL label, applying symmetric skip-logic
    # for purely enumerative tasks. Pre-round-3 only items 2+3 had it.
    assert rule.count("CONDITIONAL") >= 3
    assert "purely enumerative" in rule
    # Nobel anti-example is cited for each item so the LLM sees the same
    # concrete skip scenario in all three contexts.
    assert rule.count("Nobel Chemistry") >= 3
    # Specific anti-patterns named per item:
    #   item 1: don't manufacture star ratings via invented tier criterion.
    #   item 2: don't manufacture a ranking criterion to fake a TOP-N.
    #   item 3: skip the action list on historical enumeration.
    assert "do NOT invent a tier criterion" in rule
    assert "do NOT invent a ranking criterion" in rule


def test_refiner_emphasis_recommend_mentions_action_list():
    emph = wr.refiner_emphasis("recommend")
    assert "action list" in emph or "立即可执行" in emph


def test_refiner_emphasis_recommend_mentions_executable_criterion():
    """Greptile follow-up (PR #15): the recommend refiner emphasis names the
    'specific enough to execute without further research' invariant, matching
    the writer rule's executable-criterion. Regression-guards a trimmed-down
    refiner that would weaken the dimension match."""
    emph = wr.refiner_emphasis("recommend")
    assert "execute" in emph and "further research" in emph


def test_refiner_emphasis_compare_unchanged():
    """Compare archetype emphasis still mentions the matrix/quantify pattern."""
    emph = wr.refiner_emphasis("compare")
    assert "matrix" in emph and "quantify" in emph
