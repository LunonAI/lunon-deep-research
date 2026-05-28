"""Deterministic post-refiner cleanup (Step 2a + 2d + 2c-validator from
docs/post_compact_plan.md v3).

W9 judge analysis (bottom-10 cross-cutting themes) identified:
- Inconsistent section numbering (14 judge hits — top complaint)
- Methodology meta-commentary leaking into prose ("evidence atoms",
  "as discussed in section X", "it is worth noting that")
- Empty/placeholder sections under headings
- Structural-cap violations (>7 subsections, depth >3)

This module runs AFTER refiner, BEFORE adapter output. NO LLM CALLS — pure
deterministic regex + tree rebuild. Three operations in fixed order:

1. STOP-LIST REGEX   (2d)  — delete stage-direction phrases and jargon lines
2. EMPTY-SECTION COLLAPSE — drop headings whose body is <10 words after step 1
3. NUMBERING RENUMBER (2a + P2-F) — rebuild a valid heading-number tree AND
                                    rewrite in-body cross-references via an
                                    old→new heading map. Cross-refs to numbers
                                    without a mapping target are left alone
                                    (orphan count tracked).

The ordering matters: stop-list might delete content under a heading, leaving
it empty; we collapse the empty heading; THEN renumber the now-clean tree.

P2-F (2026-05-22): the renumber step formerly SKIPPED rebuilding the tree
when in-body cross-refs were present (to avoid breaking them). It now always
renumbers and rewrites cross-refs using the heading_map built during the pass.
Validation: zero broken cross-refs across all 89 W9-scored articles
(scripts/p2_validate_f.py).

Citation: NVIDIA AI-Q middleware validator (HF blog, 2025) for the deterministic
post-edit pattern. No published paper specifically on heading renumbering —
this is an engineering task the literature hasn't bothered to write up.
"""

import re
from dataclasses import dataclass

# ---------- Step 2d: stage-direction stop-list ----------

# Per-line patterns deleted entirely (case-insensitive, applied to whole lines).
# Curated from W9 judge rationales — exact phrases the judge flagged as
# fluency-reducing in bottom-10 articles.
_LINE_PATTERNS = [
    re.compile(r"^\s*methodology\s+note\s*:.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*evidence\s+pack\s*:.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*\[evidence[-_ ]?pack\].*$", re.IGNORECASE | re.MULTILINE),
]

# Inline phrases deleted from prose (case-insensitive, mid-sentence).
# Phrases that reference a section number need the trailing number absorbed too
# so we don't leave orphan digits ("section 2, evidence atoms" → ", evidence
# atoms" — we want "as discussed in section 2" stripped whole).
# Pattern is (phrase, absorb_trailing_section_number).
_INLINE_PHRASES = [
    ("as discussed in section", True),
    ("as covered in section", True),
    ("as shown in section", True),
    ("as discussed above", False),
    ("as previously mentioned", False),
    ("as discussed earlier", False),
    ("it is worth noting that", False),
    ("it is also worth noting that", False),
    ("for the purposes of this analysis", False),
    ("in this section we will", False),
    ("this section examines", False),
    ("this section discusses", False),
    ("this section will examine", False),
    ("the purpose of this section is to", False),
    ("evidence atom", False),
    ("evidence atoms", False),
    ("cleaning-resistant attribution", False),
    ("cleaning-resistant", False),
    ("cleaning resistant", False),
]

# Compile case-insensitive matchers. For "absorb_num=True" phrases, also eat
# the trailing section-number reference so "as discussed in section 2.1, X"
# becomes "X" cleanly (not "2.1, X").
_INLINE_REGEXES = [
    re.compile(
        r"[, ]*\b" + re.escape(p) + r"\b" + (r"\s*\d+(?:\.\d+)*" if absorb_num else r"") + r"[, ]*",
        re.IGNORECASE,
    )
    for p, absorb_num in _INLINE_PHRASES
]


