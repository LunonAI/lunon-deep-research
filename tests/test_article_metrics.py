"""Advisory final-article metrics (2026-05-29). Deterministic structural /
cleanliness signals on the shipped article — distance-from-reference + round-2
fix verification. Pinned against the values measured on the real corpora
(the reference frontload ~0.46, scaffolding ~0; Lunon prior-dev6 frontload ~1.5,
hundreds of bare R-N) so the thresholds can't silently drift."""

from deep_research.pipeline import article_metrics as am


def _chapters(sizes, lvl="#"):
    """Build an article: a title H1 + numbered chapters at `lvl`, each padded
    to roughly `size` chars of prose."""
    parts = ["# Title\n"]
    for i, sz in enumerate(sizes, 1):
        parts.append(f"{lvl} {i} Chapter {i}\n\n" + ("word " * (sz // 5)).strip() + "\n")
    return "\n".join(parts)


def test_heading_profile_counts_levels():
    art = "# T\n\n# 1 A\n\n## 1.1 a\n\n### 1.1.1 x\n\n#### too deep\n"
    p = am.compute(art)["heading_profile"]
    assert p["h1"] == 2 and p["h2"] == 1 and p["h3"] == 1 and p["h4plus"] == 1


def test_frontload_ratio_flags_hollow_tail():
    # early chapters big, late chapters tiny → ratio > 1 (hollow tail, the
    # Lunon failure mode). the reference's is ~0.46.
    hollow = am.compute(_chapters([4000, 4000, 4000, 200, 200, 200]))
    assert hollow["frontload_ratio"] > 1.5
    # balanced/back-loaded → ratio <= 1 (the reference profile)
    rich = am.compute(_chapters([300, 300, 300, 4000, 4000, 4000]))
    assert rich["frontload_ratio"] < 1.0
    assert hollow["n_top_chapters"] == 6


def test_h1_chapter_detection_matches_reference_shape():
    # the reference puts chapters at H1 ('# 1'); a Lunon-style H2 chapter scheme
    # ('## 1') is detected as the chapter level just the same.
    qf_like = am.compute(_chapters([1000, 1000, 1000], lvl="#"))
    lu_like = am.compute(_chapters([1000, 1000, 1000], lvl="##"))
    assert qf_like["n_top_chapters"] == 3
    assert lu_like["n_top_chapters"] == 3
    assert lu_like["heading_profile"]["h1"] == 1  # only the title


def test_spaced_cjk_rate():
    assert am.compute("# T\n\n中文内容很多中文内容")["spaced_cjk_rate"] == 0.0
    # one spaced boundary among several adjacencies → small positive rate
    r = am.compute("# T\n\n中 文内容很多中文内容")["spaced_cjk_rate"]
    assert r is not None and r > 0
    # a pure-EN article has no CJK adjacency → None (not 0, so it's excluded
    # from aggregation rather than dragging the mean down).
    assert am.compute("# T\n\nAll english prose here, nothing else.")["spaced_cjk_rate"] is None


def test_spaced_cjk_rate_counts_boundaries_overlapping():
    """Greptile PR #70: boundaries are counted with overlapping lookaheads, so
    a run of N adjacent CJK chars yields N-1 boundaries (not ⌊N/2⌋) and
    CONSECUTIVE spaced boundaries each count."""
    # 甲乙丙 丁 → boundaries 甲乙, 乙丙, 丙⎵丁 = 3 total, 1 spaced → 1/3
    assert am.compute("甲乙丙 丁")["spaced_cjk_rate"] == round(1 / 3, 5)
    # 中⎵文⎵字 → both boundaries spaced → 2/2 = 1.0 (the consuming-findall bug
    # would have returned 0.5 by consuming the middle char).
    assert am.compute("中 文 字")["spaced_cjk_rate"] == 1.0


def test_scaffold_residual_counts_leaks():
    art = (
        "# T\n\nThe system is strong on R-2 and weak on R-13. Per the rubric this holds. "
        "Where one might expect failure, it adapts. AC19 is met. 本报告的契约 规定如下。\n"
    )
    res = am.compute(art)["scaffold_residual"]
    assert res["bare_R_n"] == 2
    assert res["per_the_rubric"] == 1
    assert res["where_one_might_expect"] == 1
    assert res["AC_n"] == 1
    assert res["contract_phrase"] == 1


def test_scaffold_residual_clean_article_is_zero():
    res = am.compute("# T\n\nA perfectly clean paragraph with no scaffolding leaks at all.\n")["scaffold_residual"]
    assert sum(res.values()) == 0


def test_numbering_anomalies():
    assert am.compute(_chapters([100, 100, 100]))["numbering_anomalies"] == 0
    gapped = "# T\n\n# 1 A\n\nx\n\n# 3 B\n\ny\n\n# 4 C\n\nz\n"  # 1,3,4 → gap
    assert am.compute(gapped)["numbering_anomalies"] >= 1


def test_paragraph_density_excludes_structure():
    art = "# T\n\n| a | b |\n| - | - |\n\n```\ncode\n```\n\n" + ("w " * 120).strip() + "\n"
    m = am.compute(art)
    assert m["n_prose_paragraphs"] == 1  # only the prose paragraph, not table/code
    assert m["para_chars_p90"] > 0


def test_fail_soft_on_bad_input():
    assert am.compute(None) == {}
    assert am.compute("") == {}
    assert am.compute("   ") == {}
