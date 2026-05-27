"""Unit tests for P3-W2 — `_validate_framing_chapter` reuse compliance scorer.

The validator measures how DOWNSTREAM chapters (§2+) re-engage with the
framing chapter's published_vocabulary + published_rubric_items. This is
the reference's verified corpus-wide pattern: vocabulary terms reused ~2-5×
across the article; rubric items cited 1+ times from each evaluation chapter.

Tests pin: None for missing/empty framing; vocabulary reuse counts
(case-insensitive EN, verbatim ZH); rubric reference counts; reuse rate
computation; §1 region exclusion (avoid attributing in-§1 mentions as
"downstream reuse"); long-article proportional skip (Greptile PR #38
round-1); end-to-end wiring from `validation.run()` (Greptile PR #38
round-1).
"""

from deep_research.pipeline.validation import _validate_framing_chapter


def test_validate_returns_none_for_missing_framing():
    """No framing chapter → no check applies."""
    assert _validate_framing_chapter("body", None) is None
    assert _validate_framing_chapter("body", {}) is None


def test_validate_returns_none_for_empty_vocab_and_rubric():
    """Framing chapter with empty vocabulary AND empty rubric: nothing
    to measure."""
    fc = {"published_vocabulary": [], "published_rubric_items": []}
    assert _validate_framing_chapter("body", fc) is None


def test_validate_counts_vocab_reuse_in_body():
    """Each vocabulary term: count occurrences after the §1 region
    (first `max(8000, 0.09 × len(article))` chars). Body text repeats
    some terms; reuse rate = fraction with ≥1 body reuse."""
    fc = {
        "published_vocabulary": ["axiom1", "axiom2", "axiom3"],
        "published_rubric_items": [],
    }
    # Article must exceed the 8k skip-chars floor for the validator to
    # have a meaningful body region. At ~10k chars, skip_chars =
    # max(8000, 0.09×10000) = 8000, so body = article[8000:] (~2k chars).
    article = "x" * 10000 + " ... axiom1 ... and axiom1 again ... but axiom2 only once. and axiom3 once too."
    out = _validate_framing_chapter(article, fc)
    assert out is not None
    # axiom1 appears 2× in body; axiom2 1×; axiom3 1×. All ≥1 → reuse_rate = 1.0
    assert out["vocabulary_terms_reused"]["axiom1"] == 2
    assert out["vocabulary_terms_reused"]["axiom2"] == 1
    assert out["vocabulary_terms_reused"]["axiom3"] == 1
    assert out["vocabulary_reuse_rate"] == 1.0


def test_validate_flags_missing_vocab_reuse():
    """A term not present in the body counts 0; reuse rate < 1.0."""
    fc = {
        "published_vocabulary": ["axiom1", "axiom2"],
        "published_rubric_items": [],
    }
    article = "x" * 10000 + " ... axiom1 only ... no second one anywhere."
    out = _validate_framing_chapter(article, fc)
    assert out["vocabulary_terms_reused"]["axiom1"] == 1
    assert out["vocabulary_terms_reused"]["axiom2"] == 0
    assert out["vocabulary_reuse_rate"] == 0.5


def test_validate_excludes_s1_region():
    """The first `max(8000, 0.09 × len(article))` chars are excluded as
    §1. A vocab term mentioned ONLY in §1 should not count as downstream
    reuse."""
    fc = {
        "published_vocabulary": ["axiom1"],
        "published_rubric_items": [],
    }
    # axiom1 is in the first 100 chars (§1 region); body region (chars
    # 10000+) has no mention.
    article = ("axiom1 introduced here. " + "filler ") * 50 + "x" * 20000
    out = _validate_framing_chapter(article, fc)
    # axiom1 in §1 only; body region has 0 → reuse rate = 0
    assert out["vocabulary_terms_reused"]["axiom1"] == 0