def strip_stage_directions(text: str) -> tuple[str, int]:
    """Remove stage-direction lines and inline scaffolding phrases.

    Returns (cleaned_text, n_deletions). Designed to be safe: replaces with a
    single space and normalizes whitespace so deleted phrases don't leave
    'word  ,  rest' artifacts.
    """
    n = 0
    cleaned = text
    for pat in _LINE_PATTERNS:
        cleaned, k = pat.subn("", cleaned)
        n += k
    for rgx in _INLINE_REGEXES:
        cleaned, k = rgx.subn(" ", cleaned)
        n += k
    # Normalize: collapse multi-space and stray ' , ' artifacts
    cleaned = re.sub(r"\s+,", ",", cleaned)
    # Orphaned parens left behind when a parenthetical was entirely a stripped
    # phrase, e.g. "(as discussed in section 3.1)" → "( )" → "".
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


# ---------- Empty-section collapse ----------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

# Structural headings the writer/post-process emits whose body is INTRINSICALLY
# short. These must NEVER be subject to the empty-section collapse heuristic —
# the heuristic exists to catch stub content sections like `## 4 Conclusion\n\nTBD`,
# not the appended bibliography. Set kept identical to the regex used in
# `writing_rules.citation_strip_audit` (`(References|参考文献|Sources)`) so both
# sides of the pipeline recognise the same names.
#
# Greptile PR #24 round-3 follow-up (2026-05-25): without this guard,
# `footnote_normalize` emits `## References\n\n[^1]: Source — url` (~6 body
# words) for a 1-citation article and `collapse_empty_sections` then silently
# deletes the entire block. The `footnote_normalize_stats.n_renumbered`
# telemetry shows the block was built, but the shipped article has no
# References section — confusing for post-hoc debugging.
_PROTECTED_HEADING_TITLES = frozenset({"references", "参考文献", "sources"})

# Strip a leading "1.2.3 " / "5 " numeric prefix from a heading title so the
# protected-title check matches both pre-renumber (`## References`) and any
# post-renumber form (`## 5 References`). Reused later for the renumber
# step; defined here so `collapse_empty_sections` can use it.
_LEADING_NUM_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")


def _is_protected_heading(title: str, protected: frozenset[str]) -> bool:
    """Case-insensitive, numeric-prefix-insensitive match against the
    protected-titles set."""
    stripped = _LEADING_NUM_RE.sub("", title).strip().lower()
    return stripped in protected


def collapse_empty_sections(
    text: str,
    min_words: int = 10,
    *,
    protected_titles: frozenset[str] = _PROTECTED_HEADING_TITLES,
) -> tuple[str, int]:
    """If a heading is immediately followed by another heading (or EOF) with
    fewer than `min_words` words of body between them, drop the empty heading.

    Returns (cleaned_text, n_collapsed). Conservative — only drops headings
    that have effectively no content (≤9 words). A heading whose next heading
    is at a DEEPER level is treated as a parent (its content lives in the
    subsections) and is preserved regardless of body-word count.

    Headings whose normalized title is in `protected_titles` are ALSO
    preserved regardless of body length — these are structural sections
    (References / 参考文献 / Sources) whose body is intrinsically short and
    whose deletion would silently strip the bibliography from low-citation
    articles. See `_PROTECTED_HEADING_TITLES` for the default set.
    """
    lines = text.splitlines()
    keep = [True] * len(lines)
    # (line_index, depth, title) so we can detect a parent-of-subsection
    # AND protect well-known structural headings by title.
    heading_info = []
    for i, ln in enumerate(lines):
        m = _HEADING_RE.match(ln)
        if m:
            heading_info.append((i, len(m.group(1)), m.group(2)))
    n_collapsed = 0
    for k, (i, depth, title) in enumerate(heading_info):
        if k + 1 < len(heading_info):
            nxt, next_depth = heading_info[k + 1][0], heading_info[k + 1][1]
        else:
            nxt, next_depth = len(lines), 0
        # If next heading is deeper, this heading is a parent — keep it,
        # its substance is carried by its subsections.
        if next_depth > depth:
            continue
        # Protected structural heading (References block, etc.) — keep
        # regardless of body length.
        if _is_protected_heading(title, protected_titles):
            continue
        body = "\n".join(lines[i + 1 : nxt])
        if len(body.split()) < min_words:
            # Drop both the heading AND its body — otherwise the body lines
            # survive as floating, heading-less prose in the final article.
            keep[i] = False
            for j in range(i + 1, nxt):
                keep[j] = False
            n_collapsed += 1
    return "\n".join(ln for ln, k in zip(lines, keep, strict=False) if k), n_collapsed


# ---------- Step 2a: deterministic heading renumbering ----------

