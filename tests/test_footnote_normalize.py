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


def test_n_inline_markers_includes_orphans_on_success_path():
    """Greptile PR #24 round-2 follow-up: `n_inline_markers` is the RAW
    count of inline markers found in the body, INCLUDING orphans whose
    token had no matching definition. The prior implementation set it to
    `n_renum` only — a downstream consumer computing 'orphan rate' as
    `n_orphans_stripped / n_inline_markers` would then divide by a
    denominator that excluded the orphans themselves, yielding a
    nonsensical ratio > 1. The matched subset stays recoverable as
    `n_inline_markers - n_orphans_stripped`."""
    article = (
        "# T\n\n## 1 X\n\n"
        "Claim A with a real source[^S1-1]. "
        "Claim B with a missing source[^MISSING-1]. "
        "Claim C with another missing source[^GHOST-1]. "
        "Claim D reuses the real source[^S1-1].\n\n"
        "[^S1-1]: Source A — https://a.example.com\n"
    )
    out = footnote_normalize.normalize(article)
    # 4 inline markers in the body: 2 matched (both → [^S1-1]) + 2 orphans.
    assert out.n_inline_markers == 4, out
    assert out.n_orphans_stripped == 2, out
    # Orphan-rate ratio must be sensible.
    assert out.n_orphans_stripped / out.n_inline_markers <= 1.0, out
    # And the matched-subset is recoverable by subtraction.
    assert out.n_inline_markers - out.n_orphans_stripped == 2


def test_n_inline_markers_includes_orphans_in_all_orphan_early_exit_path():
    """Second occurrence of the same bug lived in the all-orphan early
    exit branch (when token_to_n is empty after step 2). To trigger that
    branch we need at least one definition (so we don't take the
    no-definitions early exit at step 1) plus inline markers that all
    fail to match it. Pin the raw count here too."""
    article = (
        "# T\n\n## 1 X\n\n"
        "Claim with missing source[^GHOST-1]. "
        "Another with missing[^GHOST-2]. "
        "Third with missing[^GHOST-3].\n\n"
        # A definition that nothing inline references — forces
        # `token_to_n` to be empty after step 2 (all inlines orphan,
        # this definition is unused) and triggers the early-exit return.
        "[^UNUSED]: Unused source — https://unused.example.com\n"
    )
    out = footnote_normalize.normalize(article)
    assert out.n_unused_dropped == 1, out
    assert out.n_orphans_stripped == 3, out
    # The early-exit branch must also report the raw inline count, not 0.
    assert out.n_inline_markers == 3, out
    assert out.n_renumbered == 0, out


def test_docstring_does_not_overclaim_idempotency():
    """Greptile PR #24 round-2 follow-up: the function is NOT idempotent
    on already-normalized articles — a second pass would re-detect the
    `[^N]: ...` definition lines inside the existing `## References`
    block, strip them, and append a fresh `## References` block, leaving
    the original heading orphaned. Pin the corrected docstring so a
    future cleanup doesn't accidentally re-introduce the misleading
    'Idempotent on already-normalized articles' claim — that claim would
    invite a retry/re-process path that produces a duplicate heading."""
    doc = footnote_normalize.normalize.__doc__ or ""
    assert "NOT idempotent" in doc, "docstring no longer warns that the function is not idempotent"
    # The literal misleading wording must NOT come back.
    assert "Idempotent on already-normalized articles" not in doc, (
        "docstring re-introduced the false idempotency claim Greptile flagged"
    )


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


# ---- Wave 1 §2.1a (2026-05-26): writer-emitted References pre-strip ----


def test_writer_refs_section_with_bare_markers_stripped():
    """Canonical id=91 morning-smoke pattern from gap-map §2.1a: the
    writer invented its own `## 29 References` section in the body with
    bare `[^N]` markers above each `[^N]: source` line. Pre-Wave-1
    behaviour left the orphan heading + bare markers in the body
    alongside the canonical `## References` block — duplicate headings
    + 32 stray markers in the output. The pre-strip pass must remove
    the writer's section entirely while still capturing its defs into
    the canonical block."""
    article = (
        "# Title\n\n## 1 Intro\n\n"
        "The standard reading per Lebrun (1999)[^S1-1] is established.\n\n"
        "## 29 References (Sources for this section)\n\n"
        "[^S1-1]\n"
        "[^S1-1]: Lebrun, B. (1999) — https://example.com/lebrun\n"
    )
    out = footnote_normalize.normalize(article)
    # The orphan heading must be gone.
    assert "## 29 References" not in out.article
    # The bare `[^S1-1]` on its own line (above the def in the writer
    # block) must be gone — it should not appear except as the renumbered
    # `[^1]` inline marker in the prose.
    assert "\n[^S1-1]\n" not in out.article
    # The canonical References block at the end must still be present
    # with the captured definition.
    assert "## References" in out.article
    assert "Lebrun" in out.article
    # Telemetry counter must reflect the strip.
    assert out.n_writer_refs_sections_stripped == 1


def test_writer_refs_section_without_numbering_stripped():
    """The writer may emit `## References` with no leading number (vs
    `## 29 References`). The pre-strip regex must catch both."""
    article = "# Title\n\n## 1 Intro\n\nClaim per Source A[^S1-1].\n\n## References\n\n[^S1-1]: Source A\n"
    out = footnote_normalize.normalize(article)
    assert out.n_writer_refs_sections_stripped == 1
    # Output has exactly ONE `## References` heading (the canonical one
    # we append in Step 4) — not two.
    assert out.article.count("## References") == 1


