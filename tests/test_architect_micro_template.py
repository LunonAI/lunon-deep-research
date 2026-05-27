"""Unit tests for P3-W1 — per-entity micro-template architect contract.

reference-verified corpus-wide pattern (11/11 articles): every article body
applies an identical multi-axis schema to N entities with lexically
identical bolded sub-headers. Lunon's pre-W1 entity_matrix had the right
shape (entities + dimensions) but: (1) dimensions were rendered ONLY as
table columns at §1, never as per-entity prose sub-headers; (2) gated to
list-all/compare only; (3) cap of 20 entities undershot the reference id=91's
25-28 knights.

P3-W1 extends the schema:
- `dimensions` may be string OR object form (string auto-wrapped to
  {axis_name, render_order, content_template})
- `instantiation_mode` ("prose_subheaders" default) controls writer render
- `min_axes_per_entity` (default 3) is the writer compliance floor
- Per-archetype entity cap dict (list-all=30, compare=20, others=15)
- Auto-promote to predict/explain-mech/trend/recommend when outline has
  ≥3 sibling sub-chapters with proper-noun-titles

These tests pin the contract end-to-end at the architect layer.
"""

from deep_research.pipeline import architect


def _bare_plan_with_matrix(archetype_hint=None, **em_overrides):
    em = {
        "entities": ["IBM", "Google", "Origin", "Microsoft", "Baidu"],
        "dimensions": [
            {"axis_name": "Winning Logic", "render_order": 1, "content_template": "factors + chain"},
            {"axis_name": "Stall Risk", "render_order": 2, "content_template": "scenario + falsifier"},
            {"axis_name": "Team Combination", "render_order": 3, "content_template": "1-3 names"},
            {"axis_name": "Time Window", "render_order": 4, "content_template": "2-year range"},
        ],
    }
    em.update(em_overrides)
    return {
        "report_title": "T",
        "report_toc": [
            {
                "id": "S1",
                "title": "Sec",
                "subsections": [
                    {"id": "S1.1", "title": "Sub", "depth_seeds": []},
                ],
                "depth_target": "broad",
            }
        ],
        "queries": [{"id": f"Q{i}", "text": f"q{i}", "type": "factual"} for i in range(50)],
        "acceptance_criteria": [],
        "entity_matrix": em,
    }


# --------------------------------------------------------------------------
# 1. Per-archetype entity cap.
# --------------------------------------------------------------------------


def test_max_entities_for_archetype_list_all_30():
    """list-all archetype cap raised to 30 (the reference id=91 has 25-28 knights)."""
    assert architect._max_entities_for_archetype("list-all") == 30


def test_max_entities_for_archetype_compare_unchanged_at_20():
    """compare cap unchanged at 20 — the reference compare-archetype docs (q23,
    q37) have 6-17 cases, well under 20."""
    assert architect._max_entities_for_archetype("compare") == 20


def test_max_entities_for_archetype_optional_archetypes_15():
    """predict / explain-mechanism / trend / recommend get a smaller cap
    (15) — they're entity-iterating less aggressively than list-all."""
    for arch in ("predict", "explain-mechanism", "trend", "recommend"):
        assert architect._max_entities_for_archetype(arch) == 15, (
            f"got {architect._max_entities_for_archetype(arch)} for {arch}"
        )


def test_max_entities_for_archetype_unknown_falls_back_to_legacy_20():
    """Unknown archetype falls back to the legacy flat constant (20)."""
    assert architect._max_entities_for_archetype(None) == 20
    assert architect._max_entities_for_archetype("not-real") == 20
    assert architect._max_entities_for_archetype("") == 20
    # Legacy constant is preserved for back-compat with callers that
    # imported it directly.
    assert architect._ENTITY_MATRIX_ENTITIES_MAX == 20


# --------------------------------------------------------------------------
# 2. Dimensions normalization (string ↔ object form, malformed handling).
# --------------------------------------------------------------------------


def test_normalize_dimensions_accepts_object_form():
    """The canonical post-W1 form: list of {axis_name, render_order, content_template}."""
    raw = [
        {"axis_name": "Dim1", "render_order": 1, "content_template": "tpl1"},
        {"axis_name": "Dim2", "render_order": 2, "content_template": "tpl2"},
    ]
    out = architect._normalize_dimensions(raw)
    assert len(out) == 2
    assert out[0]["axis_name"] == "Dim1"
    assert out[0]["render_order"] == 1
    assert out[1]["content_template"] == "tpl2"


