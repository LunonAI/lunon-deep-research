"""Unit tests for P3-W7 — tier ranking + sensitivity analysis.

Qianfan pattern (q14 §7.3-§7.6: 10 teams × 6 rubric items with explicit
$S_{base}$/RBM/$S_{final}$ scoring and ±10pp weight sensitivity; q3 §8.1:
11 sub-sectors with 6-dim weighted score). Required for compare/predict
archetypes when entity_matrix has ≥5 entities.
"""

from deep_research.pipeline import architect


def _bare_plan_with_tr(em_entity_count=10, **tr_overrides):
    tr = {
        "title": "Tier Ranking",
        "scoring_formula": "S_final = Σ(weight_i × dim_i)",
        "weights": {"R-1": 0.20, "R-2": 0.22, "R-3": 0.13, "R-4": 0.18, "R-5": 0.15, "R-6": 0.12},
        "tiers": [
            {"name": "Tier 1", "threshold": ">=8.0"},
            {"name": "Tier 2", "threshold": ">=6.0"},
            {"name": "Tier 3", "threshold": "<6.0"},
        ],
        "sensitivity_check": {"perturbation_pp": 10, "report": "rank_stability"},
    }
    tr.update(tr_overrides)
    return {
        "report_title": "T",
        "report_toc": [{"id": "S1", "title": "S", "subsections": [], "depth_target": "broad"}],
        "queries": [{"id": f"Q{i}", "text": "q", "type": "factual"} for i in range(50)],
        "acceptance_criteria": [],
        "entity_matrix": {
            "entities": [f"E{i + 1}" for i in range(em_entity_count)],
            "dimensions": ["D1", "D2", "D3", "D4"],
        },
        "tier_ranking": tr,
    }


def test_tier_ranking_constants_pinned():
    assert architect._TIER_RANKING_REQUIRED_ARCHETYPES == frozenset({"compare", "predict"})
    assert architect._TIER_RANKING_MIN_TIERS == 2
    assert architect._TIER_RANKING_MAX_TIERS == 5
    assert architect._TIER_RANKING_DEFAULT_PERTURBATION_PP == 10


def test_normalize_predict_with_complete_tier_ranking_no_shortfall():
    plan = _bare_plan_with_tr()
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    tr_sf = [s for s in audit["shortfalls"] if "tier_ranking" in s]
    assert tr_sf == [], f"got {tr_sf}"


def test_normalize_compare_with_complete_tier_ranking_no_shortfall():
    plan = _bare_plan_with_tr()
    architect._normalize(plan, archetype="compare")
    audit = plan["_outline_audit"]
    tr_sf = [s for s in audit["shortfalls"] if "tier_ranking" in s]
    assert tr_sf == [], f"got {tr_sf}"


def test_normalize_missing_tier_ranking_for_required_archetype_emits_shortfall():
    plan = _bare_plan_with_tr()
    plan.pop("tier_ranking")
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert any("tier_ranking=missing" in s for s in audit["shortfalls"])
    # Backfill produced empty-but-shaped object
    tr = plan["tier_ranking"]
    assert isinstance(tr, dict)
    assert tr["weights"] == {}


def test_normalize_with_fewer_than_5_entities_no_tier_ranking_required():
    """When entity_matrix has <5 entities, tier_ranking isn't required
    (ranking 3 entities is low-signal)."""
    plan = _bare_plan_with_tr(em_entity_count=3)
    plan.pop("tier_ranking")
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    tr_sf = [s for s in audit["shortfalls"] if "tier_ranking=missing" in s]
    assert tr_sf == []


def test_normalize_explain_mechanism_no_tier_ranking_required():
    """explain-mechanism / list-all / trend / recommend don't require
    tier_ranking."""
    plan = _bare_plan_with_tr()
    plan.pop("tier_ranking")
    architect._normalize(plan, archetype="explain-mechanism")
    audit = plan["_outline_audit"]
    tr_sf = [s for s in audit["shortfalls"] if "tier_ranking" in s]
    assert tr_sf == []


def test_normalize_weights_sum_below_1_flagged():
    """Weights summing far below 1.0 → shortfall."""
    plan = _bare_plan_with_tr(weights={"R-1": 0.20, "R-2": 0.20})  # sum 0.40
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert any("weights_sum" in s for s in audit["shortfalls"]), f"got {audit['shortfalls']}"


