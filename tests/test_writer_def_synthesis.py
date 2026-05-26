"""Wave 2 §2.1c (2026-05-26): post-process synthesis of missing
`[^{sid}-N]: source` def lines.

The 2026-05-26 post-Wave-1 id=91 smoke surfaced the operative distance-
score blocker: writer emitted 183 clean inline `[^X]` markers but ZERO
trailing def lines, so `footnote_normalize` stripped every marker as
orphan and the rendered article had no References block (distance score
regressed to 1.966 from 1.456 baseline).

The deep fix has two layers:
  Layer 1 (prompt): each evidence atom is pre-assigned its
    `[^{sid}-N]` marker so the writer can't pick a wrong number, plus
    a FORBIDDEN example explicitly calling out missing-def emissions.
  Layer 2 (safety net): `_synthesize_missing_defs` parses the writer's
    output, finds cited markers in the section's namespace that lack
    matching def lines, looks up the corresponding evidence atom by
    marker index (1-indexed), and appends synthesized def lines at
    section end.

These tests pin the safety-net behavior so a future refactor that drops
or weakens the synthesis is caught at CI time.
"""

from deep_research.pipeline.writer import _synthesize_missing_defs

_EVIDENCE = [
    {"eid": "e1", "source_name": "McKinsey (2025)", "url": "https://mck.example.com/2025"},
    {"eid": "e2", "source_name": "Gartner (2024)", "url": ""},  # url-empty case
    {"eid": "e3", "source_name": "Lebrun (1999)", "url": "https://example.com/lebrun"},
]


def test_synthesize_when_writer_emitted_inline_markers_but_zero_defs():
    """Canonical post-Wave-1 smoke failure: 3 inline markers in body,
    0 def lines emitted. Safety net must synthesize all 3."""
    text = "## 1 Intro\n\nClaim per Source A[^S1-1]. Claim per Source B[^S1-2]. And Source C[^S1-3]. End of section.\n"
    out, n = _synthesize_missing_defs(text, "S1", _EVIDENCE)
    assert n == 3
    # All three def lines appended at section end.
    assert "[^S1-1]: McKinsey (2025) — https://mck.example.com/2025" in out
    assert "[^S1-2]: Gartner (2024)" in out  # url empty → no ` — <url>` suffix
    assert "[^S1-3]: Lebrun (1999) — https://example.com/lebrun" in out
    # Synthesized defs come AFTER the original body content.
    body_end = out.index("End of section.")
    def_start = out.index("[^S1-1]:")
    assert def_start > body_end


def test_synthesize_only_for_undefined_markers():
    """When the writer emitted def lines for SOME markers (compliant on
    those), synthesize ONLY for the ones it skipped. Don't duplicate."""
    text = (
        "## 1 Intro\n\n"
        "Claim per Source A[^S1-1]. Claim per Source B[^S1-2]. "
        "And Source C[^S1-3].\n\n"
        '[^S1-1]: McKinsey (2025), "Report A," McKinsey Quarterly.\n'  # writer-emitted
    )
    out, n = _synthesize_missing_defs(text, "S1", _EVIDENCE)
    # 2 missing (S1-2, S1-3); S1-1 already defined by writer.
    assert n == 2
    # Writer's def line for S1-1 must survive untouched.
    assert '[^S1-1]: McKinsey (2025), "Report A," McKinsey Quarterly.' in out
    # New defs synthesized for S1-2, S1-3.
    assert "[^S1-2]: Gartner (2024)" in out
    assert "[^S1-3]: Lebrun (1999) — https://example.com/lebrun" in out


def test_no_synthesis_when_writer_emitted_all_defs():
    """Full compliance case — writer emitted both inline markers AND
    def lines for all of them. Safety net is a no-op."""
    text = (
        "## 1 Intro\n\n"
        "Claim[^S1-1]. Another[^S1-2].\n\n"
        '[^S1-1]: McKinsey (2025), "Report A," McKinsey Quarterly.\n'
        '[^S1-2]: Gartner (2024), "Analysis," Gartner.\n'
    )
    out, n = _synthesize_missing_defs(text, "S1", _EVIDENCE)
    assert n == 0
    assert out == text  # unchanged


def test_no_synthesis_when_no_inline_markers():
    """Section emitted no inline markers (e.g. a methodology section
    with no citations). Safety net is a no-op."""
    text = "## 1 Intro\n\nA section with no citations whatsoever.\n"
    out, n = _synthesize_missing_defs(text, "S1", _EVIDENCE)
    assert n == 0
    assert out == text


def test_no_synthesis_when_no_evidence():
    """Section had no evidence atoms allocated (edge case — should not
    happen in production but the safety net must not crash). Returns
    unchanged text."""
    text = "## 1 Intro\n\nClaim[^S1-1].\n"
    out, n = _synthesize_missing_defs(text, "S1", [])
    assert n == 0
    assert out == text


def test_synthesis_only_touches_this_sections_namespace():
    """Inline markers from OTHER sections (a writer leak — copying
    from a prior section) must not be synthesized into this section's
    output. Only `[^S1-*]` markers get processed by S1's safety net."""
    text = "## 1 Intro\n\nClaim[^S1-1]. Cross-leak from another section[^S3-2].\n"
    out, n = _synthesize_missing_defs(text, "S1", _EVIDENCE)
    assert n == 1  # only S1-1 synthesized
    assert "[^S1-1]:" in out
    # S3-2 left alone — that's S3's problem (footnote_normalize will
    # handle the cross-section concern at the article-assembly step).
    assert "[^S3-2]:" not in out


def test_synthesis_out_of_bounds_marker_gets_placeholder_def():
    """Edge case: writer picked a marker number larger than the
    evidence pack (e.g. [^S1-99] when only 3 atoms exist). Synthesis
    must still produce SOMETHING so the marker isn't stripped as
    orphan, even if the source mapping is lost. Operator can inspect
    the placeholder def + investigate via drift log."""
    text = "## 1 Intro\n\nClaim[^S1-99].\n"
    out, n = _synthesize_missing_defs(text, "S1", _EVIDENCE)
    assert n == 1
    # Placeholder def synthesized — marker won't be stripped as orphan.
    assert "[^S1-99]:" in out
    # And the placeholder must signal the out-of-bounds condition so
    # operator inspection surfaces it.
    assert "out of bounds" in out


def test_synthesis_preserves_writer_def_blocks_with_blank_separator():
    """Synthesized def lines must be appended with a blank-line
    separator so they don't merge into the writer's final paragraph
    (would otherwise be unreadable + would break footnote_normalize's
    `^...$` line-anchored regex)."""
    text = "## 1 Intro\n\nFinal paragraph with claim[^S1-1]."
    out, n = _synthesize_missing_defs(text, "S1", _EVIDENCE)
    assert n == 1
    # The blank line between body and def block must be present.
    assert "Final paragraph with claim[^S1-1].\n\n[^S1-1]:" in out


def test_synthesis_counts_unique_markers_not_total_occurrences():
    """When the writer reuses the same marker N times across the
    section (the documented the reference ~7× reuse pattern), synthesis
    must produce ONE def line per unique marker, not N."""
    text = "## 1 Intro\n\nFirst cite[^S1-1]. Reuse 1[^S1-1]. Reuse 2[^S1-1]. Reuse 3[^S1-1]. Reuse 4[^S1-1].\n"
    out, n = _synthesize_missing_defs(text, "S1", _EVIDENCE)
    assert n == 1  # one unique marker → one def
    # Only one def line appended.
    assert out.count("[^S1-1]:") == 1
