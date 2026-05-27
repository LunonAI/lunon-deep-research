"""Unit tests for P3-W0a — per-archetype `query.type` minimum proportions.

The HARD RULES bullet "Distribute query type to cover all needed analytical
functions" (architect.py line ~102) is structurally vague. P3-W0a quantifies
it: per-archetype FLOORS sourced from the per-archetype query-type
distributions in 14 Qianfan #1 reference articles. These tests pin the
contract that downstream specialists (mechanism_explorer, critic, etc.) and
the post-write compliance scorer rely on.

Test coverage targets (per the plan at /Users/hyattc/.claude/plans/...):
- Pin the dict values match the gap-map / phase3_engine_plan spec.
- Verify `_normalize` populates `query_type_*` audit fields.
- Verify `build()` system+user prompt interpolates the archetype-specific %.
- Verify unknown-archetype falls back to default proportions.
- Verify the audit shortfall fires when a query distribution misses a floor.

Test style mirrors `tests/test_architect.py` and
`tests/test_architect_per_archetype_shape.py`: no LLM mocks except via
`monkeypatch.setattr(llm.call_json, fake)`; helper `_make_queries(...)`
builds synthetic query lists; assertions include `f"got {actual}"` context
per the Greptile-pre-scan checklist.
"""

import pytest

from deep_research.pipeline import architect

# --------------------------------------------------------------------------
# 1. Constant integrity — pin the dict values.
# --------------------------------------------------------------------------


def test_per_archetype_mins_match_published_spec():
    """The constant must match the spec in
    transfer/p2_artifacts/phase3_engine_plan.md §1 (and gap-map §13.A
    review). Drift in the table = drift in the contract = drift in the
    compliance scorer = silent grading-bar shift. Pin every entry.
    """
    expected = {
        "list-all": {"factual": 0.40, "comparative": 0.20, "causal": 0.10, "critical": 0.10, "trend": 0.10},
        "compare": {"factual": 0.30, "comparative": 0.30, "causal": 0.10, "critical": 0.15, "trend": 0.10},
        "explain-mechanism": {
            "factual": 0.25,
            "causal": 0.30,
            "comparative": 0.10,
            "critical": 0.20,
            "trend": 0.10,
        },
        "predict": {"factual": 0.20, "causal": 0.20, "trend": 0.25, "critical": 0.15, "comparative": 0.15},
        "trend": {"factual": 0.20, "trend": 0.35, "causal": 0.15, "critical": 0.10, "comparative": 0.15},
        "recommend": {"factual": 0.25, "comparative": 0.25, "critical": 0.20, "causal": 0.15, "trend": 0.10},
    }
    assert architect._ARCHETYPE_QUERY_TYPE_MIN_PCT == expected, (
        f"_ARCHETYPE_QUERY_TYPE_MIN_PCT drifted from published spec; got {architect._ARCHETYPE_QUERY_TYPE_MIN_PCT}"
    )


def test_per_archetype_mins_sum_to_at_most_one():
    """Each archetype's floors must sum to ≤ 1.0 (residual lets the
    architect choose where the marginal queries go). A sum > 1.0 would
    make the contract structurally unsatisfiable."""
    for archetype, mins in architect._ARCHETYPE_QUERY_TYPE_MIN_PCT.items():
        total = sum(mins.values())
        assert total <= 1.0 + 1e-9, f"{archetype} floors sum to {total:.4f} > 1.0"


def test_per_archetype_mins_use_only_known_query_types():
    """Every key in each archetype's mins must be a valid query.type
    (one of factual/causal/comparative/critical/trend, matching the
    TYPE_TO_SPECIALIST routing table)."""
    valid = set(architect.TYPE_TO_SPECIALIST.keys())
    for archetype, mins in architect._ARCHETYPE_QUERY_TYPE_MIN_PCT.items():
        unknown = set(mins.keys()) - valid
        assert not unknown, f"{archetype} has unknown query types {unknown}; valid={valid}"