def test_normalize_weights_sum_above_1_flagged():
    """Weights summing above 1.0+tolerance → shortfall."""
    plan = _bare_plan_with_tr(weights={"R-1": 0.5, "R-2": 0.5, "R-3": 0.5, "R-4": 0.5})  # sum 2.0
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert any("weights_sum" in s for s in audit["shortfalls"])


def test_normalize_weights_sum_within_tolerance_passes():
    """LLM often emits 0.98 instead of 1.0 — tolerance accommodates."""
    plan = _bare_plan_with_tr(weights={"R-1": 0.20, "R-2": 0.20, "R-3": 0.20, "R-4": 0.20, "R-5": 0.18})  # 0.98
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    weight_sf = [s for s in audit["shortfalls"] if "weights_sum" in s]
    assert weight_sf == [], f"0.98 sum should be within tolerance; got {weight_sf}"


def test_normalize_tiers_below_min_flagged():
    plan = _bare_plan_with_tr(tiers=[{"name": "Tier 1", "threshold": ">=5.0"}])  # 1 tier
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert any("tier_ranking.tiers=1<2" in s for s in audit["shortfalls"])


def test_normalize_tiers_above_max_flagged():
    sh = [{"name": f"T{i}", "threshold": ">=0"} for i in range(7)]
    plan = _bare_plan_with_tr(tiers=sh)
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert any("tier_ranking.tiers=7>5" in s for s in audit["shortfalls"])


def test_normalize_missing_sensitivity_check_flagged():
    plan = _bare_plan_with_tr(sensitivity_check=None)
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert audit["tier_ranking_has_sensitivity_check"] is False
    assert any("sensitivity_check=missing" in s for s in audit["shortfalls"])


def test_normalize_empty_scoring_formula_flagged():
    plan = _bare_plan_with_tr(scoring_formula="")
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert any("scoring_formula=empty" in s for s in audit["shortfalls"])


def test_normalize_records_tier_ranking_audit_fields():
    plan = _bare_plan_with_tr()
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert audit["tier_ranking_n_tiers"] == 3
    assert audit["tier_ranking_has_sensitivity_check"] is True
    assert abs(audit["tier_ranking_weights_sum"] - 1.0) < 0.01


def test_normalize_handles_malformed_weights_field():
    plan = _bare_plan_with_tr(weights="not a dict")
    architect._normalize(plan, archetype="predict")
    tr = plan["tier_ranking"]
    assert tr["weights"] == {}


def test_normalize_handles_malformed_tiers_field():
    plan = _bare_plan_with_tr(tiers="not a list")
    architect._normalize(plan, archetype="predict")
    tr = plan["tier_ranking"]
    assert tr["tiers"] == []


def test_normalize_boolean_weights_excluded_from_sum():
    """Greptile PR #43 round-3: `bool` is a subclass of `int` in Python, so
    a naive `isinstance(v, (int, float))` filter silently admits boolean
    weights. A dict like `{"R-1": True}` would compute weights_sum=1.0,
    pass the ±0.05 tolerance check, and mask an LLM type error.

    The fix excludes bool the same way the perturbation_pp guard does
    (`not isinstance(v, bool)`). Verified by feeding the auditor a weights
    dict of all-True values — the audit must record weights_sum=0.0 and
    emit a `weights_sum=0.000!=1.0±0.05` shortfall."""
    plan = _bare_plan_with_tr(weights={"R-1": True, "R-2": True, "R-3": True, "R-4": True})
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    assert audit["tier_ranking_weights_sum"] == 0.0, (
        f"booleans should be filtered from weights_sum; got {audit['tier_ranking_weights_sum']}"
    )
    assert any("weights_sum" in s for s in audit["shortfalls"]), (
        f"weights_sum tolerance shortfall must fire when every weight is bool; got {audit['shortfalls']}"
    )


def test_normalize_mixed_numeric_and_bool_weights_excludes_only_bool():
    """A mix of valid floats and a stray bool: the floats are summed; the
    bool is ignored. Confirms the filter doesn't drop legitimate numeric
    weights as collateral damage of the bool exclusion."""
    plan = _bare_plan_with_tr(weights={"R-1": 0.5, "R-2": 0.5, "R-3": True})
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    # 0.5 + 0.5 = 1.0; True ignored. Within ±0.05 tolerance → no shortfall.
    assert abs(audit["tier_ranking_weights_sum"] - 1.0) < 0.01
    assert not any("weights_sum" in s for s in audit["shortfalls"])


