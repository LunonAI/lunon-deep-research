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
    """Pin the ceiling at 30_000 (P3b-v5: raised 20_000→30_000 in lockstep with
    writer max_tokens 14000→21000, 30000×0.7=21000, for the ZH length lever).
    Allows future bumps but flags accidental reverts."""
    assert SECTION_BUDGET_CEILING == 30_000


# --- P3b-v5: leaf-aware allocation (the candidate-vs-reference length lever) ---
from deep_research.pipeline import init_format as initf  # noqa: E402


def _toc_section(sid, n_subs, seeds_per_sub, depth="broad"):
    return {
        "id": sid, "title": sid, "depth_target": depth,
        "subsections": [
            {"title": f"{sid}.{j}", "depth_seeds": [f"s{k}" for k in range(seeds_per_sub)]}
            for j in range(n_subs)
        ],
    }


def _expected_map(plan, language="zh", domain="default"):
    out = initf.run(initf.InitFormatInput(plan=plan, language=language, domain=domain)).scaffold
    return {s.section_id: s.expected_length_tokens for s in out.sections}


def test_leaf_aware_budget_scales_with_planned_leaves():
    """A deep multi-leaf section gets proportionally more budget than a shallow
    1-leaf section — was ~equal under the old depth-only split, the root cause of
    starved deep ZH chapters."""
    plan = {
        "_outline_audit": {"archetype": "explain-mechanism"},
        "report_toc": [_toc_section("S1", 5, 3), _toc_section("S2", 1, 0)],  # 15 leaves vs 1
    }
    em = _expected_map(plan, language="zh")
    assert em["S1"] >= 3 * em["S2"], f"leaf-heavy section not scaled: {em}"
    assert em["S1"] >= 15 * initf._PER_LEAF_TOKENS * 0.9  # near the leaf floor


def test_en_list_all_allocation_is_leaf_blind_regression_lock():
    """id91 / EN list-all MUST NOT grow: the leaf-aware weights + leaf_floor are
    gated OFF, so leaf count is ignored and two same-depth sections get the SAME
    share regardless of leaf count. The single pass/fail tripwire for the gate."""
    toc = [_toc_section("S1", 10, 4), _toc_section("S2", 1, 0)]  # 40 leaves vs 1
    en = _expected_map({"_outline_audit": {"archetype": "list-all"}, "report_toc": toc}, language="en")
    assert en["S1"] == en["S2"], f"EN list-all leaked leaf scaling (id91 regression): {en}"
    # the SAME toc on a ZH task DOES scale → proves the gate is the only difference
    zh = _expected_map({"_outline_audit": {"archetype": "list-all"}, "report_toc": toc}, language="zh")
    assert zh["S1"] > zh["S2"]