# Patterns that look like cross-references TO a section number. With P2-F
# (cross-ref-aware renumbering), we no longer SKIP renumbering when these are
# present — we rewrite them using the old→new heading map. The detection regex
# stays for diagnostics and was used by the pre-F skip path.
# `§` is `\W`, so a leading `\b` only matches when the prior char is `\w`
# (e.g. "text§2"). In real prose `§` follows a space, so the boundary never
# fires — split `§` out of the `\b`-prefixed alternation so it matches on
# its own.
# The number is capped at \d{1,2} (not \d+) so it doesn't match 4-digit
# years — "as shown in 2024 surveys" was previously matching and silently
# suppressing renumber on any article with year-dated prose, which is most
# of them. Section refs are realistically 1-99, so {1,2} keeps real matches
# like "as shown in 3" or "as shown in 3.2".
_CROSS_REF_RE = re.compile(
    r"(?:\b(?:section|sec\.?|see)|§)\s*\d{1,2}(?:\.\d+){0,3}\b|"
    r"(?:as\s+(?:shown|covered|discussed)\s+in\s+)\d{1,2}(?:\.\d+){0,3}\b",
    re.IGNORECASE,
)

# Substitution variant of _CROSS_REF_RE: captures the prefix and the number
# separately so we can rewrite the number while preserving the surrounding
# phrasing. Used by the P2-F cross-ref-aware renumber path.
_CROSS_REF_SUB_RE = re.compile(
    r"(?P<prefix>(?:\b(?:section|sec\.?|see)\s+|§\s*|as\s+(?:shown|covered|discussed)\s+in\s+))"
    r"(?P<num>\d{1,2}(?:\.\d+){0,3})\b",
    re.IGNORECASE,
)

# Strip an EXISTING numeric prefix from a heading line: "1.2.3 Title" → "Title".
# Handles "1." "1.1" "1.1.1" and optional trailing dot/space. Defined ONCE
# near the top of the module (above `collapse_empty_sections`, which is the
# earliest consumer post-PR #24 round-3) and reused by the renumber path.


def _has_cross_refs(text: str) -> bool:
    return bool(_CROSS_REF_RE.search(text))


# ---------- Pre-renumber: hash-from-number normalization (P2-Option-A-#2) ----------
#
# W9 audit (2026-05-23): 99/100 articles had MULTIPLE H1 headings and 100/100
# had hash-vs-number-depth mismatches. Root cause: the writer's training prior
# treats `#` as "top-level chapter" (e.g. `# 1. Introduction`), but the rest
# of the pipeline assumes `#` is reserved for the report TITLE (single `# Foo`
# at the top, never numbered). `renumber_headings()` walks hashes as the
# source of depth truth, so a `## 1.1.1` heading gets renumbered as if it
# were a top-level section (single-digit number), collapsing the article's
# real depth tree to flat noise.
#
# This pre-pass restores hash↔number agreement BEFORE renumber runs by using
# the leading-number's dot-count as the depth source of truth. The number is
# the writer's intent (writers number reliably; they hash unreliably).
#
# Mapping (dot_count = number.count('.') + 1, so "1" → 1; "1.1" → 2; "1.1.1" → 3):
#   - heading with NO leading number → unchanged (preserves title + prose-titled headings)
#   - 1-dot ("1")     → H2 (##)   top-level section
#   - 2-dot ("1.1")   → H3 (###)  sub-section
#   - 3+-dot ("1.1.1" or deeper) → H4 (####) sub-sub-section (cap matches renumber spec)
#
# Why ONLY rewrite numbered headings: the title and any genuinely H1-prose
# heading (no number) is left alone, which means an already-correct article
# (one H1 title, all section headings at proper depth) passes through unchanged.
# Articles affected by the bug get their depth tree reconstructed without us
# having to guess at writer intent.


