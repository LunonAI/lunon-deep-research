"""Unit tests for P3-W1 — `_validate_micro_template` compliance scorer.

The validator computes per-entity micro-template compliance: for each
entity in entity_matrix, what fraction of dimensions appeared as bolded
sub-headers within ~3000 chars after the entity's first mention. Below-
threshold entities = ratio < (min_axes_per_entity / len(dimensions)).

These tests pin: full-compliance article, partial-compliance, missing-
entity, missing-matrix (returns None), legacy table-only mode (returns
None), language-aware colon detection (EN + ZH).
"""

from deep_research.pipeline.validation import _validate_micro_template


def _em(entities, dim_names, mode="prose_subheaders", min_axes=3):
    return {
        "entities": entities,
        "dimensions": [
            {"axis_name": name, "render_order": i + 1, "content_template": "t"} for i, name in enumerate(dim_names)
        ],
        "instantiation_mode": mode,
        "min_axes_per_entity": min_axes,
    }


def _article_with_perfect_compliance(entities, dim_names):
    """Generate an article body where every entity has every dimension
    rendered as a bolded sub-header. Used to validate the happy-path."""
    parts = []
    for ent in entities:
        parts.append(f"\n## {ent}\n\n")
        for d in dim_names:
            parts.append(f"**{d}:** content for {ent}.\n\n")
    return "".join(parts)


def test_validate_returns_none_for_missing_matrix():
    """No matrix → no check applies."""
    assert _validate_micro_template("body", None) is None
    assert _validate_micro_template("body", {}) is None


def test_validate_returns_none_for_legacy_table_only_mode():
    """Legacy mode skips the check (writer doesn't emit sub-headers)."""
    em = _em(["E1", "E2"], ["D1", "D2"], mode="table_columns_only")
    assert _validate_micro_template("body", em) is None


def test_validate_returns_none_for_empty_dimensions():
    """No axis names → no compliance to measure."""
    em = _em(["E1"], [])
    assert _validate_micro_template("body", em) is None


def test_validate_returns_none_for_empty_entities():
    """No entities → no compliance to measure."""
    em = _em([], ["D1", "D2"])
    assert _validate_micro_template("body", em) is None


def test_validate_perfect_compliance_returns_1_point_0():
    """An article with every entity instantiating every axis: compliance = 1.0."""
    entities = ["IBM", "Google", "Origin"]
    dims = ["Winning Logic", "Stall Risk", "Time Window"]
    article = _article_with_perfect_compliance(entities, dims)
    em = _em(entities, dims, min_axes=3)
    out = _validate_micro_template(article, em)
    assert out is not None
    assert out["article_compliance"] == 1.0, f"got {out}"
    assert out["below_threshold_entities"] == [], f"got {out}"
    for ent in entities:
        assert out["per_entity_compliance"][ent] == 1.0


def test_validate_partial_compliance_drops_one_axis():
    """Drop one axis from one entity: per-entity ratio = (N-1)/N for that entity."""
    entities = ["IBM", "Google", "Origin"]
    dims = ["Winning Logic", "Stall Risk", "Time Window", "Team Combination"]
    # Build article: IBM gets all 4 axes, Google gets 3 (Time Window dropped), Origin gets 4
    article = (
        "\n## IBM\n\n**Winning Logic:** ibm.\n**Stall Risk:** ibm.\n**Time Window:** ibm.\n**Team Combination:** ibm.\n"
        "\n## Google\n\n**Winning Logic:** g.\n**Stall Risk:** g.\n**Team Combination:** g.\n"
        "\n## Origin\n\n**Winning Logic:** o.\n**Stall Risk:** o.\n**Time Window:** o.\n**Team Combination:** o.\n"
    )
    em = _em(entities, dims, min_axes=3)  # min_axes=3 → threshold=3/4=0.75
    out = _validate_micro_template(article, em)
    assert out["per_entity_compliance"]["IBM"] == 1.0
    assert out["per_entity_compliance"]["Google"] == 0.75, f"got {out}"
    assert out["per_entity_compliance"]["Origin"] == 1.0
    # Google has ratio 0.75, threshold 0.75 → NOT below threshold (strict less-than)
    assert "Google" not in out["below_threshold_entities"], f"got {out['below_threshold_entities']}"


