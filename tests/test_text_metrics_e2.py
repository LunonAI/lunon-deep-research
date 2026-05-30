"""E2 (audit): the chapter-completion gate and the validation length gate must
share ONE CJK-aware token estimator instead of disagreeing ~2.5× on CJK text.

Before this fix, validation._section_length_ok used a uniform `len(body) // 4`
while orchestrate._approx_tokens counted CJK at ~1.6 chars/token — so a ZH
section could pass one gate and fail the other from the accounting mismatch.
"""

from deep_research import text_metrics
from deep_research.pipeline.validation import _section_length_ok


def test_approx_tokens_non_cjk_equals_legacy_quarter():
    # For non-CJK text the shared estimator equals the prior len // 4, so EN
    # behavior (and the EN gate tests) is unchanged.
    for n in (0, 1, 199, 200, 201, 1000):
        assert text_metrics.approx_tokens("x" * n) == n // 4


def test_approx_tokens_cjk_denser_than_latin():
    assert text_metrics.approx_tokens("研究背景" * 25) > text_metrics.approx_tokens("x" * 100)


def test_approx_tokens_counts_extension_a():
    # Ext A ideographs must count at the CJK rate, not the non-CJK baseline.
    assert text_metrics.approx_tokens("㐀" * 16) > text_metrics.approx_tokens("x" * 16)


def test_count_cjk_and_empty():
    assert text_metrics.count_cjk("研究x背景") == 4
    assert text_metrics.approx_tokens("") == 0
    assert text_metrics.count_cjk("") == 0


def test_validation_gate_now_cjk_aware():
    # ~400 CJK chars under a heading. CJK-aware ≈ 400/1.6 ≈ 250 tokens; the old
    # uniform len//4 would have reported ≈ 100. Assert the gate uses the higher,
    # correct CJK-aware count now (proving both gates share the estimator).
    text = "## 方法\n\n" + ("研" * 400)
    ok, body_tok = _section_length_ok(text, "方法", expected_tok=100)
    assert body_tok > 200  # uniform //4 would give ~100
    assert ok is True


def test_validation_gate_unchanged_for_english():
    # Same length in EN must behave as before (cjk=0 → identical to len//4).
    body = "word " * 100  # 500 chars
    text = "## Method\n\n" + body
    ok, body_tok = _section_length_ok(text, "Method", expected_tok=50)
    assert body_tok == text_metrics.approx_tokens("\n\n" + body)
    assert ok is True
