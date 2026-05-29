"""Unit tests for P3-W3 — xref_repair post-write pass.

Belt-and-braces against two failure modes the writer occasionally produces
despite the in-prompt rules:
  1. Chapter-opening "Building on §X" templates leaking in (Wave-3 §12.A.v4
     reduced these to 0% in the W3 smoke; repair is regression safety net).
  2. Dangling forward-refs (`§47` in an article ending at §40, or `§5.16`
     when chapter 5 renders only §5.1–§5.4).

G2 (2026-05-28): dangling refs are now EXCISED (with orphan-glue cleanup),
not rewritten to "a later section". G12 (2026-05-28): a `§N.M` is dangling
unless `§N.M` (or a deeper `§N.M.x`) actually renders — the prior
top-chapter exemption is gone. Tests pin idempotency, fail-soft on bad
input, the excise-vs-delete branching, and that "a later section" never
appears in repaired output.
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


def test_repair_excises_dangling_forward_ref():
    """A §N where N is not in the heading set is EXCISED (G2), with the
    surrounding prose left clean — never rewritten to 'a later section'."""
    text = "## 1 Intro\n\n## 2 Body\n\nThe topic is examined further elsewhere (Section 99). Other content surrounds."
    out, stats = repair(text)
    assert stats["dangling_refs_excised"] >= 1, f"got {stats}; out={out!r}"
    assert "Section 99" not in out
    assert "a later section" not in out
    # The ref was excised and the space-before-period seam cleaned up.
    assert "examined further elsewhere. Other content surrounds." in out


def test_repair_deletes_sentence_when_only_clause_is_dangling_ref():
    """A sentence whose ONLY meaningful clause is the dangling §N gets deleted."""
    text = "## 1 Intro\n\n## 2 Body\n\nReal sentence one. See (Section 99). Final sentence."
    out, stats = repair(text)
    # The "See (Section 99)." sentence has <15 chars of residual content
    # after stripping the ref → deleted.
    assert stats["sentences_deleted"] >= 1, f"got {stats}"
    assert "Section 99" not in out
    assert "a later section" not in out
    assert "Real sentence one." in out
    assert "Final sentence." in out


def test_repair_preserves_legitimate_xrefs():
    """References to existing chapters/sections (incl. rendered sub-sections)
    survive unchanged. The §3.1 ref is legitimate ONLY because `### 3.1`
    actually renders — see test_repair_excises_ref_to_unrendered_subsection
    for the G12 counter-case."""
    text = (
        "## 1 Intro\n\n## 2 Body\n\n## 3 More\n\n### 3.1 Detail\n\n"
        "See (Section 2) for context and (Section 3.1) for detail."
    )
    out, stats = repair(text)
    assert "(Section 2)" in out
    assert "(Section 3.1)" in out
    assert stats["dangling_refs_excised"] == 0
    assert stats["sentences_deleted"] == 0


def test_repair_excises_ref_to_unrendered_subsection():
    """G12: `§5.16` is dangling when chapter 5 renders only §5.1 — the prior
    top-chapter exemption (any N.M valid if chapter N exists) is removed."""
    text = "## 5 Five\n\n### 5.1 Sub\n\nThe mechanism is detailed in (Section 5.16) at length. More prose surrounds it."
    out, stats = repair(text)
    assert stats["dangling_refs_excised"] >= 1, f"§5.16 not flagged dangling: {stats}; {out!r}"
    assert "5.16" not in out
    assert "a later section" not in out
    # The legitimately-rendered §5.1 chapter/heading is untouched.
    assert "### 5.1 Sub" in out


def test_repair_excises_range_ref_without_orphan_dash():
    """G2: a dangling ref inside a numeric range ('§9–§15', §15 dangling) is
    excised together with its orphan range dash — no trailing '§9–' leak."""
    text = "## 9 Nine\n\nThe arc spans §9–§15 across the saga. The remainder is summarized after."
    out, stats = repair(text)
    assert stats["dangling_refs_excised"] >= 1, f"got {stats}; {out!r}"
    assert "§15" not in out
    assert "a later section" not in out
    # The valid §9 survives; the orphan en-dash that the excision would have
    # left ("§9–") must be gone.
    assert "§9" in out
    assert "§9–" not in out and "§9 –" not in out


def test_repair_excises_consecutive_list_refs_without_orphan_commas():
    """G2: a run of dangling refs in a list ('§5.16, §5.31, §5.42') is excised
    with the orphan list commas cleaned up — no ', ,' leak."""
    text = (
        "## 5 Five\n\n### 5.1 Sub\n\n"
        "Clues are scattered across §5.16, §5.31, and §5.42 throughout the work. End sentence here."
    )
    out, stats = repair(text)
    assert stats["dangling_refs_excised"] >= 1, f"got {stats}; {out!r}"
    for ref in ("5.16", "5.31", "5.42"):
        assert ref not in out, f"{ref} survived: {out!r}"
    assert "a later section" not in out
    assert ", ," not in out and " , " not in out, f"orphan list comma leaked: {out!r}"
    assert "End sentence here." in out


def test_repair_never_emits_a_later_section():
    """Regression pin: 'a later section' (the retired G2 rewrite token) must
    NEVER appear in repaired output, across a mix of dangling-ref shapes."""
    text = (
        "## 1 Intro\n\n## 2 Body\n\n"
        "Bare ref §99 appears here mid-sentence with content. "
        "A parenthetical (Section 88) sits inside this clause too. "
        "A range §2–§77 and a list §5.16, §5.31 round it out, with prose after."
    )
    out, _ = repair(text)
    assert "a later section" not in out, f"retired rewrite token leaked: {out!r}"


def test_repair_preserves_legitimate_xrefs_returns_zero():
    """References to existing chapters survive; no excision/deletion fires."""
    text = "## 1 Intro\n\n## 2 Body\n\n## 3 More\n\nSee (Section 2) and (Section 3) for context here."
    out, stats = repair(text)
    assert "(Section 2)" in out and "(Section 3)" in out
    assert stats["dangling_refs_excised"] == 0
    assert stats["sentences_deleted"] == 0


def test_repair_is_idempotent():
    """Running repair() twice produces the same output."""
    text = (
        "## 2 Foo\n\nBuilding on §1 established earlier, this section continues.\n\n"
        "Substantive paragraph (Section 99) hallucinated ref with lots of trailing prose. End."
    )
    out_1, _ = repair(text)
    out_2, stats_2 = repair(out_1)
    assert out_1 == out_2, "second repair pass changed the output"
    # Second pass should find nothing to repair
    assert stats_2["templates_repaired"] == 0
    assert stats_2["dangling_refs_excised"] == 0


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
    expected = {"templates_repaired", "dangling_refs_excised", "sentences_deleted"}
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

    Post-fix, the `\n\n` separator from the deleted sentence is carried
    forward onto the preceding separator slot so structural whitespace
    is preserved.
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
    """The boundary-preservation must hold even on the dangling-ref excise
    branch (the path that previously did `out_parts.append(...)` + final
    `" ".join`). This routes through the path Greptile flagged."""
    text = (
        "## 1 Intro\n\n## 2 Body\n\n"
        "Real sentence (Section 99) hallucinated mid-clause with plenty of trailing prose. End of paragraph.\n\n"
        "## 3 More\n\nNext chapter prose.\n"
    )
    out, stats = repair(text)
    # Repair fired on the dangling ref.
    assert stats["dangling_refs_excised"] + stats["sentences_deleted"] >= 1
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
    heading included — was silently deleted pre-fix.

    Fix: when the token contains a markdown heading line, route to
    the excise path (heading preserved, dangler excised) instead of
    the delete path.
    """
    text = "## 1 Results\n\nSee (Section 47).\n\n## 2 Body\n\nContent here is fine.\n"
    out, stats = repair(text)
    # The heading MUST survive.
    assert "## 1 Results" in out, f"heading silently destroyed: {out!r}"
    # The dangler must have been excised (not rewritten, not deleted).
    assert "a later section" not in out, f"retired rewrite token leaked: {out!r}"
    assert "(Section 47)" not in out
    # The delete path must NOT have fired — heading guard routes to excise.
    assert stats["sentences_deleted"] == 0, f"heading-rooted token wrongly deleted: {stats}; {out!r}"
    assert stats["dangling_refs_excised"] >= 1
    # Downstream content is unaffected.
    assert "## 2 Body" in out
    assert "Content here is fine." in out


