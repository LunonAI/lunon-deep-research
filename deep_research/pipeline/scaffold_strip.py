"""Round 5 T1-PR1: residual-scaffolding strip (deterministic post-assembly).

The round-4 dev run shipped id=89 with raw CAPEL countdown markers visible in
the body — `<5093`, `<4788`, `<6904`, `<4898` — and the gemini judge scored its
"Professional Formatting/Layout" 2.0/10 ("raw scaffolding / unprofessional").

Why the existing strip missed them: ``_capel_strip._MARKER_RE`` is ``<\\d{1,5}>``
— it requires a CLOSING ``>``. These markers had NONE (the writer truncated
mid-marker, so ``<4898`` shipped open). The closed-form strip found nothing.

Scope — CAPEL open-markers ONLY. Inspection of id=89 showed the co-leaked
``R-N`` / ``AC-n`` tokens the scaffold *detector* counts are in fact
LEGITIMATE CONTENT here (a ``| R-1 | Theoretical Novelty | 15% |`` rubric table
and prose like "satisfies acceptance criterion AC10"), so stripping them would
CORRUPT real content. They are intentionally NOT touched. The open CAPEL
marker is the only unambiguous leak: a bare ``<dddd`` sitting at a line end has
no legitimate meaning (a real numeric comparison "values <50 mg/L" is followed
by a space+word, never a line break).

Run on the FINAL assembled article (after numbering_fix, before cjk_despace) so
it also catches a marker left at a mid-sentence truncation seam. Span-masked
(code/tables/headings/footnote-defs protected), idempotent, fail-soft.
"""

from __future__ import annotations

import re

from .style_clamp import _in_ranges, _protected_ranges

# Open (unclosed) CAPEL countdown marker leaked at a LINE END. The id=89 leaks
# (`<5093`, `<4788`, `<6904`, `<4898`) all sat at a paragraph end (immediately
# before `\n\n`) — that is the observed failure mode, and the line-end anchor is
# what makes the strip precise: a real inline numeric comparison ("values <50
# mg/L") is followed by a space+word, NOT a line break, so it is never matched.
# The end-of-line lookahead also rejects the CLOSED form `<4898>` (next char is
# `>`, not whitespace/newline) — that stays the job of the existing
# `_capel_strip`. `\d{2,5}` (not `\d{1}`) avoids a stray `<5` at a line end.
_CAPEL_OPEN_RE = re.compile(r"<\d{2,5}(?=[ \t]*(?:\n|$))")


def strip_residual_scaffolding(article: str) -> tuple[str, dict]:
    """Remove leaked open CAPEL countdown markers from the shipped article.

    Span-masked: code fences, markdown tables, ATX headings and footnote
    definition lines (via ``style_clamp._protected_ranges``) are never edited,
    so a real ``<5093`` inside a code block survives. Idempotent (a second pass
    is a no-op). Returns ``(article, stats)``; fail-soft on non-string/empty.
    """
    stats = {"capel_open": 0, "n_total": 0}
    if not isinstance(article, str) or not article:
        return article, stats

    protected = _protected_ranges(article)
    spans = [(m.start(), m.end()) for m in _CAPEL_OPEN_RE.finditer(article) if not _in_ranges(m.start(), protected)]
    if not spans:
        return article, stats

    out: list[str] = []
    last = 0
    for s, e in spans:
        seg = article[last:s]
        prev = seg[-1] if seg else ""  # char right before the token
        nxt = article[e] if e < len(article) else ""  # char right after
        if prev in " \t" and nxt in " \t":
            # space on BOTH sides -> drop the trailing space (no doubled space)
            e += 1
        elif prev in " \t" and nxt in ("", "\n"):
            # token alone at a line end ("boundary) <4788\n") -> drop the
            # leading space so no trailing whitespace is left before the break
            seg = seg[:-1]
        out.append(seg)
        last = e
        stats["capel_open"] += 1
    out.append(article[last:])

    stats["n_total"] = stats["capel_open"]
    return "".join(out), stats
