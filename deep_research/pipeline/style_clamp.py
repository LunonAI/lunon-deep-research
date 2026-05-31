"""Deterministic style clamps (P3b-opt2, 2026-05-28).

The writer ignores density directives ("asked 6/1k, got 19.5/1k"), so these
post-passes ENFORCE the reference-corpus rates the PR-C1 directives ask for.

Runs in orchestrate BETWEEN ``mermaid_validate`` and ``footnote_normalize``,
on the per-section ``[^{section_id}-N]`` marker form (defs still inline). Any
inline marker this pass removes leaves an unused ``[^X]:`` definition that
``footnote_normalize`` then auto-drops — so no orphan/dangling refs are
produced (footnote_normalize is self-cleaning on both sides).

Two independent, fail-soft, idempotent clamps:
  - clamp_citations: cut inline-marker density to the reference band WITHOUT
    ever leaving a sentence that had a citation with zero (never un-cite a
    claim). Two tiers: (1) collapse consecutive "citation salad" runs to the
    first marker — grammatically free; (2) if still over the ceiling, drop
    non-first-per-sentence markers in document order until in band.
  - clamp_emdash: reduce U+2014 density toward the band via the PAIRED-
    parenthetical transform only ("X — clause — Y" → "X, clause, Y"), the
    lowest grammar-risk conversion. EN default ceiling = the corpus median,
    so it is a NO-OP on English (our body rate is already under it).

Density basis: inline markers in the full article (def lines, headings, tables
and code are excluded via ``_protected_ranges``) over a CJK-aware word count
(mirrors scripts/reference_style_profile.py so the band math matches what graders
measure).
"""

from __future__ import annotations

import re

from ..text_metrics import approx_words

# Mirror footnote_normalize: inline marker = [^token] NOT followed by ':'
# (the lookahead excludes definition lines).
_INLINE_RE = re.compile(r"\[\^([A-Za-z0-9._-]+)\](?!:)")
# Definition LINE (anchored), so we never count/touch the bibliography markers.
_DEF_LINE_RE = re.compile(r"^[ \t]*\[\^[A-Za-z0-9._-]+\]:", re.MULTILINE)
# Sentence terminator followed by whitespace/EOL (avoids splitting "3.5").
_SENT_END_RE = re.compile(r"[.!?](?=\s|$)")
# Common abbreviations whose trailing "." is NOT a sentence end — counting
# them as boundaries would over-protect the marker after them from PASS 2
# (the un-cite invariant still holds; this only sharpens density reduction in
# abbreviation-heavy prose). Python's `re` forbids variable-width lookbehind,
# so we post-filter in `_sentence_end_positions` instead of a lookbehind.
_ABBREV = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "st",
        "jr",
        "sr",
        "fig",
        "no",
        "vol",
        "pp",
        "cf",
        "al",
        "vs",
        "eg",
        "ie",
        "etc",
        "inc",
        "ltd",
        "co",
        "ca",
        "approx",
        "est",
        "dept",
        "univ",
    }
)
_WORD_BEFORE_DOT_RE = re.compile(r"([A-Za-z]+)$")
# U+2014 em-dash ONLY (never en-dash U+2013, which marks numeric ranges).
_EMDASH = "—"
# Paired parenthetical: "X — clause — Y" (spaced em-dashes, no nested dash or
# newline in the clause, bounded length) → appositive commas.
_EMDASH_PAIR_RE = re.compile(rf"(?<=\S)[ \t]{_EMDASH}[ \t](?P<mid>[^{_EMDASH}\n]{{1,120}}?)[ \t]{_EMDASH}[ \t](?=\S)")

# Corpus-median ceilings (per language) from reference_style_targets.json.
_CITE_CEIL = {"en": 7.0, "zh": 13.0}  # EN median 6.29, ZH 12.18 (+ small headroom)
_EMDASH_CEIL = {"en": 12.45, "zh": 21.54}  # corpus medians; EN is a no-op (body ~10.6)

# round 4 W4 (2026-05-31): paragraph-density ceiling, in approx_words units
# (CJK-aware: ~1 unit/char for ZH). The dev8 gemini judge flagged our prose as
# "suffocating equal-intensity density / wall of text / expert monograph" — the
# #1 readability complaint — and L6/L8/L9 PROMPT rules were already active in
# that run and did NOT move it. The root fix is DETERMINISTIC: split an overlong
# paragraph at its EXISTING sentence boundaries (never rewriting a sentence, so
# zero grammar/content/citation risk) so a dense block becomes several scannable
# paragraphs. Web research target ~100-120 EN words/paragraph; ZH packs denser so
# the ceiling is higher in raw units. Env-overridable for dev-run A/B.
_PARA_CEIL = {"en": 120, "zh": 220}
# A trailing chunk below this (in units) is merged back rather than left as a
# stub paragraph — avoids creating one-sentence orphans.
_PARA_MIN_TAIL = 30


