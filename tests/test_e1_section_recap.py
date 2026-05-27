"""Unit tests for the section-opening prose-lead directive.

History:
- v1 (early 2026-05-23): "framework recap" rule that assumed prose openings;
  silently failed on table-first sections (id=91 pilot: 0/50 compliance).
- v2 (2026-05-23): fixed the structural blind-spot by mandating prose-
  before-table even when primary content is a table. Templates encouraged
  "Building on §N..." style framework recaps with §N refs.
- v3 (2026-05-26, gap-map §12.A): post-PR-31 fresh-corpus A/B retro
  showed v2's "Calibrated against Qianfan #1" claim was BACKWARDS. Live
  leaderboard #1 vintage uses the "Building on §N..." template at 0%
  (vs Lunon's 77%); judge flagged the result as "repeated setup language"
  and "forward references to missing sections". v3 keeps the prose-before-
  table requirement but drops the recap templates, §N opening refs, and
  meta-subject openings ("this section"). Opening templates are now
  modeled on verified Qianfan chapter openers.

The tests below pin BOTH the structural requirement that survived v3 AND
the v3-specific antipattern bans, so any future regression to "Building
on §X..." or "this section" openings fails loud locally before the
writer ships it again.
"""

from deep_research import writing_rules as wr


def _sys(monkeypatch) -> str:
    monkeypatch.setenv("DR_CAPEL_G", "off")
    return wr.writer_system("compare", "default", "en", ["A", "B"])


# --- structural requirements preserved from v2 ---------------------------


def test_prose_lead_rule_present_in_writer_system(monkeypatch):
    sys = _sys(monkeypatch)
    assert "SECTION-OPENING PROSE LEAD" in sys


def test_rule_names_calibration_source(monkeypatch):
    """The rule body must reference the gap-map section / wave tag so
    future engineers can trace WHY this rule shipped in this form."""
    sys = _sys(monkeypatch)
    assert "§12.A" in sys
    assert "Qianfan" in sys


def test_rule_exempts_first_section(monkeypatch):
    """The first section (article opener) is exempt from the topic-
    restriction — it establishes the framework rather than diving into
    a sub-topic. The prose-before-table requirement still applies."""
    sys = _sys(monkeypatch)
    body = sys.lower()
    assert "first section" in body or "first chapter" in body
    assert "EXEMPT" in sys


def test_rule_forbids_disconnected_topic_statements(monkeypatch):
    """The FORBIDDEN list must name the failure mode (stating topic
    with no substantive claim reads as disconnected exposition)."""
    sys = _sys(monkeypatch)
    assert "FORBIDDEN opening patterns" in sys
    assert "disconnected exposition" in sys


def test_rule_ordering_after_cleaning_rule(monkeypatch):
    """The prose-lead rule must appear AFTER the source-attribution
    rule so the writer reads attribution discipline first, then layers
    the rhetorical move on top."""
    sys = _sys(monkeypatch)
    idx_cleaning = sys.find("SOURCE ATTRIBUTION")
    idx_lead = sys.find("SECTION-OPENING PROSE LEAD")
    assert 0 < idx_cleaning < idx_lead


def test_mandates_prose_before_table(monkeypatch):
    """v1's compliance failure mode on id=91 (0/50) was table-first
    sections with no prose lead. v2 mandated prose-paragraph-then-table.
    v3 preserves this requirement — it's the part of v2 that worked."""
    sys = _sys(monkeypatch)
    body = sys.lower()
    assert "prose-paragraph-then-data" in body or ("prose paragraph" in body and "before any data block" in body)


def test_forbids_table_first_openings(monkeypatch):
    """The forbidden list must explicitly name 'opening with a markdown
    table' as a failure mode so the writer knows the structural rule
    isn't optional or interpretive."""
    sys = _sys(monkeypatch)
    body = sys.lower()
    assert "opening with a markdown table" in body


# --- v3-specific: Qianfan-parity antipattern bans -----------------------


def test_v3_marker_present(monkeypatch):
    """Version marker pins the rule's iteration. A future revision that
    forgets to bump the marker fails this test, surfacing the missing
    audit trail."""
    sys = _sys(monkeypatch)
    assert "P2-Wave-3-§12.A.v3" in sys


