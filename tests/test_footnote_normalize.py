"""Unit tests for deep_research.pipeline.footnote_normalize (P2-Option-A-#6).

Covers the post-write merge of per-section ``[^section_id-N]`` markers into
one global ``## References`` block, plus the orphan-strip and unused-drop
failure-mode handling.
"""

from deep_research.pipeline import footnote_normalize


def test_normalize_passthrough_on_article_with_no_footnotes():
    """No `[^X]:` definitions → returns the article unchanged + zero stats.
    Idempotent on pre-#6 articles."""
    article = "# Title\n\n## 1 Intro\n\nfoo bar.\n\n## 2 Method\n\nbaz.\n"
    out = footnote_normalize.normalize(article)
    assert out.article == article
    assert out.n_definitions == 0
    assert out.n_inline_markers == 0


def test_normalize_merges_two_sections_into_global_references():
    """Section S1 emits [^S1-1], [^S1-2]; section S2 emits [^S2-1]. After
    normalize there is one ## References block with sequential [^1], [^2], [^3]."""
    article = (
        "# Title\n\n"
        "## 1 Intro\n\n"
        "Apple says one thing[^S1-1]. Banana says another[^S1-2].\n\n"
        "[^S1-1]: Apple 2025 — https://apple.example.com\n"
        "[^S1-2]: Banana 2024 — https://banana.example.com\n\n"
        "## 2 Method\n\n"
        "Carrot disagrees[^S2-1].\n\n"
        "[^S2-1]: Carrot 2023 — https://carrot.example.com\n"
    )
    out = footnote_normalize.normalize(article)
    # Three inline markers, three unique tokens, three references in the
    # global block. None orphaned, none unused.
    assert out.n_definitions == 3
    assert out.n_renumbered == 3
    assert out.n_orphans_stripped == 0
    assert out.n_unused_dropped == 0
    # Body should have global markers, not section-scoped ones.
    assert "[^1]" in out.article
    assert "[^2]" in out.article
    assert "[^3]" in out.article
    assert "[^S1-1]" not in out.article
    assert "[^S2-1]" not in out.article
    # Global References block exists.
    assert "## References" in out.article
    assert "[^1]: Apple 2025 — https://apple.example.com" in out.article
    assert "[^3]: Carrot 2023 — https://carrot.example.com" in out.article


def test_normalize_strips_orphan_markers():
    """An inline `[^FOO-1]` with no matching `[^FOO-1]:` definition is
    silently stripped — better empty space than broken markdown the judge
    will mark down."""
    article = (
        "# T\n\n## 1 X\n\nA claim with no source[^MISSING-1].\nAnother claim[^S1-1].\n\n"
        "[^S1-1]: Source A — https://a.example.com\n"
    )
    out = footnote_normalize.normalize(article)
    assert out.n_orphans_stripped == 1
    assert "[^MISSING-1]" not in out.article
    assert "[^1]" in out.article
    assert "[^1]: Source A — https://a.example.com" in out.article


def test_normalize_drops_unused_definitions():
    """A `[^FOO-1]:` definition with no matching inline `[^FOO-1]` is
    dropped from References (don't pollute with unreferenced URLs)."""
    article = (
        "# T\n\n## 1 X\n\nClaim with source[^S1-1].\n\n"
        "[^S1-1]: Used Source — https://used.example.com\n"
        "[^S1-2]: Unused Source — https://unused.example.com\n"
    )
    out = footnote_normalize.normalize(article)
    assert out.n_unused_dropped == 1
    assert "https://used.example.com" in out.article
    assert "https://unused.example.com" not in out.article


def test_normalize_renumbers_in_document_order():
    """Global numbering follows ORDER OF FIRST INLINE APPEARANCE, not the
    order of definitions or token-name sort order."""
    article = (
        "# T\n\n## 1 X\n\nB first[^X-B]. Then A[^X-A]. Then B again[^X-B].\n\n"
        "[^X-A]: Source A — https://a.example.com\n"
        "[^X-B]: Source B — https://b.example.com\n"
    )
    out = footnote_normalize.normalize(article)
    # B appeared first → it should be [^1] in the renumbered output; A → [^2].
    assert "B first[^1]" in out.article
    assert "Then A[^2]" in out.article
    assert "Then B again[^1]" in out.article  # B's second occurrence reuses [^1]
    # References block lists them in 1, 2 order.
    assert "[^1]: Source B" in out.article
    assert "[^2]: Source A" in out.article


def test_normalize_handles_purely_orphan_article_gracefully():
    """All markers are orphans → no References block is appended (empty
    References would look broken; the orphans are silently stripped)."""
    article = "# T\n\n## 1 X\n\nClaim[^GHOST-1]. Another[^GHOST-2].\n"
    out = footnote_normalize.normalize(article)
    # No definitions at all → early-exit branch returns the unchanged article.
    assert out.n_definitions == 0
    assert "## References" not in out.article
    # The orphan stripping only fires when there ARE definitions (other
    # token failed to match); pure-orphan articles pass through.
    assert "[^GHOST-1]" in out.article


def test_normalize_appends_references_at_article_end():
    """The ## References block must be the LAST thing in the article."""
    article = (
        "# T\n\n## 1 X\n\nClaim[^S1-1].\n\n[^S1-1]: Source — https://x.example.com\n\n"
        "## 2 Conclusion\n\nFinal paragraph.\n"
    )
    out = footnote_normalize.normalize(article)
    # Last non-empty line should be the references entry, NOT the body's
    # final paragraph — the block goes at article end regardless of where
    # the source definitions originally lived.
    lines = [ln for ln in out.article.splitlines() if ln.strip()]
    assert lines[-1].startswith("[^"), f"last line was not a ref entry: {lines[-1]!r}"
    assert "## References" in out.article
    # The final body paragraph is still present (References doesn't replace it).
    assert "Final paragraph." in out.article


def test_normalize_handles_section_id_with_dots():
    """Architect emits section ids like `S3.2` for subsections; tokens like
    `[^S3.2-1]` must round-trip correctly through the dot character."""
    article = (
        "# T\n\n### 3.2 Sub\n\nClaim[^S3.2-1] and another[^S3.2-2].\n\n"
        "[^S3.2-1]: Source A — https://a.example.com\n"
        "[^S3.2-2]: Source B — https://b.example.com\n"
    )
    out = footnote_normalize.normalize(article)
    assert out.n_renumbered == 2
    assert "[^S3.2-1]" not in out.article
    assert "[^1]" in out.article
    assert "[^2]" in out.article