# --------------------------------------------------------------------------
# Greptile PR #43 round-2 — non-list entity_matrix.entities must not falsely
# trigger tier_ranking requirement, and the perturbation_pp constant must
# have runtime enforcement (not just dead documentation).
# --------------------------------------------------------------------------


def test_normalize_predict_with_string_entities_does_not_trigger_tier_ranking():
    """Greptile PR #43 round-2: if the LLM emits `entity_matrix.entities` as
    a comma-separated string (`"E1, E2, E3, E4, E5"`) instead of a list, the
    `or []` guard previously let it through and `len()` returned the
    character count (18), spuriously triggering `tr_is_required=True` for
    "predict" plans where entity_matrix normalization doesn't run pre-tier.
    The fix is an explicit isinstance(list) check: a non-list value yields
    `em_entities=[]`, `len()=0`, `tr_is_required=False`."""
    plan = _bare_plan_with_tr()
    plan["entity_matrix"]["entities"] = "E1, E2, E3, E4, E5, E6, E7"  # string, not list
    plan.pop("tier_ranking")
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    tr_sf = [s for s in audit["shortfalls"] if "tier_ranking=missing" in s]
    assert tr_sf == [], f"non-list entities should not trigger tier_ranking requirement; got {tr_sf}"


def test_normalize_predict_with_dict_entities_does_not_trigger_tier_ranking():
    """Symmetric guard: dict-valued entities (another plausible LLM
    malformation) must also fall through to `em_entities=[]`."""
    plan = _bare_plan_with_tr()
    plan["entity_matrix"]["entities"] = {"E1": 1, "E2": 2}  # dict, not list
    plan.pop("tier_ranking")
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    tr_sf = [s for s in audit["shortfalls"] if "tier_ranking=missing" in s]
    assert tr_sf == []


def test_normalize_predict_with_none_entity_matrix_does_not_trigger_tier_ranking():
    """Pin the original pre-fix `or []` behavior is preserved when
    `entity_matrix` itself is None (the case the original guard targeted)."""
    plan = _bare_plan_with_tr()
    plan["entity_matrix"] = None
    plan.pop("tier_ranking")
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    tr_sf = [s for s in audit["shortfalls"] if "tier_ranking=missing" in s]
    assert tr_sf == []


def test_normalize_perturbation_pp_constants_pinned():
    """Greptile PR #43 round-2: the band constants must be pinned so a
    future tweak that widens them is a deliberate test edit, not silent
    behavior drift."""
    assert architect._TIER_RANKING_PERTURBATION_PP_MIN == 5
    assert architect._TIER_RANKING_PERTURBATION_PP_MAX == 20
    # Default still must lie within the band — sanity check that wiring
    # the constant to validation didn't create a contradiction.
    assert (
        architect._TIER_RANKING_PERTURBATION_PP_MIN
        <= architect._TIER_RANKING_DEFAULT_PERTURBATION_PP
        <= architect._TIER_RANKING_PERTURBATION_PP_MAX
    )


def test_normalize_sensitivity_check_perturbation_default_passes():
    """The default (10pp) is within the accepted band and emits no shortfall."""
    plan = _bare_plan_with_tr()  # default fixture uses perturbation_pp=10
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    pp_sf = [s for s in audit["shortfalls"] if "perturbation_pp" in s]
    assert pp_sf == [], f"default 10pp must not flag; got {pp_sf}"
    assert audit["tier_ranking_sensitivity_perturbation_pp"] == 10


def test_normalize_sensitivity_check_perturbation_in_band_passes():
    """Values inside [5, 20] (e.g., 7pp, 15pp) are accepted without flag."""
    for value in (5, 7, 15, 20):
        plan = _bare_plan_with_tr(sensitivity_check={"perturbation_pp": value, "report": "x"})
        architect._normalize(plan, archetype="predict")
        audit = plan["_outline_audit"]
        pp_sf = [s for s in audit["shortfalls"] if "perturbation_pp" in s]
        assert pp_sf == [], f"perturbation_pp={value} is in-band; got {pp_sf}"
        assert audit["tier_ranking_sensitivity_perturbation_pp"] == value


