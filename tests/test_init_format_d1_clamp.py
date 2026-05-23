"""Unit tests for P2-Wave-2.5-D1 Greptile follow-up (PR #12):
SECTION_BUDGET_CEILING clamp + WRITER_CALL_TOKEN_CAP scaling.

The scaffold's per-section `expected_length_tokens` MUST stay below what
`writer.write_section` can produce in a single LLM call, so the validator's
0.7× pass-line is reachable without triggering refiner-pass loops on the
comprehensive tier.
"""

from deep_research.pipeline.init_format import SECTION_BUDGET_CEILING, InitFormatInput, run
from deep_research.pipeline.writer import WRITER_CALL_TOKEN_CAP


def _plan(report_depth_tier: str | None, n_sections: int = 8, deep_weight_count: int = 4) -> dict:
    toc = []
    for i in range(n_sections):
        toc.append(
            {
                "id": f"S{i + 1}",
                "title": f"Section {i + 1}",
                "subsections": [],
                "depth_target": "deep" if i < deep_weight_count else "broad",
            }
        )
    plan = {"report_toc": toc, "queries": []}
    if report_depth_tier:
        plan["report_depth_tier"] = report_depth_tier
    return plan


def test_ceiling_constant_below_writer_cap():
    """The scaffold ceiling × 1.4 headroom must stay inside the writer call cap."""
    assert SECTION_BUDGET_CEILING * 1.4 <= WRITER_CALL_TOKEN_CAP


def test_ceiling_supports_validator_pass_line():
    """validator passes at >=0.7× expected. The writer cap must allow producing
    that many tokens for a section budgeted at SECTION_BUDGET_CEILING."""
    pass_line = int(SECTION_BUDGET_CEILING * 0.7)
    assert pass_line < WRITER_CALL_TOKEN_CAP


def test_comprehensive_deep_section_does_not_exceed_ceiling():
    """The original Greptile scenario: comprehensive report, half of 8 sections
    deep-weighted → would request 11,700 tokens per deep section without the
    clamp. With the clamp, every section comes out at SECTION_BUDGET_CEILING
    or below."""
    out = run(InitFormatInput(plan=_plan("comprehensive"), language="en", domain="default"))
    for sec in out.scaffold.sections:
        assert sec.expected_length_tokens <= SECTION_BUDGET_CEILING, (
            f"section {sec.section_id} budget {sec.expected_length_tokens} > ceiling"
        )


def test_compact_tier_still_gets_modest_budgets():
    """Compact tier shouldn't be inflated upward by the ceiling — it should
    still allocate per share, not at the cap."""
    out = run(InitFormatInput(plan=_plan("compact"), language="en", domain="default"))
    # Compact total tokens ≈ 9000 × 1.5 / 0.75 = 18,000 → 8 sections share.
    # Even with deep weighting the per-section budget should sit well below
    # ceiling on this tier.
    for sec in out.scaffold.sections:
        assert sec.expected_length_tokens < SECTION_BUDGET_CEILING


def test_min_floor_still_respected():
    """The pre-D1 800-token floor for tiny sections must still apply."""
    out = run(InitFormatInput(plan=_plan("compact", n_sections=14), language="en", domain="default"))
    for sec in out.scaffold.sections:
        assert sec.expected_length_tokens >= 800
