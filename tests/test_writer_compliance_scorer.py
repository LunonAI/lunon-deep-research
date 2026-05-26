"""Wave 2 §6.1 (2026-05-26): per-rule writer-compliance landing-rate
scorer tests.

The compliance scorer is the meta-tool that closes the
prompt-iteration loop: instead of running a $30 smoke + waiting for
RACE scoring to see if a prompt change landed, we run the scorer on
the smoke output and get per-rule landing rates in seconds.

These tests pin the scoring math + the per-rule edge cases. The
scorer is offline diagnostic — bugs here surface as wrong-direction
feedback during iteration, not as production runtime issues.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from p2_writer_compliance import (  # noqa: E402
    _classify_leaf_elements,
    _score_footnotes,
    _score_heading_numbering,
    _score_insight_distribution,
    _score_outline_shape,
    _score_section_opening_recap,
    _split_into_leaves,
    compute_compliance,
)


def test_footnote_density_counts_inline_markers_only():
    """`[^X-N]: ...` def lines must NOT count toward inline density —
    they're definitions, not body citations."""
    article = "Claim with cite[^S1-1]. Another[^S1-2]. And reuse[^S1-1].\n\n[^S1-1]: Source A\n[^S1-2]: Source B\n"
    scores = _score_footnotes(article)
    assert scores["n_inline_markers"] == 3  # 3 inline marker occurrences
    assert scores["n_unique_markers"] == 2  # S1-1 + S1-2
    assert scores["n_def_lines"] == 2
    # def coverage: 2 of 2 unique markers defined
    assert scores["def_coverage_rate"] == 1.0


def test_footnote_def_coverage_zero_when_no_defs():
    """The post-Wave-1 smoke failure mode: 183 inline markers, 0 def
    lines. Scorer must report def_coverage = 0% so the operator sees
    the synthesis safety net (Wave 2 §2.1c) didn't fire OR the writer
    skipped def emission entirely."""
    article = "Body with[^S1-1] markers[^S1-2] only.\n"
    scores = _score_footnotes(article)
    assert scores["n_def_lines"] == 0
    assert scores["def_coverage_rate"] == 0.0


def test_footnote_density_below_qianfan_floor_flagged():
    """Qianfan-target density is ≥4-6 markers per 1000 words. Below
    that, the scorer flags so the operator knows the article doesn't
    meet citation-density parity (§2.1b target)."""
    # 100 words, 0 markers → density 0/1000 → below floor.
    article = ("word " * 100).strip() + "\n"
    scores = _score_footnotes(article)
    assert scores["below_qianfan_target"] is True


def test_classify_leaf_elements_detects_each_element():
    """Each element regex must fire on a representative example."""
    # Forward-looking: date anchor + "by 20XX" phrasing.
    fl = _classify_leaf_elements("By 2027, the cohort will likely expand.")
    assert fl["forward_looking"] is True
    # Contrarian: "Despite the standard reading"
    ct = _classify_leaf_elements("Despite the standard reading, the Episode G data suggests otherwise.")
    assert ct["contrarian"] is True
    # Quant: percent range
    qt = _classify_leaf_elements("60-75% of the cohort falls within this band.")
    assert qt["quant"] is True
    # Alternative: "Whereas X, Y"
    al = _classify_leaf_elements("Whereas Mu's wall absorbs radially, Aiolia's propagates directionally.")
    assert al["alternative"] is True


# ---- Wave 2 PR #30 self-review (gap #4): expanded regex coverage ----


def test_classify_forward_looking_catches_expanded_idioms():
    """Pre-fix regex missed common forward-looking idioms like 'looking
    ahead' / 'trajectory' / 'going forward'. Expanded coverage must
    fire on each + on the ZH equivalents."""
    samples = [
        "Looking ahead, the next decade will see continued expansion.",
        "The trajectory of the industry points to consolidation.",
        "Going forward, three constraints will bind.",
        "We anticipate three structural shifts.",
        "The outlook remains positive over the next 5 years.",
        "Over the next 3 years, several patterns will emerge.",
        "未来将会有更多的发展。",  # ZH "future will have ..."
        "展望整个行业...",  # ZH "looking forward to industry"
    ]
    for s in samples:
        assert _classify_leaf_elements(s)["forward_looking"], f"missed: {s!r}"