def _normalize_hash_from_number(text: str) -> tuple[str, int]:
    """Rewrite each numbered heading's hash level to match its number depth.

    Returns ``(rewritten_text, n_modified)``. ``n_modified`` counts headings
    whose hash level changed (an already-correct heading passes through with
    no rewrite and is not counted). Headings without a leading digit are
    not touched by the first pass, so the report title (``# Foo`` with no
    number) is preserved.

    A second pass handles the residual case where the writer prefixes a
    top-level section with a non-digit label ("S6 实际分红", "Section III",
    "Part A") that the digit regex misses. If multiple ``#`` headings remain
    after the first pass, every ``#`` after the first one is demoted to
    ``##`` — they're necessarily not the title (there's only one title).

    The H4 cap mirrors ``renumber_headings``: a 4-dot number like ``1.1.1.1``
    gets H4 hashes here, and ``renumber_headings`` then further re-numbers
    the H4 line to fit the 3-numeric-level tree.
    """
    n_modified = 0

    def repl(m: re.Match) -> str:
        nonlocal n_modified
        hashes = m.group(1)
        title = m.group(2)
        num_m = _LEADING_NUM_RE.match(title)
        if not num_m:
            return m.group(0)
        num_str = num_m.group().strip().rstrip(".")
        # Number of segments in the dotted number: "1" → 1, "1.1" → 2,
        # "1.1.1" → 3. (NOT the literal dot count; that'd be 0/1/2.) Target
        # hash depth is segments+1 because H1 is reserved for the title.
        segments = num_str.count(".") + 1
        target_depth = min(segments + 1, 4)
        if target_depth == len(hashes):
            return m.group(0)
        n_modified += 1
        return f"{'#' * target_depth} {title}"

    out = _HEADING_RE.sub(repl, text)

    # Second pass: demote stray H1s. After number-based rewrite, any H1
    # other than the FIRST one is a section the writer mistakenly labelled
    # `# Foo` (often with a non-digit prefix like "S6" or "Part III"). The
    # first H1 stays as the report title.
    h1_positions = [m.start() for m in _HEADING_RE.finditer(out) if len(m.group(1)) == 1]
    if len(h1_positions) > 1:
        # Walk the headings; second-and-beyond H1s become H2 (which `renumber`
        # will then assign a top-section number to). Build the rewrite by
        # iterating heading match boundaries to keep the rest of the article
        # untouched.
        pieces: list[str] = []
        last_end = 0
        n_seen_h1 = 0
        for m in _HEADING_RE.finditer(out):
            hashes = m.group(1)
            if len(hashes) != 1:
                continue
            n_seen_h1 += 1
            if n_seen_h1 == 1:
                continue  # the title — leave it alone
            pieces.append(out[last_end : m.start()])
            pieces.append(f"## {m.group(2)}")
            last_end = m.end()
            n_modified += 1
        pieces.append(out[last_end:])
        out = "".join(pieces)

    return out, n_modified


