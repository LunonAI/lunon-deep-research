"""PR-B-safe: `_section_length_ok` must count a parent chapter's whole subtree.

Validation runs BEFORE the final numbering_fix flatten, so it sees the nested
H2/H3 shape. The prior implementation measured a section's body only up to the
next heading of ANY level, so a parent `##` with `###`/`####` children was
measured as just the intro before its first child → false "short" → a wasteful
corrective refiner pass on an article that was actually complete.
"""

from deep_research.pipeline.validation import _section_length_ok

_TOK = 4  # mirror validation._TOK (chars-per-token)


def _body_of(words: int) -> str:
    return ("word " * words).strip()


def test_nested_parent_counts_children_in_its_body():
    """A `##` parent with a thin intro but large `###` children is NOT short —
    the children belong to the parent's subtree."""
    intro = _body_of(20)  # thin intro
    child = _body_of(800)  # substantial child content
    text = f"# Title\n\n## 1 Gold Saints\n\n{intro}\n\n### 1.1 Aries\n\n{child}\n\n### 1.2 Taurus\n\n{child}\n"
    # expected ~ a few hundred tokens; intro alone (~20 words) would fail, the
    # subtree (1600+ words) passes.
    ok, body_tok = _section_length_ok(text, "Gold Saints", expected_tok=400)
    assert ok is True
    assert body_tok > 400


def test_body_ends_at_next_same_level_heading():
    """A `##` section's body stops at the next `##` (sibling), not at a `###`
    inside it, and does not bleed into the following `##`."""
    body = _body_of(300)
    nextbody = _body_of(900)
    text = f"# T\n\n## 1 Alpha\n\n{body}\n\n### 1.1 Sub\n\nsub.\n\n## 2 Beta\n\n{nextbody}\n"
    _, alpha_tok = _section_length_ok(text, "Alpha", expected_tok=1)
    _, beta_tok = _section_length_ok(text, "Beta", expected_tok=1)
    # Alpha must not absorb Beta's 900 words.
    assert alpha_tok < beta_tok


def test_genuinely_short_leaf_still_flagged():
    """The fix must not mask real shorts: a leaf with too little body fails."""
    text = "# T\n\n## 1 Alpha\n\ntiny.\n\n## 2 Beta\n\nbody\n"
    ok, _ = _section_length_ok(text, "Alpha", expected_tok=1000)
    assert ok is False


def test_shallower_heading_also_terminates_body():
    """A `###` child's body ends at the next `##` (shallower) too, not only at
    a same-level `###`."""
    body = _body_of(50)
    text = f"# T\n\n## 1 A\n\nintro\n\n### 1.1 Child\n\n{body}\n\n## 2 B\n\nother\n"
    _, tok = _section_length_ok(text, "Child", expected_tok=1)
    # ~50 words ≈ 250 chars / 4 ≈ 62 tokens; must not include "## 2 B"'s body.
    assert 0 < tok < 120
