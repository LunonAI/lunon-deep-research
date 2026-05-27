"""Unit tests for P3-W3 — xref_repair post-write pass.

Belt-and-braces against two failure modes the writer occasionally produces
despite the in-prompt rules:
  1. Chapter-opening "Building on §X" templates leaking in (Wave-3 §12.A.v4
     reduced these to 0% in the W3 smoke; repair is regression safety net).
  2. Dangling forward-refs (`§47` in an article ending at §40).

Tests pin idempotency, fail-soft on bad input, and the dangling-rewrite vs
sentence-delete branching logic.
"""

from deep_research.pipeline.xref_repair import repair


def test_repair_replaces_building_on_template_with_clean_intro():
    """Chapter opening 'Building on §1 established in §2, this section…'
    has the offending sentence stripped; heading + downstream prose retained."""
    text = "## 2 Foo\n\nBuilding on §1 established earlier, this section continues. Substantive content follows here."
    out, stats = repair(text)
    assert stats["templates_repaired"] == 1
    assert "Building on" not in out
    assert "Substantive content follows here." in out
    # Heading line preserved
    assert "## 2 Foo" in out


def test_repair_rewrites_dangling_forward_ref_to_a_later_section():
    """A §N where N is not in the heading set is rewritten to
    'a later section', preserving the surrounding prose."""
    text = "## 1 Intro\n\n## 2 Body\n\nWe will cover this in (Section 99) in detail. Other content surrounds."
    out, stats = repair(text)
    assert stats["dangling_refs_rewritten"] >= 1, f"got {stats}; out={out!r}"
    assert "Section 99" not in out
    assert "a later section" in out
    assert "Other content surrounds." in out


def test_repair_deletes_sentence_when_only_clause_is_dangling_ref():
    """A sentence whose ONLY meaningful clause is the dangling §N gets deleted."""
    text = "## 1 Intro\n\n## 2 Body\n\nReal sentence one. See (Section 99). Final sentence."
    out, stats = repair(text)
    # The "See (Section 99)." sentence has <15 chars of residual content
    # after stripping the ref → deleted.
    assert stats["sentences_deleted"] >= 1, f"got {stats}"
    assert "Section 99" not in out
    assert "Real sentence one." in out
    assert "Final sentence." in out


def test_repair_preserves_legitimate_xrefs():
    """References to existing chapters/sections survive unchanged."""
    text = "## 1 Intro\n\n## 2 Body\n\n## 3 More\n\nSee (Section 2) for context and (Section 3.1) for detail."
    out, stats = repair(text)
    assert "(Section 2)" in out
    assert stats["dangling_refs_rewritten"] == 0
    assert stats["sentences_deleted"] == 0


def test_repair_is_idempotent():
    """Running repair() twice produces the same output."""
    text = (
        "## 2 Foo\n\nBuilding on §1 established earlier, this section continues.\n\n"
        "Substantive paragraph (Section 99) hallucinated ref. End."
    )
    out_1, _ = repair(text)
    out_2, stats_2 = repair(out_1)
    assert out_1 == out_2, "second repair pass changed the output"
    # Second pass should find nothing to repair
    assert stats_2["templates_repaired"] == 0
    assert stats_2["dangling_refs_rewritten"] == 0


def test_repair_handles_empty_input_gracefully():
    """Empty string → empty string, no stats."""
    out, stats = repair("")
    assert out == ""
    assert all(v == 0 for v in stats.values())


def test_repair_handles_none_input_gracefully():
    """None → None passthrough, no crash."""
    out, stats = repair(None)
    assert out is None
    assert all(v == 0 for v in stats.values())


def test_repair_handles_non_string_input_gracefully():
    """Non-string (e.g. list, dict) → passthrough."""
    out, stats = repair(["not a string"])
    assert out == ["not a string"]
    assert all(v == 0 for v in stats.values())


def test_repair_returns_required_stats_keys():
    """Pin the stats dict keys."""
    _, stats = repair("## 1 X\n\nbody")
    expected = {"templates_repaired", "dangling_refs_rewritten", "sentences_deleted"}
    assert set(stats.keys()) == expected, f"got {set(stats.keys())}"


def test_repair_preserves_paragraph_boundaries_before_next_heading():
    r"""Greptile PR #39 round-2 issue #1: the prior `re.split(r"(?<=[.!?])\s+")`
    + `" ".join(...)` collapsed every `\n\n` separator into a single space,
    pushing the next `## N` heading INLINE with the preceding sentence and
    silently breaking markdown rendering. This test feeds a canonical
    paragraph-then-heading shape and confirms the `\n\n` separator is
    preserved verbatim."""
    text = (
        "## 1 Intro\n\n"
        "First sentence in paragraph one. Second sentence here.\n\n"
        "## 2 Body\n\nThird sentence in chapter two.\n"
    )
    out, _ = repair(text)
    # Critical: `## 2 Body` must remain at the start of a line.
    assert "\n\n## 2 Body" in out, f"paragraph→heading separator collapsed: {out!r}"
    # The separator must NOT have been replaced by a single space.
    assert "Second sentence here. ## 2 Body" not in out, f"sentence and heading collapsed inline: {out!r}"