def test_default_query_type_mins_present_and_balanced():
    """Unknown-archetype fallback must exist and cover all 5 query types
    (a default that omits a type would force unknown-archetype plans
    into starvation on that type)."""
    valid = set(architect.TYPE_TO_SPECIALIST.keys())
    missing = valid - set(architect._DEFAULT_QUERY_TYPE_MIN_PCT.keys())
    assert not missing, f"_DEFAULT_QUERY_TYPE_MIN_PCT missing {missing}"


def test_query_type_mins_accessor_returns_fresh_dict():
    """`_query_type_mins_for_archetype` must return a fresh dict so
    callers mutating the result don't corrupt the module-level constant.
    Mirrors PR #23 round-2 fix on `_bounds_for_archetype`."""
    a = architect._query_type_mins_for_archetype("predict")
    a["factual"] = 999
    b = architect._query_type_mins_for_archetype("predict")
    assert b["factual"] == 0.20, f"mutation leaked into module-level constant; got {b['factual']}"


def test_query_type_mins_accessor_unknown_archetype_falls_back():
    out_unknown = architect._query_type_mins_for_archetype("not-an-archetype")
    out_none = architect._query_type_mins_for_archetype(None)
    out_empty = architect._query_type_mins_for_archetype("")
    assert out_unknown == architect._DEFAULT_QUERY_TYPE_MIN_PCT, f"got {out_unknown}"
    assert out_none == architect._DEFAULT_QUERY_TYPE_MIN_PCT, f"got {out_none}"
    assert out_empty == architect._DEFAULT_QUERY_TYPE_MIN_PCT, f"got {out_empty}"


# --------------------------------------------------------------------------
# 2. `_normalize` audit instrumentation.
# --------------------------------------------------------------------------


def _make_queries(type_counts: dict) -> list:
    """Helper: build a synthetic query list with the given count per type.

    `type_counts = {"factual": 10, "causal": 5}` → 15 queries, first 10
    factual, next 5 causal. Other types absent.
    """
    out = []
    qid = 0
    for qtype, n in type_counts.items():
        for _ in range(n):
            qid += 1
            out.append({"id": f"Q{qid}", "text": f"q{qid}", "type": qtype})
    return out


def _plan_with_queries(queries: list) -> dict:
    """Minimal plan-shaped dict with the given query list."""
    return {
        "report_title": "T",
        "report_toc": [{"id": "S1", "title": "S1", "subsections": [], "depth_target": "broad"}],
        "queries": queries,
        "acceptance_criteria": [],
    }


def test_normalize_populates_query_type_counts_and_fractions():
    """A plan with 50 queries split 25/10/5/5/5 across the 5 types must
    surface counts + fractions in `_outline_audit`."""
    queries = _make_queries({"factual": 25, "causal": 10, "comparative": 5, "critical": 5, "trend": 5})
    plan = _plan_with_queries(queries)
    architect._normalize(plan, archetype="explain-mechanism")
    audit = plan["_outline_audit"]
    counts = audit["query_type_counts"]
    fractions = audit["query_type_fractions"]
    assert counts == {"factual": 25, "causal": 10, "comparative": 5, "critical": 5, "trend": 5}, f"got {counts}"
    assert fractions["factual"] == pytest.approx(0.5, abs=1e-3), f"got {fractions}"
    assert fractions["causal"] == pytest.approx(0.2, abs=1e-3), f"got {fractions}"


def test_normalize_flags_query_type_shortfall_for_archetype_floor():
    """explain-mechanism requires causal ≥30%. A plan with only 5/50 = 10%
    causal queries must produce `query_type.causal=10%<30%` shortfall.

    Query-type shortfalls live in their OWN audit list
    (`query_type_shortfalls`) and are NOT propagated into the global
    `shortfalls` list, because that list triggers the retry-on-shortfall
    loop and we don't want a 9-vs-10% query-type miss to burn a retry
    while the outline is structurally fine. The compliance scorer and
    retry-feedback string (which interpolates the floors when a retry IS
    triggered for a structural reason) jointly enforce the contract.
    """
    queries = _make_queries({"factual": 35, "causal": 5, "comparative": 5, "critical": 3, "trend": 2})
    plan = _plan_with_queries(queries)
    architect._normalize(plan, archetype="explain-mechanism")
    audit = plan["_outline_audit"]
    shortfalls = audit["query_type_shortfalls"]
    assert any("causal" in s for s in shortfalls), f"got {shortfalls}"