def test_v3_forbids_building_on_template(monkeypatch):
    """The 'Building on §X...' template fired ~77% in pre-v3 Lunon and 0%
    in Qianfan #1; v3 forbids it explicitly in the antipattern list."""
    sys = _sys(monkeypatch)
    # The rule body must call this out by name in the forbidden list so a
    # writer that emits 'Building on the framework introduced in §1...'
    # has been told that exact phrasing is wrong.
    forbidden_idx = sys.find("FORBIDDEN opening patterns")
    assert forbidden_idx > 0
    assert "'Building on [the framework" in sys[forbidden_idx:]


def test_v3_forbids_section_n_refs_in_openings(monkeypatch):
    """§N refs in opening sentences was a v2 allowance that produced the
    judge-flagged 'forward references to missing sections' bug. v3
    forbids §N refs in openings entirely (still allowed in body text
    per the unchanged narrowing)."""
    sys = _sys(monkeypatch)
    forbidden_idx = sys.find("FORBIDDEN opening patterns")
    # The §N-in-openings antipattern must appear in the forbidden list AND
    # the body narrowing must explicitly carve openings out of the
    # 'named artefact OK' allowance.
    assert "ANY '§N'" in sys[forbidden_idx:]
    assert "OPENING-SENTENCE FORBIDDEN-§N RULE OVERRIDES" in sys


def test_v3_forbids_this_section_meta_subject(monkeypatch):
    """'This section/chapter/report' as the opening subject is meta-
    narration; Qianfan opens with the substantive topic noun. v3 names
    this as a forbidden antipattern."""
    sys = _sys(monkeypatch)
    forbidden_idx = sys.find("FORBIDDEN opening patterns")
    section_of_rule = sys[forbidden_idx:]
    assert "'This section'" in section_of_rule
    assert "'This chapter'" in section_of_rule
    assert "'This report'" in section_of_rule


def test_v3_acceptable_templates_are_substantive_not_recap(monkeypatch):
    """v2's acceptable templates were all 'Building on...' / 'Applied
    to...' recap variants. v3 replaces them with subject-noun-first
    openings modeled on verified Qianfan chapter openers — definition,
    quantified-claim, factual-anchor, substantive-contextualisation."""
    sys = _sys(monkeypatch)
    acceptable_idx = sys.find("Acceptable opening patterns (EN")
    assert acceptable_idx > 0
    # Each of the four v3 EN templates must be named so future readers
    # see the substantive shape of valid openings.
    assert "Definition opening" in sys
    assert "Quantified-claim opening" in sys
    assert "Factual-anchor opening" in sys
    assert "Substantive-contextualisation opening" in sys


def test_v3_provides_both_en_and_zh_acceptable_templates(monkeypatch):
    """Bilingual coverage preserved: v3 must offer both EN templates
    (modeled on verified Qianfan EN samples) and ZH templates (modeled
    on Qianfan ZH samples). Each of the four ZH templates is asserted
    individually to mirror the EN test — a single-token proxy would
    pass even if templates were deleted."""
    sys = _sys(monkeypatch)
    assert "Acceptable opening patterns (EN" in sys
    acceptable_zh_idx = sys.find("Acceptable opening patterns (ZH")
    assert acceptable_zh_idx > 0
    zh_block = sys[acceptable_zh_idx:]
    # Each of the four v3 ZH templates must be named (definition,
    # quantified-claim, factual-anchor, substantive-contextualisation —
    # the ZH counterparts of the four EN templates checked above).
    assert "主题名词" in zh_block  # definition + contextualisation openings
    assert "具体数字" in zh_block  # quantified-claim opening
    assert "事实陈述" in zh_block  # factual-anchor opening
    assert "起源于" in zh_block  # substantive-contextualisation opening


def test_v3_body_narrowing_preserved_for_named_artefacts(monkeypatch):
    """The v2 body-text narrowing — §N refs in BODY are GOOD when paired
    with a named artefact, BAD as bare temporal pointers — is preserved
    by v3. Only OPENING-sentence §N refs are newly forbidden."""
    sys = _sys(monkeypatch)
    body = sys.lower()
    assert "named artefact" in body
    assert "bare temporal pointers" in body
