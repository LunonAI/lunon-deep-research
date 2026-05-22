"""Unit tests for deep_research.pipeline.numbering_fix (P2-F).

Verifies the cross-reference-aware renumbering: when a heading is renumbered,
any in-body cross-ref to its old number is rewritten to the new number.
Tests use small synthetic articles; the full 89-W9 validation lives in
scripts/p2_validate_f.py.
"""

from deep_research.pipeline.numbering_fix import (
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
