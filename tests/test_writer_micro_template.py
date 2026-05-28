"""Unit tests for the per-entity directive (P3b-opt2: retired the rigid W1
micro-template in favor of the VERIFIED the reference prose form).

When `entity_matrix.instantiation_mode == "prose_subheaders"`, the writer's
user prompt must instruct the verified the reference q91 form: render EACH entity as
a SINGLE FLAT `##` section (no `###`/`####` inside an entity) whose body is
N dense single-theme paragraphs, each opened by a short descriptive bold
lead-in, covering the matrix dimensions as paragraph THEMES in render_order
(NOT as fixed bolded `**axis:**` labels — that rigid template was retired
after the fresh q91 corpus showed the reference uses no such template).
"""

from deep_research.pipeline import memory_bank, writer


def _bare_plan_with_em(em, archetype_titles=None):
    return {
        "report_title": "T",
        "report_toc": [
            {
                "id": "S1",
                "title": "Sec 1",
                "subsections": [{"id": "S1.1", "title": "Sub 1.1", "depth_seeds": []}],
            },
            {
                "id": "S2",
                "title": "Sec 2",
                "subsections": [{"id": "S2.1", "title": "Sub 2.1", "depth_seeds": []}],
            },
        ],
        "acceptance_criteria": [],
        "queries": [],
        "entity_matrix": em,
    }


def _capture_writer_call(monkeypatch):
    captured = []

    def fake_llm_call(role, user, *, system, max_tokens, note, **kw):
        captured.append({"role": role, "user": user, "system": system})
        return "## 1 Body\n\nbody\n"

    monkeypatch.setattr(writer.llm, "call", fake_llm_call)
    return captured


def _call_writer(monkeypatch, plan, archetype, sid="S1", language="en"):
    captured = _capture_writer_call(monkeypatch)
    bank = memory_bank.MemoryBank()
    section = next((s for s in plan["report_toc"] if s["id"] == sid), plan["report_toc"][0])
    writer.write_section(
        plan=plan,
        unit={"id": sid, "title": section["title"], "depth": "broad", "subs": section["subsections"]},
        bank=bank,
        prior_titles=[s["title"] for s in plan["report_toc"]],
        archetype=archetype,
        prompt="test",
        language=language,
        domain="default",
    )
    return captured


# --------------------------------------------------------------------------
# 1. prose_subheaders mode emits the micro-template directive.
# --------------------------------------------------------------------------


