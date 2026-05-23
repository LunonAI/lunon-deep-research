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
    emph = wr.refiner_emphasis("list-all")
    assert "priority indicator" in emph or "★★★" in emph


def test_refiner_emphasis_recommend_mentions_action_list():
    emph = wr.refiner_emphasis("recommend")
    assert "action list" in emph or "立即可执行" in emph


def test_refiner_emphasis_compare_unchanged():
    """Compare archetype emphasis still mentions the matrix/quantify pattern."""
    emph = wr.refiner_emphasis("compare")
    assert "matrix" in emph and "quantify" in emph
