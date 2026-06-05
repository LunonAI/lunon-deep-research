"""Phase 3 (2026-06-04): deterministic redundancy/density clamp.

The GPT-5.5 judge's verbatim readability complaint across dev6 was "极度冗长，重复
使用'究其根本''由此可以预见'等句式". Measured: id-38 ships 142 formulaic sentence-opening
connectives (由此可以预见×50, 可以预见×50, 值得注意的是×23, 究其根本×18); id-37=35; id-8=26
— while Qianfan #1 uses ~4-5 TOTAL per article. These markers carry zero content;
their repetition is a pure readability tax and a machine-assembled tell.

`clamp_connectives` caps each formulaic opener at a small budget (Qianfan's level):
it keeps the first N sentence-initial occurrences and strips the phrase (+ its
trailing comma) from the rest, leaving the CLAUSE intact — no fact, number, or
citation is ever removed. Protected-range-safe (never edits headings/tables/code/
footnote-defs) via style_clamp utilities. ZH-only; fail-soft + idempotent.
Kill-switch DR_DENSITY_CLAMP=off.
"""

from __future__ import annotations

import os
import re

from .style_clamp import _in_ranges, _protected_ranges

_ENABLED = os.environ.get("DR_DENSITY_CLAMP", "on") != "off"

# Formulaic sentence-opening connectives over-used by our ZH writer. Ordered
# LONGEST-first so a super-phrase (由此可以预见) is clamped before its sub-phrase
# (可以预见), preventing a double-strip.
_CONNECTIVES = [
    "由此可以预见",
    "值得注意的是",
    "由此不难看出",
    "由此可以看出",
    "需要指出的是",
    "归根结底",
    "综上所述",
    "总而言之",
    "总的来说",
    "究其根本",
    "由此可见",
    "不难发现",
    "不难看出",
    "可以预见",
    "换言之",
]
# Keep this many sentence-initial occurrences PER phrase (Qianfan ≈4-5 total
# across all of them); strip the repeats.
_KEEP_PER_PHRASE = 2
_SENT_BOUNDARY = set("。！？；：…」』）.!?\n")
_TRAILING = set("，、：,")


def _strip_excess(text: str, phrase: str, keep: int) -> tuple[str, int]:
    """Keep the first `keep` sentence-initial occurrences of `phrase`; strip the
    rest (phrase + a trailing comma). Recomputes protected ranges on `text`."""
    protected = _protected_ranges(text)
    spans: list[tuple[int, int]] = []
    kept = 0
    for m in re.finditer(re.escape(phrase), text):
        s = m.start()
        if _in_ranges(s, protected):
            continue
        # sentence-initial = preceding non-space char is a boundary (or start)
        j = s - 1
        while j >= 0 and text[j] in " \t":
            j -= 1
        if not (j < 0 or text[j] in _SENT_BOUNDARY):
            continue
        kept += 1
        if kept <= keep:
            continue
        e = m.end()
        if e < len(text) and text[e] in _TRAILING:
            e += 1
        spans.append((s, e))
    for s, e in reversed(spans):
        text = text[:s] + text[e:]
    return text, len(spans)


def clamp_connectives(article: str, *, language: str | None = None) -> tuple[str, dict]:
    stats: dict = {"stripped": 0, "per_phrase": {}}
    if not _ENABLED or language != "zh" or not isinstance(article, str) or not article.strip():
        return article, stats
    try:
        out = article
        for phrase in _CONNECTIVES:
            out, n = _strip_excess(out, phrase, _KEEP_PER_PHRASE)
            if n:
                stats["per_phrase"][phrase] = n
                stats["stripped"] += n
        return out, stats
    except Exception:  # noqa: BLE001 — post-pass must never break the run
        return article, stats
