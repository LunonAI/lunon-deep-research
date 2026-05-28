"""P3b-opt2: `_validate_prose_form` advisory readability telemetry.

Replaces the retired micro-template compliance check (the prose form merged
in #53 uses descriptive bold lead-ins, not fixed `**axis:**` labels). Measures
paragraph density (vs the Qianfan EN corpus median ~81 words) and heading
flatness (corpus h4=0). Advisory only — these are counts, never a hard-fail.
"""

from deep_research.pipeline.validation import _validate_prose_form, _validate_prose_reasoning


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
    art = "# Title\n\n## 1 A\n"  # headings only, no body, no nesting → all zero
    pf = _validate_prose_form(art)
    assert pf["para_count"] == 0
    assert pf["para_median_words"] == 0
    assert pf["choppy_frac"] == 0.0
    assert pf["h3_count"] == 0
    assert pf["h4_count"] == 0


def test_mixed_density_median_is_robust():
    dense = ("word " * 120).strip()
    choppy = ("word " * 20).strip()
    # 3 paragraphs: 20, 120, 120 → median 120, one choppy.
    art = f"## 1 A\n\n{choppy}\n\n{dense}\n\n{dense}\n"
    pf = _validate_prose_form(art)
    assert pf["para_count"] == 3
    assert pf["para_median_words"] == 120
    assert pf["choppy_paras"] == 1
    assert pf["choppy_frac"] == 0.333  # round(1/3, 3)


# --- P3b-D1: _validate_prose_reasoning (labeled-reasoning adoption) ---------


def test_prose_reasoning_counts_synthesis_per_chapter():
    art = (
        "## 1 Alpha\n\nbody.\n\n### 1.4 Synthesis\n\nThese together establish X.\n\n"
        "## 2 Beta\n\nbody.\n\n### 2.4 Synthesis\n\nThe set proves Y.\n"
    )
    pr = _validate_prose_reasoning(art)
    assert pr["synthesis_headings"] == 2
    assert pr["h2_chapters"] == 2
    assert pr["synthesis_per_chapter"] == 1.0


def test_prose_reasoning_zero_synthesis_when_absent():
    art = "## 1 A\n\nplain body paragraph here.\n\n## 2 B\n\nanother body paragraph.\n"
    pr = _validate_prose_reasoning(art)
    assert pr["synthesis_headings"] == 0
    assert pr["synthesis_per_chapter"] == 0.0


def test_prose_reasoning_tension_resolution_rate():
    art = (
        "## 1 A\n\n"
        "The apparent paradox here resolves once we see the deeper mechanism.\n\n"
        "There is a clear tension between scale and speed in this design.\n"  # unresolved
    )
    pr = _validate_prose_reasoning(art)
    assert pr["tension_paras"] == 2
    assert pr["tension_resolved"] == 1
    assert pr["tension_resolution_rate"] == 0.5


def test_prose_reasoning_comparative_instead_not_counted_as_resolved():
    """A bare comparative `instead` must NOT mark a tension paragraph as
    resolved — it inflates the rate without any actual resolution (PR #59)."""
    art = (
        "## 1 A\n\n"
        "There is a trade-off here: we use batch processing instead of "
        "online processing to keep costs down.\n"
    )
    pr = _validate_prose_reasoning(art)
    assert pr["tension_paras"] == 1
    assert pr["tension_resolved"] == 0
    assert pr["tension_resolution_rate"] == 0.0