def test_normalize_dimensions_auto_wraps_legacy_string_form():
    """Pre-W1 plans use `dimensions: [str, ...]`. Each string auto-wraps
    to object form with sequential render_order and a generic template."""
    raw = ["Dim A", "Dim B", "Dim C"]
    out = architect._normalize_dimensions(raw)
    assert len(out) == 3
    assert [d["axis_name"] for d in out] == ["Dim A", "Dim B", "Dim C"]
    assert [d["render_order"] for d in out] == [1, 2, 3]
    # All wrapped strings get a non-empty content_template
    assert all(d["content_template"] for d in out), f"empty templates: {out}"


def test_normalize_dimensions_handles_mixed_form():
    """A plan that emits a mix of string + object dimensions (e.g., the
    LLM transitioned mid-emission) auto-coerces each entry independently."""
    raw = [
        "Legacy String",
        {"axis_name": "New Object", "render_order": 5, "content_template": "explicit template"},
    ]
    out = architect._normalize_dimensions(raw)
    assert len(out) == 2
    assert out[0]["axis_name"] == "Legacy String"
    assert out[0]["render_order"] == 1  # positional index
    assert out[1]["axis_name"] == "New Object"
    assert out[1]["render_order"] == 5  # explicit value preserved


def test_normalize_dimensions_drops_empty_axis_names():
    """An object missing axis_name (or empty/whitespace) is dropped — a
    bolded sub-header for an empty axis would render as `**:**` which is
    visual garbage."""
    raw = [
        {"axis_name": "A", "render_order": 1},
        {"axis_name": "", "render_order": 2},
        {"axis_name": "   ", "render_order": 3},
        {"axis_name": "B", "render_order": 4},
    ]
    out = architect._normalize_dimensions(raw)
    axes = [d["axis_name"] for d in out]
    assert axes == ["A", "B"], f"got {axes}"


def test_normalize_dimensions_drops_malformed_types():
    """Non-string, non-dict entries (int, None, list) are silently dropped
    to avoid crashing the writer's JSON serialization."""
    raw = [
        {"axis_name": "Valid"},
        42,
        None,
        ["nested", "list"],
        "Also Valid",
    ]
    out = architect._normalize_dimensions(raw)
    axes = [d["axis_name"] for d in out]
    assert axes == ["Valid", "Also Valid"], f"got {axes}"


def test_normalize_dimensions_handles_non_list_input():
    """None / dict / string input → empty list."""
    assert architect._normalize_dimensions(None) == []
    assert architect._normalize_dimensions({}) == []
    assert architect._normalize_dimensions("string") == []
    assert architect._normalize_dimensions([]) == []


def test_normalize_dimensions_fills_missing_object_fields():
    """An object form with `axis_name` but missing render_order /
    content_template gets defaults filled."""
    raw = [{"axis_name": "Only name"}]
    out = architect._normalize_dimensions(raw)
    assert len(out) == 1
    assert out[0]["axis_name"] == "Only name"
    assert out[0]["render_order"] == 1
    assert out[0]["content_template"]  # non-empty default


def test_normalize_dimensions_coerces_null_content_template_to_default():
    """Greptile PR #37 round-6: `dict.get(key, default)` returns the
    stored `None` when the key is present-with-null — the default only
    fires on a MISSING key. So a LLM response with
    `"content_template": null` previously reached `str(None)` and stored
    the literal string "None", which the writer then emitted as
    `**Axis:** (None)` in the directive. The `or`-based guard mirrors
    PR #37 round-2 through round-5's null-handling pattern."""
    raw = [
        {"axis_name": "Axis1", "render_order": 1, "content_template": None},  # the case Greptile flagged
        {"axis_name": "Axis2", "render_order": 2, "content_template": ""},  # empty-string also coerced
        {"axis_name": "Axis3", "render_order": 3, "content_template": "explicit valid template"},
    ]
    out = architect._normalize_dimensions(raw)
    assert len(out) == 3
    # Null and empty-string both coerce to the default — no "None"
    # literal, no empty hint, no crash.
    assert out[0]["content_template"] and out[0]["content_template"] != "None", (
        f"null content_template leaked through; got {out[0]}"
    )
    assert out[1]["content_template"], f"empty content_template not defaulted; got {out[1]}"
    # First two should share the same default value.
    assert out[0]["content_template"] == out[1]["content_template"], (
        f"defaults diverge between null and empty-string paths; got {out[:2]}"
    )
    # Explicit valid value preserved.
    assert out[2]["content_template"] == "explicit valid template"


