"""Unit tests for P2-Wave-2.5-D2-F4 architect TOC section-count expansion.

The architect schema was bumped from `<=8` to `5-14` top-level sections,
calibrated against the #1 reference leaderboard's 12-14 mean on top-scoring
research reports.

Architect uses an LLM call so we can't unit-test the output directly here,
but we can verify the SYSTEM prompt carries the new schema bounds and the
depth-tier section-count guidance.
"""

from deep_research.pipeline.architect import _SYSTEM


def test_system_prompt_mentions_new_section_count_range():
    """The schema string must say `5-14` (not the old `<=8`)."""
    assert "5-14" in _SYSTEM
    assert "<=8 ]" not in _SYSTEM  # old cap must be gone


def test_system_prompt_includes_depth_tier_section_guidance():
    """The new SECTION COUNT GUIDANCE block must name all four tiers."""
    block = _SYSTEM
    assert "SECTION COUNT GUIDANCE" in block
    assert "compact / standard scope" in block
    assert "deep scope" in block
    assert "comprehensive scope" in block


def test_system_prompt_anchors_count_to_reference_envelope():
    """Calibration source (the reference corpus average 12-14) named in the prompt
    so the LLM understands why the count moved. Greptile follow-up (PR #13,
    round 2): both halves asserted independently — pre-fix `or` would let a
    future edit drop "the reference" attribution while keeping "12-14" and not
    surface the regression."""
    assert "the reference" in _SYSTEM and "12-14" in _SYSTEM


def test_system_prompt_compact_count_band():
    """Compact / standard band: 5-7 top-level sections per the guidance."""
    assert "5-7 top-level sections" in _SYSTEM


def test_system_prompt_deep_count_band():
    """Deep band: 8-12 top-level sections."""
    assert "8-12 top-level sections" in _SYSTEM


def test_system_prompt_comprehensive_count_band():
    """Comprehensive band: 12-14 top-level sections."""
    assert "12-14 top-level sections" in _SYSTEM


def test_system_prompt_warns_against_filler():
    """The guidance explicitly prohibits 'misc' / 'appendix' filler sections.
    Greptile follow-up (PR #13, round 2): both signals required so trimming
    either word doesn't silently weaken the assertion."""
    assert "filler" in _SYSTEM.lower() and "misc" in _SYSTEM.lower()
