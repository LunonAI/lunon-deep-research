"""Unit tests for P3-W6 — stakeholder chapter architect contract.

the reference pattern (6/11 articles): closing chapter splits recommendations
into 3-5 stakeholder addressee blocks with non-overlapping content.
The architect populates `stakeholder_chapter` when prompt signals a
plural audience.
"""

from deep_research.pipeline import architect


def _bare_plan_with_sc(stakeholders=None):
    sh = (
        stakeholders
        if stakeholders is not None
        else [
            {"id": "investors", "label": "For Investors", "content_directive": "..."},
            {"id": "policymakers", "label": "For Policymakers", "content_directive": "..."},
            {"id": "industry", "label": "For Industry Practitioners", "content_directive": "..."},
        ]
    )
    return {
        "report_title": "T",
        "report_toc": [{"id": "S1", "title": "S", "subsections": [], "depth_target": "broad"}],
        "queries": [{"id": f"Q{i}", "text": "q", "type": "factual"} for i in range(50)],
        "acceptance_criteria": [],
        "stakeholder_chapter": {
            "title": "Strategic Recommendations by Stakeholder",
            "stakeholders": sh,
        },
    }


def test_stakeholder_count_bounds_pinned():
    assert architect._STAKEHOLDER_COUNT_MIN == 3
    assert architect._STAKEHOLDER_COUNT_MAX == 5


def test_normalize_with_3_stakeholders_no_shortfall():
    plan = _bare_plan_with_sc()
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    sc_sf = [s for s in audit["shortfalls"] if "stakeholder_chapter" in s]
    assert sc_sf == [], f"got {sc_sf}"
    assert audit["stakeholder_chapter_count"] == 3


def test_normalize_below_min_count_emits_shortfall():
    plan = _bare_plan_with_sc(stakeholders=[{"id": "a", "label": "A", "content_directive": "..."}])
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert any("stakeholder_chapter.count=1<3" in s for s in audit["shortfalls"]), f"got {audit['shortfalls']}"


def test_normalize_above_max_count_emits_shortfall():
    sh = [{"id": f"s{i}", "label": f"S{i}", "content_directive": "..."} for i in range(7)]
    plan = _bare_plan_with_sc(stakeholders=sh)
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert any("stakeholder_chapter.count=7>5" in s for s in audit["shortfalls"])


def test_normalize_drops_malformed_stakeholders():
    """Entries missing `id` or not dict are filtered out."""
    sh = [
        {"id": "valid1", "label": "L1", "content_directive": "..."},
        {"label": "no-id"},  # missing id
        "not a dict",
        {"id": "valid2", "label": "L2", "content_directive": "..."},
        {"id": "valid3", "label": "L3", "content_directive": "..."},
    ]
    plan = _bare_plan_with_sc(stakeholders=sh)
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert audit["stakeholder_chapter_count"] == 3  # only valid1/2/3
    # 3 is at the floor — no shortfall.
    sc_sf = [s for s in audit["shortfalls"] if "stakeholder_chapter" in s]
    assert sc_sf == []


def test_normalize_missing_stakeholder_chapter_no_shortfall():
    """stakeholder_chapter is OPTIONAL — never required."""
    plan = _bare_plan_with_sc()
    plan.pop("stakeholder_chapter")
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    sc_sf = [s for s in audit["shortfalls"] if "stakeholder_chapter" in s]
    assert sc_sf == []


def test_prompt_signals_plural_audience_recognizes_investors_and_policymakers():
    assert architect._prompt_signals_plural_audience(
        "Provide recommendations for investors and policymakers on the future of clean energy."
    )


def test_prompt_signals_plural_audience_recognizes_recommendations_for_X():
    assert architect._prompt_signals_plural_audience(
        "What are the policy implications? Recommendations for industry stakeholders."
    )


def test_prompt_signals_plural_audience_recognizes_zh_patterns():
    assert architect._prompt_signals_plural_audience("面向多元主体提出战略建议")
    assert architect._prompt_signals_plural_audience("为投资者和决策者提供建议")


