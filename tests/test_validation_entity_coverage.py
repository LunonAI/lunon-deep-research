"""L3 (2026-05-29): `_validate_entity_coverage` — every declared entity must get
its own body expansion (heading), not just a §1 matrix row. Catches the
collapsed-coverage failure the reference head-to-head exposed (id8 expanded 1/12
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


def test_coverage_is_case_insensitive():
    """Greptile PR #69 round-1: a casing-only mismatch between the architect's
    entity name and the writer's heading ("IBM Quantum" -> "## IBM quantum")
    must still count as expanded — otherwise EN-named entities spuriously trip
    entity_coverage_collapsed and force a needless regen."""
    ents = ["IBM Quantum", "Google QAI", "Origin", "Baidu"]
    # Every entity has a body heading, but the casing differs from the declared name.
    art = "# T\n\n## 1 Matrix\n\n| e | a |\n|---|---|\n" + "".join(
        f"## {e.lower()}\n\nbody about {e}.\n\n" for e in ents
    )
    a = validation._validate_entity_coverage(art, _em(entities=ents))
    assert a["coverage"] == 1.0 and a["n_expanded"] == 4 and a["missing"] == []


def test_missing_entity_keeps_original_casing_in_telemetry():
    """A genuinely-absent entity is still reported in `missing` with its declared
    casing (case-insensitive matching must not lowercase the telemetry output)."""
    ents = ["IBM Quantum", "Google QAI", "Origin"]
    art = "# T\n\n## IBM quantum\n\nbody.\n\n## google qai\n\nbody.\n"  # Origin absent
    a = validation._validate_entity_coverage(art, _em(entities=ents))
    assert a["n_expanded"] == 2
    assert a["missing"] == ["Origin"]


def test_short_entity_name_no_substring_false_positive():
    """Greptile PR #69 round-3: a short EN entity must NOT count as expanded just
    because its letters appear inside an unrelated heading word ("AI" in "SAIL",
    "OS" in "POSIX", "ML" in "HTML"). The ASCII-alnum word-boundary guard removes
    that false positive (pre-fix the unanchored substring test counted all three,
    silently hiding a real coverage gap below the 0.5 threshold)."""
    ents = ["AI", "OS", "ML"]
    art = "# T\n\n## SAIL Research\n\nbody.\n\n## POSIX layer\n\nbody.\n\n## HTML rendering\n\nbody.\n"
    a = validation._validate_entity_coverage(art, _em(entities=ents))
    assert a["n_expanded"] == 0
    assert set(a["missing"]) == {"AI", "OS", "ML"}


def test_short_entity_name_matches_standalone_heading():
    """The same short entities DO count when they head their own section — the
    guard anchors on boundaries, it does not require the name to be multi-word."""
    ents = ["AI", "OS", "ML"]
    art = "# T\n\n## AI Overview\n\nb.\n\n## OS Internals\n\nb.\n\n## ML Pipeline\n\nb.\n"
    a = validation._validate_entity_coverage(art, _em(entities=ents))
    assert a["coverage"] == 1.0 and a["n_expanded"] == 3


def test_cjk_entity_matches_within_longer_heading():
    """Greptile PR #69 round-3 regression guard: the boundary guard keys on ASCII
    alnum ONLY, so a CJK entity embedded in a longer CJK heading still matches. A
    naive `\\b` anchor would wrongly miss these (no ASCII word boundary between Han
    chars) — this pins that the false-positive fix did not break CJK coverage."""
    ents = ["量子计算", "人工智能", "区块链"]
    art = "# 报告\n\n## 量子计算的发展\n\n正文。\n\n## 人工智能概述\n\n正文。\n\n## 区块链技术\n\n正文。\n"
    a = validation._validate_entity_coverage(art, _em(entities=ents))
    assert a["coverage"] == 1.0 and a["n_expanded"] == 3


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