def _protected_ranges(body: str) -> list[tuple[int, int]]:
    """Char ranges the clamp must not edit: fenced code/mermaid blocks,
    markdown table lines, ATX heading lines, and footnote definition lines."""
    ranges: list[tuple[int, int]] = []
    in_fence = False
    fence_start = 0
    pos = 0
    for line in body.splitlines(keepends=True):
        stripped = line.lstrip()
        is_fence_marker = stripped.startswith("```") or stripped.startswith("~~~")
        if in_fence:
            if is_fence_marker:
                ranges.append((fence_start, pos + len(line)))
                in_fence = False
        elif is_fence_marker:
            in_fence = True
            fence_start = pos
        else:
            # table row | ... |, heading # ..., or def line [^x]:
            if stripped.startswith("|") or re.match(r"#{1,6}\s", stripped) or _DEF_LINE_RE.match(line):
                ranges.append((pos, pos + len(line)))
        pos += len(line)
    if in_fence:  # unterminated fence → protect to end
        ranges.append((fence_start, len(body)))
    return ranges


def _in_ranges(pos: int, ranges: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in ranges)


def _count_before(sorted_positions: list[int], pos: int) -> int:
    """How many positions are strictly < pos (sentence id helper)."""
    lo, hi = 0, len(sorted_positions)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_positions[mid] < pos:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _sentence_end_positions(text: str) -> list[int]:
    """Positions of real sentence terminators, skipping abbreviation dots
    ("Mr.", "Fig.", "etc.") and dotted abbreviations ("e.g.", "i.e.", "U.S.")
    so PASS 2 doesn't over-protect the marker that follows them."""
    out: list[int] = []
    for m in _SENT_END_RE.finditer(text):
        i = m.start()
        if text[i] == ".":
            # dotted abbreviation: the char two back is also a dot (e.g./U.S.)
            if i >= 2 and text[i - 2] == ".":
                continue
            wm = _WORD_BEFORE_DOT_RE.search(text[:i])
            if wm and wm.group(1).lower() in _ABBREV:
                continue
        out.append(i)
    return out


def _zero_cite_stats(language: str) -> dict:
    return {
        "markers_before": 0,
        "markers_after": 0,
        "salad_collapsed": 0,
        "removed": 0,
        "density_before": 0.0,
        "density_after": 0.0,
        "floor_exceeded": False,
        "language": language,
    }


def clamp_citations(article: str, *, language: str = "en", max_per_1k: float | None = None) -> tuple[str, dict]:
    """Cut inline citation-marker density to the reference band, never leaving
    a sentence that had a marker with zero. Returns (article, stats)."""
    if not isinstance(article, str) or not article.strip():
        return article, _zero_cite_stats(language)
    ceiling = max_per_1k if max_per_1k is not None else _CITE_CEIL.get(language, _CITE_CEIL["en"])

    # P3b-D2: process the WHOLE article — def lines, headings, tables and code
    # are already protected by _protected_ranges, so a trailing References
    # block is never edited. (The old _split_references over-cut on the first
    # mid-article "references"-like heading, leaving ~74% of the article
    # unclamped pre-footnote_normalize.)
    body = article
    protected = _protected_ranges(body)
    sent_ends = _sentence_end_positions(body)

    # Candidate (non-protected) inline markers, in document order.
    cands = [(m.start(), m.end()) for m in _INLINE_RE.finditer(body) if not _in_ranges(m.start(), protected)]
    words = approx_words(body)
    markers_before = len(cands)
    if markers_before == 0:
        st = _zero_cite_stats(language)
        st["density_before"] = 0.0
        return article, st

    # PASS 1 — collapse consecutive "salad" runs to the first marker. Two
    # candidates are in the same run if only whitespace separates them.
    remove: set[int] = set()  # indices into `cands`
    salad_collapsed = 0
    for i in range(1, len(cands)):
        between = body[cands[i - 1][1] : cands[i][0]]
        if between.strip() == "":
            remove.add(i)
            salad_collapsed += 1

    survivors = [i for i in range(len(cands)) if i not in remove]
    density_before = round(markers_before / words * 1000, 2)

    # PASS 2 — if still over the ceiling, drop non-first-per-sentence markers.
    floor_exceeded = False
    # round (not truncate) and floor at 1: int() truncation can make a short
    # body's target 0 (e.g. 142 words @ 7/1k → 0.99 → 0), over-removing even
    # though one marker is already within band.
    target = max(1, round(ceiling * words / 1000))
    if len(survivors) > target:
        # First survivor in each sentence is PROTECTED (never un-cite a claim).
        protected_first: set[int] = set()
        seen_sent: set[int] = set()
        for i in survivors:  # survivors already in document order
            sid = _count_before(sent_ends, cands[i][0])
            if sid not in seen_sent:
                seen_sent.add(sid)
                protected_first.add(i)
        removable = [i for i in survivors if i not in protected_first]
        need = len(survivors) - target
        if need >= len(removable):
            floor_exceeded = True  # can't reach band without un-citing claims
            need = len(removable)
        for i in removable[:need]:
            remove.add(i)

    if not remove:
        st = _zero_cite_stats(language)
        st["markers_before"] = markers_before
        st["markers_after"] = markers_before
        st["density_before"] = density_before
        st["density_after"] = density_before
        st["floor_exceeded"] = floor_exceeded
        return article, st

    # Apply removals: rebuild body skipping removed marker spans.
    remove_spans = sorted(cands[i] for i in remove)
    out = []
    prev = 0
    for a, b in remove_spans:
        out.append(body[prev:a])
        prev = b
    out.append(body[prev:])
    new_body = "".join(out)

    # Cleanup: collapse the space the removed marker left and drop space
    # before punctuation (e.g. "word [^3]." → "word ." → "word."). Scope it
    # to NON-protected spans only, so code-fence indentation, mermaid blocks,
    # tables, and definition lines are never disturbed (offsets recomputed on
    # the rebuilt body).
    def _cleanup(seg: str) -> str:
        seg = re.sub(r"[ \t]{2,}", " ", seg)
        return re.sub(r"[ \t]+([.,;:!?)])", r"\1", seg)

    prot_after = sorted(_protected_ranges(new_body))
    pieces: list[str] = []
    cur = 0
    for a, b in prot_after:
        pieces.append(_cleanup(new_body[cur:a]))
        pieces.append(new_body[a:b])  # protected span verbatim
        cur = b
    pieces.append(_cleanup(new_body[cur:]))
    new_body = "".join(pieces)

    new_article = new_body
    markers_after = markers_before - len(remove)
    return new_article, {
        "markers_before": markers_before,
        "markers_after": markers_after,
        "salad_collapsed": salad_collapsed,
        "removed": len(remove),
        "density_before": density_before,
        "density_after": round(markers_after / words * 1000, 2),
        "floor_exceeded": floor_exceeded,
        "language": language,
    }


