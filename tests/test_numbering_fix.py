"""Unit tests for deep_research.pipeline.numbering_fix (P2-F).

Verifies the cross-reference-aware renumbering: when a heading is renumbered,
any in-body cross-ref to its old number is rewritten to the new number.
Tests use small synthetic articles; the full 89-W9 validation lives in
scripts/p2_validate_f.py.
"""

from deep_research.pipeline.numbering_fix import (
    _normalize_hash_from_number,
    collapse_empty_sections,
    renumber_headings,
)
from deep_research.pipeline.numbering_fix import (
    run as numbering_fix_run,
)


def _extract_headings(text):
    """(hashes, title_with_num) tuples for every heading line."""
    import re

    return [(m.group(1), m.group(2)) for m in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text, re.MULTILINE)]


# --- Renumber-only cases (no cross-refs) -----------------------------------


def test_renumber_simple_tree():
    text = "# Title\n\n## Intro\n\nfoo\n\n## Method\n\nbar\n\n### Sub\n\nbaz\n"
    out, stats = renumber_headings(text)
    assert stats["applied"] is True
    assert stats["n_renumbered"] == 3
    assert stats["cross_refs_rewritten"] == 0
    assert stats["cross_refs_orphaned"] == 0
    hh = _extract_headings(out)
    assert hh == [("#", "Title"), ("##", "1 Intro"), ("##", "2 Method"), ("###", "2.1 Sub")]


def test_renumber_strips_existing_numeric_prefix():
    text = "# Title\n\n## 7 Wrong\n\nfoo\n\n## 8 Worse\n\nbar\n"
    out, _ = renumber_headings(text)
    hh = _extract_headings(out)
    assert hh == [("#", "Title"), ("##", "1 Wrong"), ("##", "2 Worse")]


def test_renumber_h5_demoted():
    text = "# T\n## A\n### B\n#### C\n##### D\n"
    out, stats = renumber_headings(text)
    assert stats["n_demoted"] == 1
    hh = _extract_headings(out)
    # H5 demotes to H4 and gets 1.1.2 (sibling of C at level 3-of-numbers).
    assert hh[-1] == ("####", "1.1.2 D")


# --- Cross-ref rewriting cases ---------------------------------------------


def test_xref_rewritten_section_keyword():
    """An article whose ## H2's old numbers don't match a clean tree:
    Alpha=2, Beta=3, Gamma=5. After renumber: Alpha=1, Beta=2, Gamma=3.
    Cross-refs to those old numbers should follow the new mapping."""
    text = (
        "# T\n\n"
        "## 2 Alpha\n\nintro paragraph here.\n\n"
        "## 3 Beta\n\nas covered in section 5 we see foo. see section 3 too.\n\n"
        "## 5 Gamma\n\ngamma body content.\n"
    )
    out, stats = renumber_headings(text)
    assert stats["cross_refs_rewritten"] == 2  # 5→3 in "covered in", 3→2 in "see section"
    # "as covered in section 5" → "as covered in section 3" (Gamma moved 5→3)
    assert "as covered in section 3" in out
    # "see section 3 too" → "see section 2 too" (Beta moved 3→2)
    assert "see section 2 too" in out
    # Old numbers should no longer appear as cross-refs.
    assert "section 5" not in out
    # Verify headings.
    hh = _extract_headings(out)
    assert ("##", "1 Alpha") in hh and ("##", "2 Beta") in hh and ("##", "3 Gamma") in hh


def test_xref_orphan_left_alone():
    """Cross-ref to a section number that doesn't exist in the heading map
    should be left as-is, with cross_refs_orphaned incremented."""
    text = "# T\n\n## 1 Alpha\n\nas shown in 99 we see nothing.\n\n## 2 Beta\n\nbody\n"
    out, stats = renumber_headings(text)
    assert stats["cross_refs_rewritten"] == 0
    assert stats["cross_refs_orphaned"] == 1
    assert "as shown in 99 we see nothing." in out


def test_xref_with_subsection_number():
    text = "# T\n\n## 4 Alpha\n\nfoo\n\n### 4.1 Sub\n\nsee §4.1 again. or §4 maybe.\n"
    out, stats = renumber_headings(text)
    # § 4 → § 1 (matches H2 Alpha old_num=4), § 4.1 → § 1.1 (matches H3 Sub).
    assert stats["cross_refs_rewritten"] == 2
    assert "§1.1" in out  # match either "§1.1" or "§ 1.1" depending on prefix preservation
    assert "§1" in out or "§ 1" in out
    assert "§4" not in out
    assert "§4.1" not in out