def test_no_writer_refs_section_telemetry_zero():
    """When the writer does NOT emit its own References block, the
    telemetry counter stays at 0 and normalize behaviour is unchanged
    vs the pre-Wave-1 contract."""
    article = "# Title\n\n## 1 Intro\n\nClaim per Source A[^S1-1].\n\n[^S1-1]: Source A — https://example.com\n"
    out = footnote_normalize.normalize(article)
    assert out.n_writer_refs_sections_stripped == 0
    # Renumber + def-strip still works as before.
    assert out.n_renumbered == 1
    assert "[^1]" in out.article


def test_writer_refs_section_does_not_swallow_following_section():
    """The pre-strip regex must stop at the next markdown heading so it
    doesn't accidentally swallow a following body section that happens
    to come after the writer's References block."""
    article = (
        "# Title\n\n## 1 Intro\n\n"
        "Claim per Source A[^S1-1].\n\n"
        "## 5 References (Sources)\n\n"
        "[^S1-1]: Source A\n\n"
        "## 6 Following Section\n\n"
        "Important content that must survive the pre-strip pass.\n"
    )
    out = footnote_normalize.normalize(article)
    assert out.n_writer_refs_sections_stripped == 1
    # The following section's heading + content must still be in the body.
    assert "## 6 Following Section" in out.article
    assert "Important content that must survive" in out.article


def test_writer_refs_section_stops_at_h3_following_heading():
    """Greptile PR #29 follow-up: the pre-Wave-1 regex used `#{1,2}` in
    the lookahead, which only stopped at H1/H2 headings. An H3+ heading
    directly after the writer's bogus References block — with no H2 in
    between — would have been silently swallowed, deleting the H3
    section's heading + body. The fix widens the lookahead to `#+` so
    any heading depth terminates the strip.

    This is a content-destructive edge case (rare because the writer
    conventionally uses ## for top-level sections, but unbounded in
    severity when it happens). Pin so a future regex tightening that
    re-introduces `#{1,2}` is caught immediately."""
    article = (
        "# Title\n\n## 1 Intro\n\n"
        "Claim per Source A[^S1-1].\n\n"
        "## 5 References\n\n"
        "[^S1-1]: Source A\n\n"
        "### 6.1 Important Subsection\n\n"
        "H3 content that must survive the writer-refs strip.\n\n"
        "#### 6.1.1 Deeper Leaf\n\n"
        "H4 content that must also survive.\n"
    )
    out = footnote_normalize.normalize(article)
    assert out.n_writer_refs_sections_stripped == 1
    # H3 heading + body survives (would have been destroyed pre-fix).
    assert "### 6.1 Important Subsection" in out.article
    assert "H3 content that must survive" in out.article
    # H4 (the heading even deeper) also survives — the regex terminates
    # at the first `#+` heading regardless of depth.
    assert "#### 6.1.1 Deeper Leaf" in out.article
    assert "H4 content that must also survive" in out.article


# --- P3b-D2: source-based dedup (number by SOURCE, not token) ---------------


def test_dedup_same_url_across_sections_gets_one_number():
    """The same source cited from two sections (different per-section tokens,
    SAME url) collapses to ONE `[^1]`, cited twice."""
    article = (
        "# T\n\n## 1 A\n\nClaim one[^S1-1].\n\n[^S1-1]: Fandom — https://x.example/wiki/cloths\n\n"
        "## 2 B\n\nClaim two[^S2-3].\n\n[^S2-3]: Fandom — https://x.example/wiki/cloths\n"
    )
    out = footnote_normalize.normalize(article)
    assert out.n_definitions == 2  # two def lines seen
    assert out.n_renumbered == 1  # ONE distinct source → one References entry
    assert out.n_sources_merged == 1  # two used tokens collapsed to one source
    assert out.article.count("[^1]:") == 1  # single References entry
    assert out.article.count("[^1]") == 3  # 2 inline + 1 def line
    assert "[^2]" not in out.article


def test_dedup_no_url_same_source_name():
    """No-URL defs with the same normalized source-name dedup too."""
    article = (
        "# T\n\n## 1 A\n\nx[^S1-1].\n\n[^S1-1]: Lebrun (1999)\n\n"
        "## 2 B\n\ny[^S2-1].\n\n[^S2-1]: Lebrun (1999)\n"
    )
    out = footnote_normalize.normalize(article)
    assert out.n_renumbered == 1
    assert out.n_sources_merged == 1


def test_dedup_distinct_urls_stay_separate():
    """Different paths on the same host are different sources (path preserved
    by _normalize_url) → NOT merged."""
    article = (
        "# T\n\n## 1 A\n\nx[^S1-1] y[^S1-2].\n\n"
        "[^S1-1]: Src — https://x.example/wiki/aries\n"
        "[^S1-2]: Src — https://x.example/wiki/taurus\n"
    )
    out = footnote_normalize.normalize(article)
    assert out.n_renumbered == 2
    assert out.n_sources_merged == 0


def test_dedup_preserves_first_appearance_order():
    """Numbering follows first inline appearance of each SOURCE."""
    article = (
        "# T\n\n## 1 A\n\nbeta[^S1-9] alpha[^S1-1].\n\n"
        "[^S1-9]: B — https://x.example/b\n[^S1-1]: A — https://x.example/a\n"
    )
    out = footnote_normalize.normalize(article)
    # B is cited first → [^1]; A second → [^2]
    assert "[^1]: B" in out.article
    assert "[^2]: A" in out.article
