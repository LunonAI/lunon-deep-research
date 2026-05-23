"""Unit tests for P2-Wave-2.5-D0 profiler CJK fix.

Verifies `count_cjk_chars` + `word_equivalents` correctly handle EN, ZH,
and mixed text so the Phase A profile is meaningful across languages.

The pre-D0 `.split()` count under-reported ZH length by ~10× because
Chinese has no whitespace between characters. After D0, ZH articles are
length-comparable to EN via `n_cjk_chars / 2` word-equivalents.
"""

import sys
from pathlib import Path

# Add scripts/ to path so we can import the profiler module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from p2_qianfan_profile import compute_metrics, count_cjk_chars, word_equivalents  # noqa: E402


def test_count_cjk_returns_zero_on_pure_english():
    assert count_cjk_chars("Hello world. This is English text only.") == 0


def test_middle_excerpt_zh_heading_snap_is_accurate():
    """Greptile follow-up (PR #16, round 2): for ZH-dominated text the
    middle excerpt must slice directly in CHAR space from the heading
    offset, NOT round-trip through unit-space (which dropped non-CJK chars
    and drifted the start by 5k+ chars on realistic mixed-content articles).
    """
    from p2_qianfan_excerpts import _middle_excerpt

    # Construct a ZH article with mixed content: 75% CJK + 25% non-CJK
    # (punctuation, paragraph breaks, occasional latin). The heading
    # 'TARGET' sits exactly at the middle; a correct snap puts the excerpt
    # START at the heading char-offset.
    chunk = "中国高校教师竞赛全国一等奖课程的研究与分析。" * 50  # ZH body
    pre = chunk + "\n\n"  # paragraph break
    target_heading = "## TARGET MIDDLE HEADING\n\n"
    post = chunk
    text = pre + target_heading + post

    excerpt = _middle_excerpt(text, n=200)
    # The excerpt must START at (or very near) the target heading — proving
    # the snap survived for ZH text. Pre-fix the excerpt started ~5k chars
    # before the heading.
    assert "TARGET MIDDLE HEADING" in excerpt[:100]


def test_count_cjk_counts_basic_ideographs():
    # `你好世界` = 4 CJK Unified Ideographs. `！` is fullwidth punctuation
    # (U+FF01), correctly EXCLUDED from the count. Greptile follow-up
    # (PR #16, round 2): pre-fix comment said "5 common-use CJK characters"
    # which contradicted the (correct) `== 4` assertion.
    assert count_cjk_chars("你好世界！") == 4


def test_count_cjk_ignores_latin_punctuation_and_spaces():
    text = "中国 university 教师 competition: 一等奖"
    # CJK chars: 中国教师一等奖 = 7 ideographs.
    assert count_cjk_chars(text) == 7


def test_word_equivalents_en_returns_split_count():
    assert word_equivalents("Hello world this is English") == 5


def test_word_equivalents_zh_uses_cjk_div_2():
    """Pure ZH paragraph (no whitespace): word-equivalent is n_cjk / 2."""
    text = "中国高校教师竞赛全国一等奖课程研究报告"  # 18 chars
    assert word_equivalents(text) == 18 // 2  # = 9


def test_word_equivalents_mixed_text_uses_max():
    """Mixed ZH+EN: the larger of latin-split or cjk/2 wins.
    `.split()` treats whitespace-bounded CJK clusters as tokens too — the
    sentence below splits into 8 tokens, only 4 CJK chars present, so
    max(8, 2) = 8. The fixed-quantity story is: pure-EN text uses split,
    pure-ZH text uses cjk/2, mixed text uses whichever happens to be larger.
    """
    text = "Compare 中国 vs 美国 in higher education research"
    assert word_equivalents(text) == len(text.split())


def test_compute_metrics_includes_n_length_and_n_cjk():
    """compute_metrics dict surfaces both raw metrics + the unit-comparable one."""
    m = compute_metrics("Hello world 中国 教师")
    assert "n_words" in m
    assert "n_cjk_chars" in m
    assert "n_length" in m
    assert m["n_words"] == 4  # latin split
    assert m["n_cjk_chars"] == 4
    # length = max(4, 4//2) = 4.
    assert m["n_length"] == 4


def test_compute_metrics_zh_article_now_has_realistic_length():
    """A realistic-length ZH paragraph should report a length > 100, not <30.

    Pre-D0, .split() on this paragraph reported ~3 (the few whitespace-
    separated tokens). Post-D0, n_length reflects the actual character
    density.
    """
    zh = "中国高校教师竞赛分为创新赛和青教赛两大类。" * 10  # ~200+ CJK chars
    m = compute_metrics(zh)
    assert m["n_length"] >= 100


def test_compute_metrics_hedge_per_1k_uses_n_length():
    """hedge_per_1k must use n_length so ZH and EN articles are comparable.
    With .split() denominator a ZH article would over-report hedge density
    by an order of magnitude."""
    zh = "可能存在不同观点。" * 100  # ~800 CJK chars, ~10 hedge hits (可能)
    m = compute_metrics(zh)
    # hedge_per_1k = hedge_count / (n_length / 1000) — must NOT be in the
    # thousands. With n_length = ~400 word-equivalents and 100 hedge hits,
    # expected ~250/1k. Without the fix, n_words might be ~10 → 10,000/1k.
    assert m["hedge_per_1k"] < 600