def test_xref_year_not_rewritten():
    """The cross-ref regex must not match 4-digit years."""
    text = "# T\n\n## 1 Alpha\n\nThe 2024 study by Foo et al. (2024) ...\n\n## 2 Beta\n\nbody\n"
    out, stats = renumber_headings(text)
    assert stats["cross_refs_rewritten"] == 0
    assert "2024 study" in out
    assert "(2024)" in out


def test_xref_punctuation_preserved():
    """Cross-ref followed by punctuation: 'see section 5.' should rewrite the
    number but preserve the trailing period."""
    text = "# T\n\n## 5 Alpha\n\nsee section 5. and section 5,\n\n## 6 Beta\n\nbody\n"
    out, stats = renumber_headings(text)
    assert stats["cross_refs_rewritten"] == 2
    assert "see section 1." in out
    assert "section 1," in out


# --- Correctness invariant: ref-target preserves conceptual section --------


def test_invariant_xref_points_to_same_heading_title():
    """The plan's F validation criterion: after renumber, every cross-ref must
    point to the same conceptual section it did before. Verified by title."""
    text = (
        "# T\n\n"
        "## 8 Alpha\n\nbody1\n\n"
        "## 3 Beta\n\nas shown in section 8 we see foo. section 3 too. section 11 missing.\n\n"
        "## 11 Gamma\n\nas covered in section 3 we see bar.\n"
    )
    # Pre-renumber: map old_num → title.
    pre_map = {"8": "Alpha", "3": "Beta", "11": "Gamma"}
    # Find all cross-refs in pre-text and their target titles.
    import re

    sub_re = re.compile(r"(?:section)\s+(\d{1,2}(?:\.\d+){0,3})\b", re.IGNORECASE)
    pre_targets = []
    for m in sub_re.finditer(text):
        num = m.group(1)
        pre_targets.append(pre_map.get(num))

    out, stats = renumber_headings(text)
    # Post-renumber: H2 sequence becomes 1, 2, 3.
    post_map = {"1": "Alpha", "2": "Beta", "3": "Gamma"}
    post_targets = []
    for m in sub_re.finditer(out):
        num = m.group(1)
        post_targets.append(post_map.get(num))
    # Every pre-target with a real heading should equal its post-target.
    # Orphans (None in pre_map) should remain orphans in post too.
    assert pre_targets == post_targets


# --- numbering_fix.run() integration ---------------------------------------


def test_run_carries_cross_ref_stats():
    # Bodies must be ≥10 words; collapse_empty_sections runs before renumber.
    text = (
        "# T\n\n"
        "## 5 Alpha\n\nthis is the alpha section body with enough words to survive collapse.\n\n"
        "## 6 Beta\n\nbeta body content here, with see section 5 as an explicit cross-reference inside.\n"
    )
    nfo = numbering_fix_run(text)
    assert nfo.cross_refs_rewritten == 1
    assert nfo.cross_refs_orphaned == 0
    assert nfo.renumbering_applied is True
    assert "see section 1" in nfo.article


def test_run_no_skip_on_cross_refs_anymore():
    """Pre-F behavior was to set renumbering_applied=False when cross-refs were
    present. Post-F always renumbers."""
    text = (
        "# T\n\n"
        "## 7 Alpha\n\nalpha section body with enough words to keep the collapse filter happy.\n\n"
        "## 8 Beta\n\nbeta section also long enough, with see section 7 reference inside the body.\n"
    )
    nfo = numbering_fix_run(text)
    assert nfo.renumbering_applied is True
    assert nfo.skipped_reason is None
    assert nfo.cross_refs_rewritten == 1


# --- P2-Option-A-#2: hash-from-number normalization ------------------------


def test_hash_norm_passthrough_correct_tree():
    """A correctly-emitted article (one H1 title, ## sections, ### subs) is
    untouched by the pre-pass."""
    text = "# Title\n\n## 1 Intro\n\n## 2 Method\n\n### 2.1 Sub\n\n#### 2.1.1 Deep\n"
    out, n = _normalize_hash_from_number(text)
    assert out == text
    assert n == 0


def test_hash_norm_demotes_writer_h1_section_bug():
    """The 99/100-W9 bug: writer emits `# 1. Section` (H1) for top sections."""
    text = "# Title\n\n# 1. Intro\n\n## 1.1.1 Scope\n\n# 1.2 Bronze\n"
    out, n = _normalize_hash_from_number(text)
    assert n == 3  # all three numbered headings rewritten
    headings = _extract_headings(out)
    assert headings[0] == ("#", "Title")  # title preserved
    assert headings[1] == ("##", "1. Intro")  # 1-dot → H2
    assert headings[2] == ("####", "1.1.1 Scope")  # 3-dot → H4
    assert headings[3] == ("###", "1.2 Bronze")  # 2-dot → H3


