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
3. NUMBERING RENUMBER (2a) — rebuild a valid heading-number tree IFF the article
                             doesn't contain cross-references that would break

The ordering matters: stop-list might delete content under a heading, leaving
it empty; we collapse the empty heading; THEN renumber the now-clean tree.

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
        r"[, ]*\b" + re.escape(p) + r"\b"
        + (r"\s*\d+(?:\.\d+)*" if absorb_num else r"")
        + r"[, ]*",
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


def collapse_empty_sections(text: str, min_words: int = 10) -> tuple[str, int]:
    """If a heading is immediately followed by another heading (or EOF) with
    fewer than `min_words` words of body between them, drop the empty heading.

    Returns (cleaned_text, n_collapsed). Conservative — only drops headings
    that have effectively no content (≤9 words). A heading whose next heading
    is at a DEEPER level is treated as a parent (its content lives in the
    subsections) and is preserved regardless of body-word count.
    """
    lines = text.splitlines()
    keep = [True] * len(lines)
    # (line_index, depth) so we can detect a parent-of-subsection.
    heading_info = []
    for i, l in enumerate(lines):
        m = _HEADING_RE.match(l)
        if m:
            heading_info.append((i, len(m.group(1))))
    n_collapsed = 0
    for k, (i, depth) in enumerate(heading_info):
        if k + 1 < len(heading_info):
            nxt, next_depth = heading_info[k + 1]
        else:
            nxt, next_depth = len(lines), 0
        # If next heading is deeper, this heading is a parent — keep it,
        # its substance is carried by its subsections.
        if next_depth > depth:
            continue
        body = "\n".join(lines[i + 1:nxt])
        if len(body.split()) < min_words:
            # Drop both the heading AND its body — otherwise the body lines
            # survive as floating, heading-less prose in the final article.
            keep[i] = False
            for j in range(i + 1, nxt):
                keep[j] = False
            n_collapsed += 1
    return "\n".join(l for l, k in zip(lines, keep) if k), n_collapsed


# ---------- Step 2a: deterministic heading renumbering ----------

# Patterns that look like cross-references TO a section number. If the article
# contains these, renumbering would silently break the references, which is
# worse than the original numbering inconsistency. We skip renumbering in that
# case and log it. (Documented as P2 item: cross-ref-aware renumber.)
# `§` is `\W`, so a leading `\b` only matches when the prior char is `\w`
# (e.g. "text§2"). In real prose `§` follows a space, so the boundary never
# fires — split `§` out of the `\b`-prefixed alternation so it matches on
# its own.
_CROSS_REF_RE = re.compile(
    r"(?:\b(?:section|sec\.?|see)|§)\s*\d+(?:\.\d+){0,3}\b|"
    r"(?:as\s+(?:shown|covered|discussed)\s+in\s+)\d+(?:\.\d+){0,3}",
    re.IGNORECASE,
)

# Strip an EXISTING numeric prefix from a heading line: "1.2.3 Title" → "Title".
# Handles "1." "1.1" "1.1.1" and optional trailing dot/space.
_LEADING_NUM_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")


def _has_cross_refs(text: str) -> bool:
    return bool(_CROSS_REF_RE.search(text))


def renumber_headings(text: str) -> tuple[str, dict]:
    """Rebuild a valid numbering tree on all #/##/### headings.

    Heading-level → numbering mapping (matches AgentCPM ≤3-depth cap):
    - H1 (`#`) — the report title; no number added
    - H2 (`##`) — top-level sections: "1", "2", "3", ...
    - H3 (`###`) — subsections: "1.1", "1.2", ... resetting at each new H2
    - H4+ (`####` and deeper) — demoted to H3 first, then numbered as H3

    Three-level numbering (e.g. "1.1.1") is intentionally NOT produced; H4+
    content is collapsed to H3 by the structural cap above and then numbered
    as the next H3 under its current H2. Existing numeric prefixes on heading
    text are stripped before renumbering.

    Returns (renumbered_text, stats). Stats includes:
        applied: bool — False if cross-refs detected (skipped to avoid breaking)
        n_renumbered: int — number of headings updated
        n_demoted: int — number of #### → ### demotions (cap enforcement)
        skipped_reason: str | None
    """
    if _has_cross_refs(text):
        return text, {"applied": False, "n_renumbered": 0, "n_demoted": 0,
                      "skipped_reason": "cross_references_present"}

    counters = [0, 0]   # index 0 = H2 sequence, index 1 = H3 sequence under current H2
    n_renumbered = 0
    n_demoted = 0

    def repl(m: re.Match) -> str:
        nonlocal n_renumbered, n_demoted
        hashes = m.group(1)
        title = m.group(2)
        depth = len(hashes)
        # Enforce 3-level cap (2c structural rule)
        if depth >= 4:
            depth = 3
            hashes = "###"
            n_demoted += 1
        # H1 is the report title — leave numbering off it. H2 is the top
        # section unit (counter index 0); H3 is subsection (index 1); H4+
        # was already demoted to 3.
        if depth == 1:
            clean_title = _LEADING_NUM_RE.sub("", title)
            return f"{hashes} {clean_title}"
        # depth=2 → d=0, depth=3 → d=1
        d = depth - 2
        counters[d] += 1
        # Reset deeper counters
        for j in range(d + 1, len(counters)):
            counters[j] = 0
        # Build numeric prefix from counters[0..d]
        nums = ".".join(str(counters[j]) for j in range(d + 1))
        clean_title = _LEADING_NUM_RE.sub("", title)
        n_renumbered += 1
        return f"{hashes} {nums} {clean_title}"

    out = _HEADING_RE.sub(repl, text)
    return out, {"applied": True, "n_renumbered": n_renumbered,
                 "n_demoted": n_demoted, "skipped_reason": None}


# ---------- Step 2c: post-write structural-cap warning ----------

def cap_violations(text: str) -> dict:
    """Return counts of structural-cap violations. Logging-only by default;
    fixable violations (depth-4+) are already collapsed by renumber_headings;
    >7-subsection violations are reported but NOT auto-fixed (destructive).
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
        "deeper_than_3": depth_counts.get(4, 0) + depth_counts.get(5, 0)
                         + depth_counts.get(6, 0),
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
    cap_violations: dict
    skipped_reason: str | None


def run(article: str) -> NumberingFixOutput:
    """Run the deterministic post-refiner cleanup in fixed order.

    Order (CRITICAL — see plan v3 §2a):
      1. Stop-list deletes meta-commentary lines/phrases
      2. Empty-section collapse drops now-empty headings
      3. Renumber rebuilds the heading-number tree (or skips if cross-refs)
    """
    a, n_strip = strip_stage_directions(article)
    a, n_collapse = collapse_empty_sections(a)
    a, renum = renumber_headings(a)
    caps = cap_violations(a)
    return NumberingFixOutput(
        article=a,
        stage_directions_removed=n_strip,
        sections_collapsed=n_collapse,
        renumbering_applied=renum["applied"],
        headings_renumbered=renum["n_renumbered"],
        headings_demoted=renum["n_demoted"],
        cap_violations=caps,
        skipped_reason=renum["skipped_reason"],
    )