def test_classify_quant_avoids_bare_range_false_positive():
    """Pre-fix regex matched bare 'range' which fires on every 'wide
    range of topics' / 'broad range of cases' false positive. Tightened
    patterns require scoped quantification (a number nearby) to fire."""
    # Should NOT fire — bare "range" with no quantification.
    false_positives = [
        "The book covers a wide range of topics.",
        "A broad range of cases were examined.",
        "Range of motion was preserved.",
    ]
    for s in false_positives:
        assert not _classify_leaf_elements(s)["quant"], f"false positive: {s!r}"
    # Should fire — scoped quantification.
    true_positives = [
        "60-75% of the cohort.",
        "In the range of 100 to 200 cases.",
        "Roughly 40% of subjects.",
        "Approximately 1500 entries.",
        "Range of 2-5 hours per task.",
        "On the order of 10000 transactions.",
    ]
    for s in true_positives:
        assert _classify_leaf_elements(s)["quant"], f"missed: {s!r}"


def test_classify_contrarian_catches_expanded_idioms():
    """Pre-fix regex was thin. Expanded coverage adds 'argue against'
    / 'push back on' / 'in fact, the [reverse|opposite|contrary]' /
    ZH 实际上 / 事实上.

    Wave 2 PR #30 round-5 follow-up: bare `in fact` was narrowed (it
    matched too many non-contrarian analytical openings); now requires
    a reversal marker (reverse/opposite/contrary) after."""
    samples = [
        "The Episode G analysis argues against the standard reading.",
        "Critics push back on this consensus.",
        # Updated to match the narrowed `in fact, the reverse/opposite/contrary` form.
        "In fact, the opposite pattern holds across all archetypes.",
        "Differs from the standard interpretation, the model predicts...",
        "实际上，数据显示相反的结果。",
        "事实上，传统的解释并不成立。",
    ]
    for s in samples:
        assert _classify_leaf_elements(s)["contrarian"], f"missed: {s!r}"


def test_classify_alternative_catches_expanded_idioms():
    """Pre-fix regex caught 'whereas' / 'however' but missed common
    comparative idioms like 'compared to' / 'as opposed to' / 'rather
    than'."""
    samples = [
        "Compared to the symmetric case, the asymmetric one requires...",
        "As opposed to the consensus model, this approach uses...",
        "Method A rather than Method B is preferred when...",
        "The tradeoff between speed and accuracy.",
        "对比之下，另一种方法更高效。",
        "相比之前的研究，本方法...",
    ]
    for s in samples:
        assert _classify_leaf_elements(s)["alternative"], f"missed: {s!r}"


def test_classify_contrarian_does_not_fire_on_bare_yet():
    """Greptile PR #30 round-3 follow-up: the `\\byet\\b` pattern was
    REMOVED from the contrarian regex. The previous negative-lookahead
    `(?!,? \\w+ ago)` was logically inverted — it checked what came
    AFTER 'yet', not before — so all the common non-contrarian uses
    ('not yet', 'yet another', '5 years ago, yet the pattern...')
    still matched, inflating contrarian leaf counts.

    Pin: 'not yet' and 'yet another' must NOT fire contrarian. Genuine
    contrarian framing must still fire via the other patterns (despite,
    contrary to, argue against, in fact, etc.)."""
    # Common non-contrarian uses that previously false-fired.
    false_uses = [
        "The data is not yet conclusive.",
        "Yet another study confirms the trend.",
        "Five years ago, yet the pattern continues today.",
    ]
    for s in false_uses:
        assert not _classify_leaf_elements(s)["contrarian"], f"false positive: {s!r}"
    # Genuine contrarian framing still fires via OTHER patterns.
    real_contrarian = [
        "Despite the standard reading, the data shows otherwise.",
        "Critics argue against the consensus view.",
        "In fact, the opposite holds.",
        "Contrary to popular belief, the model predicts X.",
    ]
    for s in real_contrarian:
        assert _classify_leaf_elements(s)["contrarian"], f"missed: {s!r}"