def test_validate_flags_entities_below_threshold():
    """An entity below the min_axes_per_entity floor → flagged."""
    entities = ["IBM", "Google"]
    dims = ["D1", "D2", "D3", "D4"]
    article = (
        "\n## IBM\n\n**D1:** ibm.\n**D2:** ibm.\n**D3:** ibm.\n**D4:** ibm.\n"
        "\n## Google\n\n**D1:** g.\n"  # only 1 of 4 axes
    )
    em = _em(entities, dims, min_axes=3)  # threshold=0.75
    out = _validate_micro_template(article, em)
    assert out["per_entity_compliance"]["IBM"] == 1.0
    assert out["per_entity_compliance"]["Google"] == 0.25
    assert "Google" in out["below_threshold_entities"]
    assert "IBM" not in out["below_threshold_entities"]


def test_validate_missing_entity_compliance_zero():
    """An entity name that never appears in the article: compliance 0,
    flagged below-threshold."""
    entities = ["IBM", "Microsoft"]
    dims = ["D1", "D2", "D3"]
    article = "\n## IBM\n\n**D1:** ibm.\n**D2:** ibm.\n**D3:** ibm.\n"
    em = _em(entities, dims, min_axes=2)
    out = _validate_micro_template(article, em)
    assert out["per_entity_compliance"]["Microsoft"] == 0.0
    assert "Microsoft" in out["below_threshold_entities"]


def test_validate_case_insensitive_entity_match():
    """Entity name in matrix is "IBM"; article body uses "ibm" — match anyway."""
    entities = ["IBM"]
    dims = ["D1", "D2"]
    article = "\n## ibm (corp.)\n\n**D1:** x.\n**D2:** y.\n"
    em = _em(entities, dims, min_axes=2)
    out = _validate_micro_template(article, em)
    assert out["per_entity_compliance"]["IBM"] == 1.0


def test_validate_zh_fullwidth_colon_recognized():
    """ZH articles use the full-width colon — the validator accepts both
    forms so it doesn't false-negative against ZH-mode writer output."""
    entities = ["IBM"]
    dims = ["维度一", "维度二"]
    article = "\n## IBM\n\n**维度一：** 内容一。\n**维度二：** 内容二。\n"
    em = _em(entities, dims, min_axes=2)
    out = _validate_micro_template(article, em)
    assert out["per_entity_compliance"]["IBM"] == 1.0


def test_validate_string_form_dimensions_normalized():
    """A legacy string-form `dimensions: [str, ...]` matrix is normalized
    inside the validator (defensive — production code goes through
    architect._normalize_dimensions first, but tests may pass raw plans)."""
    entities = ["IBM"]
    em = {
        "entities": entities,
        "dimensions": ["Cost", "Speed"],  # legacy string form
        "instantiation_mode": "prose_subheaders",
        "min_axes_per_entity": 2,
    }
    article = "\n## IBM\n\n**Cost:** $1M.\n**Speed:** fast.\n"
    out = _validate_micro_template(article, em)
    assert out is not None
    assert out["per_entity_compliance"]["IBM"] == 1.0


def test_validate_article_compliance_is_mean_across_entities():
    """article_compliance = mean of per-entity ratios."""
    entities = ["A", "B"]
    dims = ["D1", "D2", "D3", "D4"]
    article = (
        "\n## A\n\n**D1:** a.\n**D2:** a.\n**D3:** a.\n**D4:** a.\n"  # 4/4 = 1.0
        "\n## B\n\n**D1:** b.\n**D2:** b.\n"  # 2/4 = 0.5
    )
    em = _em(entities, dims, min_axes=2)
    out = _validate_micro_template(article, em)
    assert out["article_compliance"] == 0.75, f"got {out}"


def test_validate_min_axes_per_entity_exposed_in_result():
    """The returned dict surfaces min_axes_per_entity so dev-run
    analysers can correlate compliance ratios with the active threshold
    (drift telemetry needs this)."""
    em = _em(["E1"], ["D1", "D2", "D3"], min_axes=2)
    out = _validate_micro_template("\n## E1\n\n**D1:** x.\n", em)
    assert out["min_axes_per_entity"] == 2


