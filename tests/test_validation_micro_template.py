"""G5 (2026-05-28): `_validate_micro_template` — per-axis canonical-label
coverage for the prose_subheaders entity micro-template.

The writer now PINS one byte-identical bold axis label per axis (q91 form);
this validator measures how often that canonical label actually appears across
the entities, so fragmentation (per-entity variant phrasings, the dev4 id=91
failure) is caught and re-pinned by the regen loop.
"""

from deep_research.pipeline import validation


def _em(mode="prose_subheaders", entities=None, axes=("Signature techniques", "Key arc appearances")):
    return {
        "entities": entities if entities is not None else ["A", "B", "C", "D"],
        "dimensions": [{"axis_name": a, "render_order": i + 1} for i, a in enumerate(axes)],
        "instantiation_mode": mode,
    }


def _article_with_labels(entities, per_entity_labels):
    """Build an article where each entity opens each axis paragraph with the
    given bold label string (allows simulating fragmentation by varying it)."""
    parts = ["# Title\n"]
    for ent, labels in zip(entities, per_entity_labels):
        parts.append(f"## {ent}\n")
        for lab in labels:
            parts.append(f"**{lab}.** Dense paragraph about {ent} on this axis.\n")
    return "\n".join(parts)


def test_returns_none_for_non_dict():
    assert validation._validate_micro_template("x", None) is None
    assert validation._validate_micro_template("x", "not a dict") is None


def test_returns_none_for_table_columns_only_mode():
    assert validation._validate_micro_template("x", _em(mode="table_columns_only")) is None


def test_returns_none_when_fewer_than_three_entities():
    assert validation._validate_micro_template("x", _em(entities=["A", "B"])) is None


def test_full_coverage_when_canonical_label_used_for_every_entity():
    """Every entity opens both axes with the EXACT canonical label → 1.0."""
    entities = ["A", "B", "C", "D"]
    axes = ("Signature techniques", "Key arc appearances")
    article = _article_with_labels(entities, [list(axes)] * len(entities))
    audit = validation._validate_micro_template(article, _em(entities=entities, axes=axes))
    assert audit is not None
    assert audit["n_entities"] == 4
    assert audit["axis_coverage"]["Signature techniques"] == 1.0
    assert audit["axis_coverage"]["Key arc appearances"] == 1.0
    assert audit["min_axis_coverage"] == 1.0


def test_fragmented_labels_drop_coverage_below_threshold():
    """Only 1 of 4 entities uses the canonical 'Signature techniques' label;
    the rest fragment into variants → coverage 0.25 < 0.5 threshold."""
    entities = ["A", "B", "C", "D"]
    axes = ("Signature techniques", "Key arc appearances")
    per_entity = [
        ["Signature techniques", "Key arc appearances"],  # canonical
        ["Signature waza", "Key arc appearances"],  # variant on axis 1
        ["Signature moves", "Key arc appearances"],  # variant on axis 1
        ["Notable techniques", "Key arc appearances"],  # variant on axis 1
    ]
    article = _article_with_labels(entities, per_entity)
    audit = validation._validate_micro_template(article, _em(entities=entities, axes=axes))
    assert audit["axis_coverage"]["Signature techniques"] == 0.25
    assert audit["axis_coverage"]["Key arc appearances"] == 1.0
    assert audit["min_axis_coverage"] == 0.25
    assert audit["min_axis_coverage"] < validation._MICRO_TEMPLATE_MIN_COVERAGE


def test_coverage_capped_at_one_when_label_appears_more_than_entity_count():
    """A label used more times than there are entities still caps at 1.0."""
    entities = ["A", "B", "C"]
    axes = ("Final outcome",)
    # 5 uses of the label, only 3 entities → capped 1.0, not 1.67.
    article = "# T\n" + "\n".join("**Final outcome.** x" for _ in range(5))
    audit = validation._validate_micro_template(article, _em(entities=entities, axes=axes))
    assert audit["axis_coverage"]["Final outcome"] == 1.0