def test_classify_contrarian_in_fact_narrowed_to_reversal_marker():
    """Greptile PR #30 round-5 follow-up: bare `\\bin fact\\b` was too
    broad — it matched common analytical openings like 'In fact,
    performance improved by 30%' or 'In fact, this method is well-
    understood', which are NOT contrarian framing. Over-counting
    inflates `per_element_rate_pct['contrarian']` and masks genuine
    under-performance the §3.2 rule is meant to surface.

    Pin: bare 'In fact, X' must NOT fire contrarian; only the
    narrowed form 'In fact, the reverse/opposite/contrary' fires."""
    # Common non-contrarian "In fact, ..." openings — must NOT fire.
    false_positives = [
        "In fact, performance improved by 30%.",
        "In fact, this method is well-understood across the literature.",
        "In fact, the dataset contains 50,000 entries.",
    ]
    for s in false_positives:
        assert not _classify_leaf_elements(s)["contrarian"], f"false positive: {s!r}"
    # Genuine adversative "In fact" framing — MUST still fire.
    real_contrarian = [
        "In fact, the reverse holds — yields are higher under this constraint.",
        "In fact, the opposite pattern emerges from the Episode G data.",
        "In fact, the contrary is true: alignment drops with size.",
    ]
    for s in real_contrarian:
        assert _classify_leaf_elements(s)["contrarian"], f"missed: {s!r}"


def test_classify_forward_looking_does_not_fire_on_retrospective_date():
    """Greptile PR #30 round-3 follow-up: `_DATE_RE` was REMOVED from
    the forward-looking detector. Pre-fix, ANY year in 20XX (2020-2099)
    would fire forward-looking, including retrospective sentences like
    'In 2023, the recession hit market valuations.' This inflated the
    most under-fired element's count and masked the genuine §3.2 gap.

    Pin: retrospective date mentions must NOT fire forward-looking.
    Genuine forward-looking phrases (by 20XX / through 20XX / looking
    ahead / trajectory / etc.) must still fire via `_FORWARD_RE`."""
    # Retrospective sentences with dates — must NOT fire forward-looking.
    retrospective = [
        "In 2023, the recession hit market valuations.",
        "The 2022 dataset showed three patterns.",
        "Released in 2024, the model achieved 80% accuracy.",
        "Historical records from 2020 to 2024 reveal a cyclic pattern.",
    ]
    for s in retrospective:
        assert not _classify_leaf_elements(s)["forward_looking"], f"false positive: {s!r}"
    # Genuine forward-looking still fires.
    forward = [
        "By 2027, the cohort will likely expand.",
        "Through 2030, the trend is expected to continue.",
        "Looking ahead, three constraints will bind.",
        "Over the next 5 years, several shifts will emerge.",
    ]
    for s in forward:
        assert _classify_leaf_elements(s)["forward_looking"], f"missed: {s!r}"


def test_split_into_leaves_flat_archetype_uses_h2():
    """list-all / compare archetypes treat H2 body sections as leaves
    (Wave 2 §1.2 dropped H4 for these archetypes). The splitter must
    not look for H4 here."""
    article = (
        "# Title\n\nIntro frame.\n\n"
        "## 1 First Entity\nBody of first entity.\n\n"
        "## 2 Second Entity\nBody of second entity.\n\n"
        "## 3 References\nDef block.\n"
    )
    leaves = _split_into_leaves(article, "list-all")
    # 2 H2 leaves (References stops the walk).
    assert len(leaves) == 2
    assert "first entity" in leaves[0].lower()
    assert "second entity" in leaves[1].lower()


def test_split_into_leaves_deep_archetype_uses_h4():
    """explain-mechanism / predict / trend / recommend archetypes
    treat H4 leaves as the per-leaf unit (Wave 2 §1.2 keeps H4 for
    deep archetypes)."""
    article = (
        "# Title\n\n## 1 Section\n\n### 1.1 Sub\n\n"
        "#### 1.1.1 Leaf A\nBody A.\n\n"
        "#### 1.1.2 Leaf B\nBody B.\n\n"
        "## 2 References\nDefs.\n"
    )
    leaves = _split_into_leaves(article, "explain-mechanism")
    assert len(leaves) == 2
    assert "body a" in leaves[0].lower()
    assert "body b" in leaves[1].lower()