def test_repair_preserves_paragraph_boundary_when_dangler_only_sentence_deleted():
    r"""Greptile PR #39 round-2 (round-2 follow-up): when a dangler-only
    sentence sits at the end of a paragraph (its trailing separator is
    `\n\n`), the DELETE path previously discarded both the sentence AND
    its sep — collapsing the following `## N` heading inline with the
    preceding sentence and silently producing invalid markdown.

    Concrete failure case (from the Greptile report):
      "## 1 Intro\n\nReal content. See (Section 99).\n\n## 2 Body"
    Pre-fix, repair produced:
      "## 1 Intro\n\nReal content. ## 2 Body"  ← heading inlined
    Post-fix, the `\n\n` separator from the deleted sentence is carried
    forward onto the preceding separator slot so structural whitespace
    is preserved.

    The complementary REWRITE path already preserved sep unconditionally
    (test_repair_preserves_paragraph_boundaries_with_dangling_ref_present);
    this test pins symmetry for the delete path.
    """
    text = "## 1 Intro\n\nReal content. See (Section 99).\n\n## 2 Body\n\nNext chapter prose.\n"
    out, stats = repair(text)
    # The dangler-only sentence ("See (Section 99).") must have been deleted —
    # the residual after stripping "(Section 99)" is "See ." which is <15 chars.
    assert stats["sentences_deleted"] >= 1, f"expected a delete on dangler-only sentence: {stats}"
    # Critical: the `## 2 Body` heading must remain block-level (preceded
    # by `\n\n`), not collapsed inline with "Real content.".
    assert "\n\n## 2 Body" in out, f"delete-path dropped trailing sep: {out!r}"
    assert "Real content. ## 2 Body" not in out, f"heading inlined after delete: {out!r}"
    # And the surviving "Real content." text is still present (the delete
    # must not have over-reached).
    assert "Real content." in out


def test_repair_delete_path_preserves_multi_paragraph_structure():
    r"""Greptile PR #39 round-2 follow-up: even when multiple dangler-only
    sentences are deleted in sequence, the structural `\n\n` boundaries
    around them must survive — the most newline-rich sep in the run wins."""
    text = (
        "## 1 Intro\n\n"
        "Real content here ends paragraph.\n\n"
        "See (Section 99). See (Section 98).\n\n"  # both dangler-only → both deleted
        "## 2 Body\n\nNext chapter prose.\n"
    )
    out, stats = repair(text)
    assert stats["sentences_deleted"] >= 2, f"expected ≥2 deletes, got {stats}"
    # The paragraph break before `## 2 Body` survives both deletions.
    assert "\n\n## 2 Body" in out, f"sep lost across multi-delete run: {out!r}"


def test_repair_preserves_paragraph_boundaries_with_dangling_ref_present():
    """The boundary-preservation must hold even on the dangling-ref repair
    branch (the path that previously did `out_parts.append(...)` + final
    `" ".join`). This routes through the path Greptile flagged."""
    text = (
        "## 1 Intro\n\n## 2 Body\n\n"
        "Real sentence (Section 99) hallucinated. End of paragraph.\n\n"
        "## 3 More\n\nNext chapter prose.\n"
    )
    out, stats = repair(text)
    # Repair fired on the dangling ref.
    assert stats["dangling_refs_rewritten"] + stats["sentences_deleted"] >= 1
    # The `## 3 More` heading must remain at line start.
    assert "\n\n## 3 More" in out, f"separator collapsed near repair site: {out!r}"
    assert "## 3 More\n\nNext chapter prose." in out


def test_repair_handles_dotted_section_numbers_in_building_on_template():
    """Greptile PR #39 round-2 issue #2: `[^.]*\\.` stopped at the FIRST
    dot, which in "Building on §1.2 established in §3, this section…"
    matched the embedded decimal dot in `§1.2` and left
    `.2 established in §3, this section…` stranded as an orphan
    fragment. The corrected pattern (`\\.(?=\\s|$)`) requires a
    sentence-end-style dot, so `§1.2` is skipped."""
    text = (
        "## 2 Foo\n\n"
        "Building on §1.2 established in §3, this section covers Pegasus mechanics. "
        "Substantive content follows after.\n"
    )
    out, stats = repair(text)
    assert stats["templates_repaired"] == 1, f"template not detected: {stats}; {out!r}"
    # The orphan fragment that the old pattern left behind must NOT appear:
    assert ".2 established in" not in out, f"orphan decimal fragment leaked: {out!r}"
    assert "Building on" not in out
    # Heading + downstream prose intact.
    assert "## 2 Foo" in out
    assert "Substantive content follows after." in out


def test_repair_preserves_legitimate_text_in_forbidden_block():
    """Defensive: if the literal 'Building on' string appears INSIDE a
    legitimate sentence mid-paragraph (not at chapter open), it's NOT
    flagged. The regex matches `^##` heading immediately followed by
    'Building on'."""
    text = (
        "## 1 Intro\n\n"
        "The author's strategy of building on prior work shapes the discussion. "
        "Specifically (Section 2)…\n\n"
        "## 2 Body\n\n"
    )
    out, stats = repair(text)
    assert stats["templates_repaired"] == 0, f"false positive: {stats}; out={out}"
    assert "building on prior work" in out


