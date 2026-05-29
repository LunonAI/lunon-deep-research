"""G7 (2026-05-28): tests for the ZH-aware de-spacing post-pass.

Pins: (a) CAPEL-induced spaces between Hanzi are collapsed; (b) spaces inside
link/anchor text, footnote refs/defs, and inline code are PROTECTED (so the
Qianfan-style nested-link-title pattern isn't mangled); (c) Hanzi↔Latin spaces
are preserved; (d) the `Per the rubric` scaffolding leak is stripped; (e)
fail-soft on bad input.
"""

from deep_research.pipeline import cjk_despace


def test_collapses_spaces_between_hanzi():
    out, stats = cjk_despace.despace("本 章 的 分 组 方 式" + "，" + "见 下 文。" * 20)
    assert "本章的分组方式" in out
    assert stats["cjk_space_collapsed"] >= 6


def test_collapses_space_before_cjk_punctuation():
    body = "这 是 正 文 内 容 " * 20  # force CJK-bearing
    out, _ = cjk_despace.despace(body + "结 论 ， 见 后。")
    assert "结论，见后" in out


def test_preserves_spaces_inside_link_anchor_text():
    """Qianfan's incidental spaced-CJK lives inside source-title anchors —
    the de-spacer MUST NOT touch them."""
    padding = "正 文 段 落 内 容 充 足 " * 20
    anchor = "[锚定新质生产力 券商投行全生命周期](https://example.com/a)"
    out, _ = cjk_despace.despace(padding + "参见" + anchor + "的报道。")
    assert anchor in out, f"link anchor text was mangled: {out!r}"


def test_preserves_spaces_inside_reference_style_link_anchor():
    """Reference-style links (`[anchor text][ref-id]`) carry the same incidental
    spaced-CJK source titles as inline links — the de-spacer MUST NOT collapse
    the spaces inside the anchor text."""
    padding = "正 文 段 落 内 容 充 足 " * 20
    anchor = "[锚定新质生产力 券商投行全生命周期][src1]"
    out, _ = cjk_despace.despace(padding + "参见" + anchor + "的报道。")
    assert anchor in out, f"reference-style link anchor was mangled: {out!r}"


def test_preserves_bare_reference_label():
    """A bare `[label]` (no following `(`) is protected verbatim — even when
    its content is spaced CJK that the de-spacer would otherwise collapse."""
    padding = "正 文 段 落 内 容 充 足 " * 20
    label = "[锚定 生产力]"
    out, _ = cjk_despace.despace(padding + "见来源" + label + "的说明。")
    assert label in out, f"bare reference label was mangled: {out!r}"


def test_preserves_footnote_refs_and_defs():
    padding = "正 文 内 容 段 落 " * 20
    text = padding + "结论可靠[^src-1]。\n\n[^src-1]: 某 来 源 标 题"
    out, _ = cjk_despace.despace(text)
    assert "[^src-1]" in out  # ref token intact
    # The def lead `[^src-1]:` is protected; its title text is inside the
    # protected def-lead span only up to the colon — title body may de-space,
    # which is fine (it's prose, not an anchor). Ref marker integrity is what
    # matters for footnote coverage.


def test_does_not_collapse_hanzi_latin_boundary():
    body = "正 文 内 容 段 落 " * 20
    out, _ = cjk_despace.despace(body + "使用 GPT 模型")
    assert "使用 GPT 模型" in out, f"Hanzi↔Latin space wrongly collapsed: {out!r}"


def test_does_not_touch_pure_english():
    text = "This is a fully English paragraph with normal spacing throughout." * 5
    out, stats = cjk_despace.despace(text)
    assert out == text
    assert stats["cjk_space_collapsed"] == 0


def test_strips_per_the_rubric_scaffolding():
    text = "This controversy is, Per the rubric, strong on the originality axis." * 3
    out, stats = cjk_despace.despace(text)
    assert "Per the rubric" not in out
    assert stats["boilerplate_stripped"] >= 1
    assert "strong on the originality axis" in out