def test_insight_distribution_per_archetype_target_applied():
    """The distribution scorer must pull per-archetype targets from
    `writing_rules.insight_distribution`. predict archetype expects
    ≥50% forward-looking; list-all expects ≥30% alternative."""
    article = (
        "# Title\n\n"
        "## 1 A\n#### 1.1.1 L1\nBy 2027 things change. Whereas X, Y.\n\n"
        "## 2 B\n#### 2.1.1 L2\nBy 2028 more change.\n"
    )
    # predict archetype — forward-looking target = 45 (Wave 2 PR #30
    # corpus calibration).
    p = _score_insight_distribution(article, "predict")
    assert p["per_element_target_pct"]["forward_looking"] == 45
    # list-all archetype — alternative target = 47 (Wave 2 PR #30
    # corpus calibration).
    la = _score_insight_distribution(article, "list-all")
    assert la["per_element_target_pct"]["alternative"] == 47


def test_outline_shape_flags_out_of_bounds_h2_for_list_all():
    """Wave 2 §1.2: list-all expects 30-80 H2. A 10-H2 article (typical
    pre-Wave-2 hierarchical output) must be flagged out-of-bounds."""
    article = "# T\n\n" + "\n\n".join(f"## {i + 1} Foo" for i in range(10)) + "\n"
    scores = _score_outline_shape(article, "list-all")
    assert scores["rendered_h2"] == 10
    assert scores["h2_in_bounds"] is False  # 10 < 30


def test_outline_shape_flags_h4_in_flat_archetype():
    """Flat archetypes (list-all / compare) have `seed_max=0` in their
    preset → no H4 leaves expected. Articles with H4 trip the
    `h4_violates_flat_constraint` flag."""
    article = (
        "# T\n\n" + "\n\n".join(f"## {i + 1} Foo" for i in range(30)) + "\n\n#### 1.1.1 Leaf (forbidden for list-all)\n"
    )
    scores = _score_outline_shape(article, "list-all")
    assert scores["rendered_h4plus"] == 1
    assert scores["h4_violates_flat_constraint"] is True


def test_heading_numbering_clean_on_well_formed_article():
    """Post-Wave-0 the `## 4 . 1 . 1` corruption should never appear.
    A clean article reports 0 corrupt lines."""
    article = "# Title\n\n## 1 Section\n### 1.1 Sub\n#### 1.1.1 Leaf\n## 2 Another\n"
    scores = _score_heading_numbering(article)
    assert scores["n_corrupt_heading_numbering"] == 0


def test_heading_numbering_catches_pre_wave_0_corruption():
    """The pre-Wave-0 fragmentation pattern (verified on id=91 morning
    smoke) must register on the corruption detector."""
    article = "# T\n\n## 4 . 1 . 1 Corrupted Sub\nbody\n"
    scores = _score_heading_numbering(article)
    assert scores["n_corrupt_heading_numbering"] >= 1


def test_section_opening_recap_compliance_excludes_first_section():
    """§1 establishes the framework rather than recapping it, so the
    recap rule applies to sections AFTER §1 only."""
    article = (
        "# T\n\n"
        "## 1 Intro\nNo recap needed here.\n\n"
        "## 2 Body\nRecap of framework from §1.\n\n"
        "## 3 More\n| col1 | col2 |\n| --- | --- |\n| a | b |\n"  # table-first violation
    )
    scores = _score_section_opening_recap(article)
    # 3 sections, 2 non-first. §2 has prose recap → compliant; §3 starts
    # with a table → non-compliant.
    assert scores["n_non_first_sections"] == 2
    assert scores["n_with_recap"] == 1
    assert scores["recap_compliance_rate"] == 0.5


