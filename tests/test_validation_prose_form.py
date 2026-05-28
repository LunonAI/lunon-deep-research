"""P3b-opt2: `_validate_prose_form` advisory readability telemetry.

Replaces the retired micro-template compliance check (the prose form merged
in #53 uses descriptive bold lead-ins, not fixed `**axis:**` labels). Measures
paragraph density (vs the reference EN corpus median ~81 words) and heading
flatness (corpus h4=0). Advisory only — these are counts, never a hard-fail.
"""

from deep_research.pipeline.validation import _validate_prose_form


def test_dense_paragraphs_high_median_no_choppy():
    dense = ("word " * 100).strip()
    art = f"## 1 A\n\n{dense}\n\n{dense}\n"
    pf = _validate_prose_form(art)
    assert pf["para_count"] == 2
    assert pf["para_median_words"] == 100
    assert pf["choppy_frac"] == 0.0
    assert pf["choppy_paras"] == 0


def test_choppy_paragraphs_flagged():
    choppy = ("word " * 30).strip()  # < 80 words
    art = f"## 1 A\n\n{choppy}\n\n{choppy}\n\n{choppy}\n"
    pf = _validate_prose_form(art)
    assert pf["para_median_words"] == 30
    assert pf["choppy_paras"] == 3
    assert pf["choppy_frac"] == 1.0


def test_counts_h3_and_h4_nesting():
    art = "# T\n\n## 1 A\n\nbody words here are fine.\n\n### 1.1 Sub\n\nmore body.\n\n#### 1.1.1 Deep\n\ndeep body.\n"
    pf = _validate_prose_form(art)
    assert pf["h3_count"] == 1  # only the ### line
    assert pf["h4_count"] == 1  # only the #### line


def test_headings_not_counted_as_paragraphs():
    art = "# Title\n\n## 1 A\n\nThe body paragraph has some words here today.\n"
    pf = _validate_prose_form(art)
    assert pf["para_count"] == 1  # headings excluded; only the body block


def test_no_prose_is_all_zero():
    art = "# Title\n\n## 1 A\n\n### 1.1 B\n"  # headings only, no body
    pf = _validate_prose_form(art)
    assert pf["para_count"] == 0
    assert pf["para_median_words"] == 0
    assert pf["choppy_frac"] == 0.0


def test_mixed_density_median_is_robust():
    dense = ("word " * 120).strip()
    choppy = ("word " * 20).strip()
    # 3 paragraphs: 20, 120, 120 → median 120, one choppy.
    art = f"## 1 A\n\n{choppy}\n\n{dense}\n\n{dense}\n"
    pf = _validate_prose_form(art)
    assert pf["para_count"] == 3
    assert pf["para_median_words"] == 120
    assert pf["choppy_paras"] == 1
