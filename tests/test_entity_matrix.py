"""Unit tests for the entity_matrix architect schema + writer wiring
(P2-Option-A-#7).

The entity_matrix is the article's structural spine for list-all and compare
archetypes — a matrix of entities × dimensions that the writer renders as a
table near the article start and uses to enforce equal-depth treatment per
entity downstream. The architect MUST populate it for those archetypes;
other archetypes omit (or null) it.
"""

import json

from deep_research.pipeline import architect, writer


def _plan_with_em(entities, dimensions):
    """Plan dict shape post-#7 with an explicit entity_matrix."""
    return {
        "report_title": "T",
        "entity_matrix": {"entities": entities, "dimensions": dimensions},
        "report_toc": [
            {
                "id": "S1",
                "title": "Sec 1",
                "subsections": [{"id": "S1.1", "title": "Sub", "depth_seeds": ["a", "b"]}],
                "depth_target": "broad",
            }
        ],
        "queries": [],
        "acceptance_criteria": [],
    }


def test_normalize_backfills_missing_entity_matrix_for_listall():
    """list-all archetype with NO entity_matrix field gets an empty backfilled
    matrix + a shortfall record. Writer never crashes on `em["entities"]`."""
    plan = {
        "report_title": "T",
        "report_toc": [],
        "queries": [],
        "acceptance_criteria": [],
    }
    architect._normalize(plan, archetype="list-all")
    assert plan["entity_matrix"] == {"entities": [], "dimensions": []}
    audit = plan["_outline_audit"]
    assert any("entity_matrix=missing" in s for s in audit["shortfalls"])


def test_normalize_backfills_missing_entity_matrix_for_compare():
    plan = {"report_toc": [], "queries": [], "acceptance_criteria": []}
    architect._normalize(plan, archetype="compare")
    assert plan["entity_matrix"]["entities"] == []
    assert any("entity_matrix=missing" in s for s in plan["_outline_audit"]["shortfalls"])


def test_normalize_does_not_inject_entity_matrix_for_other_archetypes():
    """explain-mechanism, predict, trend, recommend should NOT get an
    entity_matrix backfilled — it'd just be noise in the writer payload."""
    for archetype in ("explain-mechanism", "predict", "trend", "recommend"):
        plan = {"report_toc": [], "queries": [], "acceptance_criteria": []}
        architect._normalize(plan, archetype=archetype)
        assert "entity_matrix" not in plan, f"archetype={archetype} should not have entity_matrix injected"


def test_normalize_records_entity_undercount_shortfall():
    plan = _plan_with_em(["only-one"], ["a", "b", "c", "d"])
    architect._normalize(plan, archetype="list-all")
    audit = plan["_outline_audit"]
    assert audit["entity_matrix_entities"] == 1
    assert audit["entity_matrix_dimensions"] == 4
    assert any(s.startswith("entity_matrix.entities=") and "<" in s for s in audit["shortfalls"])


def test_normalize_records_entity_overcount_shortfall():
    plan = _plan_with_em(["e" + str(i) for i in range(25)], ["a", "b", "c", "d"])
    architect._normalize(plan, archetype="compare")
    audit = plan["_outline_audit"]
    assert audit["entity_matrix_entities"] == 25
    assert any(s.startswith("entity_matrix.entities=") and ">" in s for s in audit["shortfalls"])


def test_normalize_records_no_shortfalls_when_matrix_meets_bounds():
    """5-20 entities, 4-8 dimensions → no entity_matrix shortfalls."""
    plan = _plan_with_em(
        ["e1", "e2", "e3", "e4", "e5", "e6"],
        ["d1", "d2", "d3", "d4", "d5"],
    )
    # Use a fuller plan so the other audits also pass.
    plan["report_toc"] = [
        {
            "id": f"S{i + 1}",
            "title": "x",
            "subsections": [{"id": f"S{i + 1}.{j + 1}", "title": "x", "depth_seeds": ["a", "b"]} for j in range(3)],
            "depth_target": "broad",
        }
        for i in range(8)
    ]
    architect._normalize(plan, archetype="list-all")
    audit = plan["_outline_audit"]
    assert audit["shortfalls"] == [], f"unexpected shortfalls: {audit['shortfalls']}"