def test_prompt_signals_plural_audience_negative_cases():
    """Single-audience prompts should NOT trigger."""
    assert not architect._prompt_signals_plural_audience("Provide an overview of recent advances in quantum computing.")
    assert not architect._prompt_signals_plural_audience("分析最新的科技趋势")
    assert not architect._prompt_signals_plural_audience("")
    assert not architect._prompt_signals_plural_audience(None)


# --------------------------------------------------------------------------
# Greptile PR #42 round-2 — issue #2 wiring: `_prompt_signals_plural_audience`
# must be invoked from `build()` (the production code path) and its result
# must be reflected in the architect's user prompt as a `PLURAL_AUDIENCE_
# DETECTED: true/false` line. Previously the function was unreachable from
# production — only invoked by tests.
# --------------------------------------------------------------------------


def _capture_call_json(monkeypatch):
    """Intercept `llm.call_json` and return the captured kwargs/positional
    args so tests can inspect the user prompt."""
    captured: list[dict] = []

    def fake_call_json(role, user, *, system, max_tokens, effort=None, think=None, note=""):
        captured.append({"role": role, "user": user, "note": note})
        # Return a minimal valid plan so build() can normalize without crashing.
        return {
            "task_analysis": "x",
            "report_title": "T",
            "report_toc": [
                {
                    "id": f"S{i}",
                    "title": f"S{i}",
                    "subsections": [
                        {"id": f"S{i}.{j}", "title": f"S{i}.{j}", "depth_seeds": ["a", "b"]} for j in range(1, 4)
                    ],
                }
                for i in range(1, 10)
            ],
            "queries": [{"id": f"Q{i}", "text": "q", "type": "factual"} for i in range(1, 50)],
            "acceptance_criteria": [],
        }

    monkeypatch.setattr(architect.llm, "call_json", fake_call_json)
    return captured


def test_build_injects_plural_audience_true_into_user_prompt(monkeypatch):
    """When the prompt signals plural audience, `build()` must inject
    `PLURAL_AUDIENCE_DETECTED: true — populate stakeholder_chapter ...`
    into the architect's user prompt before the strict-JSON instruction.
    This is the production wiring of `_prompt_signals_plural_audience`."""
    captured = _capture_call_json(monkeypatch)
    architect.build(
        "Provide recommendations for investors and policymakers on clean energy.",
        "en",
        "predict",
        [],
        {},
        [],
    )
    assert captured, "architect.build did not invoke llm.call_json"
    user_prompt = captured[0]["user"]
    assert "PLURAL_AUDIENCE_DETECTED: true" in user_prompt, f"plural-audience hint missing: {user_prompt[-1500:]}"
    assert "populate `stakeholder_chapter`" in user_prompt, f"populate directive missing: {user_prompt[-1500:]}"
    # Sanity: the hint precedes the strict-JSON marker (so the LLM reads it
    # before deciding the chapter field).
    assert user_prompt.index("PLURAL_AUDIENCE_DETECTED") < user_prompt.index("Produce the STRICT JSON plan now"), (
        "plural-audience hint must precede the strict-JSON instruction"
    )


def test_build_injects_plural_audience_false_into_user_prompt(monkeypatch):
    """When the prompt has a single audience, the hint must be FALSE
    and direct the architect to set the chapter to null. This is the
    conservative path — prevents the chapter from bloating articles
    on prompts that don't ask for stakeholder-segmented advice."""
    captured = _capture_call_json(monkeypatch)
    architect.build(
        "Provide an overview of recent advances in quantum computing.",
        "en",
        "predict",
        [],
        {},
        [],
    )
    user_prompt = captured[0]["user"]
    assert "PLURAL_AUDIENCE_DETECTED: false" in user_prompt, (
        f"plural-audience=false hint missing: {user_prompt[-1500:]}"
    )
    assert "set `stakeholder_chapter` to null" in user_prompt, f"null directive missing: {user_prompt[-1500:]}"


