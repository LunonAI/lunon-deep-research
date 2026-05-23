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


def test_write_section_uses_writer_call_token_cap(monkeypatch):
    """P2-Wave-2.5-D1 Greptile follow-up (PR #12, second round): the actual
    llm.call inside write_section MUST use the WRITER_CALL_TOKEN_CAP constant
    (scaled with target_tokens), not the legacy literal 7000. Pre-fix the
    constant existed but the call used a hardcoded 7000 → real safety
    margin was only 350 tokens vs validator pass-line, not the documented
    16k headroom."""
    from deep_research.pipeline import writer as writer_mod

    captured: dict = {}

    def fake_llm_call(role, user, *, system="", max_tokens=8000, note="", **kw):
        captured["max_tokens"] = max_tokens
        return "stub section text"

    monkeypatch.setattr(writer_mod.llm, "call", fake_llm_call)
    monkeypatch.setenv("DR_CAPEL_G", "off")  # quiet CAPEL block

    class _StubBank:
        def for_section(self, sid):
            return []

    unit = {"id": "S1", "title": "Section", "subs": [], "depth": "deep"}
    plan = {"report_toc": [{"id": "S1", "title": "Section"}], "acceptance_criteria": []}
    writer_mod.write_section(
        unit,
        plan,
        _StubBank(),
        prompt="q",
        language="en",
        archetype="explain-mechanism",
        domain="default",
        prior_titles=["Section"],
        target_tokens=SECTION_BUDGET_CEILING,
    )
    # Dynamic cap: max(7000, int(9500 * 1.4)) = 13300 — well above the legacy
    # 7000. Confirms the WRITER_CALL_TOKEN_CAP constant is actually wired
    # into the llm.call invocation, not just declared in module scope.
    assert captured["max_tokens"] > 7_000
    assert captured["max_tokens"] <= WRITER_CALL_TOKEN_CAP
    assert captured["max_tokens"] == int(SECTION_BUDGET_CEILING * 1.4)


def test_write_section_max_tokens_clamped_to_writer_call_cap(monkeypatch):
    """Very large target_tokens must not exceed WRITER_CALL_TOKEN_CAP — a
    future SECTION_BUDGET_CEILING bump can't accidentally push max_tokens
    past Opus's per-call output budget."""
    from deep_research.pipeline import writer as writer_mod

    captured: dict = {}

    def fake_llm_call(role, user, *, system="", max_tokens=8000, note="", **kw):
        captured["max_tokens"] = max_tokens
        return "stub"

    monkeypatch.setattr(writer_mod.llm, "call", fake_llm_call)
    monkeypatch.setenv("DR_CAPEL_G", "off")

    class _StubBank:
        def for_section(self, sid):
            return []

    unit = {"id": "S1", "title": "x", "subs": [], "depth": "deep"}
    plan = {"report_toc": [{"id": "S1", "title": "x"}], "acceptance_criteria": []}
    writer_mod.write_section(
        unit,
        plan,
        _StubBank(),
        prompt="q",
        language="en",
        archetype="compare",
        domain="default",
        prior_titles=["x"],
        target_tokens=100_000,  # ridiculously large; clamp engages
    )
    assert captured["max_tokens"] == WRITER_CALL_TOKEN_CAP


def test_write_section_falls_back_to_7000_when_no_target(monkeypatch):
    """Smoke runs without target_tokens (unit tests, ad-hoc callers) keep
    the legacy 7000 cap so backward-compat with non-scaffold callers holds."""
    from deep_research.pipeline import writer as writer_mod

    captured: dict = {}

    def fake_llm_call(role, user, *, system="", max_tokens=8000, note="", **kw):
        captured["max_tokens"] = max_tokens
        return "stub"

    monkeypatch.setattr(writer_mod.llm, "call", fake_llm_call)
    monkeypatch.setenv("DR_CAPEL_G", "off")

    class _StubBank:
        def for_section(self, sid):
            return []

    unit = {"id": "S1", "title": "x", "subs": [], "depth": "broad"}
    plan = {"report_toc": [{"id": "S1", "title": "x"}], "acceptance_criteria": []}
    writer_mod.write_section(
        unit,
        plan,
        _StubBank(),
        prompt="q",
        language="en",
        archetype="compare",
        domain="default",
        prior_titles=["x"],
        # target_tokens omitted → fall back to legacy 7000
    )
    assert captured["max_tokens"] == 7_000
