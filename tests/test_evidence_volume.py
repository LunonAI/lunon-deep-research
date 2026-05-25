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

# Local mirrors of the production search-cap constants. Mirroring (rather
# than re-importing) is intentional: when production bumps the constant,
# the test using `_..._EXPECTED` fails until this mirror is bumped too —
# a "two keys turn the lock" guard against silent serialisation-cap drift.
_MAX_SEARCHES_PER_SPECIALIST_EXPECTED = 12
_RESULTS_EXPECTED = 10


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
    fired per specialist.

    Greptile PR #22 follow-up: pin via the constant rather than
    inspect.getsource — autoformatting (renaming the loop variable,
    splitting the slice across lines, introducing an intermediate variable)
    can silently break a source-string match without touching the cap. The
    constant is the actual contract."""
    assert specialists._FALLBACK_CAP == 24
    # Cross-check: _EXTRACT_SYSTEM still advertises the same upper bound the
    # fallback cap is supposed to mirror. If someone bumps the LLM ceiling
    # without bumping the fallback cap, this catches it.
    assert "14-24 findings" in specialists._EXTRACT_SYSTEM


def test_specialist_serialisation_cap_fits_post_p4_payload():
    """Greptile PR #22 follow-up: the SEARCH RESULTS string sent to the
    extraction LLM must fit the full post-#4 payload, not the pre-#4
    payload. With 12 searches × 10 results × ~1,600 chars/result ≈ 192k
    chars of expected payload, the prior 42k cap dropped ~75-80% of hits
    before the LLM ever saw them. The cap should sit at the upper end
    of the expected payload size with headroom — pin it here so a
    refactor lowering it (e.g. cargo-culting the old `[:42000]`) is
    caught loudly."""
    expected_payload_chars = _MAX_SEARCHES_PER_SPECIALIST_EXPECTED * _RESULTS_EXPECTED * 1_600
    # Cap must be at least the expected payload (no truncation in the
    # nominal case) and within a sensible headroom band.
    assert specialists._RESULTS_SERIALISATION_CAP >= expected_payload_chars, (
        f"cap {specialists._RESULTS_SERIALISATION_CAP} truncates the nominal "
        f"post-#4 payload ({expected_payload_chars} chars)"
    )
    # Upper sanity: don't blow past a reasonable input-token budget. At
    # ~4 chars/token, 400k chars ≈ 100k input tokens — well inside any
    # frontier model's context.
    assert specialists._RESULTS_SERIALISATION_CAP <= 400_000, (
        f"cap {specialists._RESULTS_SERIALISATION_CAP} is suspiciously large"
    )