def test_build_plural_audience_hint_works_for_zh_prompts(monkeypatch):
    """ZH plural-audience prompts must also be detected — the regex
    patterns include CJK variants. This pins the cross-lingual coverage."""
    captured = _capture_call_json(monkeypatch)
    architect.build("为投资者和决策者提供清洁能源建议", "zh", "predict", [], {}, [])
    user_prompt = captured[0]["user"]
    assert "PLURAL_AUDIENCE_DETECTED: true" in user_prompt, f"ZH plural-audience hint missing: {user_prompt[-1500:]}"


def test_normalize_zero_valid_stakeholders_emits_shortfall():
    """Greptile PR #42 round-5 issue #1: when the LLM emits stakeholders
    without `id` fields (e.g., `[{"label": "X"}, {"label": "Y"}, {"label":
    "Z"}]`), the normalization step strips them all and the list becomes
    `[]`. Pre-fix the `if sc["stakeholders"]:` guard skipped both count
    checks for the empty case, so the audit recorded
    `stakeholder_chapter_count=0` with NO shortfall — contradicting the
    `< _STAKEHOLDER_COUNT_MIN` check that fires for count=1 or count=2.
    Post-fix the count check covers 0 uniformly."""
    sh = [
        {"label": "Investors"},  # no id
        {"label": "Policymakers"},  # no id
        {"label": "Researchers"},  # no id
    ]
    plan = _bare_plan_with_sc(stakeholders=sh)
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert audit["stakeholder_chapter_count"] == 0
    sc_sf = [s for s in audit["shortfalls"] if "stakeholder_chapter.count=0<3" in s]
    assert sc_sf, f"zero-valid-stakeholders case must emit count<MIN shortfall; got {audit['shortfalls']}"


def test_plural_audience_for_both_pattern_rejects_non_audience_terms():
    """Greptile PR #42 round-6 issue #2: pre-fix the `\\bfor\\s+(?:both|
    each\\s+of)\\s+\\w+\\s+(?:and|&)\\s+\\w+` regex matched ANY "for both
    X and Y" construction, regardless of whether X and Y were audience
    terms. Prompts like "for both short and long time horizons" or "for
    both old and new architectures" would set PLURAL_AUDIENCE_DETECTED
    to true and force a spurious stakeholder_chapter.

    Post-fix the regex anchors both slots to the known audience
    vocabulary (investors / policymakers / regulators / researchers /
    practitioners / industry / stakeholders / consumers / users). The
    false-positive cases below must NOT match."""
    false_positives = [
        "Analyze this for both short and long time horizons.",
        "Compare for both old and new architectures.",
        "Evaluate for both quantum and classical regimes.",
        "Review the data for both Q1 and Q2 results.",
        "Document the API for both REST and GraphQL endpoints.",
        "Test for both happy and error paths thoroughly.",
        "Plan for both base and stretch scenarios.",
        "Optimize for both speed and memory usage.",
    ]
    for prompt in false_positives:
        assert architect._prompt_signals_plural_audience(prompt) is False, (
            f"false positive — prompt should NOT signal plural audience: {prompt!r}"
        )


def test_plural_audience_for_both_pattern_still_matches_audience_pairs():
    """Symmetric regression guard: the `for both X and Y` pattern must
    still fire for legitimate audience pairings (the post-fix vocabulary
    is the full set used by the other patterns)."""
    true_positives = [
        "Provide guidance for both investors and policymakers.",
        "Recommendations for both researchers and practitioners on AI.",
        "Analysis for both regulators and industry on energy transition.",
        "Advice for both consumers and users navigating the platform.",
        "Brief for each of stakeholders and researchers in the field.",
    ]
    for prompt in true_positives:
        assert architect._prompt_signals_plural_audience(prompt) is True, (
            f"regression — audience pair must signal plural audience: {prompt!r}"
        )