def test_hash_norm_caps_deep_numbers_at_h4():
    """A 4+-dot number gets capped to H4; renumber later compresses the
    number to fit the 3-numeric-level tree."""
    text = "# T\n\n## 1 A\n\n### 1.1 B\n\n#### 1.1.1 C\n\n##### 1.1.1.1 D\n"
    out, n = _normalize_hash_from_number(text)
    # Only the H5 line needed rewriting; everything else already correct.
    assert n == 1
    headings = _extract_headings(out)
    assert headings[-1] == ("####", "1.1.1.1 D")


def test_hash_norm_skips_unnumbered_headings():
    """Headings without a leading number are not modified — the report title
    and any prose-titled sections pass through untouched."""
    text = "# Title\n\n## Untitled section\n\n### 1.1 Numbered sub\n\n## Another untitled\n"
    out, n = _normalize_hash_from_number(text)
    # Only "1.1 Numbered sub" was a numbered-heading mismatch (H3 needed for
    # a 2-dot number; was already H3 in the input, so n=0).
    assert n == 0
    headings = _extract_headings(out)
    assert headings == [
        ("#", "Title"),
        ("##", "Untitled section"),
        ("###", "1.1 Numbered sub"),
        ("##", "Another untitled"),
    ]


def test_hash_norm_demotes_stray_h1_with_non_digit_prefix():
    """Real W9 case (id=2): writer prefixes a top section with `S6` (or
    `Part A`, `Section III`) — the digit-only number regex misses it, so
    we need the second-pass stray-H1 demotion to catch it."""
    text = "# Real Title\n\n# S6 Comparison\n\n# Appendix A\n"
    out, n = _normalize_hash_from_number(text)
    # Both stray H1s get demoted to H2.
    assert n == 2
    headings = _extract_headings(out)
    assert headings[0] == ("#", "Real Title")
    assert headings[1] == ("##", "S6 Comparison")
    assert headings[2] == ("##", "Appendix A")


def test_run_normalization_wired_into_pipeline():
    """End-to-end: bug-style article goes through run() and emerges with one
    H1, hash levels matching number depth, and the renumber step then makes
    the numbers sequential."""
    text = (
        "# Saint Seiya Report\n\n"
        "# 1. Introduction\n\n"
        "intro body long enough to survive empty-section collapse, talking about cosmos.\n\n"
        "## 1.1.1 Scope\n\n"
        "scope body long enough to survive empty-section collapse with content.\n\n"
        "# 1.2 Bronze\n\n"
        "bronze body long enough to survive empty-section collapse, talking about pegasus.\n"
    )
    nfo = numbering_fix_run(text)
    headings = _extract_headings(nfo.article)
    # First heading is the title; nothing else should be H1.
    assert headings[0][0] == "#"
    assert all(h[0] != "#" for h in headings[1:]), f"non-title H1 leaked through: {headings}"
    assert nfo.headings_hash_normalized >= 1


# --- P2-Option-A-#6 round-3 (Greptile PR #24): References protection -------


def test_collapse_protects_references_block_with_single_entry():
    """A single-citation `## References` block is ~6 body words — below the
    10-word `collapse_empty_sections` threshold. Without the protected-
    titles guard the entire block (heading + entry) gets silently dropped,
    leaving footnote_normalize_stats showing references were built while
    the shipped article has none."""
    text = (
        "## 1 Body\n\nplenty of body words here to keep the section, talking about evidence.\n\n"
        "## References\n\n[^1]: Source A 2025 — https://a.example.com\n"
    )
    cleaned, n_collapsed = collapse_empty_sections(text)
    assert "## References" in cleaned, f"References heading was dropped:\n{cleaned}"
    assert "[^1]: Source A 2025" in cleaned, "the bibliography entry was dropped with the heading"
    # The body section also survives (>=10 words), so 0 collapses total.
    assert n_collapsed == 0, f"unexpected collapses: {n_collapsed}"


def test_collapse_protects_references_block_with_zero_entries():
    """Pathological but possible: References heading with NO body at all
    (e.g. every citation was orphaned/unused). Even then the heading must
    survive — the collapse heuristic is for stub content sections, not
    structural anchors."""
    text = "## 1 Body\n\nbody words enough to survive collapse with margin to spare for sure.\n\n## References\n"
    cleaned, _ = collapse_empty_sections(text)
    assert "## References" in cleaned


