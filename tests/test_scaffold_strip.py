"""Phase 1 A2: deterministic meta-scaffolding strip. Removes whole
本章小结/报告路线图/阅读路径/可信度分级 sections (Qianfan ~0; ours 3-9) the GPT-5.5
judge penalizes as 层级过多/重复小节. These tests pin: the strip removes scaffold
subsections (incl. their children), NEVER removes an H1 chapter, never touches a
fenced code block or a prose mention, is idempotent, and no-ops on EN.
"""

from deep_research.pipeline import scaffold_strip as ss

_PROSE = "正文段落，讨论本章的核心论点与数据支撑。\n\n"


def test_removes_recap_subsection():
    art = "# 1 第一章\n\n" + _PROSE + "## 1.1 本章小结：要点回顾\n\n这是小结正文。\n\n# 2 第二章\n\n正文。\n"
    out, st = ss.strip_meta_sections(art, language="zh")
    assert "本章小结" not in out
    assert st["sections_removed"] == 1
    assert "# 1 第一章" in out and "# 2 第二章" in out  # chapters preserved


def test_removes_roadmap_section_with_children():
    art = (
        "# 1 框架\n\n" + _PROSE
        + "## 1.3 报告路线图与章节导航\n\n路线图正文。\n\n"
        + "### 1.3.1 §2→§9的阅读路径\n\n阅读路径正文。\n\n"
        + "### 1.3.2 各章研究问题映射\n\n映射正文。\n\n"
        + "## 1.4 实质内容\n\n保留。\n"
    )
    out, st = ss.strip_meta_sections(art, language="zh")
    assert "报告路线图" not in out and "阅读路径" not in out and "研究问题映射" not in out
    assert "## 1.4 实质内容" in out and "保留。" in out
    # the H2 roadmap + its two H3 children removed as ONE nested span
    assert st["sections_removed"] == 1


def test_never_removes_h1_chapter():
    # even a chapter whose title contains a scaffold phrase stays (we only strip H2+)
    art = "# 1 本章小结式总章\n\n正文内容。\n\n# 2 下一章\n\n正文。\n"
    out, st = ss.strip_meta_sections(art, language="zh")
    assert out == art and st["sections_removed"] == 0


def test_keeps_prose_mention_of_benzhang():
    art = "# 1 章\n\n本章小结性地讨论了若干问题，但这是正文不是标题。\n\n## 1.1 实质小节\n\n正文。\n"
    out, st = ss.strip_meta_sections(art, language="zh")
    assert out == art and st["sections_removed"] == 0


def test_never_edits_inside_code_fence():
    art = "# 1 章\n\n```\n## 1.1 本章小结\n伪标题在代码块内\n```\n\n## 1.2 实质\n\n正文。\n"
    out, st = ss.strip_meta_sections(art, language="zh")
    assert out == art and st["sections_removed"] == 0


def test_idempotent():
    art = "# 1 章\n\n正文。\n\n## 1.1 本章综合\n\n综合正文。\n\n# 2 章\n\n正文。\n"
    out1, _ = ss.strip_meta_sections(art, language="zh")
    out2, st2 = ss.strip_meta_sections(out1, language="zh")
    assert out1 == out2 and st2["sections_removed"] == 0


def test_en_is_noop():
    art = "# 1 Chapter\n\nProse.\n\n## 1.1 Chapter Summary\n\nRecap.\n\n# 2 Chapter\n\nProse.\n"
    out, st = ss.strip_meta_sections(art, language="en")
    assert out == art and st["sections_removed"] == 0


def test_fail_soft_on_non_string():
    out, st = ss.strip_meta_sections(None)  # type: ignore[arg-type]
    assert out is None and st["sections_removed"] == 0


def test_credibility_grading_section_removed():
    art = "# 8 数据\n\n正文。\n\n## 8.1 数据来源清单与可信度分级\n\n清单正文。\n\n# 9 章\n\n正文。\n"
    out, st = ss.strip_meta_sections(art, language="zh")
    assert "可信度分级" not in out and st["sections_removed"] == 1
    assert "# 9 章" in out
