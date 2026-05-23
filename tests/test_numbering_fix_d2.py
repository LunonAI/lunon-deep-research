"""Unit tests for P2-Wave-2.5-D2-F3 pre_fix_deep_numeric telemetry.

The renumber pass (P2-F) already auto-fixes 4+-level numeric prefixes in
headings by stripping them and re-assigning based on markdown depth. This
test suite verifies the NEW telemetry that surfaces how often the writer
attempts the violation — so drift logs can answer "is our prompt working?"
without us having to re-instrument every dev pass.
"""

from deep_research.pipeline.numbering_fix import count_pre_fix_deep_numeric, run


def test_count_pre_fix_zero_for_compliant_text():
    text = "# Title\n\n## 1 Section\n\n### 1.1 Sub\n\n#### 1.1.1 SubSub\n\nBody."
    assert count_pre_fix_deep_numeric(text) == 0


def test_count_pre_fix_finds_4_level_numeric():
    """`### 1.8.3.6 Title` is 4 numeric levels — the W9 id=91 failure case."""
    text = "## 1 Outer\n\n### 1.8.3.6 Inner\n\nBody."
    assert count_pre_fix_deep_numeric(text) == 1


def test_count_pre_fix_finds_5_level_numeric():
    text = "### 1.1.1.1.1 Way too deep\n\nBody."
    assert count_pre_fix_deep_numeric(text) == 1


def test_count_pre_fix_counts_multiple_violations():
    text = (
        "# Title\n\n"
        "## 1 Outer\n\n"
        "### 1.8.3.3 Anime\n\n"
        "### 1.8.3.4 Critique\n\n"
        "### 1.8.3.5 Projection\n\n"
        "### 1.8.3.6 Legacy\n\nBody."
    )
    assert count_pre_fix_deep_numeric(text) == 4


def test_count_pre_fix_ignores_3_level_numeric():
    """3 numeric levels (`1.1.1`) is the documented cap — must NOT count."""
    text = "## 1 Outer\n\n### 1.1 Mid\n\n#### 1.1.1 Inner\n\nBody."
    assert count_pre_fix_deep_numeric(text) == 0


def test_count_pre_fix_ignores_body_text():
    """Numeric chains in body prose must not count — only heading lines."""
    text = "## 1 Section\n\nAs discussed in 1.8.3.6 above, the result is X."
    assert count_pre_fix_deep_numeric(text) == 0


def test_run_includes_pre_fix_deep_numeric_in_cap_violations():
    """Integration: the run() result surfaces the count in cap_violations."""
    text = (
        "# Report Title\n\n"
        "## 1 Outer\n\n"
        "Body sentence one with substantial content here for the section.\n\n"
        "### 1.8.3.6 Way too deep\n\n"
        "Body sentence with enough content to survive collapse.\n\n"
        "Another body paragraph here for full coverage.\n"
    )
    out = run(text)
    assert "pre_fix_deep_numeric" in out.cap_violations
    assert out.cap_violations["pre_fix_deep_numeric"] >= 1


def test_run_post_fix_zero_4_level_numeric():
    """After run(), the article must contain zero 4+-level numeric headings —
    the renumber pass strips them. Verifies the F3 fix is intact."""
    text = (
        "# Report Title\n\n"
        "## 1 Outer\n\n"
        "Body with enough words to survive the empty-section collapse here.\n\n"
        "### 1.8.3.6 Deep one\n\n"
        "Body with enough words here to keep this section alive too.\n\n"
        "### 1.8.3.7 Deep two\n\n"
        "More body words to stay above the collapse threshold for sure.\n"
    )
    out = run(text)
    # After renumbering, all headings have <= 3 numeric levels.
    assert count_pre_fix_deep_numeric(out.article) == 0
