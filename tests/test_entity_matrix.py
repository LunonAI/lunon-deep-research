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
    matrix + a shortfall record. Writer never crashes on `em["entities"]`.

    P3-W1 (2026-05-27): the backfilled matrix now also includes the new
    `instantiation_mode` and `min_axes_per_entity` defaults so the writer
    sees a fully-shaped matrix regardless of whether the architect emitted
    one. We assert the load-bearing fields rather than the full dict to
    keep this test forward-compatible with future schema additions.
    """
    plan = {
        "report_title": "T",
        "report_toc": [],
        "queries": [],
        "acceptance_criteria": [],
    }
    architect._normalize(plan, archetype="list-all")
    em = plan["entity_matrix"]
    assert em["entities"] == []
    assert em["dimensions"] == []
    assert em["instantiation_mode"] == "prose_subheaders"
    assert em["min_axes_per_entity"] == 3
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
    """5-20 entities, 4-8 dimensions → no entity_matrix shortfalls.

    Wave 2 §1.2: `list-all` archetype now requires a FLAT outline
    (30-80 top sections, 0-2 subsections, 0 depth_seeds) per the
    Qianfan corpus calibration. The fixture below is built to that
    flat shape so the only audit dimension under test is the
    entity_matrix one."""
    plan = _plan_with_em(
        ["e1", "e2", "e3", "e4", "e5", "e6"],
        ["d1", "d2", "d3", "d4", "d5"],
    )
    # Wave 2 §1.2: flat list-all outline = top_min top sections, no
    # subsections, no depth_seeds. Matches Qianfan id=91 (78 H2 / 0 H3).
    list_all_top_min = architect._ARCHETYPE_OUTLINE_SHAPE["list-all"]["top_min"]
    plan["report_toc"] = [
        {
            "id": f"S{i + 1}",
            "title": "x",
            "subsections": [],
            "depth_target": "broad",
        }
        for i in range(list_all_top_min)
    ]
    # PR #25 merge follow-up (2026-05-25): satisfy PR #22's _QUERIES_MIN=48
    # query-count audit, which otherwise fires `queries=0<48` on `_plan_with_em`'s
    # empty queries list and breaks the `shortfalls == []` invariant.
    plan["queries"] = [
        {"id": f"Q{i + 1}", "text": f"q{i + 1}", "type": "factual"} for i in range(architect._QUERIES_MIN)
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


def test_missing_entity_matrix_emits_exactly_one_entity_matrix_shortfall():
    """Greptile PR #25 follow-up round 2: when entity_matrix is entirely
    absent on a list-all/compare task, _normalize must emit ONE shortfall
    (the `entity_matrix=missing` entry) — NOT three (missing + entities=0<5
    + dimensions=0<4) for what is structurally a single root cause.

    Pre-fix, the backfilled empty matrix would trip BOTH count-shortfall
    checks, padding the shortfall list to three entries for a single LLM
    failure. PR #23's retry-on-shortfall logic could then waste a retry
    attempting to fix three "independent" failures when adding a single
    entity_matrix block would fix all three at once.

    The fix is to gate the count checks behind a `matrix_was_missing` flag
    so count shortfalls only emit when the matrix was PRESENT but
    under/over-populated. This test pins that contract."""
    for archetype in ("list-all", "compare"):
        plan = {"report_toc": [], "queries": [], "acceptance_criteria": []}
        architect._normalize(plan, archetype=archetype)
        em_shortfalls = [s for s in plan["_outline_audit"]["shortfalls"] if s.startswith("entity_matrix")]
        # Exactly one entity_matrix-related shortfall, and it must be the
        # missing entry (not the count entries that would be redundant noise).
        assert len(em_shortfalls) == 1, (
            f"archetype={archetype}: expected exactly 1 entity_matrix shortfall "
            f"when matrix is missing, got {len(em_shortfalls)}: {em_shortfalls}"
        )
        assert em_shortfalls[0].startswith("entity_matrix=missing"), (
            f"archetype={archetype}: the single shortfall must be the "
            f"`entity_matrix=missing` entry, got {em_shortfalls[0]!r}"
        )
        # Belt-and-suspenders: explicitly assert the count shortfalls are
        # NOT present — those would be the regression.
        assert not any("entity_matrix.entities=0<" in s for s in em_shortfalls), em_shortfalls
        assert not any("entity_matrix.dimensions=0<" in s for s in em_shortfalls), em_shortfalls
        # But the count TELEMETRY counters MUST still be populated (a dev-run
        # reader needs to see entity_matrix_entities=0 / dimensions=0 to know
        # the backfill fired). Telemetry counts are separate from shortfalls.
        assert plan["_outline_audit"]["entity_matrix_entities"] == 0
        assert plan["_outline_audit"]["entity_matrix_dimensions"] == 0


def test_present_but_under_populated_matrix_still_emits_count_shortfalls():
    """Counter-test to the above: when the entity_matrix WAS present in
    the plan but under-populated (e.g. 1 entity, 1 dimension), the count
    shortfalls MUST still fire — those are real, non-redundant signals
    that the architect produced a too-shallow matrix. The fix only
    suppresses count shortfalls when the matrix was entirely MISSING."""
    plan = _plan_with_em(["only-one"], ["only-dim"])
    architect._normalize(plan, archetype="list-all")
    em_shortfalls = [s for s in plan["_outline_audit"]["shortfalls"] if s.startswith("entity_matrix")]
    # Two distinct shortfalls — both the entity undercount AND the
    # dimension undercount — because the matrix was PRESENT but each
    # axis is below its minimum.
    assert any("entity_matrix.entities=1<" in s for s in em_shortfalls), em_shortfalls
    assert any("entity_matrix.dimensions=1<" in s for s in em_shortfalls), em_shortfalls
    # And there must be NO `missing` entry — the matrix was present.
    assert not any("entity_matrix=missing" in s for s in em_shortfalls), em_shortfalls


def test_arch_emphasis_list_all_pins_s1_placement_wording():
    """Greptile PR #25 follow-up round 2: the architect's planning prompt
    for list-all archetype must match the canonical placement enforced by
    writer.write_section's S1-only render-as-table directive
    ("immediately under the §1 heading"). The prior wording said "near the
    article's start" which is ambiguous against the executive opening
    frame that write_opening produces separately — the architect could
    have embedded contradictory placement guidance into task_analysis,
    misleading downstream review or future maintainers."""
    emphasis = architect._ARCH_EMPHASIS["list-all"]
    # New wording present.
    assert "immediately under the §1 heading" in emphasis, emphasis
    assert "S1's body" in emphasis, emphasis
    assert "executive opening" in emphasis, emphasis
    # Old wording removed (would re-create the ambiguity Greptile flagged).
    assert "near the article's start" not in emphasis, emphasis


def test_arch_emphasis_compare_pins_s1_placement_wording():
    """Same as the list-all test above — the compare archetype's
    planning prompt must also pin the canonical S1 placement."""
    emphasis = architect._ARCH_EMPHASIS["compare"]
    assert "immediately under the §1 heading" in emphasis, emphasis
    assert "near the article's start" not in emphasis, emphasis
    # The compare-specific equal-depth instruction must SURVIVE the
    # rewrite — it's the load-bearing half of the compare prompt.
    assert "equal-depth treatment downstream" in emphasis, emphasis


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
    # Greptile PR #25 follow-up: pin the S1-specific canonical-placement
    # wording. The block must tell the writer to render the table at the
    # top of THIS section (S1's body), not in the executive opening frame
    # (which is written separately by write_opening and intentionally does
    # NOT receive the matrix).
    assert "render this as a markdown table" in captured_user["text"]
    assert "immediately under the §1 heading" in captured_user["text"]
    assert "executive opening" in captured_user["text"]


def test_writer_render_directive_only_fires_on_s1(monkeypatch):
    """Greptile PR #25 follow-up regression test for the duplicate-table
    risk. The previous block sent the "render this as a markdown table"
    directive to every section (S1-S12); each section LLM is independent
    and could emit the table at the top of its own body, producing up to
    12 duplicate tables in the assembled article.

    The fix gates the render directive on `sid == "S1"`. S2 (and every
    other non-S1 section) must instead receive a leaner equal-depth
    REMINDER plus an explicit `MUST NOT re-render the matrix table`
    prohibition. The matrix JSON itself is still surfaced so the writer
    knows the entity roster it must treat fairly.

    Without this test the regression would slip back through silently —
    the original PR #25 test suite only exercised S1."""
    captured_user: dict[str, str] = {}

    def fake_call(_role, user, *, system, max_tokens, note):  # noqa: ARG001
        captured_user["text"] = user
        return "## 2.1 stub\n\nstub body."

    monkeypatch.setattr(writer.llm, "call", fake_call)

    plan = _plan_with_em(
        ["Bronze Saints", "Silver Saints", "Gold Saints", "Marina Generals", "Specters"],
        ["armor tier", "Cosmo class", "speed class", "wearer roster"],
    )
    # The S2 unit shape mirrors S1 — only the id is different so the
    # routing branch is the only thing under test.
    unit = {
        "id": "S2",
        "title": "Power Hierarchy",
        "depth": "deep",
        "subs": [{"id": "S2.1", "title": "Sub", "depth_seeds": []}],
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
    text = captured_user["text"]

    # The equal-depth reminder MUST still appear on non-S1 sections —
    # that's the contract every section must satisfy on its slice of the
    # matrix.
    assert "ENTITY MATRIX REMINDER" in text
    assert "equal-depth treatment" in text
    # And the entity roster MUST still be visible so the writer knows
    # what entities to treat fairly.
    assert "Bronze Saints" in text
    assert "Cosmo class" in text

    # CRITICAL: the render-as-table directive MUST NOT appear on non-S1
    # sections. This is the regression guard for the duplicate-table risk.
    assert "render this as a markdown table" not in text, (
        "non-S1 sections must not receive the render-as-table directive — "
        "S1 owns the canonical placement to avoid up to 12 duplicate tables"
    )
    # And the explicit prohibition MUST be present so a capable LLM that
    # might otherwise hallucinate a table is stopped at the prompt layer.
    assert "MUST NOT re-render the matrix table" in text


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


def test_writer_suppresses_block_when_dimensions_missing_or_empty(monkeypatch):
    """Greptile PR #25 follow-up round 3: the suppression guard must be
    symmetric across the (entities, dimensions) axes. A matrix with
    populated entities but an empty (or missing) dimensions list is a
    state _normalize flags as `entity_matrix.dimensions=0<4` but does NOT
    reject — so without a `dimensions` guard, the S1 render directive
    would fire telling the LLM to "render this as a markdown table" with
    no column headers, forcing it to hallucinate dimensions or produce a
    degenerate single-column table. This test pins both halves:
    entities-without-dimensions AND dimensions-without-entities must
    suppress the block (the latter was already covered by the truthy
    `entities` guard but is asserted here for symmetry)."""

    class _DummyBank:
        def for_section(self, _sid):
            return []

    unit = {
        "id": "S1",
        "title": "Foundations",
        "depth": "broad",
        "subs": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}],
    }

    # Case 1: entities populated, dimensions empty list.
    captured: dict[str, str] = {}

    def fake_call_a(_role, user, *, system, max_tokens, note):  # noqa: ARG001
        captured["a"] = user
        return "## 1 stub\n\nstub body."

    monkeypatch.setattr(writer.llm, "call", fake_call_a)
    plan_a = _plan_with_em(["a", "b", "c", "d", "e"], [])
    writer.write_section(
        unit,
        plan_a,
        _DummyBank(),
        prompt="p",
        language="en",
        archetype="list-all",
        domain="default",
        prior_titles=[],
        task_id=None,
        target_tokens=None,
    )
    assert "ENTITY MATRIX" not in captured["a"], (
        "entities-without-dimensions must suppress the block — the render "
        "directive would otherwise tell the LLM to build a table with no columns"
    )

    # Case 2: entities populated, dimensions key missing entirely.
    def fake_call_b(_role, user, *, system, max_tokens, note):  # noqa: ARG001
        captured["b"] = user
        return "## 1 stub\n\nstub body."

    monkeypatch.setattr(writer.llm, "call", fake_call_b)
    plan_b = {
        "report_title": "T",
        "entity_matrix": {"entities": ["a", "b", "c", "d", "e"]},  # no `dimensions` key
        "report_toc": [],
        "queries": [],
        "acceptance_criteria": [],
    }
    writer.write_section(
        unit,
        plan_b,
        _DummyBank(),
        prompt="p",
        language="en",
        archetype="list-all",
        domain="default",
        prior_titles=[],
        task_id=None,
        target_tokens=None,
    )
    assert "ENTITY MATRIX" not in captured["b"], (
        "missing `dimensions` key must suppress the block — symmetric with the empty-list case"
    )

    # Case 3 (symmetry counter-check): dimensions populated, entities empty
    # — already covered by the pre-existing `em.get('entities')` guard,
    # but assert it here too so future refactors can't lose the symmetry.
    def fake_call_c(_role, user, *, system, max_tokens, note):  # noqa: ARG001
        captured["c"] = user
        return "## 1 stub\n\nstub body."

    monkeypatch.setattr(writer.llm, "call", fake_call_c)
    plan_c = _plan_with_em([], ["d1", "d2", "d3", "d4"])
    writer.write_section(
        unit,
        plan_c,
        _DummyBank(),
        prompt="p",
        language="en",
        archetype="list-all",
        domain="default",
        prior_titles=[],
        task_id=None,
        target_tokens=None,
    )
    assert "ENTITY MATRIX" not in captured["c"], (
        "dimensions-without-entities must also suppress (a table with rows "
        "but no row identifiers is equally degenerate)"
    )


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