def _emdash_count(body: str, protected: list[tuple[int, int]]) -> int:
    return sum(1 for i, c in enumerate(body) if c == _EMDASH and not _in_ranges(i, protected))


def clamp_emdash(article: str, *, language: str = "en", max_per_1k: float | None = None) -> tuple[str, dict]:
    """Reduce U+2014 density toward the band via the paired-parenthetical
    transform only (lowest grammar risk). EN default = corpus median ⇒ no-op
    on English. Returns (article, stats)."""
    zero = {
        "emdash_before": 0,
        "emdash_after": 0,
        "pairs_converted": 0,
        "density_before": 0.0,
        "density_after": 0.0,
        "language": language,
    }
    if not isinstance(article, str) or not article.strip():
        return article, zero
    ceiling = max_per_1k if max_per_1k is not None else _EMDASH_CEIL.get(language, _EMDASH_CEIL["en"])

    body = article  # whole article; protected spans cover any References block
    protected = _protected_ranges(body)
    words = approx_words(body)
    before = _emdash_count(body, protected)
    density_before = round(before / words * 1000, 2)
    if before == 0 or density_before <= ceiling:
        zero["emdash_before"] = before
        zero["emdash_after"] = before
        zero["density_before"] = density_before
        zero["density_after"] = density_before
        return article, zero

    # Convert paired parentheticals left-to-right until in band. Each pair
    # converted removes 2 em-dashes. Skip pairs inside protected ranges.
    pairs = 0
    remaining = before

    def _repl(m: re.Match) -> str:
        nonlocal pairs, remaining
        if remaining / words * 1000 <= ceiling:
            return m.group(0)
        if _in_ranges(m.start(), protected):
            return m.group(0)
        pairs += 1
        remaining -= 2
        return f", {m.group('mid')}, "

    new_body = _EMDASH_PAIR_RE.sub(_repl, body)
    if pairs == 0:
        zero["emdash_before"] = before
        zero["emdash_after"] = before
        zero["density_before"] = density_before
        zero["density_after"] = density_before
        return article, zero

    after = _emdash_count(new_body, _protected_ranges(new_body))
    return new_body, {
        "emdash_before": before,
        "emdash_after": after,
        "pairs_converted": pairs,
        "density_before": density_before,
        "density_after": round(after / words * 1000, 2),
        "language": language,
    }


# ── round 4 W4: paragraph-density clamp ────────────────────────────────────
_LIST_LINE_RE = re.compile(r"^[ \t]*(?:[-*+]\s|\d+[.)]\s|>|\[\^)")