def test_normalize_query_type_shortfalls_isolated_from_global_shortfalls():
    """Query-type shortfalls must NOT enter the global `shortfalls` list
    (which is the retry trigger). A plan that misses every query-type
    floor but has perfect structural counts should have 0 global
    shortfalls (so no retry fires) and non-zero query-type shortfalls
    (so drift telemetry still sees the miss)."""
    # 100% factual — fails every other archetype floor.
    queries = _make_queries({"factual": 50})
    plan = _plan_with_queries(queries)
    architect._normalize(plan, archetype="explain-mechanism")
    audit = plan["_outline_audit"]
    # Query-type shortfalls present:
    assert audit["query_type_shortfalls"], f"expected query-type shortfalls; got {audit}"
    # But not any of them are in the global shortfalls list (other
    # structural shortfalls might be — e.g. queries=50 is within band
    # but top-sections might trip; for this specific plan only top-
    # sections=1 trips so global shortfalls is non-empty, but it must
    # NOT contain any query_type strings).
    qt_in_global = [s for s in audit["shortfalls"] if s.startswith("query_type.")]
    assert qt_in_global == [], f"query-type shortfalls leaked into global retry list: {qt_in_global}"


def test_normalize_no_shortfall_when_distribution_above_floor():
    """When a plan is generously above all archetype floors, no query-
    type shortfalls fire. (Other shortfalls — e.g. query count — may
    still fire and are unrelated; this test asserts query-type silence
    only.)"""
    # predict floors: factual≥20%, causal≥20%, trend≥25%, critical≥15%, comparative≥15%
    # Use 12/12/14/9/9 = 56 total → 21.4%/21.4%/25%/16.1%/16.1% (all above floors with margin).
    queries = _make_queries({"factual": 12, "causal": 12, "trend": 14, "critical": 9, "comparative": 9})
    plan = _plan_with_queries(queries)
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert audit["query_type_shortfalls"] == [], f"got unexpected shortfalls {audit['query_type_shortfalls']}"


def test_normalize_handles_zero_queries_without_division_by_zero():
    """Empty query list shouldn't crash the fraction computation. Audit
    reports 0.0 fractions and shortfall for each non-zero floor."""
    plan = _plan_with_queries([])
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    fractions = audit["query_type_fractions"]
    # All fractions are 0.0; shortfalls list is EMPTY because the
    # contract only kicks in when n_q > 0 (zero-query is already covered
    # by the `queries=0<48` structural shortfall).
    assert all(v == 0.0 for v in fractions.values()), f"got {fractions}"
    assert audit["query_type_shortfalls"] == []


def test_normalize_unknown_archetype_uses_default_floors():
    """Unknown archetype → default floors used in the audit. A plan
    below those defaults still surfaces shortfalls."""
    queries = _make_queries({"factual": 50})  # 100% factual, missing every other type
    plan = _plan_with_queries(queries)
    architect._normalize(plan, archetype="not-a-real-archetype")
    audit = plan["_outline_audit"]
    # Default has causal≥20%, comparative≥20%, etc. — should surface shortfalls.
    assert audit["query_type_shortfalls"], f"expected shortfalls; got {audit}"
    for qtype in ("causal", "comparative", "critical", "trend"):
        assert any(qtype in s for s in audit["query_type_shortfalls"]), (
            f"missing {qtype} shortfall in {audit['query_type_shortfalls']}"
        )


def test_normalize_audit_carries_min_pct_snapshot():
    """`audit["query_type_min_pct"]` carries the active floors so dev-run
    analysers can correlate shortfall measurements with the contract that
    was in effect at that moment (e.g. when the spec changes, prior runs
    in the drift log retain their original floors). Independent dict so
    mutation doesn't leak back."""
    plan = _plan_with_queries(_make_queries({"factual": 10}))
    architect._normalize(plan, archetype="trend")
    audit = plan["_outline_audit"]
    assert audit["query_type_min_pct"] == architect._ARCHETYPE_QUERY_TYPE_MIN_PCT["trend"], (
        f"got {audit['query_type_min_pct']}"
    )


