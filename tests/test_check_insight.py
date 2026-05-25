"""Unit tests for deep_research.writing_rules.check_insight_minimums (Wave-1.5-N0).

Verifies the expanded EN+ZH alternatives regex catches comparative discourse
patterns that W9 writers actually produced (per L2 diagnostic: pre-fix ZH
fire-rate was 78%, retry-success 0%).
"""

from deep_research.writing_rules import check_insight_minimums


def test_en_alternatives_hits_diverse_vocab():
    """EN-side: pre-fix vocab was 5 tokens; post-fix should match common
    comparative-discourse moves."""
    text = (
        "Header. The data show several patterns. "
        "However, the second analysis contradicts the first. "
        "On the other hand, the regional breakdown suggests heterogeneity. "
        "By contrast, the cohort study finds no effect. "
        "Alternatively, one might use a Bayesian framework. "
        "Instead of relying on regression, an instrumental variable approach. "
        "The trade-off between sensitivity and specificity is well-documented. "
        "Conversely, ignoring confounders inflates the estimate. "
        # 8 EN comparative moves above
    )
    out = check_insight_minimums(text)
    assert out["counts"]["alternatives"] >= 6, f"got {out['counts']['alternatives']}"


def test_zh_alternatives_hits_diverse_vocab():
    """ZH-side: pre-fix vocab was 4 tokens (另一种 / 相比之下 / 劣于 / 优于) and
    failed on 78% of W9 ZH tasks. Post-fix should match the comparative-discourse
    vocabulary writers actually use."""
    text = (
        "标题。本文比较多种方法。"
        "然而，第二个方法在某些场景下表现更好。"
        "另一方面，其计算成本更高。"
        "相比之下，第三种方法成本较低。"
        "相对而言，可靠性也更稳定。"
        "与之相对，第四种方法对噪声更敏感。"
        "替代方案包括基于贝叶斯的框架。"
        "权衡稳定性与速度，可以选择折中方案。"
        "不同于经典方法，新方法在小样本上更稳健。"
        "反观竞争对手的实现，缺少这一改进。"
        # 9 ZH comparative moves above
    )
    out = check_insight_minimums(text)
    assert out["counts"]["alternatives"] >= 7, f"got {out['counts']['alternatives']}"


def test_pre_fix_examples_still_match():
    """Backwards-compat: the original 9 tokens must still match — no regression
    on EN/ZH text that was already passing the gate."""
    # Original EN
    en_text = (
        "alternative one is better. another shown whereas the second weaker. trade-off matters. stronger fit overall."
    )
    out = check_insight_minimums(en_text)
    assert out["counts"]["alternatives"] >= 4, f"EN regression: {out['counts']['alternatives']}"

    # Original ZH
    zh_text = "另一种方法更好。相比之下，参数也更稳定。劣于第一种但优于第三种。"
    out = check_insight_minimums(zh_text)
    assert out["counts"]["alternatives"] >= 3, f"ZH regression: {out['counts']['alternatives']}"


def test_no_false_positives_on_year_or_neutral_text():
    """The fix should NOT match plain text without comparative vocabulary —
    no false positives that would silently pass the gate."""
    text = (
        "The 2024 study described methods. "
        "Researchers collected data. "
        "Results were summarized in a table. "
        "The 2025 update is forthcoming."
        # No comparative vocabulary above; should be 0 hits.
    )
    out = check_insight_minimums(text)
    assert out["counts"]["alternatives"] == 0, f"got false positives: {out['counts']['alternatives']}"


def test_no_false_positive_on_bijiao_compound():
    """`较` is meant to match comparative uses (`较好`, `较大`, `较低`) but NOT
    the neutral compound `比较` (compare/comparative). Pre-fix the bare `较`
    token matched inside `比较`, inflating alts count on neutral comparative
    prose. The negative lookbehind `(?<!比)较` enforces this. Greptile PR #3
    post-merge follow-up."""
    text = (
        "通过比较多种方法可以发现一些规律。比较分析表明各方法在不同场景下都有优势。进一步比较显示，结果具有一致性。"
        # 3 instances of 比较, ZERO contrastive moves. Should NOT match.
    )
    out = check_insight_minimums(text)
    assert out["counts"]["alternatives"] == 0, (
        f"bare 较 matched inside 比较 — got {out['counts']['alternatives']} false positives"
    )

    # Still match legitimate comparative uses of bare 较.
    legit = "新方法在小样本上较稳健。其精度也较低。整体表现较优于经典方法。"
    out2 = check_insight_minimums(legit)
    # 较稳健 (1), 较低 (1), 较优于 (1, plus 优于 as separate match — net should be ≥3)
    assert out2["counts"]["alternatives"] >= 3, (
        f"legitimate 较X uses didn't match — got {out2['counts']['alternatives']}"
    )