def test_normalize_dimensions_tolerates_malformed_render_order():
    """Greptile PR #37 round-2: the LLM occasionally emits malformed
    `render_order` values (`null`, non-numeric strings, even nested lists).
    `dict.get()` returns an explicit `None` when the key is present-but-null
    (the default `i + 1` never fires), and the prior `int(...)` would crash
    with TypeError / ValueError, propagating up through `_normalize` and
    leaving the plan unnormalized. Each malformed entry must fall back to
    the positional index instead of raising — this path is the malformed-
    input resilience guarantee for the whole normalize step.
    """
    raw = [
        {"axis_name": "Null Order", "render_order": None},  # explicit null
        {"axis_name": "Word Order", "render_order": "first"},  # non-numeric str
        {"axis_name": "Nested Order", "render_order": ["1"]},  # nested list
        {"axis_name": "Str Numeric", "render_order": "4"},  # numeric str → preserved
        {"axis_name": "Float Order", "render_order": 5.7},  # float → int-truncated
        {"axis_name": "Empty Str", "render_order": ""},  # empty str
    ]
    out = architect._normalize_dimensions(raw)
    assert [d["axis_name"] for d in out] == [
        "Null Order",
        "Word Order",
        "Nested Order",
        "Str Numeric",
        "Float Order",
        "Empty Str",
    ]
    # Malformed entries fall back to positional index (1-based).
    assert out[0]["render_order"] == 1  # None → i+1
    assert out[1]["render_order"] == 2  # "first" → i+1
    assert out[2]["render_order"] == 3  # ["1"] → i+1
    # Numeric forms are preserved (string coerces, float truncates).
    assert out[3]["render_order"] == 4
    assert out[4]["render_order"] == 5
    # Empty string also falls back (float("") raises ValueError).
    assert out[5]["render_order"] == 6


# --------------------------------------------------------------------------
# 3. `_normalize` end-to-end — entity_matrix path produces the new fields.
# --------------------------------------------------------------------------


def test_normalize_populates_instantiation_mode_default():
    """When the architect omits `instantiation_mode`, _normalize defaults
    to "prose_subheaders" (the P3-W1 canonical mode)."""
    plan = _bare_plan_with_matrix()
    architect._normalize(plan, archetype="list-all")
    assert plan["entity_matrix"]["instantiation_mode"] == "prose_subheaders"


def test_normalize_preserves_explicit_instantiation_mode():
    """If the architect explicitly sets `table_columns_only` (legacy
    mode), _normalize leaves it alone."""
    plan = _bare_plan_with_matrix(instantiation_mode="table_columns_only")
    architect._normalize(plan, archetype="list-all")
    assert plan["entity_matrix"]["instantiation_mode"] == "table_columns_only"


def test_normalize_populates_min_axes_per_entity_default():
    """min_axes_per_entity defaults to 3 when absent."""
    plan = _bare_plan_with_matrix()
    architect._normalize(plan, archetype="list-all")
    assert plan["entity_matrix"]["min_axes_per_entity"] == 3


def test_normalize_coerces_explicit_null_to_default():
    """Greptile PR #37 round-3 (issue 2): when the LLM emits an explicit
    `"min_axes_per_entity": null` or `"instantiation_mode": null`,
    `dict.setdefault` does NOT overwrite the stored None — only missing
    keys. The result was a None flowing to `int(em.get(...))` in the
    writer / validator, raising TypeError. `_normalize` now uses
    `or`-based assignment so explicit null is coerced to the default
    (the same fix PR #37 round-2 applied to render_order)."""
    plan = _bare_plan_with_matrix(min_axes_per_entity=None, instantiation_mode=None)
    architect._normalize(plan, archetype="list-all")
    em = plan["entity_matrix"]
    assert em["min_axes_per_entity"] == 3, f"explicit null leaked through; got {em}"
    assert em["instantiation_mode"] == "prose_subheaders", f"explicit null leaked through; got {em}"
    # The defaults must also propagate to the audit fields (drift telemetry).
    audit = plan["_outline_audit"]
    assert audit["entity_matrix_min_axes_per_entity"] == 3
    assert audit["entity_matrix_instantiation_mode"] == "prose_subheaders"


