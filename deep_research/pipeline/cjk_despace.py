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
    r"|\[\^[^\]\n]*\]:?"  # [^ref]  and  [^ref]: definition lead
    r"|\[[^\]\n]*\]\[[^\]\n]*\]"  # [anchor text][ref-id] reference-style links
    r"|\[[^\]\n]+\](?!\()"  # bare [ref-id] labels
    r"|`[^`\n]*`"  # inline code
)

# G7 sibling: leaked RACE scaffolding. Strip the `Per the rubric` connective
# (with optional leading/trailing punctuation/space) — conservative: only the
# scaffolding phrase is removed, the surrounding clause stays. Greptile PR #66
# round-2 (2026-05-29): the surrounding whitespace is matched as `[^\S\n]`
# (horizontal only) so a phrase at a paragraph start can't swallow the
# preceding newline and silently merge two paragraphs.
_BOILERPLATE_RE = re.compile(r"[^\S\n]*(?:[，,（(][^\S\n]*)?[Pp]er the rubric[,，]?[^\S\n]*")


def _strip_boilerplate(text: str) -> tuple[str, int]:
    out, n = _BOILERPLATE_RE.subn(" ", text)
    if n:
        # Tidy the seams the strip leaves (double spaces / space-before-punct).
        # Greptile PR #66 round-3 (2026-05-29): both passes use HORIZONTAL
        # whitespace only ([ \t]) so a boilerplate strip anywhere in the article
        # can never collapse a paragraph break elsewhere (a body line that
        # happens to start with `.`/`,` — common in CJK continuation contexts —
        # must keep its preceding newline). Mirrors the `[^\S\n]` intent of
        # _BOILERPLATE_RE.
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r"[ \t]+([.,;:!?])", r"\1", out)
    return out, n


# Languages whose prose can carry CAPEL CJK spacing. A label outside this set
# is treated as an explicit "skip the CJK scan" override (see despace()).
_CJK_LANGS = frozenset({"zh", "ja", "ko"})


def despace(text: str, language: str | None = None) -> tuple[str, dict]:
    """Collapse CAPEL-induced spaces between adjacent CJK chars (and between a
    CJK char and CJK punctuation), scoped to body prose. Also strips the
    `Per the rubric` scaffolding leak. Returns (text, stats)."""
    stats = {"cjk_space_collapsed": 0, "boilerplate_stripped": 0}
    if not isinstance(text, str) or not text:
        return text, stats

    # Greptile PR #66 round-5: strip any pre-existing NUL up front so the
    # `\x00…\x00` stash sentinels below stay unambiguous. Otherwise a
    # NUL-contaminated input (malformed API chunk, binary bleed) could be
    # mis-read by the restore pass as a stash marker, IndexError into
    # `protected`, and crash the run — this phase promises never to raise.
    text = text.replace("\x00", "")

    # Mask protected spans (inline/reference links, footnote refs, inline code)
    # FIRST so neither the boilerplate strip nor the CJK de-spacer can reach
    # inside a span (Greptile PR #66 round-5: a "[Per the rubric …](url)" anchor
    # must not be mangled by the boilerplate strip running on raw text).
    protected: list[str] = []

    def _stash(m: re.Match) -> str:
        protected.append(m.group(0))
        return f"\x00{len(protected) - 1}\x00"

    def _restore(s: str) -> str:
        return re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], s)

    masked = _PROTECT_RE.sub(_stash, text)

    # Strip the `Per the rubric` scaffolding leak (EN and ZH alike) on masked
    # prose only — spans are already hidden, so a link/code interior is safe.
    masked, n_bp = _strip_boilerplate(masked)
    stats["boilerplate_stripped"] = n_bp

    # De-spacing only matters for CJK-bearing articles. A confidently non-CJK
    # `language` label (e.g. "en") is an explicit override that skips the scan;
    # otherwise the Hanzi-count guard — robust to an absent/mislabeled label —
    # is authoritative. (Greptile PR #66 round-2: makes `language` a real gate
    # instead of an ignored parameter.) Round-4: split on BOTH `-` and `_` so
    # underscore locales ("zh_CN") yield primary subtag "zh".
    if language is not None and re.split(r"[-_]", language)[0].strip().lower() not in _CJK_LANGS:
        return _restore(masked), stats
    if len(re.findall(rf"[{_CJK}]", masked)) < 50:
        return _restore(masked), stats

    # Collapse CJK↔CJK and CJK↔CJK-punct spaces on the masked prose.
    masked, n1 = re.subn(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK}{_CJK_PUNCT}])", "", masked)
    masked, n2 = re.subn(rf"(?<=[{_CJK_PUNCT}])[ \t]+(?=[{_CJK}])", "", masked)
    stats["cjk_space_collapsed"] = n1 + n2

    return _restore(masked), stats
