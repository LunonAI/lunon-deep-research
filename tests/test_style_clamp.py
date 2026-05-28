"""PR-C2: deterministic citation + em-dash density clamps (style_clamp).

Safety contract verified here: the citation clamp NEVER leaves a sentence
that had a marker with zero (no un-cited claims), never touches protected
spans (headings / tables / code fences / definition lines / the References
block), and pairs cleanly with footnote_normalize (removed markers leave
defs that footnote_normalize auto-drops). Em-dash uses the paired-
parenthetical transform only and is a no-op when already in band.
"""

from deep_research.pipeline import footnote_normalize, style_clamp

# --- citation clamp: PASS 1 salad collapse ---------------------------------


def test_salad_run_collapses_to_first_marker():
    art = "# T\n\n## 1 A\n\nThe cloth absorbs energy[^S1-1][^S1-2][^S1-3] in canon.\n"
    out, st = style_clamp.clamp_citations(art, language="en", max_per_1k=50.0)
    assert st["salad_collapsed"] == 2
    assert "[^S1-1]" in out
    assert "[^S1-2]" not in out and "[^S1-3]" not in out
    # high ceiling → PASS 2 does nothing beyond the salad collapse
    assert st["markers_after"] == 1


def test_salad_collapses_even_when_already_in_band():
    """PASS 1 is grammatically free and always runs."""
    art = "# T\n\n## 1 A\n\nClaim[^S1-1][^S1-2] here.\n"
    out, st = style_clamp.clamp_citations(art, language="en", max_per_1k=1000.0)
    assert st["salad_collapsed"] == 1
    assert out.count("[^S1-1]") == 1


# --- citation clamp: PASS 2 ceiling walk -----------------------------------


def test_over_ceiling_drops_to_band_keeping_one_per_sentence():
    # 4 sentences, each with 2 distinct (non-adjacent) markers → 8 markers.
    sents = []
    for i in range(1, 5):
        sents.append(f"Alpha fact {i} holds[^S1-{i}a] and beta result {i} follows[^S1-{i}b] clearly.")
    body = " ".join(sents)
    art = f"# T\n\n## 1 A\n\n{body}\n"
    # words ~ 40 → at 50/1k target ~2; force a hard cut.
    out, st = style_clamp.clamp_citations(art, language="en", max_per_1k=120.0)
    # every sentence must still carry at least its first marker
    for i in range(1, 5):
        assert f"[^S1-{i}a]" in out, f"sentence {i} lost its first marker"
    assert st["markers_after"] <= st["markers_before"]


def test_floor_exceeded_never_uncites_a_claim():
    """One marker per sentence, many sentences, tiny ceiling → the clamp
    cannot reach the band without un-citing; it must STOP and flag it."""
    sents = [f"Discrete claim number {i} is supported[^S1-{i}]." for i in range(1, 11)]
    art = "# T\n\n## 1 A\n\n" + " ".join(sents) + "\n"
    out, st = style_clamp.clamp_citations(art, language="en", max_per_1k=1.0)
    assert st["floor_exceeded"] is True
    # all 10 sentences keep their only marker
    for i in range(1, 11):
        assert f"[^S1-{i}]" in out
    assert st["markers_after"] == 10


# --- citation clamp: protected spans ---------------------------------------


def test_marker_in_heading_untouched():
    art = "# T\n\n## 1 Section[^S1-1]\n\nBody claim[^S1-2] one. Body claim[^S1-3] two.\n"
    out, _ = style_clamp.clamp_citations(art, language="en", max_per_1k=1.0)
    assert "## 1 Section[^S1-1]" in out  # heading marker never removed


def test_marker_in_table_untouched():
    art = "# T\n\n## 1 A\n\n| Col[^S1-1] | B |\n| --- | --- |\n| x | y |\n\nProse claim[^S1-2] a. Prose claim[^S1-3] b.\n"
    out, _ = style_clamp.clamp_citations(art, language="en", max_per_1k=1.0)
    assert "| Col[^S1-1] |" in out


def test_marker_in_code_fence_untouched():
    art = "# T\n\n## 1 A\n\n```\ncode[^S1-1] line\n```\n\nProse[^S1-2] one. Prose[^S1-3] two.\n"
    out, _ = style_clamp.clamp_citations(art, language="en", max_per_1k=1.0)
    assert "code[^S1-1] line" in out


def test_definition_line_never_counted_or_removed():
    art = "# T\n\n## 1 A\n\nClaim[^S1-1] holds.\n\n[^S1-1]: Source, 2024.\n"
    out, st = style_clamp.clamp_citations(art, language="en", max_per_1k=1.0)
    # the def line survives untouched; only 1 inline marker counted
    assert "[^S1-1]: Source, 2024." in out
    assert st["markers_before"] == 1


def test_references_block_untouched():
    art = "# T\n\n## 1 A\n\nClaim[^S1-1] x. Claim[^S1-2] y. Claim[^S1-3] z.\n\n## References\n\n[^1]: A\n[^2]: B\n"
    out, _ = style_clamp.clamp_citations(art, language="en", max_per_1k=1.0)
    assert "## References\n\n[^1]: A\n[^2]: B" in out


# --- citation clamp: no-ops / idempotence ----------------------------------


def test_zero_markers_is_noop():
    art = "# T\n\n## 1 A\n\nNo citations at all here.\n"
    out, st = style_clamp.clamp_citations(art, language="en")
    assert out == art
    assert st["markers_before"] == 0 and st["removed"] == 0