def test_normalize_optional_archetype_with_llm_populated_entities_still_normalizes():
    """Greptile PR #37 round-4: optional-archetype path with LLM-populated
    entities must still hit the normalize block.

    `_should_promote_entity_matrix` early-exits with False when entities
    are already non-empty (its job is auto-promotion, not re-promotion).
    Pre-fix, the gate `if is_required or should_promote:` excluded the
    "LLM populated it correctly but forgot instantiation_mode" case for
    predict/explain-mechanism/trend/recommend — instantiation_mode stayed
    unset, the writer's `em_active` check failed, and the entity matrix
    block was silently dropped on every such plan.

    The new third condition `em_optional_populated` lets that path
    through so the normalize backstop applies. Audit's
    `entity_matrix_auto_promoted` MUST stay False (the LLM populated it,
    not auto-promotion — important for drift attribution).
    """
    for archetype in ("predict", "explain-mechanism", "trend", "recommend"):
        plan = _bare_plan_with_matrix()
        plan["entity_matrix"].pop("instantiation_mode", None)  # the LLM omission
        plan["entity_matrix"].pop("min_axes_per_entity", None)  # also commonly omitted
        architect._normalize(plan, archetype=archetype)
        em = plan["entity_matrix"]
        assert em["instantiation_mode"] == "prose_subheaders", (
            f"archetype={archetype}: instantiation_mode never defaulted; got {em}"
        )
        assert em["min_axes_per_entity"] == 3, f"archetype={archetype}: min_axes_per_entity never defaulted; got {em}"
        # Dimensions must also be normalized (legacy string-form coercion).
        for d in em["dimensions"]:
            assert isinstance(d, dict) and "axis_name" in d, (
                f"archetype={archetype}: dimensions never normalized to object form; got {em}"
            )
        # Audit must distinguish LLM-populated from auto-promoted.
        audit = plan["_outline_audit"]
        assert audit["entity_matrix_instantiation_mode"] == "prose_subheaders"
        assert audit["entity_matrix_min_axes_per_entity"] == 3
        assert audit["entity_matrix_auto_promoted"] is False, (
            f"archetype={archetype}: LLM-populated path should not be flagged auto_promoted; got {audit}"
        )


def test_normalize_optional_archetype_with_empty_entities_unaffected():
    """Greptile PR #37 round-4 sanity-check: the new gate must NOT alter
    the behavior of the pre-existing auto-promote path. An optional
    archetype with an empty `entities` list should still flow through
    `_should_promote_entity_matrix` (which may return True or False
    based on outline shape) and NOT short-circuit on the new gate.

    Specifically: when entities are empty AND the outline lacks the
    sibling-sub-chapters shape, the matrix should NOT be normalized
    (no instantiation_mode default written), matching pre-fix behavior.
    """
    plan = _bare_plan_with_matrix(entities=[])  # empty entities
    plan["entity_matrix"].pop("instantiation_mode", None)
    # Default _bare_plan_with_matrix has a single-section outline — not
    # the ≥3-sibling-subchapter shape `_should_promote_entity_matrix`
    # requires. So should_promote=False AND em_optional_populated=False
    # → gate stays closed, no normalize.
    architect._normalize(plan, archetype="predict")
    em = plan["entity_matrix"]
    assert "instantiation_mode" not in em, f"empty-entities + flat-outline path should not normalize; got {em}"


def test_normalize_audit_records_new_fields():
    """The _outline_audit must surface instantiation_mode + min_axes +
    auto_promoted flag so drift telemetry can correlate them with
    compliance ratios downstream."""
    plan = _bare_plan_with_matrix()
    architect._normalize(plan, archetype="list-all")
    audit = plan["_outline_audit"]
    assert audit["entity_matrix_instantiation_mode"] == "prose_subheaders"
    assert audit["entity_matrix_min_axes_per_entity"] == 3
    assert audit["entity_matrix_auto_promoted"] is False  # list-all is REQUIRED, not promoted