def test_validate_counts_rubric_references():
    """Rubric items are cited by id (e.g. "Per R-1, ...")."""
    fc = {
        "published_vocabulary": [],
        "published_rubric_items": [
            {"id": "R-1", "label": "Quality", "weight": 0.5},
            {"id": "R-2", "label": "Speed", "weight": 0.5},
        ],
    }
    article = "x" * 10000 + " ... Per R-1 (Quality), this entity scores high. R-2 evaluation: low."
    out = _validate_framing_chapter(article, fc)
    assert out["rubric_items_referenced"]["R-1"] == 1
    assert out["rubric_items_referenced"]["R-2"] == 1
    assert out["rubric_reference_rate"] == 1.0


def test_validate_handles_cjk_vocabulary_verbatim():
    """ZH vocabulary terms: case is meaningless; count verbatim."""
    fc = {
        "published_vocabulary": ["新质生产力", "五篇大文章"],
        "published_rubric_items": [],
    }
    article = "x" * 10000 + " ... 新质生产力发展. 五篇大文章是核心. 新质生产力再次."
    out = _validate_framing_chapter(article, fc)
    assert out["vocabulary_terms_reused"]["新质生产力"] == 2
    assert out["vocabulary_terms_reused"]["五篇大文章"] == 1


def test_validate_en_vocab_case_insensitive():
    """EN vocabulary: case-insensitive count (writers may de-capitalize
    mid-sentence)."""
    fc = {
        "published_vocabulary": ["Anthropic"],
        "published_rubric_items": [],
    }
    article = "x" * 10000 + " ... Anthropic released Claude. anthropic also leads in safety. ANTHROPIC summary."
    out = _validate_framing_chapter(article, fc)
    assert out["vocabulary_terms_reused"]["Anthropic"] == 3


def test_validate_skips_malformed_rubric_items():
    """Rubric items without an id are skipped (defensive against
    incomplete LLM output)."""
    fc = {
        "published_vocabulary": [],
        "published_rubric_items": [
            {"label": "no id"},
            {"id": "R-1", "label": "valid"},
            "not a dict",
        ],
    }
    article = "x" * 10000 + " ... R-1 reference."
    out = _validate_framing_chapter(article, fc)
    assert out is not None
    assert "R-1" in out["rubric_items_referenced"]
    assert out["rubric_reference_rate"] == 1.0  # only R-1 counted


def test_validate_empty_string_article_handles_gracefully():
    """No crash on empty article."""
    fc = {"published_vocabulary": ["term1"], "published_rubric_items": []}
    out = _validate_framing_chapter("", fc)
    assert out is not None
    assert out["vocabulary_terms_reused"]["term1"] == 0
    assert out["vocabulary_reuse_rate"] == 0.0


def test_validate_returns_dict_keys_pinned():
    """Pin the result dict keys — drift would break downstream
    compliance scorer consumers."""
    fc = {"published_vocabulary": ["t"], "published_rubric_items": [{"id": "R-1", "label": "L"}]}
    article = "x" * 10000 + " ... t and R-1."
    out = _validate_framing_chapter(article, fc)
    expected_keys = {
        "vocabulary_terms_reused",
        "vocabulary_reuse_rate",
        "rubric_items_referenced",
        "rubric_reference_rate",
    }
    assert set(out.keys()) == expected_keys, f"got {set(out.keys())}"


def test_validate_skip_scales_to_long_articles():
    """Greptile PR #38 round-1 (skip heuristic): on LONG articles the
    skip must scale to 9% of article length (the reference §1 upper bound),
    not cap at 8k. A vocab term mentioned ONLY inside §1 (e.g. chars
    0-44k of a 500k article) must NOT be counted as downstream reuse —
    the prior `min(8000, len//7)` bound capped the skip at 8k for long
    articles, leaking in-§1 mentions into the downstream count."""
    fc = {"published_vocabulary": ["axiom1"], "published_rubric_items": []}
    # 9% of 500k = 45k. Place axiom1 only at chars 20k-30k (well past
    # the old 8k cap, but well inside the new 45k proportional skip).
    s1 = ("x" * 20000) + (" axiom1" * 1000) + ("x" * 10000)
    downstream = "filler content " * 30000  # ~450k chars
    article = s1 + downstream
    assert len(article) > 400_000, f"sanity: article should be long, got {len(article)}"
    out = _validate_framing_chapter(article, fc)
    assert out is not None
    # axiom1 was only in §1 — downstream count must be 0. Pre-fix this
    # would have returned ≥1000 because the skip capped at 8k and the
    # axiom1 mentions at chars 20k+ would all have leaked into "body".
    assert out["vocabulary_terms_reused"]["axiom1"] == 0, (
        f"long-article skip did not exclude §1 mentions; got {out['vocabulary_terms_reused']}"
    )


