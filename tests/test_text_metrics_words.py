"""F2 (audit): the CJK-aware word counter, previously duplicated byte-for-byte in
validation._wc and style_clamp._words, now lives once in text_metrics.

Mirrors scripts/reference_style_profile.py: CJK ideographs ~1.6 chars/word + Latin
word runs when CJK-heavy, else whitespace split; always >= 1.
"""

from deep_research import text_metrics


def test_english_whitespace_split():
    assert text_metrics.approx_words("one two three four") == 4
    assert text_metrics.approx_words("solo") == 1


def test_empty_floors_to_one():
    # Mirrors the prior max(len(split), 1) — never returns 0.
    assert text_metrics.approx_words("") == 1
    assert text_metrics.approx_words("   ") == 1


def test_cjk_heavy_uses_chars_over_1_6_plus_latin():
    # 4 CJK ideographs, no Latin → int(4 / 1.6) = 2.
    assert text_metrics.approx_words("中文字符") == int(4 / 1.6)
    # 4 CJK + one embedded Latin run ("AB") → int(4 / 1.6) + 1 = 3.
    assert text_metrics.approx_words("中文AB字符") == int(4 / 1.6) + 1


def test_is_cjk_heavy_threshold():
    assert text_metrics.is_cjk_heavy("研究背景与方法结果") is True
    assert text_metrics.is_cjk_heavy("mostly english with one 研 char in it here") is False


def test_matches_legacy_inline_formula():
    # Recompute the exact pre-F2 formula and confirm parity across samples.
    import re

    def legacy(t):
        cjk = len(re.findall(r"[一-鿿]", t))
        if cjk > 0.15 * max(len(t), 1):
            latin = len(re.findall(r"[A-Za-z]+", t))
            return max(int(cjk / 1.6) + latin, 1)
        return max(len(t.split()), 1)

    for s in ["", "hello world", "研究背景与方法", "数据 shows GPT-5 改进 50%", "a b c 研 d"]:
        assert text_metrics.approx_words(s) == legacy(s), s