def test_clamp_citations_idempotent():
    sents = [f"Claim {i} a[^S1-{i}a] and b[^S1-{i}b]." for i in range(1, 6)]
    art = "# T\n\n## 1 A\n\n" + " ".join(sents) + "\n"
    once, _ = style_clamp.clamp_citations(art, language="en", max_per_1k=50.0)
    twice, st2 = style_clamp.clamp_citations(once, language="en", max_per_1k=50.0)
    assert once == twice
    assert st2["salad_collapsed"] == 0  # nothing left to collapse


# --- citation clamp × footnote_normalize integration -----------------------


def test_clamp_then_footnote_normalize_no_orphans():
    """The designed healthy path: clamp removes inline markers BEFORE
    footnote_normalize, which then auto-drops the now-unused defs — no
    orphan markers, no dangling defs."""
    art = (
        "# T\n\n## 1 A\n\n"
        "Energy claim[^S1-1][^S1-2][^S1-3] holds. Speed claim[^S1-4] follows.\n\n"
        "[^S1-1]: Src1\n[^S1-2]: Src2\n[^S1-3]: Src3\n[^S1-4]: Src4\n"
    )
    clamped, cst = style_clamp.clamp_citations(art, language="en", max_per_1k=50.0)
    assert cst["salad_collapsed"] == 2  # [^S1-2],[^S1-3] collapsed
    fn = footnote_normalize.normalize(clamped)
    # 4 defs existed; 2 markers were removed → those 2 defs are unused-dropped.
    assert fn.n_orphans_stripped == 0  # clamp never leaves a marker without a def
    assert fn.n_unused_dropped == 2
    assert "## References" in fn.article
    # surviving markers renumber cleanly
    assert "[^1]" in fn.article and "[^2]" in fn.article


# --- Greptile #57 fixes ----------------------------------------------------


def test_code_fence_indentation_preserved_during_cleanup():
    """Issue 1: the post-removal cleanup must NOT collapse indentation inside
    a protected code/mermaid fence, even when PASS 1 collapses a salad run in
    adjacent prose (which is what triggers the cleanup)."""
    art = (
        "# T\n\n## 1 A\n\n"
        "Prose claim[^S1-1][^S1-2] with a salad run here.\n\n"
        "```mermaid\ngraph TD\n    A --> B\n        C --> D\n```\n"
    )
    out, st = style_clamp.clamp_citations(art, language="en", max_per_1k=1000.0)
    assert st["salad_collapsed"] == 1  # cleanup DID run
    assert "    A --> B\n        C --> D" in out  # 4- and 8-space indents intact


def test_sentence_end_positions_skips_abbreviations():
    """Issue 2: abbreviation dots ('Fig.', 'Dr.', 'e.g.') are not counted as
    sentence boundaries (so PASS 2 doesn't over-protect the next marker)."""
    from deep_research.pipeline.style_clamp import _sentence_end_positions

    text = "See Fig. 3 and Dr. Smith e.g. here. Real end."
    # only "here." and "end." are real boundaries
    assert len(_sentence_end_positions(text)) == 2


def test_target_rounds_so_single_marker_short_body_is_in_band():
    """Issue 3: round()+floor-1 — a short body whose single marker is within
    the rounded band must NOT trip floor_exceeded (int() truncation set the
    target to 0 and tripped it spuriously)."""
    art = "# T\n\n## 1 A\n\nShort claim here[^S1-1] indeed today.\n"
    out, st = style_clamp.clamp_citations(art, language="en", max_per_1k=7.0)
    assert st["markers_after"] == 1
    assert st["floor_exceeded"] is False


# --- em-dash clamp ---------------------------------------------------------


def test_emdash_paired_parenthetical_to_commas():
    art = "# T\n\n## 1 A\n\nThe cloth — a Pegasus-class relic — absorbs energy and more.\n"
    out, st = style_clamp.clamp_emdash(art, language="en", max_per_1k=0.0)  # force conversion
    assert "The cloth, a Pegasus-class relic, absorbs energy" in out
    assert st["pairs_converted"] == 1
    assert st["emdash_after"] == 0


def test_emdash_en_dash_range_untouched():
    art = "# T\n\n## 1 A\n\nThe 2014–2018 canon era — a key window — matters here.\n"
    out, _ = style_clamp.clamp_emdash(art, language="en", max_per_1k=0.0)
    assert "2014–2018" in out  # en-dash range preserved


def test_emdash_already_in_band_is_noop():
    art = "# T\n\n## 1 A\n\nThe cloth — a relic — absorbs energy.\n"
    out, st = style_clamp.clamp_emdash(art, language="en", max_per_1k=1000.0)
    assert out == art
    assert st["pairs_converted"] == 0


def test_emdash_in_definition_line_untouched():
    art = "# T\n\n## 1 A\n\nClaim here is plain.\n\n[^S1-1]: Source — https://x.example\n"
    out, st = style_clamp.clamp_emdash(art, language="en", max_per_1k=0.0)
    assert "[^S1-1]: Source — https://x.example" in out  # def-line em-dash preserved
    assert st["pairs_converted"] == 0


def test_emdash_clamp_idempotent():
    art = "# T\n\n## 1 A\n\nThe cloth — a relic — absorbs; the saint — a bronze — fights on.\n"
    once, _ = style_clamp.clamp_emdash(art, language="en", max_per_1k=0.0)
    twice, st2 = style_clamp.clamp_emdash(once, language="en", max_per_1k=0.0)
    assert once == twice