def test_normalize_sensitivity_check_perturbation_below_min_flagged():
    """A perturbation of 1pp is technically a sensitivity check but too
    trivial to surface real rank instability — flagged."""
    plan = _bare_plan_with_tr(sensitivity_check={"perturbation_pp": 1, "report": "x"})
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    pp_sf = [s for s in audit["shortfalls"] if "perturbation_pp=1" in s]
    assert pp_sf, f"perturbation_pp=1 should flag; got {audit['shortfalls']}"
    assert audit["tier_ranking_sensitivity_perturbation_pp"] == 1


def test_normalize_sensitivity_check_perturbation_above_max_flagged():
    """A perturbation of 50pp is no longer "sensitivity" so much as
    re-weighting — flagged."""
    plan = _bare_plan_with_tr(sensitivity_check={"perturbation_pp": 50, "report": "x"})
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    pp_sf = [s for s in audit["shortfalls"] if "perturbation_pp=50" in s]
    assert pp_sf, f"perturbation_pp=50 should flag; got {audit['shortfalls']}"


def test_normalize_sensitivity_check_missing_perturbation_backfilled():
    """When `sensitivity_check` exists as a dict but lacks `perturbation_pp`
    (or has a non-numeric value), the default constant is backfilled in-place
    AND a shortfall is recorded so the audit trail surfaces the LLM
    omission. This is the wire-in that makes the constant load-bearing."""
    plan = _bare_plan_with_tr(sensitivity_check={"report": "rank_stability"})  # missing pp
    architect._normalize(plan, archetype="predict")
    audit = plan["_outline_audit"]
    # Backfill happened in-place.
    assert plan["tier_ranking"]["sensitivity_check"]["perturbation_pp"] == (
        architect._TIER_RANKING_DEFAULT_PERTURBATION_PP
    )
    # Shortfall recorded.
    pp_sf = [s for s in audit["shortfalls"] if "perturbation_pp=missing" in s]
    assert pp_sf, f"missing perturbation_pp should flag; got {audit['shortfalls']}"
    assert "backfilled-to-10" in pp_sf[0]
    # Audit field surfaces the backfilled value (not None).
    assert audit["tier_ranking_sensitivity_perturbation_pp"] == 10


def test_normalize_sensitivity_check_string_perturbation_backfilled():
    """Non-numeric `perturbation_pp` (e.g., the LLM emitted "10pp" as a
    string) → backfilled. bool is excluded from numeric to prevent
    True/False slipping through as 1/0."""
    for bad_value in ("10pp", "ten", None, True, False, [10]):
        plan = _bare_plan_with_tr(sensitivity_check={"perturbation_pp": bad_value, "report": "x"})
        architect._normalize(plan, archetype="predict")
        audit = plan["_outline_audit"]
        assert plan["tier_ranking"]["sensitivity_check"]["perturbation_pp"] == 10, (
            f"non-numeric perturbation_pp={bad_value!r} should backfill to 10"
        )
        pp_sf = [s for s in audit["shortfalls"] if "perturbation_pp=missing" in s]
        assert pp_sf, f"perturbation_pp={bad_value!r} should flag; got {audit['shortfalls']}"


def test_normalize_perturbation_default_constant_actually_referenced():
    """Greptile PR #43 round-2 root concern: prove the
    `_TIER_RANKING_DEFAULT_PERTURBATION_PP` constant is now load-bearing
    by temporarily monkey-patching it and verifying the runtime backfill
    follows the new value. Pre-fix the constant was dead documentation —
    a change to it would silently have no effect."""
    original = architect._TIER_RANKING_DEFAULT_PERTURBATION_PP
    try:
        architect._TIER_RANKING_DEFAULT_PERTURBATION_PP = 12
        plan = _bare_plan_with_tr(sensitivity_check={"report": "x"})  # missing pp
        architect._normalize(plan, archetype="predict")
        assert plan["tier_ranking"]["sensitivity_check"]["perturbation_pp"] == 12, (
            "backfill must follow _TIER_RANKING_DEFAULT_PERTURBATION_PP at runtime"
        )
    finally:
        architect._TIER_RANKING_DEFAULT_PERTURBATION_PP = original
