"""Unit tests for P2-Wave-2.5-D1 architect `report_depth_tier` normalization."""

from deep_research.pipeline.architect import _normalize


def test_normalize_keeps_valid_depth_tier():
    plan = {"report_depth_tier": "comprehensive"}
    _normalize(plan)
    assert plan["report_depth_tier"] == "comprehensive"


def test_normalize_lowercases_depth_tier():
    plan = {"report_depth_tier": "DEEP"}
    _normalize(plan)
    assert plan["report_depth_tier"] == "deep"


def test_normalize_drops_unknown_depth_tier():
    plan = {"report_depth_tier": "extra-long"}
    _normalize(plan)
    assert "report_depth_tier" not in plan


def test_normalize_drops_non_string_depth_tier():
    plan = {"report_depth_tier": 5}
    _normalize(plan)
    assert "report_depth_tier" not in plan


def test_normalize_missing_depth_tier_is_fine():
    plan: dict = {}
    _normalize(plan)
    # Downstream uses resolve_depth_tier(archetype, None) → archetype default.
    assert "report_depth_tier" not in plan


def test_normalize_still_attaches_specialist_roles():
    plan = {
        "queries": [{"id": "Q1", "text": "x", "type": "comparative"}],
    }
    _normalize(plan)
    assert plan["queries"][0]["specialist_role"] == "comparator"
