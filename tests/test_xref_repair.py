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