def test_validate_short_article_skips_safely():
    """Greptile PR #38 round-1 (skip heuristic): the proportional skip
    is clamped to len(article), so a stub article shorter than the 8k
    floor yields an empty body (zero reuse counts), not an index error
    or partial-skip leak."""
    fc = {"published_vocabulary": ["axiom1"], "published_rubric_items": []}
    article = "axiom1 appears here in a short stub."  # ~36 chars
    out = _validate_framing_chapter(article, fc)
    assert out is not None
    # Body is empty (skip == len(article)); count must be 0.
    assert out["vocabulary_terms_reused"]["axiom1"] == 0
    assert out["vocabulary_reuse_rate"] == 0.0


def test_run_populates_framing_chapter_reuse_in_counts():
    """Greptile PR #38 round-1 (dead-code wiring): `validation.run()`
    must call `_validate_framing_chapter` and surface its output under
    `counts["framing_chapter_reuse"]`. Without this wiring, the 35-test
    isolated suite passes but the metric is a no-op in production —
    drift telemetry never sees a reuse number."""
    from deep_research.pipeline.validation import ValidationInput, run
    from deep_research.state import DesignGuide, Scaffold

    article = "x" * 10000 + " ... axiom1 here. R-1 referenced too. axiom1 again."
    plan = {
        "framing_chapter": {
            "published_vocabulary": ["axiom1"],
            "published_rubric_items": [{"id": "R-1", "label": "x"}],
        }
    }
    inp = ValidationInput(
        article=article,
        plan=plan,
        scaffold=Scaffold(sections=[]),
        design_guide=DesignGuide(),
        language="en",
        domain="default",
    )
    vout = run(inp)
    assert "framing_chapter_reuse" in vout.counts, (
        f"_validate_framing_chapter not wired into run(); got counts keys: {list(vout.counts.keys())}"
    )
    fc_reuse = vout.counts["framing_chapter_reuse"]
    for k in ("vocabulary_terms_reused", "vocabulary_reuse_rate", "rubric_items_referenced", "rubric_reference_rate"):
        assert k in fc_reuse, f"missing key `{k}` in framing_chapter_reuse: {fc_reuse}"
    # Spot-check that the wired call actually saw the article body and
    # counted reuse (axiom1 appears twice past the 8k skip).
    assert fc_reuse["vocabulary_terms_reused"]["axiom1"] >= 1, (
        f"wired call did not see downstream axiom1; got {fc_reuse}"
    )


def test_run_omits_framing_chapter_reuse_when_no_framing():
    """Greptile PR #38 round-1: when the plan has no `framing_chapter`,
    `counts["framing_chapter_reuse"]` must be ABSENT (not `None`, not
    `{}`) so drift-telemetry consumers can distinguish 'no framing
    chapter on this plan' from 'framing chapter present, zero reuse'."""
    from deep_research.pipeline.validation import ValidationInput, run
    from deep_research.state import DesignGuide, Scaffold

    inp = ValidationInput(
        article="x" * 10000,
        plan={},  # no framing_chapter
        scaffold=Scaffold(sections=[]),
        design_guide=DesignGuide(),
        language="en",
        domain="default",
    )
    vout = run(inp)
    assert "framing_chapter_reuse" not in vout.counts, (
        f"framing_chapter_reuse must be absent when plan has no framing_chapter; "
        f"got: {vout.counts.get('framing_chapter_reuse')!r}"
    )
