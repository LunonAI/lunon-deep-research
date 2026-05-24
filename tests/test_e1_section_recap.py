"""Unit tests for P2-Wave-2.5-E1 — section-opening framework-recap directive.

Single-variable change replacing the bundled Wave 2.5 push. Verifies the
rule is present in `writer_system()` output and the rule body names the
calibration source (Qianfan methodology research).
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
    assert "FORBIDDEN opening patterns" in sys
    assert "disconnected exposition" in sys or "no link" in sys


def test_recap_rule_ordering_after_cleaning_rule(monkeypatch):
    """The recap rule must appear AFTER the cleaning-resistant attribution
    rule so the writer reads attribution discipline first, then layers the
    rhetorical move on top."""
    sys = _sys(monkeypatch)
    idx_cleaning = sys.find("SOURCE ATTRIBUTION")
    idx_recap = sys.find("SECTION-OPENING FRAMEWORK RECAP")
    assert 0 < idx_cleaning < idx_recap


# --- v2-specific: table-aware structural mandate ---------------------------


def test_v2_mandates_prose_before_table(monkeypatch):
    """v1's compliance failure mode on id=91 (0/50) was table-first sections
    with no prose lead. v2 must explicitly mandate prose-paragraph-then-table."""
    sys = _sys(monkeypatch)
    body = sys.lower()
    assert "prose-paragraph-then-table" in body or (
        "prose paragraph" in body and "before any data block" in body
    )


def test_v2_forbids_table_first_openings(monkeypatch):
    """The forbidden list must explicitly name 'opening with a markdown
    table' as a failure mode so the writer knows the structural rule isn't
    optional or interpretive."""
    sys = _sys(monkeypatch)
    assert "Opening with a markdown table" in sys or "markdown table" in sys.lower()


def test_v2_narrows_section_number_reference_rule(monkeypatch):
    """Bonus-audit narrowing: §N references are GOOD when paired with a
    named artefact, BAD as bare temporal pointers. v2 must encode both
    sides — the GOOD pattern (named artefact) and the BAD pattern
    ('bare temporal pointers')."""
    sys = _sys(monkeypatch)
    assert "named artefact" in sys.lower() or "named artifact" in sys.lower()
    assert "bare temporal pointers" in sys.lower() or "as discussed in §" in sys


def test_v2_marker_present(monkeypatch):
    sys = _sys(monkeypatch)
    assert "E1.v2" in sys


def test_v2_template_demonstrates_prose_then_table(monkeypatch):
    """Acceptable templates must SHOW the prose-then-table pattern via
    concrete examples — not just abstractly mandate it. The writer copies
    patterns it sees in the prompt; abstract mandates are weaker."""
    sys = _sys(monkeypatch)
    assert (
        "table below records" in sys
        or "matrix below" in sys
        or "table records" in sys
    )
