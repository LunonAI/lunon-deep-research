"""Round 7 Fix C: numeric-spine contract.

The dev6 id-44 collapse was 6+ conflicting headline totals (judge "体系崩塌",
1.0/9.0 on the core question). The architect now plans a `numeric_spine`
(owner chapter + canonical unit + triangulation methods) and the writer
enforces ONE coherent figure: the owner chapter derives it, every other
chapter reuses it verbatim. A purely-deterministic conflict gate proved
non-viable (it flagged Qianfan's correct triangulation), so the contract is
the architect plan field + the writer directive.
"""

from deep_research.pipeline import writer as w

_PLAN = {
    "report_toc": [{"id": "S3", "title": "测算"}, {"id": "S5", "title": "供应商"}],
    "queries": [],
    "numeric_spine": {
        "quantity": "年度碳滑板用量",
        "unit": "万根",
        "owner_section": "S3",
        "methods": ["自下而上 units×rate×freq", "自上而下 market÷price"],
    },
}


class _Bank:
    def for_section(self, sid):
        return []


def _capture_user(monkeypatch):
    captured = []

    def fake_call(role, user, *, system, max_tokens, note, **kw):
        captured.append(user)
        return "synthetic body"

    monkeypatch.setattr(w.llm, "call", fake_call)
    return captured


def test_numeric_spine_owner_section_gets_derive_directive(monkeypatch):
    captured = _capture_user(monkeypatch)
    w.write_section(
        {"id": "S3", "title": "测算", "depth": "deep", "subs": []},
        _PLAN,
        _Bank(),
        prompt="t",
        language="zh",
        archetype="explain-mechanism",
        domain="default",
        prior_titles=["测算", "供应商"],
    )
    assert "NUMERIC SPINE" in captured[-1]
    assert "OWNER chapter" in captured[-1] and "restate it VERBATIM" in captured[-1]
    assert "万根" in captured[-1]


def test_numeric_spine_non_owner_section_gets_reuse_directive(monkeypatch):
    captured = _capture_user(monkeypatch)
    w.write_section(
        {"id": "S5", "title": "供应商", "depth": "broad", "subs": []},
        _PLAN,
        _Bank(),
        prompt="t",
        language="zh",
        archetype="explain-mechanism",
        domain="default",
        prior_titles=["测算", "供应商"],
    )
    assert "NUMERIC SPINE" in captured[-1]
    assert "restate that SAME figure" in captured[-1] and "S3" in captured[-1]
    assert "OWNER chapter" not in captured[-1]


def test_numeric_spine_absent_for_qualitative_plan(monkeypatch):
    captured = _capture_user(monkeypatch)
    plan = {"report_toc": [{"id": "S1", "title": "x"}], "queries": []}  # no numeric_spine
    w.write_section(
        {"id": "S1", "title": "x", "depth": "broad", "subs": []},
        plan,
        _Bank(),
        prompt="t",
        language="en",
        archetype="explain-mechanism",
        domain="default",
        prior_titles=["x"],
    )
    assert "NUMERIC SPINE" not in captured[-1]


# --- round 8: generative pre-derive (the structural fix) ---------------------

_LITERAL = "约 7-8 万根/年（区间 6-10 万根/年）"


def _plan_resolved():
    import copy

    p = copy.deepcopy(_PLAN)
    p["numeric_spine"]["resolved"] = {"value": "7-8万", "range": "6-10万", "unit": "万根", "literal": _LITERAL}
    return p


def test_resolved_literal_injected_verbatim_into_owner_and_non_owner(monkeypatch):
    """When the spine was pre-derived, EVERY section (owner + reuse) gets the SAME
    literal verbatim and the soft re-derive directive is gone — the structural fix
    for the dev6 6-conflicting-totals collapse."""
    plan = _plan_resolved()
    for sid, title, depth in [("S3", "测算", "deep"), ("S5", "供应商", "broad")]:
        captured = _capture_user(monkeypatch)
        w.write_section(
            {"id": sid, "title": title, "depth": depth, "subs": []},
            plan,
            _Bank(),
            prompt="t",
            language="zh",
            archetype="explain-mechanism",
            domain="default",
            prior_titles=["测算", "供应商"],
        )
        assert _LITERAL in captured[-1], f"{sid} missing the resolved literal"
        assert "use this EXACT figure" in captured[-1]
        # the soft re-derive phrasing must NOT appear once a literal is pinned
        assert "Derive ONE central estimate" not in captured[-1]


def test_write_opening_injects_resolved_literal_when_present_else_omits(monkeypatch):
    captured = _capture_user(monkeypatch)
    w.write_opening(_plan_resolved(), "t", "zh", "explain-mechanism", "default", "digest", task_id=None)
    assert _LITERAL in captured[-1] and "HEADLINE FIGURE" in captured[-1]

    captured2 = _capture_user(monkeypatch)
    w.write_opening(_PLAN, "t", "zh", "explain-mechanism", "default", "digest", task_id=None)  # no resolved
    assert "HEADLINE FIGURE" not in captured2[-1]  # None-safe omission


def test_write_opening_none_safe_when_numeric_spine_absent(monkeypatch):
    _capture_user(monkeypatch)
    plan = {"report_toc": [{"id": "S1", "title": "x"}], "queries": []}  # no numeric_spine at all
    # must not raise on the plan.get("numeric_spine") None path
    w.write_opening(plan, "t", "en", "explain-mechanism", "default", "digest", task_id=None)


def test_derive_numeric_spine_returns_resolved_dict(monkeypatch):
    def fake_call_json(role, user, *, system, max_tokens, note, **kw):
        assert note == "writer.spine"
        return {"value": "7-8万", "range": "6-10万", "unit": "万根", "literal": _LITERAL, "converged": True}

    monkeypatch.setattr(w.llm, "call_json", fake_call_json)
    out = w.derive_numeric_spine(_PLAN, "digest", "zh")
    assert out and out["literal"] == _LITERAL and out["unit"] == "万根"


def test_derive_numeric_spine_failsofts(monkeypatch):
    # (a) qualitative plan → no call, None
    assert w.derive_numeric_spine({"report_toc": [], "queries": []}, "d", "zh") is None
    # (b) non-converged (methods diverge >20%) → None (fall back to soft directive)
    monkeypatch.setattr(w.llm, "call_json", lambda *a, **k: {"literal": _LITERAL, "converged": False})
    assert w.derive_numeric_spine(_PLAN, "d", "zh") is None
    # (c) parse failure / exception → None
    def boom(*a, **k):
        raise ValueError("bad json")

    monkeypatch.setattr(w.llm, "call_json", boom)
    assert w.derive_numeric_spine(_PLAN, "d", "zh") is None
    # (d) missing literal → None
    monkeypatch.setattr(w.llm, "call_json", lambda *a, **k: {"value": "7万"})
    assert w.derive_numeric_spine(_PLAN, "d", "zh") is None