def test_normalize_uses_per_archetype_entity_cap_for_list_all():
    """list-all archetype: 25 entities is within the new cap of 30 — no shortfall."""
    plan = _bare_plan_with_matrix()
    plan["entity_matrix"]["entities"] = [f"Entity{i}" for i in range(25)]
    architect._normalize(plan, archetype="list-all")
    audit = plan["_outline_audit"]
    em_shortfalls = [s for s in audit["shortfalls"] if "entity_matrix.entities" in s]
    assert em_shortfalls == [], f"got unexpected entity shortfalls: {em_shortfalls}"


def test_normalize_uses_per_archetype_entity_cap_for_compare():
    """compare archetype: 25 entities EXCEEDS the cap of 20 — shortfall fires."""
    plan = _bare_plan_with_matrix()
    plan["entity_matrix"]["entities"] = [f"Entity{i}" for i in range(25)]
    architect._normalize(plan, archetype="compare")
    audit = plan["_outline_audit"]
    em_shortfalls = [s for s in audit["shortfalls"] if "entity_matrix.entities" in s]
    assert any("25>20" in s for s in em_shortfalls), f"got {em_shortfalls}"


def test_normalize_legacy_string_dimensions_normalized_in_place():
    """Pre-W1 plan emits `dimensions: [str, ...]`; after _normalize the
    plan's entity_matrix.dimensions is object form for the writer."""
    plan = _bare_plan_with_matrix()
    plan["entity_matrix"]["dimensions"] = ["Cost", "Speed", "Quality", "Risk"]
    architect._normalize(plan, archetype="list-all")
    dims = plan["entity_matrix"]["dimensions"]
    assert all(isinstance(d, dict) for d in dims), f"dims not normalized: {dims}"
    assert [d["axis_name"] for d in dims] == ["Cost", "Speed", "Quality", "Risk"]


# --------------------------------------------------------------------------
# 4. Auto-promotion to optional archetypes.
# --------------------------------------------------------------------------


def _plan_with_entity_like_outline(archetype_hint, n_subs=4):
    """Build a plan whose first chapter has multiple sibling sub-chapters
    titled with proper nouns (e.g. team names, brand names) — the shape
    that triggers entity_matrix auto-promotion."""
    return {
        "report_title": "T",
        "report_toc": [
            {
                "id": "S1",
                "title": "Top teams",
                "subsections": [
                    {"id": f"S1.{i + 1}", "title": f"Anand Natarajan Lab {i + 1}", "depth_seeds": []}
                    for i in range(n_subs)
                ],
                "depth_target": "deep",
            }
        ],
        "queries": [{"id": f"Q{i}", "text": "q", "type": "factual"} for i in range(50)],
        "acceptance_criteria": [],
    }


def test_should_promote_entity_matrix_for_predict_with_entity_outline():
    """A predict plan with 4 sibling sub-chapters titled with proper
    nouns → auto-promotion candidate."""
    plan = _plan_with_entity_like_outline("predict")
    assert architect._should_promote_entity_matrix(plan, "predict") is True


def test_should_not_promote_when_plan_already_has_matrix():
    """If the architect already populated entity_matrix, don't re-suggest."""
    plan = _plan_with_entity_like_outline("predict")
    plan["entity_matrix"] = {"entities": ["E1", "E2"], "dimensions": []}
    assert architect._should_promote_entity_matrix(plan, "predict") is False


def test_should_not_promote_for_required_archetype():
    """list-all and compare don't go through the promotion path — they're
    already required."""
    plan = _plan_with_entity_like_outline("list-all")
    assert architect._should_promote_entity_matrix(plan, "list-all") is False
    assert architect._should_promote_entity_matrix(plan, "compare") is False


def test_should_not_promote_when_fewer_than_3_siblings():
    """A predict plan with only 2 sibling sub-chapters doesn't qualify."""
    plan = _plan_with_entity_like_outline("predict", n_subs=2)
    assert architect._should_promote_entity_matrix(plan, "predict") is False


