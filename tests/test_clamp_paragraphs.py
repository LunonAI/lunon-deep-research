"""Tests for the round-4 W4 paragraph-density clamp (style_clamp.clamp_paragraphs).

The dev8 gemini judge flagged our prose as "suffocating equal-intensity density /
wall of text"; the L6/L8 prompt rules were already active and did not move it.
clamp_paragraphs is the deterministic root-cause fix: it splits overlong prose
paragraphs at their EXISTING sentence boundaries (never rewriting a sentence) so a
dense block becomes several scannable ones, with zero grammar/content risk.
"""

import re

from deep_research.pipeline import style_clamp


def _nospace(t: str) -> str:
    return re.sub(r"\s", "", t)


def test_splits_wall_of_text_at_sentence_boundaries():
    # ~11 words/sentence × 16 = ~176 words, well over the EN ceiling of 120.
    sent = "The model achieves strong results across benchmarks and shows clear gains. "
    wall = (sent * 16).strip()
    art = f"# Title\n\n## 1 Chapter\n\n{wall}\n"
    out, stats = style_clamp.clamp_paragraphs(art, language="en")
    assert stats["paragraphs_split"] == 1
    assert stats["breaks_inserted"] >= 1
    # Every non-whitespace char is preserved (only paragraph breaks inserted).
    assert _nospace(art) == _nospace(out)


def test_content_preserving_and_protects_blocks():
    sent = "The model achieves strong results across benchmarks and shows clear gains. "
    wall = (sent * 16).strip()
    art = (
        "# Title\n\n## 1 Chapter\n\n"
        f"{wall}\n\n"
        "| col | col |\n| --- | --- |\n| a | b |\n\n"
        "- list item one stays intact\n- list item two stays intact\n\n"
        "```\ncode block stays\nintact across blanks\n```\n\n"
        "Short paragraph stays untouched.\n"
    )
    out, _ = style_clamp.clamp_paragraphs(art, language="en")
    assert _nospace(art) == _nospace(out)
    assert "| col | col |" in out and "| --- | --- |" in out  # table intact
    assert "- list item one stays intact" in out  # list intact
    assert "code block stays\nintact across blanks" in out  # code fence intact
    assert "## 1 Chapter" in out  # heading intact
    assert "Short paragraph stays untouched." in out


def test_noop_under_ceiling():
    art = "# T\n\n## 1 C\n\nA short paragraph well under the ceiling stays byte-identical.\n"
    out, stats = style_clamp.clamp_paragraphs(art, language="en")
    assert out == art
    assert stats["paragraphs_split"] == 0
    assert stats["breaks_inserted"] == 0


def test_single_giant_sentence_never_split():
    """A single sentence longer than the ceiling has no internal terminator to
    cut at — it must NOT be split (splitting mid-sentence = grammar damage)."""
    giant = ("word " * 300).strip() + "."
    art = f"# T\n\n## 1 C\n\n{giant}\n"
    out, stats = style_clamp.clamp_paragraphs(art, language="en")
    assert stats["breaks_inserted"] == 0
    assert _nospace(art) == _nospace(out)


def test_lists_are_skipped():
    """A long run of list items is already segmented — never re-paragraphed."""
    items = "\n".join(f"- list item number {i} with some descriptive text here" for i in range(40))
    art = f"# T\n\n## 1 C\n\n{items}\n"
    out, stats = style_clamp.clamp_paragraphs(art, language="en")
    assert stats["paragraphs_split"] == 0
    assert out == art


def test_zh_splits_on_cjk_terminator():
    # ~21 units/sentence × 16 ≈ 340 units, over the ZH ceiling of 220.
    sent = "该模型在多个基准测试中取得了优异的成绩并展示出明显的性能提升效果显著。"
    art = f"# 标题\n\n## 1 章节\n\n{sent * 16}\n"
    out, stats = style_clamp.clamp_paragraphs(art, language="zh")
    assert stats["paragraphs_split"] == 1
    assert stats["breaks_inserted"] >= 1
    assert _nospace(art) == _nospace(out)


def test_idempotent():
    sent = "The model achieves strong results across benchmarks and shows clear gains. "
    art = f"# T\n\n## 1 C\n\n{(sent * 16).strip()}\n"
    out, _ = style_clamp.clamp_paragraphs(art, language="en")
    out2, stats2 = style_clamp.clamp_paragraphs(out, language="en")
    assert stats2["breaks_inserted"] == 0  # already segmented
    assert out2 == out


def test_references_block_untouched():
    sent = "The model achieves strong results across benchmarks and shows clear gains. "
    art = f"# T\n\n## 1 C\n\n{(sent * 16).strip()}\n\n## References\n\n[^1]: Source — url\n"
    out, _ = style_clamp.clamp_paragraphs(art, language="en")
    assert "## References\n\n[^1]: Source — url" in out


def test_max_units_override():
    sent = "The model achieves strong results across benchmarks and shows clear gains. "
    art = f"# T\n\n## 1 C\n\n{(sent * 16).strip()}\n"
    # A tiny ceiling forces more breaks than the default.
    _, tight = style_clamp.clamp_paragraphs(art, language="en", max_units=20)
    _, loose = style_clamp.clamp_paragraphs(art, language="en", max_units=120)
    assert tight["breaks_inserted"] >= loose["breaks_inserted"]


def test_zh_tail_merge_inserts_no_space():
    """Greptile PR #87: when a short trailing chunk (< _PARA_MIN_TAIL) is merged
    back into the previous chunk, CJK prose must NOT get an inter-sentence ASCII
    space. Build a ZH paragraph that splits and leaves a tiny tail so the merge
    path fires, then assert no `CJK<space>CJK` appears in the output."""
    big = "该模型在多个基准测试中取得了优异的成绩并展示出明显的性能提升效果非常显著。"
    short = "结论简短。"
    art = f"# 标题\n\n## 1 章节\n\n{big * 12}{short}\n"
    out, stats = style_clamp.clamp_paragraphs(art, language="zh")
    assert stats["paragraphs_split"] == 1
    # No space flanked by CJK on both sides (the tail-merge bug signature).
    assert re.search(r"[一-鿿。][ ][一-鿿]", out) is None, "CJK tail merged with a stray space"
    assert _nospace(art) == _nospace(out)


def test_en_tail_merge_keeps_space():
    """EN tail-merge still joins with a space (no run-on words)."""
    sent = "The model achieves strong consistent measurable results across every benchmark studied here. "
    art = f"# T\n\n## 1 C\n\n{sent * 12}Short tail.\n"
    out, _ = style_clamp.clamp_paragraphs(art, language="en")
    # The merged tail must not be glued to the preceding word.
    assert "here.Short" not in out
    assert _nospace(art) == _nospace(out)


def test_final_long_sentence_tips_over_ceiling_still_splits():
    """Greptile PR #87: greedy flush-before-overflow. A paragraph whose FINAL
    sentence is the one that tips it past the ceiling (50+50+100 words, ceiling
    120) must still split — the old flush-after-crossing loop left it unsplit."""
    s50 = ("word " * 50).strip() + ". "
    s100 = ("word " * 100).strip() + "."
    art = f"# T\n\n## 1 C\n\n{s50}{s50}{s100}\n"
    out, stats = style_clamp.clamp_paragraphs(art, language="en", max_units=120)
    assert stats["paragraphs_split"] == 1, f"over-ceiling paragraph escaped the clamp: {stats}"
    assert stats["breaks_inserted"] >= 1
    assert _nospace(art) == _nospace(out)
