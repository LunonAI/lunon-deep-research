"""Unit tests for P2-Wave-2.5-E1 — section-opening framework-recap directive.

Single-variable change replacing the bundled Wave 2.5 push. Verifies the
rule is present in `writer_system()` output and the rule body names the
calibration source (the reference methodology research).
"""

from deep_research import writing_rules as wr


def _sys(monkeypatch) -> str:
    monkeypatch.setenv("DR_CAPEL_G", "off")
    return wr.writer_system("compare", "default", "en", ["A", "B"])


def test_section_recap_rule_present_in_writer_system(monkeypatch):
    sys = _sys(monkeypatch)
    assert "SECTION-OPENING FRAMEWORK RECAP" in sys


def test_recap_rule_names_calibration_source(monkeypatch):
    sys = _sys(monkeypatch)
    # The body must reference the methodology research so future engineers
    # can trace WHY this rule is shipped.
    assert "framework" in sys
    assert "P2-Wave-2.5-E1" in sys


def test_recap_rule_provides_both_en_and_zh_templates(monkeypatch):
    sys = _sys(monkeypatch)
    assert "Building on the framework introduced" in sys
    assert "沿用第一节框架" in sys


def test_recap_rule_exempts_first_section(monkeypatch):
    sys = _sys(monkeypatch)
    # The directive must explicitly carve out §1 (the framework-establishing
    # section), otherwise the writer applies a recap to the article opener
    # itself, creating a logic gap.
    assert "first section" in sys.lower() or "first chapter" in sys.lower()
    assert "EXEMPT" in sys


def test_recap_rule_forbids_disconnected_topic_statements(monkeypatch):
    sys = _sys(monkeypatch)
    # The forbidden-pattern list must name the failure mode (stating topic
    # with no framework link reads as disconnected exposition).
    assert "Forbidden opening patterns" in sys
    assert "no link" in sys or "disconnected" in sys


def test_recap_rule_ordering_after_cleaning_rule(monkeypatch):
    """The recap rule must appear AFTER the cleaning-resistant attribution
    rule so the writer reads attribution discipline first, then layers the
    rhetorical move on top."""
    sys = _sys(monkeypatch)
    idx_cleaning = sys.find("SOURCE ATTRIBUTION")
    idx_recap = sys.find("SECTION-OPENING FRAMEWORK RECAP")
    assert 0 < idx_cleaning < idx_recap