def test_prose_subheaders_mode_emits_reference_prose_directive(monkeypatch):
    """prose_subheaders mode emits the verified the reference prose directive:
    single flat section, dense single-theme paragraphs, dimensions surfaced
    as paragraph THEMES (not rigid bolded `**axis:**` labels)."""
    em = {
        "entities": ["IBM", "Google", "Origin", "Microsoft", "Baidu"],
        "dimensions": [
            {"axis_name": "Winning Logic", "render_order": 1, "content_template": "factors + chain"},
            {"axis_name": "Stall Risk", "render_order": 2, "content_template": "scenario + falsifier"},
            {"axis_name": "Time Window", "render_order": 3, "content_template": "2-year range"},
            {"axis_name": "Team Combination", "render_order": 4, "content_template": "1-3 names"},
        ],
        "instantiation_mode": "prose_subheaders",
        "min_axes_per_entity": 3,
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all", sid="S1")
    user = captured[0]["user"]
    assert "PER-ENTITY TREATMENT" in user, f"directive missing; got: {user[:2000]}"
    assert "SINGLE FLAT section" in user
    assert "ONE analytical theme per paragraph" in user
    # dimensions surfaced as themes, NOT as rigid bolded labels
    assert "Winning Logic" in user and "Team Combination" in user
    assert "**Winning Logic:**" not in user, "retired rigid bolded-label template still present"
    # Guard the rename: the directive and its wrapper must agree on one label.
    assert "MICRO-TEMPLATE" not in user, "stale MICRO-TEMPLATE label leaked into the prompt"


def test_prose_subheaders_orders_themes_by_render_order(monkeypatch):
    """Dimension themes appear in render_order in the 'cover these themes'
    line, NOT in dict-insertion order."""
    em = {
        "entities": ["E1", "E2", "E3", "E4", "E5"],
        "dimensions": [
            {"axis_name": "Third", "render_order": 3, "content_template": "t3"},
            {"axis_name": "First", "render_order": 1, "content_template": "t1"},
            {"axis_name": "Fourth", "render_order": 4, "content_template": "t4"},
            {"axis_name": "Second", "render_order": 2, "content_template": "t2"},
        ],
        "instantiation_mode": "prose_subheaders",
        "min_axes_per_entity": 3,
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all")
    user = captured[0]["user"]
    # The names also appear in the entity_matrix JSON dump (insertion order),
    # so check order WITHIN the directive's "in this order:" themes line.
    anchor = user.find("in this order:")
    assert anchor != -1, f"themes line missing; got: {user[:2500]}"
    themes_line = user[anchor : user.find("\n", anchor)]
    p_first, p_second, p_third, p_fourth = (themes_line.find(n) for n in ("First", "Second", "Third", "Fourth"))
    assert -1 < p_first < p_second < p_third < p_fourth, f"themes not in render_order: {themes_line!r}"


def test_prose_subheaders_forbids_nested_headings(monkeypatch):
    """The reference-flat directive must forbid ###/#### sub-headings within an
    entity (the bold lead-ins ARE the sub-structure)."""
    em = {
        "entities": ["E1", "E2", "E3", "E4", "E5"],
        "dimensions": [
            {"axis_name": "Dim One", "render_order": 1, "content_template": "tpl"},
            {"axis_name": "Dim Two", "render_order": 2, "content_template": "tpl"},
        ],
        "instantiation_mode": "prose_subheaders",
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all", language="en")
    user = captured[0]["user"]
    assert "SINGLE FLAT section" in user
    assert "do NOT" in user and "###" in user, f"flat-only rule missing; got: {user[:2500]}"
    assert "descriptive bold" in user.lower() or "DESCRIPTIVE BOLD" in user


def test_prose_subheaders_dense_paragraph_rule(monkeypatch):
    """The directive must push DENSE single-theme paragraphs (the readability
    one-idea-per-paragraph fix) — not stacked modes, not choppy."""
    em = {
        "entities": ["E1", "E2", "E3", "E4", "E5"],
        "dimensions": [{"axis_name": f"D{i}", "render_order": i, "content_template": "t"} for i in range(1, 6)],
        "instantiation_mode": "prose_subheaders",
        "min_axes_per_entity": 4,
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all")
    user = captured[0]["user"]
    # paragraph-count guidance derived from min_axes..len(dims): "4-5 DENSE paragraphs"
    assert "4-5 DENSE paragraphs" in user, f"paragraph-count guidance missing; got: {user[:2500]}"
    assert "internally unstable" in user  # the anti-stacking rationale
    assert "EQUAL-DEPTH" in user


def test_writer_handles_null_min_axes_per_entity_without_crash(monkeypatch):
    """Greptile PR #37 round-3 (issue 1): if a plan reaches the writer
    without passing through `architect._normalize` (e.g. unit test path,
    future caller) and the LLM emitted `"min_axes_per_entity": null`,
    `dict.get(key, default)` returns the stored None — not the default —
    and `int(None)` raises TypeError, crashing write_section. The
    writer now uses `int(em.get(...) or 3)` to coerce null → default,
    matching architect's `or`-assignment in `_normalize`."""
    em = {
        "entities": ["E1", "E2"],
        "dimensions": [{"axis_name": "D1", "render_order": 1, "content_template": "t"}],
        "instantiation_mode": "prose_subheaders",
        "min_axes_per_entity": None,  # the case Greptile flagged
    }
    plan = _bare_plan_with_em(em)
    # Must not raise.
    captured = _call_writer(monkeypatch, plan, archetype="list-all")
    user = captured[0]["user"]
    # Default of 3 applied — surfaced in the RULES block. (1 dim total,
    # so the rendered floor is min(3, len(dims_sorted)) effectively 3,
    # which renders verbatim as "3 of the 1 axes" — the test only pins
    # that the writer did not crash and the directive emitted.)
    assert "PER-ENTITY TREATMENT" in user, (
        f"directive missing — writer may have crashed silently; got: {user[:2500]}"
    )


# --------------------------------------------------------------------------
# 2. table_columns_only mode falls back to legacy directive.
# --------------------------------------------------------------------------


def test_table_columns_only_mode_omits_micro_template(monkeypatch):
    """Legacy mode: ENTITY MATRIX section present but no
    PER-ENTITY TREATMENT block."""
    em = {
        "entities": ["E1", "E2", "E3", "E4", "E5"],
        "dimensions": [
            {"axis_name": "D1", "render_order": 1, "content_template": "tpl"},
        ],
        "instantiation_mode": "table_columns_only",
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all")
    user = captured[0]["user"]
    assert "ENTITY MATRIX" in user, "matrix block should still fire in legacy mode"
    assert "PER-ENTITY TREATMENT" not in user, f"per-entity treatment block fired in legacy mode: {user[:2000]}"


# --------------------------------------------------------------------------
# 3. S1 vs non-S1 placement of canonical table render.
# --------------------------------------------------------------------------


def test_s1_section_gets_table_render_directive(monkeypatch):
    """§1 renders the canonical matrix table."""
    em = {
        "entities": ["E1", "E2", "E3", "E4", "E5"],
        "dimensions": [{"axis_name": "D1", "render_order": 1, "content_template": "t"}],
        "instantiation_mode": "prose_subheaders",
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all", sid="S1")
    user = captured[0]["user"]
    assert "ENTITY MATRIX (article spine" in user, f"§1 table render directive missing; got: {user[:2000]}"


def test_non_s1_section_gets_reminder_not_render(monkeypatch):
    """Non-§1 sections get the equal-depth reminder + per-entity treatment, but
    NOT the "render as table" directive (else we'd get duplicate tables)."""
    em = {
        "entities": ["E1", "E2", "E3", "E4", "E5"],
        "dimensions": [{"axis_name": "D1", "render_order": 1, "content_template": "t"}],
        "instantiation_mode": "prose_subheaders",
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all", sid="S2")
    user = captured[0]["user"]
    assert "ENTITY MATRIX REMINDER" in user
    assert "ENTITY MATRIX (article spine" not in user, "non-§1 should not render table"
    assert "PER-ENTITY TREATMENT" in user


# --------------------------------------------------------------------------
# 4. Suppression — empty matrix / missing dimensions / non-applicable archetype.
# --------------------------------------------------------------------------


def test_empty_matrix_suppresses_directive(monkeypatch):
    """A matrix with empty entities or empty dimensions: no directive."""
    em = {
        "entities": [],
        "dimensions": [{"axis_name": "D1", "render_order": 1, "content_template": "t"}],
        "instantiation_mode": "prose_subheaders",
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all")
    user = captured[0]["user"]
    assert "ENTITY MATRIX" not in user, f"empty matrix should suppress; got: {user[:2000]}"


def test_missing_dimensions_suppresses_directive(monkeypatch):
    """Matrix with entities but no dimensions: no directive (legacy guard
    from Greptile PR #25 follow-up round 3)."""
    em = {
        "entities": ["E1", "E2"],
        "dimensions": [],
        "instantiation_mode": "prose_subheaders",
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all")
    user = captured[0]["user"]
    assert "ENTITY MATRIX" not in user


def test_non_em_archetype_with_prose_subheaders_mode_still_fires(monkeypatch):
    """When auto-promotion lands a matrix on a predict-archetype plan
    with prose_subheaders mode, the writer activates the directive (not
    just list-all / compare)."""
    em = {
        "entities": ["IBM", "Google", "Origin", "Microsoft", "Baidu"],
        "dimensions": [
            {"axis_name": "Winning Logic", "render_order": 1, "content_template": "t"},
            {"axis_name": "Stall Risk", "render_order": 2, "content_template": "t"},
            {"axis_name": "Team Combination", "render_order": 3, "content_template": "t"},
            {"axis_name": "Time Window", "render_order": 4, "content_template": "t"},
        ],
        "instantiation_mode": "prose_subheaders",
        "min_axes_per_entity": 3,
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="predict")
    user = captured[0]["user"]
    assert "ENTITY MATRIX" in user, f"predict-archetype prose_subheaders matrix should fire; got: {user[:2000]}"
    assert "PER-ENTITY TREATMENT" in user


def test_non_em_archetype_with_legacy_mode_suppresses(monkeypatch):
    """When the writer sees a predict-archetype matrix with legacy mode,
    it should NOT fire (legacy mode is reserved for list-all/compare)."""
    em = {
        "entities": ["E1", "E2", "E3", "E4", "E5"],
        "dimensions": [{"axis_name": "D1", "render_order": 1, "content_template": "t"}],
        "instantiation_mode": "table_columns_only",
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="predict")
    user = captured[0]["user"]
    assert "ENTITY MATRIX" not in user, f"predict-archetype with legacy mode should suppress; got: {user[:2000]}"


# --------------------------------------------------------------------------
# 5. Object-form serialization survives JSON round-trip into prompt.
# --------------------------------------------------------------------------


def test_dimensions_object_form_serializes_into_prompt(monkeypatch):
    """The entity_matrix is JSON-serialized into the prompt. Object-form
    dimensions must round-trip cleanly with ensure_ascii=False (so ZH
    content_templates aren't escaped)."""
    em = {
        "entities": ["E1", "E2", "E3", "E4", "E5"],
        "dimensions": [
            {"axis_name": "维度一", "render_order": 1, "content_template": "事实 + 因果链"},
        ],
        "instantiation_mode": "prose_subheaders",
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all", language="zh")
    user = captured[0]["user"]
    # The serialized matrix JSON in the prompt contains the literal ZH text.
    assert "维度一" in user
    assert "事实 + 因果链" in user
    # Defensive: no \u escapes.
    assert "\\u7ef4" not in user, "ZH chars got ASCII-escaped — ensure_ascii=False regression"