# --------------------------------------------------------------------------
# 3. `build()` user-prompt interpolation.
# --------------------------------------------------------------------------


def test_build_interpolates_archetype_query_type_block(monkeypatch):
    """When `build()` calls llm.call_json, the user prompt must include
    the per-archetype query-type floor block with the correct percentages
    for the given archetype."""
    captured = {}

    def fake_call_json(role, user, *, system, max_tokens, effort=None, think=False, note=""):
        captured["user"] = user
        captured["system"] = system
        # Return a valid-shaped plan so build() doesn't crash post-call.
        return {
            "report_title": "T",
            "report_toc": [
                {
                    "id": f"S{i + 1}",
                    "title": f"Sec {i + 1}",
                    "subsections": [
                        {"id": f"S{i + 1}.{j + 1}", "title": f"Sub {j + 1}", "depth_seeds": ["seed1", "seed2"]}
                        for j in range(3)
                    ],
                    "depth_target": "deep",
                }
                for i in range(9)
            ],
            "queries": _make_queries({"factual": 10, "causal": 12, "comparative": 10, "critical": 9, "trend": 9}),
            "acceptance_criteria": [{"id": f"AC{i + 1}", "text": "x"} for i in range(24)],
        }

    monkeypatch.setattr(architect.llm, "call_json", fake_call_json)
    _ = architect.build(
        prompt="What are quantum advantage mechanisms?",
        language="en",
        archetype="explain-mechanism",
        intents=[],
        landscape={},
        coverage_obligations=[],
    )
    user = captured["user"]
    # Check the per-archetype block is present + contains the specific
    # explain-mechanism floors (causal ≥30% is the distinctive one).
    assert "QUERY TYPE DISTRIBUTION FLOOR" in user, f"block missing from prompt; got {user[:500]}"
    assert "causal≥30%" in user, f"explain-mech causal floor missing; got {user}"
    assert "factual≥25%" in user, f"explain-mech factual floor missing; got {user}"


def test_build_interpolates_different_floors_for_different_archetypes(monkeypatch):
    """list-all has factual≥40% while explain-mechanism has factual≥25% —
    the prompt must differ between archetypes (not a static string)."""
    captured = []

    def fake_call_json(role, user, *, system, max_tokens, effort=None, think=False, note=""):
        captured.append(user)
        return {
            "report_title": "T",
            "report_toc": [
                {
                    "id": f"S{i + 1}",
                    "title": f"Sec {i + 1}",
                    "subsections": [
                        {"id": f"S{i + 1}.{j + 1}", "title": f"Sub {j + 1}", "depth_seeds": ["a", "b"]}
                        for j in range(3)
                    ],
                    "depth_target": "deep",
                }
                for i in range(35)
            ],
            "entity_matrix": {"entities": ["E1", "E2", "E3", "E4", "E5"], "dimensions": ["D1", "D2", "D3", "D4"]},
            "queries": _make_queries({"factual": 24, "comparative": 12, "causal": 6, "critical": 6, "trend": 6}),
            "acceptance_criteria": [{"id": f"AC{i + 1}", "text": "x"} for i in range(24)],
        }

    monkeypatch.setattr(architect.llm, "call_json", fake_call_json)
    architect.build("p", "en", "list-all", [], {}, [])
    architect.build("p", "en", "explain-mechanism", [], {}, [])
    # `build()` may retry on audit shortfalls (the synthetic plan above
    # is intentionally minimal and won't satisfy every bound); capture is
    # therefore 2+ prompts per archetype. We assert per-archetype FRACTION
    # presence/absence rather than pinning the exact prompt count.
    list_all_prompts = [p for p in captured if "ARCHETYPE: list-all" in p]
    explain_mech_prompts = [p for p in captured if "ARCHETYPE: explain-mechanism" in p]
    assert list_all_prompts, f"no list-all prompt captured; got archetypes {[p[:100] for p in captured]}"
    assert explain_mech_prompts, f"no explain-mechanism prompt captured; got archetypes {[p[:100] for p in captured]}"
    for p in list_all_prompts:
        assert "factual≥40%" in p, f"list-all floor missing; got {p[:500]}"
        assert "factual≥25%" not in p.replace("factual≥40%", ""), "wrong floor in list-all prompt"
    for p in explain_mech_prompts:
        assert "factual≥25%" in p, f"explain-mech floor missing; got {p[:500]}"
        assert "factual≥40%" not in p, "list-all floor leaked into explain-mech prompt"


