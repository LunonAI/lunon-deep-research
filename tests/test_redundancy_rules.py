"""Round 5 T3-PR7: redundancy reduction.

dev4 corpus comparison: id=89's MDA definition was restated 15-20× (the judge
read it as "repeated sections", formatting 2.0); Qianfan ZH (id=8/id=23) uses
ZERO per-chapter synthesis HEADINGS while our ZH over-emitted 6-8 小结/综合
subsections. These pin (a) the define-once dedup clause and (b) the
language-gated per-chapter synthesis rule.
"""

from deep_research.writing_rules import _DEDUP_RULE, writer_system


def test_dedup_rule_has_define_once_clause():
    assert "DEFINE ONCE" in _DEDUP_RULE
    assert "EXACTLY ONCE" in _DEDUP_RULE


def test_zh_synthesis_suppresses_per_chapter_heading():
    """ZH keeps the synthesis reasoning as prose but NOT a dedicated heading
    (Qianfan ZH uses zero per-chapter synthesis headings)."""
    sys_zh = writer_system("explain-mechanism", "default", "zh", ["A", "B"], task_id=None)
    assert "ZH style" in sys_zh
    assert "NOT a dedicated" in sys_zh
    # The EN heading-based phrasing must be ABSENT for ZH.
    assert "ONE short subsection (heading containing" not in sys_zh


def test_en_synthesis_keeps_heading_variant():
    """EN keeps the synthesis-subsection heading (Qianfan EN uses it: q89 ≈ 10)."""
    sys_en = writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=None)
    assert "ONE short subsection (heading containing" in sys_en
    assert "ZH style" not in sys_en


def test_both_languages_carry_define_once():
    for lang in ("en", "zh"):
        sys = writer_system("explain-mechanism", "default", lang, ["A", "B"], task_id=None)
        assert "DEFINE ONCE" in sys, lang
