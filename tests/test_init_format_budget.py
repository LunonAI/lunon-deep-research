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
    """Pin the ceiling at 18_000 (round-5 T1-PR3: lowered 30_000→18_000 to cap a
    chapter at Qianfan's largest observed chapter ~13.5k words and prevent the
    id=89 §2.3 runaway BUDGET; writer max_tokens stays 21000, 0.7×18000=12600 is
    comfortably inside the call). Flags accidental reverts in either direction."""
    assert SECTION_BUDGET_CEILING == 18_000


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
    """A deep multi-leaf section gets more budget than a shallow 1-leaf section —
    was ~equal under the old depth-only split, the root cause of starved deep ZH
    chapters. round-5 T1-PR3: a section heavy enough to blow past the 18000
    ceiling SATURATES at it (the runaway cap) while still exceeding the shallow
    section — leaf-aware ordering holds, the runaway budget does not."""
    plan = {
        "_outline_audit": {"archetype": "explain-mechanism"},
        "report_toc": [_toc_section("S1", 5, 3), _toc_section("S2", 1, 0)],  # 15 leaves vs 1
    }
    em = _expected_map(plan, language="zh")
    assert em["S1"] > em["S2"], f"leaf-heavy section not scaled: {em}"
    assert em["S1"] == initf.SECTION_BUDGET_CEILING  # 15-leaf section saturates the ceiling


def test_leaf_aware_scaling_proportional_below_ceiling():
    """Under the ceiling, budget still scales with leaf count: a 4-leaf section
    gets more than a 1-leaf section (many sections dilute each share so neither
    saturates the 18000 runaway cap)."""
    fillers = [_toc_section(f"F{i}", 2, 2) for i in range(10)]
    plan = {
        "_outline_audit": {"archetype": "explain-mechanism"},
        "report_toc": [_toc_section("S1", 2, 2), _toc_section("S2", 1, 0), *fillers],  # 4 leaves vs 1
    }
    em = _expected_map(plan, language="zh")
    assert em["S1"] < initf.SECTION_BUDGET_CEILING and em["S2"] < initf.SECTION_BUDGET_CEILING
    assert em["S1"] > em["S2"], f"leaf-aware ordering broke below the ceiling: {em}"


def test_en_list_all_allocation_is_leaf_aware_after_gate_removal():
    """round 5 T2-PR6: the `_is_en_list_all` no-grow gate is GONE. Under the
    T2-PR4 group-and-nest shape EN list-all is ~9 nested chapters and must use
    the SAME leaf-aware allocation as everything else (the gate was starving it,
    id=89 at 0.47× Qianfan length). A leaf-heavy chapter now gets more than a
    shallow one on EN too."""
    toc = [_toc_section("S1", 4, 2), _toc_section("S2", 1, 0)]  # 8 leaves vs 1
    fillers = [_toc_section(f"F{i}", 2, 2) for i in range(10)]  # dilute share so floors bind below ceiling
    en = _expected_map({"_outline_audit": {"archetype": "list-all"}, "report_toc": [*toc, *fillers]}, language="en")
    assert en["S1"] > en["S2"], f"EN list-all should now scale with leaves: {en}"
