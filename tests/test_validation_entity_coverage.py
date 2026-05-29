"""L3 (2026-05-29): `_validate_entity_coverage` — every declared entity must get
its own body expansion (heading), not just a §1 matrix row. Catches the
collapsed-coverage failure the Qianfan head-to-head exposed (id8 expanded 1/12
material systems and left the rest as matrix rows = large Comprehensiveness loss).
"""

from deep_research.pipeline import validation


def _em(mode="prose_subheaders", entities=None):
    return {
        "entities": entities if entities is not None else ["IBM Quantum", "Google QAI", "Origin", "Baidu"],
        "dimensions": [{"axis_name": "A", "render_order": 1}],
        "instantiation_mode": mode,
    }


def test_returns_none_for_non_prose_or_few_entities():
    assert validation._validate_entity_coverage("x", None) is None
    assert validation._validate_entity_coverage("x", _em(mode="table_columns_only")) is None
    assert validation._validate_entity_coverage("x", _em(entities=["A", "B"])) is None


def test_full_coverage_when_every_entity_has_a_heading():
    ents = ["IBM Quantum", "Google QAI", "Origin", "Baidu"]
    art = "# T\n\n## 1 Matrix\n\n| e | a |\n|---|---|\n" + "".join(f"## {e}\n\nbody about {e}.\n\n" for e in ents)
    a = validation._validate_entity_coverage(art, _em(entities=ents))
    assert a["coverage"] == 1.0 and a["n_expanded"] == 4 and a["missing"] == []


def test_collapsed_coverage_flagged_when_rest_are_matrix_only():
    ents = ["IBM Quantum", "Google QAI", "Origin", "Baidu"]
    # Only IBM Quantum gets a body section; the other three live only as table rows.
    art = (
        "# T\n\n## 1 Comparison Matrix\n\n| Entity | Axis |\n|---|---|\n"
        "| Google QAI | x |\n| Origin | y |\n| Baidu | z |\n\n"
        "## 2 IBM Quantum\n\nFull body expansion of IBM Quantum here.\n"
    )
    a = validation._validate_entity_coverage(art, _em(entities=ents))
    assert a["n_expanded"] == 1
    assert a["coverage"] == 0.25
    assert a["coverage"] < validation._ENTITY_COVERAGE_MIN_RATIO
    assert set(a["missing"]) == {"Google QAI", "Origin", "Baidu"}
