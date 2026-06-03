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
    import inspect

    from deep_research.pipeline import writer

    # Read write_section's source (not a file-wide single-line regex) so the probe
    # survives the writer.sec call being formatted across multiple lines. The
    # function issues exactly one LLM call, so its sole max_tokens= literal is it.
    fn_src = inspect.getsource(writer.write_section)
    matches = re.findall(r"max_tokens=(\d+)", fn_src)
    assert matches, "could not locate writer.write_section max_tokens literal"
    assert len(matches) == 1, f"expected one max_tokens in write_section, found {matches}"
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
    """Pin the ceiling at 12_000 (round 8: lowered 30_000→12_000 in lockstep with
    writer max_tokens 32000→14000 and the architect 12-16 chapter bands — length
    now comes from BREADTH, so each chapter completes in one pass instead of
    clamping to 30k and truncating). Flags accidental reverts in either direction."""
    assert SECTION_BUDGET_CEILING == 12_000


# --- P3b-v5: leaf-aware allocation (the candidate-vs-reference length lever) ---
from deep_research.pipeline import init_format as initf  # noqa: E402


def _toc_section(sid, n_subs, seeds_per_sub, depth="broad"):
    return {
        "id": sid,
        "title": sid,
        "depth_target": depth,
        "subsections": [
            {"title": f"{sid}.{j}", "depth_seeds": [f"s{k}" for k in range(seeds_per_sub)]} for j in range(n_subs)
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
    # round 8: the 12k ceiling compresses the achievable ratio (S1 clamps at 12k,
    # S2 sits at its share/floor) — the leaf-aware scaling still holds, just not 3×.
    assert em["S1"] >= 1.5 * em["S2"], f"leaf-heavy section not scaled: {em}"
    assert em["S1"] >= 12 * initf._PER_LEAF_TOKENS * 0.9  # near the leaf floor (15 leaves capped by ceiling)


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


def test_round8_length_preserved_by_breadth_and_no_section_clamps():
    """round-8 lockstep guard: lowering the ceiling 30k→12k must NOT shrink total
    length — the same total_tokens spreads across the new 12-16 chapter bands. With
    a representative ZH 'predict' plan (14 chapters × 4 subs × 3 seeds = 12 leaves
    each) the total must stay in the Qianfan band AND no section may clamp to the
    ceiling (a clamp == the mid-section truncation this change exists to remove).
    If a future edit drops the chapter bands or raises the leaf floor, this fails
    loudly instead of silently regressing length or re-introducing truncation."""
    toc = [_toc_section(f"S{i + 1}", 4, 3, depth="deep" if i % 3 == 0 else "broad") for i in range(14)]
    plan = {"_outline_audit": {"archetype": "predict"}, "report_toc": toc}
    em = _expected_map(plan, language="zh")
    total = sum(em.values())
    # Qianfan ZH ≈ 96k tok-equivalent; we target ≥ that (longer scores better on the
    # pairwise judge) but bounded so a runaway leaf-floor can't explode length.
    assert 80_000 <= total <= 180_000, f"total_target out of band: {total} ({em})"
    # NO section at the ceiling → every chapter completes in one writer pass.
    assert max(em.values()) < SECTION_BUDGET_CEILING, f"a section clamped to the ceiling (truncation risk): {em}"
