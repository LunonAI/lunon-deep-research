"""G7 (2026-05-28): ZH-aware de-spacing post-pass.

Lunon's ZH bodies show 6–13% spaced-CJK boundaries (id14 ch8 tier-ranking
40.8%, ch9 24.6%; id37 ch11 78.5%) — `本 章 的 分 组 方 式` reads as broken
Chinese to the ZH judge and concentrates in the Insight/Comp payload chapters,
so the penalty bleeds beyond Readability. Root cause: the CAPEL rejoin pass
(`_capel_strip`) is provably English-only (ASCII regexes, vowel/consonant
guards, English stopwords, an English word-length band), so single-Hanzi
CAPEL fragments are never rejoined. The clean Qianfan corpus is ~0.01–0.03%
spaced-CJK — and those are real spaces inside source-title link anchors
(`[锚定新质生产力 券商投行全生命周期]`).

So this pass MUST be scoped to body prose: link/anchor text, footnote refs,
footnote-def leads, and inline code are masked out before de-spacing and
restored after — otherwise it would mangle the exact nested-link-title pattern
Lunon is trying to emulate.

A conservative sibling strip removes the leaked `Per the rubric` RACE-scaffolding
connective (the per-entity rubric-scoring micro-template leaking internal
dimension scaffolding into reader-facing prose; id14 ×12, id91 EN ×49).

Deterministic, no LLM. Fail-soft: bad input → returned unchanged, never raises.
"""

import re

# CJK Unified Ideographs + Extension A (covers the Hanzi the CAPEL pass shreds).
_CJK = r"一-鿿㐀-䶿"
# Full-width CJK punctuation that legitimately abuts Hanzi with no space.
_CJK_PUNCT = "，。、；：！？（）【】《》「」“”‘’—…·"

# Spans whose internal spaces are MEANINGFUL and must be protected from the
# de-spacer: markdown/image links + their anchor text, footnote refs and
# definition leads, and inline code. Stashed behind a NUL sentinel, restored
# after de-spacing.
_PROTECT_RE = re.compile(
    r"!?\[[^\]\n]*\]\([^)\n]*\)"  # [anchor text](url) / ![alt](src)
    r"|\[\^[^\]\n]*\]:?"          # [^ref]  and  [^ref]: definition lead
    r"|`[^`\n]*`"                 # inline code
)

# G7 sibling: leaked RACE scaffolding. Strip the `Per the rubric` connective
# (with optional leading/trailing punctuation/space) — conservative: only the
# scaffolding phrase is removed, the surrounding clause stays.
_BOILERPLATE_RE = re.compile(r"\s*(?:[，,（(]\s*)?[Pp]er the rubric[,，]?\s*")


def _strip_boilerplate(text: str) -> tuple[str, int]:
    out, n = _BOILERPLATE_RE.subn(" ", text)
    if n:
        # Tidy the seams the strip leaves (double spaces / space-before-punct).
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r"\s+([.,;:!?])", r"\1", out)
    return out, n


def despace(text: str, language: str | None = None) -> tuple[str, dict]:
    """Collapse CAPEL-induced spaces between adjacent CJK chars (and between a
    CJK char and CJK punctuation), scoped to body prose. Also strips the
    `Per the rubric` scaffolding leak. Returns (text, stats)."""
    stats = {"cjk_space_collapsed": 0, "boilerplate_stripped": 0}
    if not isinstance(text, str) or not text:
        return text, stats

    # The boilerplate strip applies to EN and ZH alike.
    text, n_bp = _strip_boilerplate(text)
    stats["boilerplate_stripped"] = n_bp

    # De-spacing only matters for CJK-bearing articles; cheap guard avoids the
    # mask/restore cost on pure-EN output.
    if len(re.findall(rf"[{_CJK}]", text)) < 50:
        return text, stats

    # 1. Mask protected spans.
    protected: list[str] = []

    def _stash(m: re.Match) -> str:
        protected.append(m.group(0))
        return f"\x00{len(protected) - 1}\x00"

    masked = _PROTECT_RE.sub(_stash, text)

    # 2. Collapse CJK↔CJK and CJK↔CJK-punct spaces.
    masked, n1 = re.subn(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK}{_CJK_PUNCT}])", "", masked)
    masked, n2 = re.subn(rf"(?<=[{_CJK_PUNCT}])[ \t]+(?=[{_CJK}])", "", masked)
    stats["cjk_space_collapsed"] = n1 + n2

    # 3. Restore protected spans.
    text = re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], masked)
    return text, stats
