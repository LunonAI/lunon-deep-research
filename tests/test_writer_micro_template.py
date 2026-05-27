"""Unit tests for P3-W1 — writer directive renders per-entity micro-template.

When `entity_matrix.instantiation_mode == "prose_subheaders"` (the P3-W1
default), the writer's user prompt must include the PER-ENTITY MICRO-
TEMPLATE block listing each dimension's axis_name as a bolded sub-header
in `render_order`, plus an enforcement RULES block. When mode is
`table_columns_only` (legacy), the writer falls back to the pre-W1
table-only directive.

Tests pin both modes, language-aware colon selection (EN half-width vs
ZH full-width), §1-vs-non-§1 placement of the canonical table render,
and the suppression guard for empty matrices.
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

    def fake_llm_call(role, user, *, system, max_tokens, note):
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


def test_prose_subheaders_mode_emits_axis_subheaders(monkeypatch):
    """When entity_matrix.instantiation_mode is prose_subheaders, the
    writer user prompt must include each axis_name as a bolded sub-header
    pattern in the PER-ENTITY MICRO-TEMPLATE block."""
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
    assert "PER-ENTITY MICRO-TEMPLATE" in user, f"directive missing; got: {user[:2000]}"
    assert "**Winning Logic:**" in user, f"axis 1 missing; got: {user[:2000]}"
    assert "**Stall Risk:**" in user
    assert "**Time Window:**" in user
    assert "**Team Combination:**" in user


def test_prose_subheaders_orders_axes_by_render_order(monkeypatch):
    """Axes must appear in render_order, NOT in dict-insertion order. A
    dimensions list emitted with render_order out-of-sequence must
    still produce axes in order 1, 2, 3, 4 in the prompt."""
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
    # Find positions of each axis name in the prompt
    p_first = user.find("**First:**")
    p_second = user.find("**Second:**")
    p_third = user.find("**Third:**")
    p_fourth = user.find("**Fourth:**")
    assert -1 < p_first < p_second < p_third < p_fourth, (
        f"axes not in render_order: First@{p_first}, Second@{p_second}, Third@{p_third}, Fourth@{p_fourth}"
    )


def test_prose_subheaders_uses_fullwidth_colon_for_zh(monkeypatch):
    """ZH-language tasks use the full-width colon (：) per Qianfan convention."""
    em = {
        "entities": ["E1", "E2", "E3", "E4", "E5"],
        "dimensions": [
            {"axis_name": "维度一", "render_order": 1, "content_template": "事实 + 分析"},
            {"axis_name": "维度二", "render_order": 2, "content_template": "因果链"},
        ],
        "instantiation_mode": "prose_subheaders",
        "min_axes_per_entity": 2,
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all", language="zh")
    user = captured[0]["user"]
    assert "**维度一：**" in user, f"ZH full-width colon missing; got: {user[:2000]}"
    assert "**维度二：**" in user


def test_prose_subheaders_uses_halfwidth_colon_for_en(monkeypatch):
    """EN-language tasks use the half-width colon (:)."""
    em = {
        "entities": ["E1", "E2", "E3", "E4", "E5"],
        "dimensions": [
            {"axis_name": "Dim One", "render_order": 1, "content_template": "tpl"},
        ],
        "instantiation_mode": "prose_subheaders",
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all", language="en")
    user = captured[0]["user"]
    assert "**Dim One:**" in user
    assert "**Dim One：**" not in user, "ZH full-width colon leaked into EN prompt"


def test_prose_subheaders_includes_min_axes_compliance_floor(monkeypatch):
    """The micro-template RULES block must surface the min_axes_per_entity
    floor so the writer knows the compliance bar."""
    em = {
        "entities": ["E1", "E2", "E3", "E4", "E5"],
        "dimensions": [{"axis_name": f"D{i}", "render_order": i, "content_template": "t"} for i in range(1, 6)],
        "instantiation_mode": "prose_subheaders",
        "min_axes_per_entity": 4,
    }
    plan = _bare_plan_with_em(em)
    captured = _call_writer(monkeypatch, plan, archetype="list-all")
    user = captured[0]["user"]
    assert "4 of the 5 axes must be populated" in user, f"compliance floor missing; got: {user[:2500]}"


# --------------------------------------------------------------------------
# 2. table_columns_only mode falls back to legacy directive.
# --------------------------------------------------------------------------


def test_table_columns_only_mode_omits_micro_template(monkeypatch):
    """Legacy mode: ENTITY MATRIX section present but no
    PER-ENTITY MICRO-TEMPLATE block."""
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
    assert "PER-ENTITY MICRO-TEMPLATE" not in user, f"micro-template block fired in legacy mode: {user[:2000]}"


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
    """Non-§1 sections get the equal-depth reminder + micro-template, but
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
    assert "PER-ENTITY MICRO-TEMPLATE" in user


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
    assert "PER-ENTITY MICRO-TEMPLATE" in user


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