def renumber_headings(text: str) -> tuple[str, dict]:
    """Rebuild a valid numbering tree on all #/##/###/#### headings.

    Heading-level → numbering mapping (aligned with the writer prompts in
    `writing_rules._NUMBERING_RULE` and the AgentCPM 3-numeric-level spec):
    - H1 (`#`) — the report title; no number added
    - H2 (`##`) — top-level sections: "1", "2", "3", ...
    - H3 (`###`) — subsections: "1.1", "1.2", ... resetting at each new H2
    - H4 (`####`) — sub-subsections: "1.1.1", "1.1.2", ... resetting at each new H3
    - H5+ — demoted to H4 first, then numbered as the next sub-subsection

    H4 → "1.1.1" emits TRUE three-level numbering. An earlier version
    demoted H4 to H3 and re-numbered it as a sibling of the preceding H3
    (so `### 2.1 → #### 2.1.1` became `### 2.2`), which broke the
    parent-child relationship the writer intended. That's now fixed:
    the writer-prompt cap of "1.1.1" (max three numeric levels) is matched
    by what this function emits.

    P2-F change (2026-05-22): formerly this function SKIPPED renumbering when
    cross-refs were detected (`_has_cross_refs(text) → return early`). Now it
    builds an old→new heading-number map and rewrites cross-refs alongside
    the renumber. The validation criterion is: after renumbering, every
    cross-ref points to the same conceptual section it did before.

    Returns (renumbered_text, stats). Stats includes:
        applied: bool — always True under P2-F (was False on cross-refs in P1).
        n_renumbered: int — number of headings updated
        n_demoted: int — number of H5+ → H4 demotions (cap enforcement)
        cross_refs_rewritten: int — number of in-body cross-refs substituted
        heading_map: dict[str, str] — old_num → new_num (only headings that
            had an explicit leading number; titles without numbers omitted)
        skipped_reason: str | None — None under P2-F; reserved for future
            short-circuit conditions.
    """
    # Step 1: scan headings, record old_num + clean_title for each.
    plan = []
    for m in _HEADING_RE.finditer(text):
        hashes = m.group(1)
        title_raw = m.group(2)
        old_num_match = _LEADING_NUM_RE.match(title_raw)
        old_num = old_num_match.group().strip().rstrip(".") if old_num_match else None
        plan.append(
            {
                "hashes": hashes,
                "depth": len(hashes),
                "old_num": old_num,
                "clean_title": _LEADING_NUM_RE.sub("", title_raw),
            }
        )

    # Step 2: assign new numbers, build the old→new map.
    # counters[0] = H2 sequence, [1] = H3 under current H2, [2] = H4 under current H3.
    counters = [0, 0, 0]
    n_renumbered = 0
    n_demoted = 0
    heading_map: dict[str, str] = {}
    for h in plan:
        depth = h["depth"]
        # Enforce the 4-markdown-level / 3-numeric-level cap. H5+ → H4 so
        # we still emit a numbered heading rather than dropping it.
        if depth >= 5:
            depth = 4
            h["hashes"] = "####"
            n_demoted += 1
        h["effective_depth"] = depth
        if depth == 1:
            h["new_num"] = None  # H1 = report title; no number prefix.
            continue
        d = depth - 2  # depth=2 → d=0; depth=3 → d=1; depth=4 → d=2.
        counters[d] += 1
        for j in range(d + 1, len(counters)):
            counters[j] = 0
        h["new_num"] = ".".join(str(counters[j]) for j in range(d + 1))
        n_renumbered += 1
        if h["old_num"] is not None:
            # If the same old_num appeared on multiple headings (a numbering
            # bug we're fixing), the LAST occurrence wins the map slot. Pre-F
            # this whole pass was skipped on cross-refs anyway, so duplicate
            # old_num was never a problem; we surface it now as a known minor
            # quirk: cross-refs to a duplicated old_num will point to the
            # last-renumbered occurrence, not necessarily the one the writer
            # intended. Document and move on — this is no worse than the
            # pre-F behavior of leaving the cross-ref pointing to whichever
            # heading shared the duplicate old_num.
            heading_map[h["old_num"]] = h["new_num"]

    # Step 3: rewrite headings using the plan.
    plan_iter = iter(plan)

    def repl_heading(m: re.Match) -> str:
        h = next(plan_iter)
        hashes = h["hashes"]
        if h["new_num"] is None:
            return f"{hashes} {h['clean_title']}"
        return f"{hashes} {h['new_num']} {h['clean_title']}"

    out = _HEADING_RE.sub(repl_heading, text)

    # Step 4: rewrite in-body cross-references using the heading_map.
    n_xref = 0
    n_xref_orphan = 0

    def repl_xref(m: re.Match) -> str:
        nonlocal n_xref, n_xref_orphan
        num = m.group("num")
        if num in heading_map:
            n_xref += 1
            return m.group("prefix") + heading_map[num]
        # Cross-ref points to a number that doesn't match any old heading.
        # Leave it alone — substituting would be guessing. Could be a writer
        # mistake (referenced section never existed) or an artifact of an
        # already-broken numbering before our pass. Either way, silently
        # rewriting it would make things worse.
        n_xref_orphan += 1
        return m.group(0)

    out = _CROSS_REF_SUB_RE.sub(repl_xref, out)

    return out, {
        "applied": True,
        "n_renumbered": n_renumbered,
        "n_demoted": n_demoted,
        "cross_refs_rewritten": n_xref,
        "cross_refs_orphaned": n_xref_orphan,
        "heading_map": heading_map,
        "skipped_reason": None,
    }


# ---------- Step 2c: post-write structural-cap warning ----------