def test_contrarian_framing_counts_en_and_zh_markers():
    """element (b) NAMED CONTRARIAN FRAMING — explicit pushback against a
    consensus interpretation. Greptile PR #21 follow-up added this count to
    replace causal_chain so the four advisory metrics map 1:1 to the four
    _INSIGHT_MIN contract elements."""
    text = (
        # EN markers
        "Despite the standard reading, the Episode G data tells a different story. "
        "Contrary to the prevailing view, the cohort study finds the opposite. "
        "This challenges the consensus that the upper bound is fixed. "
        "Against the commonly held assumption, the panel shows heterogeneity. "
        "Counter to the conventional framing, the bear case is plausible. "
        # ZH markers
        "尽管学界普遍认为该上限是固定的，最新数据并不支持这一结论。"
        "通常认为这是稳定的均衡，但与该共识相反，最新观测呈现震荡。"
        "这一发现挑战了上述共识。"
        "这是一个反直觉的结果。"
    )
    out = check_insight_minimums(text)
    # 5 EN + 4 ZH markers above; lower bound 7 leaves headroom for any
    # regex tightening without making the test brittle.
    assert out["counts"]["contrarian_framing"] >= 7, out["counts"]


def test_contrarian_framing_no_false_positives_on_neutral_text():
    """Neutral prose without any consensus-pushback signal must not
    contribute to contrarian_framing — protects the advisory log telemetry
    from inflation."""
    text = (
        "The 2024 study described methods. "
        "Researchers collected data across three regions. "
        "Results were summarized in a table. "
        "The 2025 update is forthcoming."
    )
    out = check_insight_minimums(text)
    assert out["counts"]["contrarian_framing"] == 0, out["counts"]


def test_counts_dict_keys_match_four_element_contract():
    """The advisory counts dict must expose exactly the four keys named in
    _INSIGHT_MIN's contract. Greptile PR #21 follow-up: causal_chain is
    GONE; contrarian_framing is its replacement. Future calibration work
    parses these keys directly out of validation_failures.jsonl."""
    out = check_insight_minimums("placeholder text with no signals")
    assert set(out["counts"].keys()) == {
        "forward_looking",
        "alternatives",
        "contrarian_framing",
        "quant_projection",
    }, out["counts"]
    # causal_chain must NOT be re-introduced — it has no equivalent in the
    # four-element rule and would re-poison the telemetry.
    assert "causal_chain" not in out["counts"]


def test_gate_passes_with_all_four_contract_elements():
    """Smoke: a text covering all four _INSIGHT_MIN contract elements should
    pass the advisory gate. Post-#3-PR21 the four tracked counts are
    forward_looking (a), contrarian_framing (b), quant_projection (c),
    alternatives (d) — one for each named element of the writer rule."""
    text = (
        # (a) forward_looking: >=3 dated horizons
        "By 2026 the market reaches $5B (range $3B-$7B). "
        "By 2028 the market reaches $10B (range $7B-$15B). "
        "By 2030 the market reaches $20B. "
        # (d) alternatives: >=2 comparative moves
        "However, alternative scenarios place the 2030 value lower. "
        "On the other hand, the bear case puts 2030 at $12B. "
        # (b) contrarian_framing: >=1 explicit pushback against consensus
        "Despite the prevailing view that supply-side drivers dominate, "
        "the cross-region panel data points the other way. "
        # (c) quant_projection: covered already by the $X-$Y ranges above
    )
    out = check_insight_minimums(text)
    assert out["ok"], f"gate should pass: {out['fail']}"
    assert out["counts"]["contrarian_framing"] >= 1, out["counts"]
    assert out["counts"]["forward_looking"] >= 3, out["counts"]
    assert out["counts"]["alternatives"] >= 2, out["counts"]
    assert out["counts"]["quant_projection"] >= 1, out["counts"]


if __name__ == "__main__":
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
