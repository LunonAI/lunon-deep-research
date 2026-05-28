"""Post-write footnote normalization (P2-Option-A-#6).

Each section's writer emits SECTION-LOCAL footnote markers of the form
``[^{section_id}-N]`` (e.g. ``[^S1-1]``, ``[^S3.2-4]``) inline, with matching
definitions ``[^{section_id}-N]: source_name — url`` at the end of that
section. The per-section scoping guarantees uniqueness across sections so
the post-process step can deterministically merge them into one global
``## References`` block at the article end.

Why per-section tokens (vs. plain ``[^1]``, ``[^2]``):
  Without scoping, section 1 and section 2 both emit ``[^1]``/``[^2]`` with
  DIFFERENT intended URLs. After assemble, the post-process can't tell
  which ``[^1]`` belongs to which URL — they collide. Per-section tokens
  make the input deterministic.

Failure modes the normalizer handles:
  - Orphan markers (``[^X]`` in body with no matching ``[^X]:`` definition):
    strip the marker (don't leave broken markdown).
  - Unused definitions (``[^X]:`` with no matching marker in body):
    drop the definition (don't pollute References).
  - Mid-paragraph definitions (writer dropped a ``[^X]:`` inline by mistake):
    accept it as a definition, treat its line as a candidate definition
    line and strip it from the body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .evidence_dedup import _normalize_url

# P3b-D2 (2026-05-28): the writer emits a fresh per-section token for the SAME
# source in every section, so footnote_normalize used to assign that one source
# N separate global numbers (e.g. one Fandom page → 35 `[^N]` entries; reuse
# 1.4× vs the reference's 4.7–8.9×). We now number by SOURCE: tokens whose definition
# resolves to the same source (URL via evidence_dedup._normalize_url, else the
# normalized source-name) collapse to ONE number, every inline marker rewritten
# to it. Deterministic, generalizes to every task, and matches the reference's
# few-sources-reused-heavily citation shape.
_DEF_SEP = " — "  # source-name — url separator emitted by CLEANING_RESISTANT_RULE
_NAME_NORM_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _def_source_key(text: str) -> str:
    """Canonical dedup key for a definition's source: its normalized URL when
    the tail after the ` — ` separator is a real http(s) URL, else the
    normalized FULL definition text.

    The http(s) guard is required: ``_normalize_url`` returns a non-empty
    pseudo-URL for ANY non-empty string (e.g. ``"See §4"`` → ``"https://see
    §4"``), so without it the name fallback is dead code AND two different
    sources sharing a coincidental non-URL tail would false-merge. Keying the
    fallback on the FULL text (not just the head) preserves tail distinctions
    like ``"Lebrun (1999) — vol 1"`` vs ``"… — vol 2"`` — conservative: only
    byte-identical sources merge when no real URL is present."""
    text = text.strip()
    if _DEF_SEP in text:
        tail = text.rsplit(_DEF_SEP, 1)[1].strip()
        if tail.startswith(("http://", "https://")):
            u = _normalize_url(tail)
            if u:
                return "u:" + u
    return "n:" + re.sub(r"\s+", " ", _NAME_NORM_RE.sub("", text.lower())).strip()


# Definition pattern: ``[^token]: definition text`` anchored to line start.
# Token may include letters, digits, dots, hyphens, underscores — enough to
# cover the architect's section_id shapes ("S1", "S1.1", "S3.2.4") and any
# legacy plain-numeric markers ("1", "12") that survive from older writers.
_DEFINITION_RE = re.compile(r"^[ \t]*\[\^([A-Za-z0-9._-]+)\]:[ \t]*(.+?)[ \t]*$", re.MULTILINE)

# Inline-marker pattern: ``[^token]`` NOT followed by a colon. The negative
# lookahead ``(?!:)`` avoids matching the definition form, which we handle
# separately above.
_INLINE_RE = re.compile(r"\[\^([A-Za-z0-9._-]+)\](?!:)")

# Wave 1 §2.1a (2026-05-26): writer-emitted References-section detector.
# The 2026-05-26 id=91 morning smoke surfaced articles where the writer
# emitted its own ``## N References`` (or ``## References``) section at
# the end of a body section — typically with bare ``[^N]`` markers above
# each ``[^N]: source`` line as a "preview/anchor" pattern the writer
# invented. Verified pattern from gap-map §2.1a:
#   ## 29 References
#   [^1]
#   [^1]: Seiyapedia (Fandom), "Cloths," — https://...
#   [^2]
#   [^2]: Wikipedia contributors, ...
# The default ``normalize`` flow extracted those defs, renumbered the
# bare-marker inlines (since they had matching defs), stripped the def
# lines, and appended a NEW ``## References`` block — but left the
# orphan ``## 29 References`` heading and the bare markers in body,
# producing a malformed article with DUPLICATE References headings +
# 32 stray ``[^N]`` markers. To fix, we strip any writer-emitted
# References section in the body BEFORE the inline-renumber + def-strip
# steps. Definitions inside the section are captured BY THE EARLIER
# def-scan (which sees the unmodified article), so they survive into
# the final clean ``## References`` block.
#
# Match permissively: optional leading whitespace, then ``##`` (level-2
# heading per the writer prompt's HEADING-HASH MAPPING rule), optional
# numbering (``29 ``, ``12. ``, ``5 `` etc.), then ``References`` or
# ``Reference`` followed by a word boundary. The match extends to the
# next markdown heading of ANY depth (``#+``) or end-of-string.
#
# Greptile PR #29 follow-up (2026-05-26): the lookahead originally used
# ``#{1,2}`` which only stopped at H1/H2 headings. An H3+ heading
# (``### M Sub-section``) appearing directly after the writer's bogus
# References block — before any H2 — would have been silently swallowed
# along with the refs content. The writer's HEADING-HASH MAPPING rule
# conventionally puts ``##`` for top-level sections so this scenario is
# unusual, but the failure is content-destructive. Widening to ``#+``
# (any heading depth) makes the strip stop at the first heading after
# the References block regardless of depth.
_WRITER_REFS_SECTION_RE = re.compile(
    r"^[ \t]*##[ \t]+\d*\.?[ \t]*References?\b.*?(?=^[ \t]*#+[ \t]|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


@dataclass
class FootnoteNormalizeOutput:
    article: str
    n_definitions: int
    n_inline_markers: int
    n_orphans_stripped: int
    n_unused_dropped: int
    n_renumbered: int
    # P3b-D2: how many used def-tokens collapsed into a smaller set of distinct
    # sources (used_tokens − distinct_sources). High = the writer is creating a
    # new token per citation of the same source; the dedup raises reuse toward
    # the reference's range. 0 = every cited token was already a distinct source.
    n_sources_merged: int = 0
    # Wave 1 §2.1a: count of writer-emitted ``## References`` sections
    # removed from the body before normalize processing. Non-zero means
    # the writer is inventing its own References blocks — a writer-side
    # behaviour worth telemetering separately from the orphan / unused
    # counters above.
    n_writer_refs_sections_stripped: int = 0


def normalize(article: str, references_heading: str = "References") -> FootnoteNormalizeOutput:
    """Merge per-section footnote markers into one global ``## References`` block.

    Steps:
      1. Extract every ``[^token]: text`` definition; remember the source line
         so we can strip it from the body later.
      2. Walk the article in document order, replacing each ``[^token]`` inline
         marker with ``[^N]`` where N is a fresh global sequence number. Markers
         whose token has no matching definition are stripped (orphans).
      3. Strip every original definition LINE from the body.
      4. Append ``## {references_heading}\n\n[^1]: ...\n[^2]: ...\n`` at the
         article end, in order of first appearance.

    Early-exit on articles with NO ``[^X]:`` definitions: returns the body
    unchanged with all stats == 0 (no References block appended).

    NOT idempotent on already-normalized articles. A second pass would
    detect the ``[^N]: ...`` definitions inside the ``## References``
    block as legitimate definitions, strip those lines, then append a
    NEW ``## References`` block at the end — leaving the original
    ``## References`` heading orphaned in the body (duplicate heading).
    Call this exactly once per article. The orchestrator (see
    ``orchestrate.from_plan``) runs it once after writer assembly and
    before numbering_fix; do not add a retry or re-process path that
    re-applies it without first stripping the prior References block.
    """
    # Step 1: collect every (token → definition_text) from `[^X]:` lines.
    # MUST run on the unmodified article so defs inside any writer-emitted
    # ``## References`` section (stripped in Step 1.5 below) are still
    # captured.
    # Greptile PR #24 follow-up (2026-05-25): dropped the parallel
    # `definition_spans` list. It was built every run (including the
    # `line_end + 1` newline-inclusion logic) but never consumed — Step 3
    # below re-scans with `_DEFINITION_RE.sub("", body_renum)` because the
    # substitution at Step 2 shifts offsets and invalidates the spans
    # anyway. Keeping the dead list misled readers into thinking offset
    # tracking was load-bearing.
    definitions: dict[str, str] = {}
    for m in _DEFINITION_RE.finditer(article):
        token = m.group(1)
        text = m.group(2).strip()
        if token not in definitions:
            definitions[token] = text

    # Step 1.5 (Wave 1 §2.1a, 2026-05-26): strip any writer-emitted
    # ``## References`` section from the body BEFORE inline renumbering.
    # The writer occasionally invents its own References block at the end
    # of a body section with bare ``[^N]`` markers above each ``[^N]:``
    # definition line. Defs were already captured in Step 1 from the
    # unmodified article, so removing the writer's section here loses
    # nothing — it just prevents the bare markers and the orphan
    # heading from surviving into the final article alongside the
    # canonical ``## References`` block we append in Step 4.
    article, n_writer_refs_stripped = _WRITER_REFS_SECTION_RE.subn("", article)
    # Collapse any blank-line storm the strip introduced.
    if n_writer_refs_stripped:
        article = re.sub(r"\n{3,}", "\n\n", article).rstrip() + "\n"

    if not definitions:
        return FootnoteNormalizeOutput(
            article=article,
            n_definitions=0,
            n_inline_markers=0,
            n_orphans_stripped=0,
            n_unused_dropped=0,
            n_renumbered=0,
            n_writer_refs_sections_stripped=n_writer_refs_stripped,
        )

    # Step 2: walk article in document order, assign global numbers by SOURCE
    # (not token), in order of first inline appearance. Tokens whose definition
    # resolves to the same source share one number (P3b-D2 dedup).
    token_to_source: dict[str, str] = {tok: _def_source_key(text) for tok, text in definitions.items()}
    source_to_n: dict[str, int] = {}
    token_to_n: dict[str, int] = {}  # used tokens → their source's number
    n_seq = 0
    n_orphans = 0
    n_renum = 0

    def repl(m: re.Match) -> str:
        nonlocal n_seq, n_orphans, n_renum
        tok = m.group(1)
        if tok not in definitions:
            n_orphans += 1
            return ""  # strip orphan marker silently
        src = token_to_source[tok]
        if src not in source_to_n:
            n_seq += 1
            source_to_n[src] = n_seq
        token_to_n[tok] = source_to_n[src]
        n_renum += 1
        return f"[^{source_to_n[src]}]"

    body_renum = _INLINE_RE.sub(repl, article)
    n_sources_merged = len(token_to_n) - len(source_to_n)

    # Step 3: strip every original definition line from the (renumbered) body.
    # Re-scan because the substitution may have shifted line positions; we
    # also want to catch definitions whose tokens were never inlined (unused).
    n_unused = sum(1 for tok in definitions if tok not in token_to_n)
    # Strip ALL definition lines, regardless of whether their token was used.
    body_stripped = _DEFINITION_RE.sub("", body_renum)
    # Collapse the blank lines left where definitions used to live.
    body_stripped = re.sub(r"\n{3,}", "\n\n", body_stripped).rstrip() + "\n"

    # Step 4: append the global References block, in global-numbering order.
    if not token_to_n:
        # All references were orphans/unused; nothing to render. Keep body
        # clean (no empty References section).
        return FootnoteNormalizeOutput(
            article=body_stripped,
            n_definitions=len(definitions),
            # Greptile PR #24 round-2 follow-up: n_inline_markers is the
            # RAW count of inline markers found in the body, including
            # orphans whose token had no matching definition. The previous
            # `n_renum` undercounted (orphan inlines were silently
            # excluded), which made any downstream "orphan rate" telemetry
            # (n_orphans_stripped / n_inline_markers) nonsense — the
            # denominator excluded the orphans themselves. The matched
            # subset is still recoverable as n_inline_markers - n_orphans_stripped.
            n_inline_markers=n_renum + n_orphans,
            n_orphans_stripped=n_orphans,
            n_unused_dropped=n_unused,
            n_renumbered=0,
            n_sources_merged=n_sources_merged,
            n_writer_refs_sections_stripped=n_writer_refs_stripped,
        )
    refs_lines = [f"## {references_heading}", ""]
    # Iterate by N order, so the output is naturally sorted 1, 2, 3. Under
    # source-dedup multiple tokens share a number; take the FIRST token (by
    # first inline appearance) for the def text — all tokens at a number
    # resolve to the same source, so any is correct, but first is deterministic.
    n_to_token: dict[int, str] = {}
    for tok, n in token_to_n.items():
        n_to_token.setdefault(n, tok)
    for n in sorted(n_to_token):
        refs_lines.append(f"[^{n}]: {definitions[n_to_token[n]]}")
    refs_lines.append("")
    refs_block = "\n".join(refs_lines)

    final = body_stripped.rstrip() + "\n\n" + refs_block

    return FootnoteNormalizeOutput(
        article=final,
        n_definitions=len(definitions),
        # See identical fix above (n_renum + n_orphans) for rationale —
        # n_inline_markers is the raw scan count, not the matched subset.
        n_inline_markers=n_renum + n_orphans,
        n_orphans_stripped=n_orphans,
        n_unused_dropped=n_unused,
        # Number of distinct global numbers = References entries. Under dedup
        # this is the distinct-source count (≤ used-token count).
        n_renumbered=len(source_to_n),
        n_sources_merged=n_sources_merged,
        n_writer_refs_sections_stripped=n_writer_refs_stripped,
    )
