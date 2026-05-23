"""Unit tests for P2-Wave-2-A CAPEL marker post-strip.

Covers:
- Round-trip strip of well-formed countdown markers.
- Adjacent-marker violation detection (paper's hard rule).
- Marker-only input (model produced no content) -> just whitespace returned.
- Preservation of legitimate angle-bracket constructs that are NOT markers
  (HTML-ish tags, comparison `<` operators).
- Empty / None-ish input fail-soft.
- Stats accounting.
"""

from deep_research.pipeline._capel_strip import strip_capel_markers


def test_well_formed_countdown_strips_cleanly():
    text = "<3>The<2>quick<1>brown<0>fox."
    out, stats = strip_capel_markers(text)
    assert "<" not in out
    assert ">" not in out
    assert "The" in out and "quick" in out and "brown" in out and "fox" in out
    assert stats["n_markers_stripped"] == 4
    assert stats["n_violations"] == 0


def test_back_to_back_markers_flagged_as_violation():
    # `<5><4>` with no intervening token = violation.
    text = "Word1 <5><4> Word2 <3>Word3<2>Word4<1>Word5<0>"
    out, stats = strip_capel_markers(text)
    assert stats["n_violations"] >= 1
    assert stats["n_markers_stripped"] == 6
    # The two violating markers still get stripped; the output is content-only.
    assert "<" not in out
    assert "Word1" in out and "Word5" in out


def test_marker_count_with_whitespace_between_violators():
    # `<5>  <4>` (whitespace only between markers) is still a violation per
    # paper: an intervening content TOKEN is required, not just whitespace.
    text = "<5>  <4>Hello<3>World<0>"
    _, stats = strip_capel_markers(text)
    assert stats["n_violations"] >= 1


def test_preserves_non_marker_angle_brackets():
    # HTML-like tags (alpha chars) and comparison ops MUST NOT be stripped.
    text = "If <a> tag and x < 5 are valid, only <3>real<2>markers<1>strip<0>."
    out, stats = strip_capel_markers(text)
    assert "<a>" in out  # html-ish tag preserved
    assert "x < 5" in out  # comparison operator preserved
    assert stats["n_markers_stripped"] == 4


def test_collapses_doubled_whitespace_left_behind():
    # When markers sit at word boundaries with surrounding spaces, the strip
    # should not leave doubled spaces.
    text = "alpha <3> beta <2> gamma <1> delta <0> epsilon"
    out, _ = strip_capel_markers(text)
    assert "  " not in out  # no doubled spaces
    assert "alpha" in out and "epsilon" in out


def test_empty_input_returns_empty():
    out, stats = strip_capel_markers("")
    assert out == ""
    assert stats == {"n_markers_stripped": 0, "n_violations": 0}


def test_no_markers_returns_unchanged_text_with_zero_stats():
    text = "Plain paragraph with no markers at all. Numbers like 2025 are fine."
    out, stats = strip_capel_markers(text)
    assert out == text
    assert stats["n_markers_stripped"] == 0
    assert stats["n_violations"] == 0


def test_marker_with_5_digits_still_recognized():
    # Marker count for large sections could realistically hit four or five
    # digits (e.g. <12000> for total-article CAPEL). Pattern must accept them.
    text = "<12000>content<11999>"
    _, stats = strip_capel_markers(text)
    assert stats["n_markers_stripped"] == 2


def test_marker_with_six_or_more_digits_not_recognized():
    # A long bracketed numeric run is probably NOT a CAPEL marker. Avoid
    # over-eager stripping.
    text = "Reference [<123456> entry] keep"
    out, stats = strip_capel_markers(text)
    assert "<123456>" in out
    assert stats["n_markers_stripped"] == 0


def test_newlines_preserved_through_strip():
    text = "Heading\n<5>line<4>one\n\n<3>line<2>two<1>here<0>"
    out, _ = strip_capel_markers(text)
    assert "\n\n" in out  # paragraph break survives