def cap_violations(text: str) -> dict:
    """Return counts of structural-cap violations. Logging-only.

    H4 is now a valid third numeric level ("1.1.1") per the writer-prompt
    spec and `renumber_headings`, so violations start at H5+. H5+ headings
    are demoted to H4 by `renumber_headings`, so in normal post-edit output
    `deeper_than_4` should always be 0. >7-subsection violations are
    reported but NOT auto-fixed (destructive).
    """
    headings = _HEADING_RE.findall(text)
    depth_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
    for h, _ in headings:
        depth_counts[len(h)] = depth_counts.get(len(h), 0) + 1
    # Subsection-per-section count: for each H2, count immediately-following
    # H3s before the next H2.
    h_iter = list(_HEADING_RE.finditer(text))
    subsections_per_h2 = []
    cur = 0
    for h in h_iter:
        if len(h.group(1)) == 2:
            if cur:
                subsections_per_h2.append(cur)
            cur = 0
        elif len(h.group(1)) == 3:
            cur += 1
    if cur:
        subsections_per_h2.append(cur)
    over_cap = sum(1 for n in subsections_per_h2 if n > 7)
    return {
        "depth_counts": depth_counts,
        # H5+ is the violation tier now that H4 emits valid "1.1.1" numbering.
        "deeper_than_4": depth_counts.get(5, 0) + depth_counts.get(6, 0),
        "subsections_per_h2": subsections_per_h2,
        "sections_over_7_subsections": over_cap,
    }


# ---------- Pipeline entry point ----------


@dataclass
class NumberingFixOutput:
    article: str
    stage_directions_removed: int
    sections_collapsed: int
    renumbering_applied: bool
    headings_renumbered: int
    headings_demoted: int
    headings_hash_normalized: int
    cross_refs_rewritten: int
    cross_refs_orphaned: int
    cap_violations: dict
    skipped_reason: str | None
    headings_flattened: int = 0


def _flatten_depth(text: str, max_depth: int) -> tuple[str, int]:
    """Demote any heading deeper than `max_depth` to `max_depth` markdown
    level, preserving the heading text (incl. its `N.M` number).

    P3b-opt2 (2026-05-28): matches Qianfan's verified flat render — q91 puts
    every section at `## N.M Title` (H3=H4=0). For list-all `max_depth=2`
    (fully flat `##`); other archetypes `max_depth=3` (cap H4 → Qianfan's
    universal `h4=0`). The per-entity bold paragraph lead-ins carry the
    sub-structure, so no information is lost. Runs LAST (after renumber), so
    the assigned numbers + rewritten cross-refs are preserved — only the
    markdown hash level changes. The first H1 (title, depth 1 < max_depth) is
    never touched."""
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        hashes, title = m.group(1), m.group(2)
        if len(hashes) > max_depth:
            n += 1
            return f"{'#' * max_depth} {title}"
        return m.group(0)

    return _HEADING_RE.sub(repl, text), n


def run(article: str, flatten_max_depth: int | None = None) -> NumberingFixOutput:
    """Run the deterministic post-refiner cleanup in fixed order.

    Order (CRITICAL — see plan v3 §2a + P2-Option-A-#2):
      1. Stop-list deletes meta-commentary lines/phrases
      2. Hash-from-number normalization rewrites heading hashes to match
         the leading-number depth (fixes the 99/100-prevalence writer bug
         where every numbered heading was emitted one hash-level too shallow,
         collapsing depth trees to flat noise after the renumber step).
         RUNS BEFORE collapse so the title's adjacent demoted heading is
         at a deeper level, letting collapse preserve the title as a parent.
      3. Empty-section collapse drops now-empty headings
      4. Renumber rebuilds the heading-number tree AND rewrites cross-refs
         using an old→new heading map (P2-F, was: skip on cross-refs)
    """
    a, n_strip = strip_stage_directions(article)
    a, n_hashnorm = _normalize_hash_from_number(a)
    a, n_collapse = collapse_empty_sections(a)
    a, renum = renumber_headings(a)
    # P3b-opt2: deterministic Qianfan-flatten runs LAST so numbers + rewritten
    # cross-refs survive — only the markdown hash level changes.
    n_flat = 0
    if flatten_max_depth is not None:
        a, n_flat = _flatten_depth(a, flatten_max_depth)
    caps = cap_violations(a)
    return NumberingFixOutput(
        article=a,
        stage_directions_removed=n_strip,
        sections_collapsed=n_collapse,
        renumbering_applied=renum["applied"],
        headings_renumbered=renum["n_renumbered"],
        headings_demoted=renum["n_demoted"],
        headings_hash_normalized=n_hashnorm,
        cross_refs_rewritten=renum.get("cross_refs_rewritten", 0),
        cross_refs_orphaned=renum.get("cross_refs_orphaned", 0),
        cap_violations=caps,
        skipped_reason=renum["skipped_reason"],
        headings_flattened=n_flat,
    )