def test_should_not_promote_for_generic_section_titles():
    """A predict plan with generic structural titles (Background,
    Methodology, Conclusion) doesn't qualify — those aren't entities."""
    plan = {
        "report_title": "T",
        "report_toc": [
            {
                "id": "S1",
                "title": "Top",
                "subsections": [
                    {"id": "S1.1", "title": "background", "depth_seeds": []},
                    {"id": "S1.2", "title": "methodology", "depth_seeds": []},
                    {"id": "S1.3", "title": "conclusion", "depth_seeds": []},
                ],
                "depth_target": "broad",
            }
        ],
        "queries": [{"id": "Q1", "text": "q", "type": "factual"}],
        "acceptance_criteria": [],
    }
    assert architect._should_promote_entity_matrix(plan, "predict") is False


def test_should_promote_recognizes_cjk_titles():
    """ZH proper nouns (lacking Title-Case markers) are recognized via
    CJK character detection."""
    plan = {
        "report_title": "T",
        "report_toc": [
            {
                "id": "S1",
                "title": "团队",
                "subsections": [
                    {"id": "S1.1", "title": "中国科学技术大学量子团队", "depth_seeds": []},
                    {"id": "S1.2", "title": "清华大学量子团队", "depth_seeds": []},
                    {"id": "S1.3", "title": "北京大学量子团队", "depth_seeds": []},
                ],
                "depth_target": "deep",
            }
        ],
        "queries": [{"id": "Q1", "text": "q", "type": "factual"}],
        "acceptance_criteria": [],
    }
    assert architect._should_promote_entity_matrix(plan, "predict") is True


def test_normalize_auto_promotes_for_qualifying_predict_plan():
    """When _normalize sees a predict plan with the entity-list shape,
    it backfills entity_matrix and flags `auto_promoted=True` in audit."""
    plan = _plan_with_entity_like_outline("predict")
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert audit.get("entity_matrix_auto_promoted") is True, f"got {audit}"
    # Matrix was backfilled to empty (no entities emitted by the architect
    # for an optional archetype; the empty backfill is the writer-safe form).
    em = plan.get("entity_matrix") or {}
    assert isinstance(em, dict)


def test_normalize_no_promotion_no_shortfall_for_non_promoted_predict():
    """A predict plan that doesn't qualify (no entity-list shape) is
    untouched by the promotion path — no entity_matrix added, no shortfall."""
    plan = {
        "report_title": "T",
        "report_toc": [
            {
                "id": "S1",
                "title": "Background",
                "subsections": [{"id": "S1.1", "title": "background", "depth_seeds": []}] * 2,
                "depth_target": "broad",
            }
        ],
        "queries": [{"id": "Q1", "text": "q", "type": "factual"}],
        "acceptance_criteria": [],
    }
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    em_shortfalls = [s for s in audit["shortfalls"] if "entity_matrix" in s]
    assert em_shortfalls == [], f"unexpected entity shortfalls: {em_shortfalls}"


# --------------------------------------------------------------------------
# 5. Back-compat — back-compat constant + pre-W1 callers still work.
# --------------------------------------------------------------------------


def test_legacy_flat_constant_still_present():
    """Back-compat: `_ENTITY_MATRIX_ENTITIES_MAX = 20` is still defined
    for any pre-W1 caller that imported it directly."""
    assert architect._ENTITY_MATRIX_ENTITIES_MAX == 20


def test_normalize_works_with_pre_w1_plan_shape():
    """A plan emitted by a pre-W1 architect (no instantiation_mode, no
    min_axes_per_entity, string-form dimensions) still normalizes cleanly."""
    plan = _bare_plan_with_matrix()
    plan["entity_matrix"]["dimensions"] = ["A", "B", "C", "D"]  # legacy string form
    plan["entity_matrix"].pop("instantiation_mode", None)
    plan["entity_matrix"].pop("min_axes_per_entity", None)
    architect._normalize(plan, archetype="list-all")
    em = plan["entity_matrix"]
    assert em["instantiation_mode"] == "prose_subheaders"
    assert em["min_axes_per_entity"] == 3
    assert all(isinstance(d, dict) for d in em["dimensions"])