def test_collapse_protects_zh_references_heading():
    """ZH-language articles emit `## 参考文献`. The protected set must
    cover EN+ZH+Sources, matching the existing
    `writing_rules.citation_strip_audit` regex
    `(References|参考文献|Sources)`. Without ZH coverage, ZH articles
    would silently lose their bibliography."""
    text = "## 1 正文\n\n正文需要足够多的字数才能通过空段折叠的阈值，因此这里加一些填充文字。\n\n## 参考文献\n\n[^1]: 来源 — https://a.example.com\n"
    cleaned, _ = collapse_empty_sections(text)
    assert "## 参考文献" in cleaned, f"ZH references heading was dropped:\n{cleaned}"


def test_collapse_protects_sources_heading_alias():
    """`## Sources` is the third name in the regex. Pin it too."""
    text = "## 1 Body\n\nbody words enough to survive collapse with margin to spare for sure.\n\n## Sources\n\n[^1]: X — https://x.example.com\n"
    cleaned, _ = collapse_empty_sections(text)
    assert "## Sources" in cleaned


def test_collapse_protects_numbered_references_heading():
    """Defensive: if the renumber step ever runs BEFORE collapse (e.g. a
    future reordering bug), the heading would arrive as
    `## 5 References`. The numeric-prefix normalization in
    `_is_protected_heading` must catch that form too."""
    text = "## 1 Body\n\nbody words enough to survive collapse with margin to spare for sure.\n\n## 5 References\n\n[^1]: X — https://x.example.com\n"
    cleaned, _ = collapse_empty_sections(text)
    assert "## 5 References" in cleaned


def test_collapse_still_drops_unrelated_short_section():
    """Negative case: a plain stub section like `## 4 Conclusion\\n\\nTBD.`
    must still get collapsed. The protected-titles set must NOT be a
    blanket exemption for low-content sections — only the named
    structural anchors."""
    text = (
        "## 1 Body\n\nplenty of body words here to keep the section, talking about evidence.\n\n"
        "## 4 Conclusion\n\nTBD.\n"
    )
    cleaned, n_collapsed = collapse_empty_sections(text)
    assert "## 4 Conclusion" not in cleaned, "non-protected stub section survived collapse"
    assert n_collapsed == 1


def test_collapse_protection_is_case_insensitive():
    """`## REFERENCES` (all caps from a writer that shouts) or `## references`
    (lowercase from a writer that doesn't) must both be recognised — case
    is not a real signal here."""
    for variant in ("## references", "## REFERENCES", "## ReFeReNcEs"):
        text = f"## 1 Body\n\nbody words enough to survive collapse with margin to spare for sure.\n\n{variant}\n\n[^1]: X — https://x.example.com\n"
        cleaned, _ = collapse_empty_sections(text)
        assert variant in cleaned, f"case variant {variant!r} was not protected"


def test_low_citation_article_full_pipeline_preserves_references():
    """End-to-end cross-module test: drive `footnote_normalize.normalize`
    on a 1-citation article (the exact failure shape Greptile flagged),
    then feed the result through `numbering_fix.run()` (the orchestrate
    ordering), and assert the References block survives. This catches
    any future regression where the protection is removed OR the
    orchestrator ordering changes in a way that re-introduces the bug."""
    from deep_research.pipeline import footnote_normalize

    article = "# Saint Seiya Report\n\n## 1 Bronze Saints\n\nPegasus Seiya is the protagonist[^S1-1]; he wears the Pegasus Cloth and trains under Mu of Aries on Sanctuary's Star Hill.\n\n[^S1-1]: Saint Seiya Encyclopedia 2024 — https://encyclopedia.example.com/saint-seiya\n"
    fno = footnote_normalize.normalize(article)
    # Sanity: footnote_normalize built the block.
    assert fno.n_renumbered == 1
    assert "## References" in fno.article
    # Now run the deterministic post-edit pipeline as orchestrate does.
    nfo = numbering_fix_run(fno.article)
    # The shipped article MUST still have the References block AND the entry.
    assert "References" in nfo.article, f"References block lost in numbering_fix:\n{nfo.article}"
    assert "[^1]:" in nfo.article, "the bibliography entry was stripped"
    # And sections_collapsed should not count the References block (the body
    # section is well above 10 words, so 0 total collapses on this input).
    assert nfo.sections_collapsed == 0, (
        f"sections_collapsed={nfo.sections_collapsed} — the References block "
        f"or another structural section was collapsed unexpectedly"
    )


if __name__ == "__main__":
    # Quick smoke run if invoked directly.
    import sys

    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for f in funcs:
        try:
            f()
            print(f"PASS {f.__name__}")
        except AssertionError as e:
            failed.append((f.__name__, e))
            print(f"FAIL {f.__name__}: {e}")
        except Exception as e:
            failed.append((f.__name__, e))
            print(f"ERROR {f.__name__}: {e}")
    if failed:
        sys.exit(1)
    print(f"\n{len(funcs)} tests passed")