def test_validate_skips_s1_matrix_table_for_anchor():
    """Greptile PR #37 round-3 (issue 3): the §1 entity matrix is
    rendered as a markdown table (writer.py §1 wrapper). Entity names
    first appear in compact pipe-bounded rows ~20-80 chars apart. If
    the validator anchored on `article.find(ent)`, the window would
    land inside the table, contain no `**Axis:**` patterns, and score
    every entity except the last 0.0 — even when the writer correctly
    instantiated the micro-template in body chapters. The anchor must
    skip table-row matches and land on a non-table line."""
    entities = ["IBM", "Google", "Origin"]
    dims = ["D1", "D2", "D3"]
    # Realistic article shape: §1 has the matrix as a markdown table
    # (rows are pipe-bounded), then §2+ contain the body sections with
    # the bolded sub-headers. Pre-fix this article scored ~0.0 on every
    # entity because anchors landed inside the table.
    s1_table = (
        "## §1 Overview\n\n"
        "| Entity | Dimension | Notes |\n"
        "|---|---|---|\n"
        "| IBM | x | y |\n"
        "| Google | x | y |\n"
        "| Origin | x | y |\n\n"
    )
    s2_body = (
        "## §2 IBM\n\n"
        "**D1:** ibm-d1.\n**D2:** ibm-d2.\n**D3:** ibm-d3.\n\n"
        "## §3 Google\n\n"
        "**D1:** g-d1.\n**D2:** g-d2.\n**D3:** g-d3.\n\n"
        "## §4 Origin\n\n"
        "**D1:** o-d1.\n**D2:** o-d2.\n**D3:** o-d3.\n"
    )
    article = s1_table + s2_body
    em = _em(entities, dims, min_axes=3)
    out = _validate_micro_template(article, em)
    assert out is not None
    # Post-fix: anchors skip the §1 table rows and land on §2/§3/§4
    # body sections, each fully compliant.
    assert out["per_entity_compliance"]["IBM"] == 1.0, f"IBM anchor leaked into §1 table; got {out}"
    assert out["per_entity_compliance"]["Google"] == 1.0, f"Google anchor leaked into §1 table; got {out}"
    assert out["per_entity_compliance"]["Origin"] == 1.0, f"Origin anchor leaked into §1 table; got {out}"
    assert out["below_threshold_entities"] == [], f"got {out['below_threshold_entities']}"


def test_validate_anchor_falls_back_when_all_mentions_table_bound():
    """If an entity appears ONLY inside the §1 matrix table (writer
    never produced a body section for it), the anchor should fall
    back to the table-row position rather than crash or skip the
    entity. The resulting compliance is correctly 0.0 — communicating
    the real failure (no body instantiation), not a measurement bug."""
    entities = ["TableOnly"]
    dims = ["D1", "D2"]
    article = (
        "## §1 Overview\n\n"
        "| Entity | x |\n"
        "|---|---|\n"
        "| TableOnly | y |\n"
        "## §2 Other section\n\nbody content without sub-headers.\n"
    )
    em = _em(entities, dims, min_axes=2)
    out = _validate_micro_template(article, em)
    assert out is not None
    # TableOnly has zero body instantiation → 0.0 compliance, flagged.
    assert out["per_entity_compliance"]["TableOnly"] == 0.0
    assert "TableOnly" in out["below_threshold_entities"]


def test_validate_handles_null_min_axes_per_entity_without_crash():
    """Greptile PR #37 round-3 (issue 1): a matrix arriving at the
    validator without passing through `architect._normalize` may carry
    `min_axes_per_entity: None` (architect uses `or`-assignment to
    coerce null → 3, but the validator can be invoked directly e.g.
    in unit tests, future caller paths). The validator must not
    crash with `int(None)` — defensive `or 3` coercion in place."""
    entities = ["E1"]
    dims = ["D1", "D2"]
    em = {
        "entities": entities,
        "dimensions": [{"axis_name": d, "render_order": i, "content_template": "t"} for i, d in enumerate(dims)],
        "instantiation_mode": "prose_subheaders",
        "min_axes_per_entity": None,  # the case Greptile flagged
    }
    article = "\n## E1\n\n**D1:** x.\n**D2:** y.\n"
    # Must not raise.
    out = _validate_micro_template(article, em)
    assert out is not None
    # Default of 3 applied: threshold = min(1.0, 3/2) = 1.0; ratio = 1.0
    # → not below threshold. Confirms the default flowed through.
    assert out["min_axes_per_entity"] == 3
    assert out["per_entity_compliance"]["E1"] == 1.0
