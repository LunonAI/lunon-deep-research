"""Pin evidence-volume constants (P2-Option-A-#4).

The depth_seeds H4-leaf contract from PR #20 expects 200-450 leaves per
article × 3-5 evidence atoms per leaf = 600-2,250 atoms total. Pre-#4
the pipeline produced ~40-70 atoms per task (5 specialists × 5 search
calls × 5 results → ~25 raw hits per specialist, extracted to 8-14
findings). #4 raises the volume at three points: architect query count
(24-32 → 48-64), per-specialist search cap (5 → 12), and per-search
result count (5 → 10).

These tests fail loudly if any of those constants regress without the
others being updated — exactly the failure mode Greptile caught for the
SECTION_BUDGET_CEILING / writer.max_tokens pair in PR #20.
"""

from deep_research.pipeline import specialists
from deep_research.pipeline.architect import _SYSTEM as ARCHITECT_SYSTEM


def test_architect_advertises_new_query_count():
    """The architect's STRICT JSON spec must request 48-64 queries (the post-#4
    band). 24-32 was the pre-#4 bound and is no longer correct."""
    assert "48-64 ]" in ARCHITECT_SYSTEM
    assert "48-64 queries" in ARCHITECT_SYSTEM
    # Acceptance criteria stays at 24-32 (only queries doubled).
    assert "24-32 acceptance_criteria" in ARCHITECT_SYSTEM


def test_specialist_search_cap_post_p4():
    """Per-specialist max search calls = 12 (was 5). Must scale with the
    architect's 48-64 query budget so queries don't get silently dropped."""
    assert specialists._MAX_SEARCHES_PER_SPECIALIST == 12


def test_specialist_results_per_search_post_p4():
    """Per-search result count = 10 (was 5). Doubles raw-hit volume per
    query so extraction has enough material to produce 14-24 findings."""
    assert specialists._RESULTS_PER_SEARCH == 10


def test_specialist_finding_ceiling_post_p4():
    """_EXTRACT_SYSTEM advertises 14-24 findings per specialist call (was 8-14).
    Pin the new band so a refactor can't silently revert."""
    assert "14-24 findings" in specialists._EXTRACT_SYSTEM
    assert "8-14 findings" not in specialists._EXTRACT_SYSTEM


def test_specialist_fallback_cap_aligned_with_extract_ceiling():
    """_snippet_fallback should not produce more atoms than the LLM extract
    path's upper bound (24). If the fallback path runs ahead of the contract
    we'd see post-#4 articles inconsistently sized depending on which path
    fired per specialist."""
    import inspect

    src = inspect.getsource(specialists._snippet_fallback)
    assert "results[:24]" in src, f"fallback cap drifted from extract ceiling: {src}"
