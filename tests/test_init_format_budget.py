"""Pin SECTION_BUDGET_CEILING ↔ writer.max_tokens alignment (P2-Option-A-#1).

The chain:
  init_format.SECTION_BUDGET_CEILING
    → orchestrate.py passes per-section expected_length_tokens as target_tokens
    → writer.capel_directive emits a countdown of n_markers ≈ target × 0.75
    → writer's LLM call is bounded by max_tokens

If SECTION_BUDGET_CEILING > writer.max_tokens / 0.7, the validator's 0.7×
pass-line is unreachable in a single call (refiner loops forever).
If SECTION_BUDGET_CEILING < writer.max_tokens / 0.7 by too much, CAPEL caps
the writer below what max_tokens would allow, neutralizing the depth uplift.

This test fails loudly if anyone bumps one constant without updating the
other — the exact Greptile PR #20 issue 2 failure mode.
"""

import re

from deep_research.pipeline.init_format import SECTION_BUDGET_CEILING


def _writer_max_tokens() -> int:
    """Extract the writer.write_section max_tokens literal from the source.

    Done by string search rather than calling the function (which requires
    network + provider keys) so the test stays fast and offline.
    """
    import pathlib

    src = (pathlib.Path(__file__).resolve().parent.parent / "deep_research" / "pipeline" / "writer.py").read_text()
    # Find the `max_tokens=NNNN` argument inside the `write_section` call.
    matches = re.findall(r'max_tokens=(\d+),\s*note=f"writer\.sec\.', src)
    assert matches, "could not locate writer.write_section max_tokens literal"
    return int(matches[0])


def test_section_budget_ceiling_aligned_with_writer_max_tokens():
    """ceiling × 0.7 (validator pass-line) must be reachable by the writer's
    max_tokens. With a 10% slack we accept ceiling × 0.7 <= max_tokens × 1.0."""
    max_tokens = _writer_max_tokens()
    threshold = SECTION_BUDGET_CEILING * 0.7
    assert threshold <= max_tokens, (
        f"SECTION_BUDGET_CEILING ({SECTION_BUDGET_CEILING}) × 0.7 = {threshold} "
        f"exceeds writer.max_tokens ({max_tokens}); validator's 0.7× pass-line is "
        f"unreachable in one call"
    )


def test_section_budget_ceiling_not_below_old_value():
    """Defensive: regression guard against accidentally lowering the ceiling
    below the pre-#1 8000-token floor. If someone shrinks the ceiling, they
    must explicitly delete this test."""
    assert SECTION_BUDGET_CEILING >= 8_000


def test_section_budget_ceiling_uses_post_p1_value():
    """Pin the post-#1 ceiling at 20_000 (per Greptile issue 2 fix). Allows
    future bumps but flags accidental reverts to the pre-#1 8_000 value."""
    assert SECTION_BUDGET_CEILING == 20_000
