"""Shared text-size heuristics (audit E2 / F2 consolidation).

A single CJK-aware token estimator so the engine's completeness gates agree
instead of disagreeing ~2.5× on CJK text (audit E2). Before this, the
chapter-completion gate (orchestrate._section_too_thin) used a CJK-aware
estimate (CJK ~1.6 chars/token, other ~4) while the validation length gate
(validation._section_length_ok) used a uniform ``len // 4`` — so a ZH section
could pass one gate and fail the other purely from the accounting mismatch,
triggering wasted corrective refiner passes (or masking a genuinely thin one).

CJK ideographs pack ~1.6 chars/token; other text ~4 chars/token. The CJK range
is sourced from ``cjk_despace._CJK`` (Unified Ideographs + Extension A) — the
single source of truth for the de-spacing pass — so token accounting can never
drift from the character class the rest of the pipeline uses.
"""

import re

from .pipeline.cjk_despace import _CJK as _CJK_RANGE

_CJK_RE = re.compile(f"[{_CJK_RANGE}]")
_CJK_CHARS_PER_TOKEN = 1.6
_OTHER_CHARS_PER_TOKEN = 4


def count_cjk(text: str) -> int:
    """Number of CJK ideographs (Unified + Extension A) in ``text``."""
    return sum(1 for _ in _CJK_RE.finditer(text)) if text else 0


def approx_tokens(text: str) -> int:
    """CJK-aware token estimate: CJK ~1.6 chars/token, other ~4 chars/token.

    For pure non-CJK text this equals the prior ``len(text) // 4`` (CJK count is
    0, so it reduces to ``int(len(text) / 4)``); only CJK text changes, which is
    the point — it is no longer under-counted at the non-CJK rate.
    """
    if not text:
        return 0
    cjk = count_cjk(text)
    other = len(text) - cjk
    return int(cjk / _CJK_CHARS_PER_TOKEN + other / _OTHER_CHARS_PER_TOKEN)


# --- Word counting (audit F2) -------------------------------------------------
# A CJK-aware *word* count, distinct from the token estimate above. It mirrors
# scripts/reference_style_profile.py — the script that defines the corpus
# word-count targets — and so intentionally uses the Unified-Ideographs range
# ONLY (not the broader Unified+Ext-A range approx_tokens uses for the
# de-spacing-aligned token estimate). The two have different sources of truth;
# keep them separate. This unifies the previously byte-identical copies in
# validation._wc and style_clamp._words.
_CJK_WORD_RE = re.compile(r"[一-鿿]")  # Unified Ideographs only — mirrors the profiler
_LATIN_WORD_RE = re.compile(r"[A-Za-z]+")
_CJK_HEAVY_FRACTION = 0.15
# Dedicated word-count constant, NOT _CJK_CHARS_PER_TOKEN: the word counter and
# the token estimator have different sources of truth (profiler vs de-spacing),
# so the separation is structural — tuning one tokenizer constant must not
# silently move the other. They happen to share the value 1.6 today.
_CJK_CHARS_PER_WORD = 1.6


def is_cjk_heavy(text: str) -> bool:
    """True when CJK ideographs exceed 15% of the characters — the profiler's
    threshold for treating text as space-less CJK (so .split() would undercount)."""
    return len(_CJK_WORD_RE.findall(text)) > _CJK_HEAVY_FRACTION * max(len(text), 1)


def approx_words(text: str) -> int:
    """CJK-aware word count mirroring scripts/reference_style_profile.py: CJK has
    no spaces so .split() undercounts — approximate CJK words as chars/1.6 plus
    Latin word runs; otherwise fall back to whitespace splitting. Always ≥1.

    Inlines the ``is_cjk_heavy`` threshold (rather than calling it) so the CJK
    scan runs once: the count it needs for the band math doubles as the
    heavy-text test."""
    cjk = len(_CJK_WORD_RE.findall(text))
    if cjk > _CJK_HEAVY_FRACTION * max(len(text), 1):  # same test as is_cjk_heavy
        latin = len(_LATIN_WORD_RE.findall(text))
        return max(int(cjk / _CJK_CHARS_PER_WORD) + latin, 1)
    return max(len(text.split()), 1)
