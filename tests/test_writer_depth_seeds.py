"""Unit tests for writer.outline_units depth_seeds propagation (P2-Option-A-#1).

The writer's section-level call needs depth_seeds surfaced from each
subsection so it can populate H4 leaves under each H3. outline_units does
the flattening; this test pins the shape it produces.
"""

from deep_research.pipeline import writer


def test_outline_units_propagates_depth_seeds():
    """A plan with depth_seeds flows them through into each unit's subs."""
    plan = {
        "report_toc": [
            {
                "id": "S1",
                "title": "Top",
                "subsections": [
                    {
                        "id": "S1.1",
                        "title": "Sub A",
                        "depth_seeds": ["seed 1", "seed 2", "seed 3"],
                    },
                    {
                        "id": "S1.2",
                        "title": "Sub B",
                        "depth_seeds": ["seed 4", "seed 5"],
                    },
                ],
                "depth_target": "deep",
            }
        ]
    }
    units = writer.outline_units(plan)
    assert len(units) == 1
    assert units[0]["id"] == "S1"
    assert units[0]["depth"] == "deep"
    assert len(units[0]["subs"]) == 2
    assert units[0]["subs"][0]["depth_seeds"] == ["seed 1", "seed 2", "seed 3"]
    assert units[0]["subs"][1]["depth_seeds"] == ["seed 4", "seed 5"]


def test_outline_units_backfills_missing_depth_seeds():
    """Pre-#1 plans without a depth_seeds field on subsections still flow
    through, with each sub getting an empty depth_seeds list. The writer
    treats this as 'no architect guidance' and chooses its own H4 leaves."""
    plan = {
        "report_toc": [
            {
                "id": "S1",
                "title": "Top",
                "subsections": [{"id": "S1.1", "title": "Sub A"}],
                "depth_target": "broad",
            }
        ]
    }
    units = writer.outline_units(plan)
    assert units[0]["subs"][0]["depth_seeds"] == []


def test_outline_units_handles_missing_subsections():
    """A top section with no subsections list yields a unit with empty subs.
    Defensive against malformed architect output; should not crash."""
    plan = {"report_toc": [{"id": "S1", "title": "Top", "depth_target": "broad"}]}
    units = writer.outline_units(plan)
    assert units[0]["subs"] == []


def test_outline_units_handles_empty_plan():
    """Empty report_toc yields an empty unit list — no crash."""
    plan = {"report_toc": []}
    assert writer.outline_units(plan) == []
