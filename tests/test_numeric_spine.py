"""Round 7 Fix C: numeric-spine contract.

The dev6 id-44 collapse was 6+ conflicting headline totals (judge "体系崩塌",
1.0/9.0 on the core question). The architect now plans a `numeric_spine`
(owner chapter + canonical unit + triangulation methods) and the writer
enforces ONE coherent figure: the owner chapter derives it, every other
chapter reuses it verbatim. A purely-deterministic conflict gate proved
non-viable (it flagged the reference's correct triangulation), so the contract is
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
