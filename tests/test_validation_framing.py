"""Unit tests for P3-W2 — `_validate_framing_chapter` reuse compliance scorer.

The validator measures how DOWNSTREAM chapters (§2+) re-engage with the
framing chapter's published_vocabulary + published_rubric_items. This is
Qianfan's verified corpus-wide pattern: vocabulary terms reused ~2-5×
across the article; rubric items cited 1+ times from each evaluation chapter.

Tests pin: None for missing/empty framing; vocabulary reuse counts
(case-insensitive EN, verbatim ZH); rubric reference counts; reuse rate
computation; §1 region exclusion (avoid attributing in-§1 mentions as
"downstream reuse").
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
    """Each vocabulary term: count occurrences after the §1 region (first
    ~8000 chars). Body text repeats some terms; reuse rate = fraction
    with ≥1 body reuse."""
    fc = {
        "published_vocabulary": ["axiom1", "axiom2", "axiom3"],
        "published_rubric_items": [],
    }
    # Article must exceed the skip-chars threshold for the validator to
    # have a meaningful body region. Padding ensures skip_chars=min(8000, len/7).
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
    """The first 8000 chars (or article-length/7) are excluded as §1.
    A vocab term mentioned ONLY in §1 should not count as downstream reuse."""
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