def test_repair_heading_guard_covers_common_short_chapter_names():
    """Greptile PR #39 round-3 issue #1: parameterized verification
    that each of the canonical short-name chapters Greptile called out
    ("Summary", "Results", "Overview", "Methods") survives a
    dangler-only first sentence."""
    short_names = ("Summary", "Results", "Overview", "Methods")
    for name in short_names:
        text = f"## 1 {name}\n\nSee (Section 99).\n\n## 2 Body\n\nReal content here.\n"
        out, _stats = repair(text)
        assert f"## 1 {name}" in out, f"heading `## 1 {name}` destroyed by repair (output: {out!r})"
        assert "## 2 Body" in out
        assert "a later section" not in out


def test_repair_strips_lowercase_building_on_template():
    r"""Greptile PR #39 round-3 issue #2: `_OPENING_TEMPLATE_PATTERN`
    previously had no `re.I` flag, so only Title-Case "Building on"
    templates were stripped. Adding `re.I` aligns repair() with the
    auditor's case-insensitive `opening_template_pattern`.
    """
    text = "## 2 Foo\n\nbuilding on §1 established earlier, this section continues. Substantive content follows here."
    out, stats = repair(text)
    assert stats["templates_repaired"] == 1, f"lowercase template not stripped: {stats}; out={out!r}"
    assert "building on" not in out.lower(), f"lowercase template leaked through: {out!r}"
    # Heading and downstream prose retained.
    assert "## 2 Foo" in out
    assert "Substantive content follows here." in out


