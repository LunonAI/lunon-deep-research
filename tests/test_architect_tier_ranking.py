"""Unit tests for P3-W7 — tier ranking + sensitivity analysis.

the reference pattern (q14 §7.3-§7.6: 10 teams × 6 rubric items with explicit
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
