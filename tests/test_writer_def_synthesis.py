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
    section (the documented Qianfan ~7× reuse pattern), synthesis
    must produce ONE def line per unique marker, not N."""
    text = "## 1 Intro\n\nFirst cite[^S1-1]. Reuse 1[^S1-1]. Reuse 2[^S1-1]. Reuse 3[^S1-1]. Reuse 4[^S1-1].\n"
    out, n = _synthesize_missing_defs(text, "S1", _EVIDENCE)
    assert n == 1  # one unique marker → one def
    # Only one def line appended.
    assert out.count("[^S1-1]:") == 1


# ---- Wave 2 PR #30 self-review: name-based mapping fallback (Tier 1) ----


def test_synthesis_name_based_mapping_when_writer_used_wrong_number():
    """The writer ignored the pre-assigned numbering and cited atom #3
    (Lebrun) as `[^S1-1]`. The body has "as Lebrun (1999) showed[^S1-1]"
    explicitly naming the source. Name-based Tier 1 lookup must override
    the index-based fallback so the def line correctly attributes
    Lebrun to S1-1 (not McKinsey, which is atom #1 by index)."""
    text = "## 1 Intro\n\nPer Lebrun (1999), the auction theory holds[^S1-1]. Other prior work disagrees.\n"
    out, n = _synthesize_missing_defs(text, "S1", _EVIDENCE)
    assert n == 1
    # Lebrun is _EVIDENCE[2] (index 2, marker S1-3 by Wave 2 contract).
    # But the body's name context attributes S1-1 to Lebrun explicitly,
    # so the synthesized def must use Lebrun's metadata.
    assert "[^S1-1]: Lebrun (1999) — https://example.com/lebrun" in out
    # And the WRONG mapping (McKinsey via index) must NOT appear.
    assert "[^S1-1]: McKinsey" not in out


def test_synthesis_falls_back_to_index_when_no_name_match():
    """When the marker's citation context doesn't name any atom's
    source (the writer wrote 'as the analysis shows[^S1-2]' with no
    attribution), Tier 2 index-based mapping fires (marker N → atom
    N-1). Verifies the fallback ladder works correctly."""
    text = "## 1 Intro\n\nThe analysis shows three findings[^S1-2]. Details follow.\n"
    out, n = _synthesize_missing_defs(text, "S1", _EVIDENCE)
    assert n == 1
    # S1-2 → atom index 1 → Gartner (no url, see _EVIDENCE fixture).
    assert "[^S1-2]: Gartner (2024)" in out


def test_synthesis_name_window_bounded_by_paragraph():
    """Greptile-style edge case: a writer-emitted def line for `[^S1-1]`
    naming "McKinsey (2025)" must NOT bleed into the name-window of
    `[^S1-2]` in an adjacent paragraph. Paragraph boundaries (≥2
    consecutive newlines) cap the window so def-line metadata doesn't
    misattribute neighbors. Pin so a future window-widening can't
    re-introduce the bleed."""
    text = (
        "## 1 Intro\n\n"
        "Per Source A[^S1-1].\n\n"  # paragraph 1: marker S1-1, no source name
        '[^S1-1]: McKinsey (2025), "Report A," McKinsey Quarterly.\n\n'
        "Per the second source[^S1-2].\n"  # paragraph 3: marker S1-2, no source name
    )
    out, n = _synthesize_missing_defs(text, "S1", _EVIDENCE)
    # S1-1 already defined (writer-emitted) → skip.
    # S1-2 → name-based lookup finds NO source name in its paragraph
    # (paragraph 3 has no atom names), so Tier 2 index fires:
    # S1-2 → atom index 1 → Gartner.
    assert n == 1
    assert "[^S1-2]: Gartner (2024)" in out
    # And McKinsey must NOT have been attributed to S1-2 via window bleed.
    assert "[^S1-2]: McKinsey" not in out


def test_writer_prompt_carries_wrong_marker_number_forbidden_example():
    """Wave 2 PR #30 self-review: the CITATION CONTRACT must include a
    FORBIDDEN section calling out wrong-marker-number renumbering (the
    failure mode the name-based fallback was added to recover from).
    Pin so the prompt safeguard isn't silently dropped."""
    import inspect

    from deep_research.pipeline import writer as writer_module

    src = inspect.getsource(writer_module.write_section)
    # The FORBIDDEN section must explicitly call out the renumbering
    # anti-pattern (writer picking own marker numbers instead of using
    # atom's pre-assigned marker).
    assert "picking your own marker numbers" in src or "do NOT renumber" in src.lower(), (
        "CITATION CONTRACT must include an explicit FORBIDDEN clause "
        "for wrong-marker-number renumbering (Wave 2 PR #30 self-review)."
    )