def test_normalize_back_compat_when_archetype_not_provided():
    """Old callers that hit _normalize without an `archetype` kwarg must
    still work — no entity_matrix audit fires, no entity_matrix backfilled."""
    plan = {"report_toc": [], "queries": [], "acceptance_criteria": []}
    architect._normalize(plan)
    assert "entity_matrix" not in plan
    # The outline_audit still gets populated, just without entity_matrix keys.
    assert "n_top_sections" in plan["_outline_audit"]


def test_writer_includes_entity_matrix_block_for_listall(monkeypatch):
    """For list-all archetype with a populated entity_matrix, the writer's
    section user-prompt must include the ENTITY MATRIX block + the matrix
    JSON. Other archetypes don't see it."""
    captured_user: dict[str, str] = {}

    def fake_call(_role, user, *, system, max_tokens, note):  # noqa: ARG001
        captured_user["text"] = user
        return "## 1 stub\n\nstub body."

    monkeypatch.setattr(writer.llm, "call", fake_call)

    plan = _plan_with_em(
        ["Bronze Saints", "Silver Saints", "Gold Saints", "Marina Generals", "Specters"],
        ["armor tier", "Cosmo class", "speed class", "wearer roster"],
    )
    unit = {
        "id": "S1",
        "title": "Foundations",
        "depth": "broad",
        "subs": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}],
    }

    class _DummyBank:
        def for_section(self, _sid):
            return []

    writer.write_section(
        unit,
        plan,
        _DummyBank(),
        prompt="p",
        language="en",
        archetype="list-all",
        domain="default",
        prior_titles=[],
        task_id=None,
        target_tokens=None,
    )
    assert "ENTITY MATRIX" in captured_user["text"]
    assert "Bronze Saints" in captured_user["text"]
    assert "Cosmo class" in captured_user["text"]


def test_writer_omits_entity_matrix_for_other_archetypes(monkeypatch):
    """Even if a plan has an entity_matrix populated, archetypes other than
    list-all/compare should NOT see it in the section prompt — it would just
    be noise that wastes context."""
    captured_user: dict[str, str] = {}

    def fake_call(_role, user, *, system, max_tokens, note):  # noqa: ARG001
        captured_user["text"] = user
        return "## 1 stub\n\nstub body."

    monkeypatch.setattr(writer.llm, "call", fake_call)

    plan = _plan_with_em(["a", "b", "c", "d", "e"], ["d1", "d2", "d3", "d4"])
    unit = {
        "id": "S1",
        "title": "Foundations",
        "depth": "broad",
        "subs": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}],
    }

    class _DummyBank:
        def for_section(self, _sid):
            return []

    writer.write_section(
        unit,
        plan,
        _DummyBank(),
        prompt="p",
        language="en",
        archetype="explain-mechanism",
        domain="default",
        prior_titles=[],
        task_id=None,
        target_tokens=None,
    )
    assert "ENTITY MATRIX" not in captured_user["text"]


def test_writer_handles_empty_entity_matrix_gracefully(monkeypatch):
    """list-all archetype where the architect emitted an EMPTY entities list
    should not crash and should not emit a malformed ENTITY MATRIX block."""
    captured_user: dict[str, str] = {}

    def fake_call(_role, user, *, system, max_tokens, note):  # noqa: ARG001
        captured_user["text"] = user
        return "## 1 stub\n\nstub body."

    monkeypatch.setattr(writer.llm, "call", fake_call)

    plan = _plan_with_em([], [])
    unit = {
        "id": "S1",
        "title": "Foundations",
        "depth": "broad",
        "subs": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}],
    }

    class _DummyBank:
        def for_section(self, _sid):
            return []

    writer.write_section(
        unit,
        plan,
        _DummyBank(),
        prompt="p",
        language="en",
        archetype="list-all",
        domain="default",
        prior_titles=[],
        task_id=None,
        target_tokens=None,
    )
    # Empty entities → block is suppressed (writer gets no noise).
    assert "ENTITY MATRIX" not in captured_user["text"]
    # Sanity: the rest of the prompt still has the section/subs payload.
    payload = json.loads(captured_user["text"].split("SUBSECTIONS")[1].split("\n", 1)[0].split(": ", 1)[1])
    assert payload[0]["id"] == "S1.1"