def test_boilerplate_strip_at_paragraph_start_preserves_newline():
    """Greptile PR #66 round-2: the leading whitespace in _BOILERPLATE_RE is
    horizontal-only ([^\\S\\n]), so a scaffolding phrase at the start of a
    paragraph cannot swallow the preceding newline and merge two paragraphs."""
    text = "First paragraph ends here.\n\nPer the rubric, the second paragraph is strong."
    out, stats = cjk_despace.despace(text)
    assert stats["boilerplate_stripped"] >= 1
    assert "Per the rubric" not in out
    # The blank line between paragraphs must survive (no paragraph merge).
    assert "\n\n" in out, f"paragraph break swallowed by boilerplate strip: {out!r}"
    assert "ends here." in out and "the second paragraph is strong." in out


def test_language_override_skips_cjk_despace():
    """Greptile PR #66 round-2: `language` is now a real gate. A confidently
    non-CJK label skips the CJK pass even on CJK-bearing text, while a CJK label
    (or no label) lets the Hanzi-count guard run. Boilerplate strip is unaffected."""
    cjk = "本 章 的 分 组 方 式" + "，" + "见 下 文。" * 20
    out_en, stats_en = cjk_despace.despace(cjk, language="en")
    assert stats_en["cjk_space_collapsed"] == 0, "en label should skip CJK de-spacing"
    out_zh, stats_zh = cjk_despace.despace(cjk, language="zh")
    assert stats_zh["cjk_space_collapsed"] >= 6, "zh label should de-space"
    # Region subtag tolerated for BOTH hyphen and underscore notation
    # (Greptile PR #66 round-4: "zh_CN" must not be read as a non-CJK label).
    for label in ("zh-CN", "zh_CN"):
        _, stats_region = cjk_despace.despace(cjk, language=label)
        assert stats_region["cjk_space_collapsed"] >= 6, label


def test_boilerplate_inside_link_anchor_is_not_stripped():
    """Greptile PR #66 round-5: spans are masked BEFORE the boilerplate strip,
    so 'Per the rubric' at the start of a link anchor is preserved (link not
    mangled) while a prose occurrence elsewhere is still removed."""
    text = "See [Per the rubric guide](https://x/y) for context. This is, Per the rubric, strong."
    out, stats = cjk_despace.despace(text)
    assert "[Per the rubric guide](https://x/y)" in out, out  # link intact
    assert "is, Per the rubric, strong" not in out  # prose scaffolding stripped
    assert stats["boilerplate_stripped"] >= 1


def test_pre_existing_nul_in_input_does_not_crash():
    """Greptile PR #66 round-5: a pre-existing NUL sequence must not be mistaken
    for a stash sentinel and IndexError the restore pass — NULs are stripped at
    entry so the phase never raises and still de-spaces the surrounding CJK."""
    text = "本 章 \x005\x00 的 分 组 方 式" + "，" + "见 下 文。" * 20
    out, stats = cjk_despace.despace(text)
    assert "\x00" not in out
    assert stats["cjk_space_collapsed"] >= 1


def test_fail_soft_on_bad_input():
    out, stats = cjk_despace.despace("")
    assert out == ""
    assert all(v == 0 for v in stats.values())
    out, stats = cjk_despace.despace(None)
    assert out is None
    assert all(v == 0 for v in stats.values())


def test_l5_strips_zh_scaffolding_tokens():
    """L5 (2026-05-29): leaked internal scaffolding tokens (本报告的契约, and
    AC\\d/R-\\d adjacent to Hanzi) are stripped from ZH prose."""
    padding = "正 文 内 容 段 落 充 足 " * 20
    out, stats = cjk_despace.despace(padding + "本报告的契约要求每个实体AC19都要展开，满足R-2标准。", language="zh")
    assert "本报告的契约" not in out
    assert "AC19" not in out
    assert "R-2" not in out
    assert stats["scaffold_stripped"] >= 3