def _approx_units(text: str) -> int:
    """Length in the same CJK-aware units the density math uses elsewhere."""
    return approx_words(text)


def _looks_like_list_or_marker(para: str) -> bool:
    """A paragraph whose lines are list items / blockquotes / footnote defs is
    already segmented — never re-paragraph it."""
    lines = [ln for ln in para.splitlines() if ln.strip()]
    if not lines:
        return True
    return any(_LIST_LINE_RE.match(ln) for ln in lines)


# CJK sentence terminators (。！？ + their fullwidth siblings). Unlike Latin
# terminators these need no trailing space — CJK runs sentences together — so
# `_sentence_end_positions` (Latin, space-gated) misses them entirely.
_CJK_SENT_END_RE = re.compile(r"[。！？]")


def _para_sentence_ends(text: str) -> list[int]:
    """Sentence-terminator positions for BOTH scripts: the Latin,
    abbreviation-aware `_sentence_end_positions` plus CJK 。！？. Sorted, deduped."""
    pts = set(_sentence_end_positions(text))
    pts.update(m.start() for m in _CJK_SENT_END_RE.finditer(text))
    return sorted(pts)


def _resegment_paragraph(para: str, ceiling: int) -> tuple[str, int]:
    """Split one overlong prose paragraph at its EXISTING sentence boundaries
    into chunks each ≈`ceiling` units. Never rewrites a sentence (a single
    sentence longer than the ceiling becomes its own chunk), so there is zero
    grammar/content/citation risk. Returns (new_text, n_breaks_inserted)."""
    sent_ends = [p + 1 for p in _para_sentence_ends(para)]  # cut AFTER the terminator
    if not sent_ends:
        return para, 0
    chunks: list[str] = []
    cur_start = 0
    for end in sent_ends:
        if _approx_units(para[cur_start:end]) >= ceiling:
            chunks.append(para[cur_start:end].strip())
            cur_start = end
    tail = para[cur_start:].strip()
    if tail:
        if chunks and _approx_units(tail) < _PARA_MIN_TAIL:
            chunks[-1] = f"{chunks[-1]} {tail}"
        else:
            chunks.append(tail)
    if len(chunks) <= 1:
        return para, 0
    return "\n\n".join(chunks), len(chunks) - 1


def _segment_free(free: str, ceiling: int) -> tuple[str, int, int]:
    """Paragraph-segment a protected-free run of body text. Splits on blank
    lines (keeping the separators), re-segments each over-ceiling prose
    paragraph. Returns (text, n_breaks_inserted, n_paragraphs_split)."""
    parts = re.split(r"(\n{2,})", free)  # keeps separators at odd indices
    n_breaks = 0
    n_split = 0
    for i in range(0, len(parts), 2):
        para = parts[i]
        if not para.strip():
            continue
        if _looks_like_list_or_marker(para):
            continue
        if _approx_units(para) <= ceiling:
            continue
        new_para, nb = _resegment_paragraph(para, ceiling)
        if nb:
            parts[i] = new_para
            n_breaks += nb
            n_split += 1
    return "".join(parts), n_breaks, n_split


def clamp_paragraphs(article: str, *, language: str = "en", max_units: int | None = None) -> tuple[str, dict]:
    """Break overlong prose paragraphs into scannable ones at existing sentence
    boundaries. Deterministic root-cause fix for the dev8 judge's #1 readability
    complaint ("suffocating equal-intensity density / wall of text"); the L6/L8/L9
    PROMPT rules were already active in dev8 and did not move it. Only inserts
    paragraph breaks at detected sentence terminators — never rewrites, reorders,
    or drops a sentence, so non-whitespace content is preserved exactly. Code
    fences / tables / headings / footnote-def lines are protected; list runs are
    skipped (already segmented); the References block is untouched."""
    if not isinstance(article, str) or not article.strip():
        return article, {"language": language, "ceiling_units": 0, "paragraphs_split": 0, "breaks_inserted": 0}
    ceiling = max_units if max_units is not None else _PARA_CEIL.get(language, _PARA_CEIL["en"])
    spans = sorted(_protected_ranges(article))
    out: list[str] = []
    n_breaks = 0
    n_split = 0
    pos = 0
    for a, b in spans:
        if a > pos:
            new_free, nb, ns = _segment_free(article[pos:a], ceiling)
            out.append(new_free)
            n_breaks += nb
            n_split += ns
        out.append(article[a:b])
        pos = max(pos, b)
    if pos < len(article):
        new_free, nb, ns = _segment_free(article[pos:], ceiling)
        out.append(new_free)
        n_breaks += nb
        n_split += ns
    stats = {
        "language": language,
        "ceiling_units": ceiling,
        "paragraphs_split": n_split,
        "breaks_inserted": n_breaks,
    }
    return "".join(out), stats
