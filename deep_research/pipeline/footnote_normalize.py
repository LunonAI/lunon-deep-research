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

# Definition pattern: ``[^token]: definition text`` anchored to line start.
# Token may include letters, digits, dots, hyphens, underscores — enough to
# cover the architect's section_id shapes ("S1", "S1.1", "S3.2.4") and any
# legacy plain-numeric markers ("1", "12") that survive from older writers.
_DEFINITION_RE = re.compile(r"^[ \t]*\[\^([A-Za-z0-9._-]+)\]:[ \t]*(.+?)[ \t]*$", re.MULTILINE)

# Inline-marker pattern: ``[^token]`` NOT followed by a colon. The negative
# lookahead ``(?!:)`` avoids matching the definition form, which we handle
# separately above.
_INLINE_RE = re.compile(r"\[\^([A-Za-z0-9._-]+)\](?!:)")


@dataclass
class FootnoteNormalizeOutput:
    article: str
    n_definitions: int
    n_inline_markers: int
    n_orphans_stripped: int
    n_unused_dropped: int
    n_renumbered: int


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

    if not definitions:
        return FootnoteNormalizeOutput(
            article=article,
            n_definitions=0,
            n_inline_markers=0,
            n_orphans_stripped=0,
            n_unused_dropped=0,
            n_renumbered=0,
        )

    # Step 2: walk article in document order, assign fresh global numbers
    # to each unique token in order of first inline appearance.
    token_to_n: dict[str, int] = {}
    n_seq = 0
    n_orphans = 0
    n_renum = 0

    def repl(m: re.Match) -> str:
        nonlocal n_seq, n_orphans, n_renum
        tok = m.group(1)
        if tok not in definitions:
            n_orphans += 1
            return ""  # strip orphan marker silently
        if tok not in token_to_n:
            n_seq += 1
            token_to_n[tok] = n_seq
        n_renum += 1
        return f"[^{token_to_n[tok]}]"

    body_renum = _INLINE_RE.sub(repl, article)

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
        )
    refs_lines = [f"## {references_heading}", ""]
    # Iterate by N order, not insertion-into-token_to_n order, so the output
    # is naturally sorted 1, 2, 3 even if dict ordering ever changes.
    n_to_token = {n: tok for tok, n in token_to_n.items()}
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
        n_renumbered=len(token_to_n),
    )