def test_repair_does_not_destroy_heading_with_short_name_when_first_sentence_is_dangler():
    r"""Greptile PR #39 round-3 issue #1: the sentence splitter
    `re.split(r"((?<=[.!?])\s+)", text)` cannot place a split-point
    BEFORE a chapter heading (headings don't end in `.!?`), so a
    heading is always grouped with the first body sentence into a
    single token. When that first sentence is a dangler-only
    reference, the residual computation INCLUDES the heading
    characters. For short chapter names ("Results", "Summary",
    "Overview", "Methods" — all ≤7 letters), the combined residual
    falls below the 15-char delete threshold, and the entire token —
    heading included — is silently deleted.

    Concrete failure (the exact case Greptile reported):
      "## 1 Results\n\nSee (Section 47).\n\n## 2 Body\n\nContent."
    Residual after stripping "(Section 47)" = "##1ResultsSee" = 13
    chars < 15 → pre-fix, the WHOLE token "## 1 Results\n\nSee
    (Section 47)." was deleted, removing the `## 1 Results` heading
    from the article. Post-write data loss in a chapter-structural
    element.

    Fix: when the token contains a markdown heading line, route to
    the rewrite path (heading preserved, dangler swapped for "a later
    section") instead of the delete path.
    """
    text = "## 1 Results\n\nSee (Section 47).\n\n## 2 Body\n\nContent here is fine.\n"
    out, stats = repair(text)
    # The heading MUST survive.
    assert "## 1 Results" in out, f"heading silently destroyed: {out!r}"
    # The dangler must have been rewritten (not deleted) — the rewrite path
    # path swaps it for "a later section".
    assert "a later section" in out, f"dangler not rewritten on heading path: {out!r}"
    assert "(Section 47)" not in out
    # The delete path must NOT have fired — heading guard routes to rewrite.
    assert stats["sentences_deleted"] == 0, f"heading-rooted token wrongly deleted: {stats}; {out!r}"
    assert stats["dangling_refs_rewritten"] >= 1
    # Downstream content is unaffected.
    assert "## 2 Body" in out
    assert "Content here is fine." in out


def test_repair_heading_guard_covers_common_short_chapter_names():
    """Greptile PR #39 round-3 issue #1: parameterized verification
    that each of the canonical short-name chapters Greptile called out
    ("Summary", "Results", "Overview", "Methods") survives a
    dangler-only first sentence. Pre-fix every one of these would have
    silently lost the heading; post-fix every heading must appear in
    the repaired output."""
    short_names = ("Summary", "Results", "Overview", "Methods")
    for name in short_names:
        text = f"## 1 {name}\n\nSee (Section 99).\n\n## 2 Body\n\nReal content here.\n"
        out, _stats = repair(text)
        assert f"## 1 {name}" in out, f"heading `## 1 {name}` destroyed by repair (output: {out!r})"
        assert "## 2 Body" in out


def test_repair_strips_lowercase_building_on_template():
    r"""Greptile PR #39 round-3 issue #2: `_OPENING_TEMPLATE_PATTERN`
    previously had no `re.I` flag, so only Title-Case "Building on"
    templates were stripped by `repair()`. But the auditor's
    `opening_template_pattern` in `writing_rules.check_xref_quality`
    uses `re.I` and flags lowercase variants too. A model regression
    that emitted lowercase `"## 2 Foo\n\nbuilding on §1 …"` would slip
    past `repair()` unchanged while the auditor reported
    `opening_template_violations=1` — a false divergence between what
    the post-write pass "repaired" and what the auditor sees. Adding
    `re.I` to the repair pattern aligns both passes.
    """
    # Same fixture as test_repair_replaces_building_on_template_with_clean_intro
    # but with a lowercase 'b' to exercise the re.I codepath.
    text = "## 2 Foo\n\nbuilding on §1 established earlier, this section continues. Substantive content follows here."
    out, stats = repair(text)
    assert stats["templates_repaired"] == 1, f"lowercase template not stripped: {stats}; out={out!r}"
    assert "building on" not in out.lower(), f"lowercase template leaked through: {out!r}"
    # Heading and downstream prose retained.
    assert "## 2 Foo" in out
    assert "Substantive content follows here." in out


def test_repair_lowercase_template_strip_does_not_false_positive_in_prose():
    """Symmetric to test_repair_preserves_legitimate_text_in_forbidden_block:
    the `re.I` flag added in round-3 must NOT cause mid-paragraph
    lowercase 'building on' to be flagged. The `^##` anchor (no
    letters) already prevents this regardless of the flag, but pin
    the invariant explicitly."""
    text = (
        "## 1 Intro\n\n"
        "The author's strategy of building on prior work shapes the discussion. "
        "Specifically (Section 2)…\n\n"
        "## 2 Body\n\n"
    )
    out, stats = repair(text)
    assert stats["templates_repaired"] == 0, f"mid-paragraph false positive: {stats}; out={out}"
    assert "building on prior work" in out