def test_l5_strips_cjk_scaffolding_in_ja_too():
    """Greptile PR #69 round-1: the scaffold strip is CJK-gated, not ZH-only. A
    JA article that clears the CJK guard has rubric-id leaks (AC\\d/R-\\d) adjacent
    to Han ideographs stripped just like ZH — the de-scaffolder follows
    `_CJK_LANGS`, which includes ja/ko."""
    padding = "技術評価基準分析結果報告書" * 5  # 65 Kanji → clears the 50-char CJK guard
    out, stats = cjk_despace.despace(padding + "基準AC19達成、評価R-2基準", language="ja")
    assert "AC19" not in out
    assert "R-2" not in out
    assert stats["scaffold_stripped"] >= 2


def test_l5_strips_scaffold_adjacent_to_cjk_extension_a():
    """Greptile PR #69 round-1: fix (B) widened the AC\\d/R-\\d adjacency class
    from the main CJK block to the full `_CJK` constant (+ Extension A). This pins
    that exact delta: a rubric-id leak flanked ONLY by Extension-A ideographs
    (U+3400–U+4DBF) is stripped now but was NOT under the old main-block class
    (the ja-gating test above passes pre- and post-fix and so can't pin it)."""
    padding = "㐀㐁㐂㐃㐄㐅㐆㐇㐈㐉" * 6  # 60 Ext-A ideographs → clears the 50-char CJK guard
    out, stats = cjk_despace.despace(padding + "㐀AC19㐁", language="zh")
    assert "AC19" not in out, f"Ext-A-adjacent scaffold not stripped: {out!r}"
    assert stats["scaffold_stripped"] >= 1


def test_l5_preserves_en_tier_ranking_rubric_ids():
    """EN tier-ranking R-N (in tables / EN prose, never Hanzi-adjacent) must
    survive — the tier-ranking validator's R-N cross-reference depends on it."""
    en = "Scored per R-1 and R-2 in the table below.\n\n| Entity | R-1 | R-2 |\n|---|---|---|\n| A | 8.0 | 7.0 |\n" * 2
    out, _ = cjk_despace.despace(en, language="en")
    assert "R-1" in out and "R-2" in out


def test_does_not_touch_heading_hashes_or_numbers():
    body = "## 3 章 节 标 题\n\n正 文 内 容 段 落 充 足 " * 10
    out, _ = cjk_despace.despace(body)
    # Heading markers + numbers survive; the de-spacer only removes spaces
    # BETWEEN cjk chars, never the "## 3 " prefix (space follows a digit).
    assert "## 3 章节标题" in out or "## 3 章 节 标 题" in out
    assert "##3" not in out  # never glued the hash to the number


def test_a3_collapses_abnormal_unicode_spaces_between_hanzi():
    """A3 (2026-05-29): NBSP / zero-width / BOM / full-width / thin spaces
    between Hanzi are collapsed, not just ASCII space/tab — the gemini judge
    flagged residual '异常空格/不可见字符' after the ASCII-only de-spacer."""
    padding = "正 文 内 容 段 落 充 足 " * 20  # force CJK-bearing
    # NBSP, full-width space, zero-width space, narrow NBSP between Hanzi
    out, stats = cjk_despace.despace(padding + "本 章　的​分 组方式。", language="zh")
    assert "本章的分组方式" in out, f"abnormal spaces not collapsed: {out!r}"
    for ws in (" ", "　", "​", " "):
        assert ws not in out.replace(padding, ""), f"{ws!r} survived"


def test_a3_abnormal_spaces_preserved_inside_protected_spans():
    """The protected-span mask still shields link/anchor/footnote text — a
    full-width space inside a link title must NOT be collapsed."""
    padding = "正 文 内 容 段 落 充 足 " * 20
    anchor = "[锚定新质生产力　券商投行](https://e.com/a)"
    out, _ = cjk_despace.despace(padding + "参见" + anchor + "。", language="zh")
    assert anchor in out, f"abnormal space inside link anchor was collapsed: {out!r}"


def test_a3_does_not_touch_english_nbsp():
    """EN articles are skipped by the CJK guard — an NBSP in English prose is
    left alone (not the de-spacer's job; avoids touching legit EN spacing)."""
    en = "A non breaking space in English prose stays put here." * 3
    out, _ = cjk_despace.despace(en, language="en")
    assert out == en