# --------------------------------------------------------------------------
# 4. Retry feedback includes the query-type floor.
# --------------------------------------------------------------------------


def test_format_retry_feedback_includes_query_type_floor():
    """The `_format_retry_feedback` string is what gets fed back to the
    architect on retry. Retries are ALWAYS triggered by structural
    shortfalls (see `_normalize`: query-type shortfalls live in
    `audit["query_type_shortfalls"]` and are advisory-only — never added
    to `audit["shortfalls"]`, so a query-type miss alone cannot cost a
    retry). But when a retry IS triggered for a structural reason, the
    per-archetype floor clause must be appended to the feedback so the
    regenerator fixes the structural problem AND keeps the query-type
    contract intact on retry — without this, the architect would refresh
    the outline but drift the query-type distribution. P3-W0a wires that
    floor clause in."""
    # Realistic audit shape: structural shortfall (drives the retry) plus
    # a query-type shortfall in its dedicated advisory bucket.
    audit = {
        "n_top_sections": 5,
        "n_subsections_total": 15,
        "n_seeds_total": 30,
        "shortfalls": ["top_sections=5<8"],
        "query_type_shortfalls": ["query_type.causal=10%<30%"],
    }
    feedback = architect._format_retry_feedback(audit, archetype="explain-mechanism")
    # Floor clause for THIS archetype's causal type must appear — sourced
    # from `_query_type_mins_for_archetype`, not from the audit. This is
    # the contract clause that keeps query-type distribution stable on retry.
    assert "causal≥30%" in feedback, f"causal floor missing from retry feedback; got: {feedback}"
    # The structural shortfall (the actual retry trigger) must be enumerated
    # so the regenerator knows what to fix.
    assert "top_sections=5<8" in feedback, f"structural shortfall missing from retry feedback; got: {feedback}"
    # Pin the advisory-only invariant: per-type shortfall strings from
    # `query_type_shortfalls` must NOT leak into the LLM-facing feedback —
    # only the floor clause does. If this assert ever fires, someone wired
    # `_format_retry_feedback` to iterate `query_type_shortfalls` and the
    # advisory/blocking separation needs to be re-justified.
    assert "query_type.causal=10%<30%" not in feedback, (
        f"per-type shortfall leaked into retry feedback (should stay advisory-only); got: {feedback}"
    )


def test_format_retry_feedback_handles_unknown_archetype():
    """Retry feedback for unknown archetype uses default floors."""
    audit = {"n_top_sections": 5, "n_subsections_total": 10, "n_seeds_total": 20, "shortfalls": ["top_sections=5<8"]}
    feedback = architect._format_retry_feedback(audit, archetype=None)
    # Default has factual≥25%.
    assert "factual≥25%" in feedback, f"default floor missing; got {feedback}"


# --------------------------------------------------------------------------
# 5. Co-existence with existing audit (no regression).
# --------------------------------------------------------------------------


def test_normalize_preserves_existing_audit_fields():
    """P3-W0a added query_type_* fields; pre-existing fields
    (n_top_sections, n_subsections_total, shortfalls re structural counts)
    must not be removed."""
    queries = _make_queries({"factual": 10})
    plan = _plan_with_queries(queries)
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    for k in (
        "n_top_sections",
        "n_subsections_total",
        "n_seeds_total",
        "n_queries",
        "shortfalls",
        "archetype",
        "bounds",
    ):
        assert k in audit, f"existing audit field `{k}` missing"


def test_normalize_called_without_archetype_uses_default_floors():
    """Back-compat: pre-Wave-2 callers that didn't pass archetype must
    still work and audit against default floors."""
    plan = _plan_with_queries(_make_queries({"factual": 50}))  # 100% factual
    architect._normalize(plan)  # no archetype
    audit = plan["_outline_audit"]
    # Default has causal≥20%; 0% causal triggers shortfall.
    assert any("causal" in s for s in audit["query_type_shortfalls"]), f"got {audit}"