def test_repair_lowercase_template_strip_does_not_false_positive_in_prose():
    """Symmetric to test_repair_preserves_legitimate_text_in_forbidden_block:
    the `re.I` flag must NOT cause mid-paragraph lowercase 'building on'
    to be flagged."""
    text = (
        "## 1 Intro\n\n"
        "The author's strategy of building on prior work shapes the discussion. "
        "Specifically (Section 2)…\n\n"
        "## 2 Body\n\n"
    )
    out, stats = repair(text)
    assert stats["templates_repaired"] == 0, f"mid-paragraph false positive: {stats}; out={out}"
    assert "building on prior work" in out


def test_repair_heading_guard_does_not_excise_chapter_title_text():
    r"""Greptile PR #39 round-4 (carried into G2): the heading-guard path
    must apply excision to BODY lines only. `ref_pattern`'s third
    alternation `(?:Section|Chapter|Sec\.)\s+([\d\.]+)\b` matches title
    words like "Chapter 47" in a heading `## 5 Chapter 47 Overview`. If
    47 is dangling, a whole-token sub would corrupt the heading.

    This test pins:
      (a) the heading title "Chapter 47" survives verbatim even though
          47 is not in the heading-id set;
      (b) the BODY dangler `(Section 47)` IS excised.
    """
    text = (
        "## 5 Chapter 47 Overview\n\n"
        "See (Section 47).\n\n"  # dangling body ref → excise
        "## 6 Next\n\nNext chapter prose is here.\n"
    )
    out, stats = repair(text)
    # (a) Heading title must NOT have been corrupted.
    assert "## 5 Chapter 47 Overview" in out, f"heading title excised by ref_pattern: {out!r}"
    assert "a later section" not in out
    # (b) Body dangler excised.
    assert "(Section 47)" not in out, f"body dangler not excised: {out!r}"
    # Stats: heading-routed path uses excise, so the excise counter
    # increments; the delete counter stays zero (heading-guard preempts it).
    assert stats["dangling_refs_excised"] >= 1
    assert stats["sentences_deleted"] == 0
    # Downstream chapter unaffected.
    assert "## 6 Next" in out
    assert "Next chapter prose is here." in out


def test_repair_heading_guard_preserves_multiple_heading_lines_verbatim():
    """When the token contains multiple consecutive heading lines, every
    heading line must survive verbatim — none should have excision applied
    even when their titles contain `Section N` / `Chapter N` patterns."""
    text = "## 5 Chapter 47 Overview\n\n### 5.1 Section 99 Subtopic\n\nSee (Section 47).\n\n## 6 Done\n\nLast prose.\n"
    out, _ = repair(text)
    # Both heading titles must survive — neither "Chapter 47" nor
    # "Section 99" should be excised by the body-xref pass.
    assert "## 5 Chapter 47 Overview" in out, f"H2 title corrupted: {out!r}"
    assert "### 5.1 Section 99 Subtopic" in out, f"H3 title corrupted: {out!r}"
    # Body dangler excised, no retired rewrite token.
    assert "(Section 47)" not in out
    assert "a later section" not in out