def test_section_opening_recap_high_numbered_list_is_not_prose_recap():
    """Greptile PR #30 round-6 follow-up: the ordered-list detection
    was previously a literal prefix tuple `("1.", "2.", "3.")` which
    only caught items 1-3. A section opening with `"4. Fourth item"`
    or any higher-numbered item was falsely counted as prose recap,
    inflating the rate.

    list-all archetype articles can have 30-80 top-level sections,
    each potentially containing independently-numbered sub-lists that
    open at 4+ (e.g. when content from a larger enumeration is
    extracted). Pin: any `^\\d+\\.` numbered-list opener must be
    excluded from prose-recap-compliant counting."""
    article = (
        "# T\n\n"
        "## 1 Intro\nIntro prose.\n\n"
        # §2 opens with item 7 of a numbered list — pre-fix this was
        # FALSELY counted as prose recap.
        "## 2 Section Two\n7. Seventh item from a larger enumeration.\n8. Eighth item.\n\n"
        # §3 opens with item 12 — also pre-fix false-positive.
        "## 3 Section Three\n12. Twelfth item from yet another list.\n\n"
        # §4 has genuine prose recap.
        "## 4 Section Four\nThis section recaps the framework from §1.\n"
    )
    scores = _score_section_opening_recap(article)
    # 3 non-first sections (§2, §3, §4). §2 + §3 are list-first (NOT
    # prose), §4 is prose-recap-compliant. So 1 of 3 compliant.
    assert scores["n_non_first_sections"] == 3
    assert scores["n_with_recap"] == 1, f"high-numbered list items wrongly counted as prose recap: {scores}"


def test_section_opening_recap_subheading_is_not_prose_recap():
    """Greptile PR #30 follow-up: a section whose first non-blank
    content line is a subheading (`### 1.1 Foo` or `#### 1.1.1 Bar`)
    must NOT be counted as prose-recap-compliant. Pre-fix the prefix
    list omitted `#`, inflating the rate and hiding the real failure
    mode (heading-first openings)."""
    article = (
        "# T\n\n"
        "## 1 Intro\n"
        "Some intro text.\n\n"
        "## 2 Body\n"
        "### 2.1 First sub\n"  # subheading-first opening — should NOT count as prose recap
        "Sub body text.\n\n"
        "## 3 More\n"
        "Real prose recap of framework from §1 applied here.\n"
    )
    scores = _score_section_opening_recap(article)
    # 2 non-first sections (§2 + §3). §2 opens with `###` subheading
    # (NOT prose), §3 opens with prose. So only 1 of 2 is compliant.
    assert scores["n_non_first_sections"] == 2
    assert scores["n_with_recap"] == 1
    assert scores["recap_compliance_rate"] == 0.5


def test_split_into_leaves_does_not_absorb_inter_h4_headings_into_preceding_leaf():
    """Greptile PR #30 follow-up: when in a deep-archetype H4 leaf and
    we hit a higher-level heading (`## Section 2` or `### 2.1 Sub`),
    flush + exit leaf mode. Pre-fix every non-H4 line after a leaf was
    appended to that leaf's body until the next H4, leaking sibling-
    section heading text into the leaf and producing false element
    detections."""
    article = (
        "# Title\n\n"
        "## 1 First\n### 1.1 Sub\n"
        "#### 1.1.1 Leaf A\n"
        "Body of leaf A.\n\n"
        # Inter-leaf H2/H3 boundary — must NOT bleed into leaf A's body.
        "## 2 Second\n"
        "Second section frame.\n"
        "### 2.1 Another sub with a By 2030 trend description that mentions forward-looking forecasting\n"
        "#### 2.1.1 Leaf B\n"
        "Body of leaf B.\n"
    )
    leaves = _split_into_leaves(article, "explain-mechanism")
    # 2 H4 leaves.
    assert len(leaves) == 2
    leaf_a = leaves[0]
    leaf_b = leaves[1]
    # Leaf A must NOT contain the heading text from §2 or §2.1.
    assert "Second section frame" not in leaf_a, (
        "leaf A absorbed §2's heading body — flush-on-shallower-heading didn't fire"
    )
    assert "By 2030 trend description" not in leaf_a, (
        "leaf A absorbed §2.1's heading text — would trigger false forward-looking detection"
    )
    # Leaf B should have only its own body (no leakage from prior).
    assert "Body of leaf B" in leaf_b
    assert "Body of leaf A" not in leaf_b


def test_compute_compliance_returns_all_rule_scores():
    """The top-level `compute_compliance` must return every rule's
    score dict so downstream tooling (drift log + JSON output) can
    pick the rules it cares about without falling back to defaults."""
    article = "# T\n\n## 1 S\n\nBody[^S1-1].\n\n[^S1-1]: src\n"
    scores = compute_compliance(article, "explain-mechanism")
    expected_keys = {
        "footnotes",
        "insight_distribution",
        "outline_shape",
        "heading_numbering",
        "section_opening_recap",
    }
    assert set(scores.keys()) == expected_keys
