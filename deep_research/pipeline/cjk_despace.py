"""G7 (2026-05-28): ZH-aware de-spacing post-pass.

Lunon's ZH bodies show 6–13% spaced-CJK boundaries (id14 ch8 tier-ranking
40.8%, ch9 24.6%; id37 ch11 78.5%) — `本 章 的 分 组 方 式` reads as broken
Chinese to the ZH judge and concentrates in the Insight/Comp payload chapters,
so the penalty bleeds beyond Readability. Root cause: the CAPEL rejoin pass
(`_capel_strip`) is provably English-only (ASCII regexes, vowel/consonant
guards, English stopwords, an English word-length band), so single-Hanzi
CAPEL fragments are never rejoined. The clean the reference corpus is ~0.01–0.03%
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
# A3 (2026-05-29): the de-spacer originally only collapsed ASCII space/tab
# (`[ \t]`), but the gemini judge still flagged "异常空格/不可见字符" between
# Hanzi — the model emits NBSP (U+00A0), zero-width space (U+200B), BOM /
# zero-width-no-break (U+FEFF), full-width space (U+3000), and the thin/figure/
# narrow spaces (U+2000–U+200A, U+202F). Collapse all of them between CJK
# boundaries. Scoped to inter-CJK only (via the lookbehind/lookahead), so
# legitimate spacing elsewhere (incl. CJK↔Latin) is untouched.
_ABNORMAL_WS = r" \t\u00a0\u200b\ufeff\u3000\u2000-\u200a\u202f"

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


# L5 (2026-05-29): leaked internal scaffolding tokens that the reference
# head-to-head saw as reader-facing junk in CJK prose (本报告的契约, bare AC19/
# R-1..R-6 rubric/criterion ids). Strip `本报告的契约` (always our literal
# contract phrase) and bare AC\d / R-\d ONLY when adjacent to a CJK ideograph
# (a CJK-prose leak). EN tier-ranking R-N (in tables / EN prose, never
# CJK-adjacent) and legitimate "AC"/"R-2" usage are untouched — and it runs on
# the MASKED text so links/footnotes/code are shielded.
#
# Greptile PR #69 round-1 (2026-05-29): this is CJK-gated, NOT strictly ZH. The
# pass runs on any article that clears despace()'s CJK guard, and
# `_CJK_LANGS = {zh, ja, ko}`, so JA/KO articles are de-scaffolded too. That is
# intentional: an AC19/R-2 rubric id abutting a Han ideograph is a scaffolding
# leak in Kanji/Hanja prose exactly as in Hanzi, and the ZH-only `本报告的契约`
# literal simply never appears in JA/KO output (harmless there). The adjacency
# class reuses `_CJK` (Unified Ideographs + Ext A) so it can never drift from the
# de-spacer's own CJK definition — hence the rename from `_ZH_SCAFFOLD_RE`.
#
# `\b` can't be used as the token boundary here: CJK chars are word characters
# in Unicode mode, so there is NO `\b` between a digit and an adjacent ideograph.
# Use explicit non-alnum guards instead so a CJK-sandwiched AC19/R-2 matches
# while EN tokens (preceded/followed by ASCII letters) are left intact.
_CJK_SCAFFOLD_RE = re.compile(
    r"本报告的契约"
    r"|(?<=[" + _CJK + r"])[ \t]*(?:AC\d{1,3}|R-\d{1,2})(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])(?:AC\d{1,3}|R-\d{1,2})[ \t]*(?=[" + _CJK + r"])"
)

# Languages whose prose can carry CAPEL CJK spacing. A label outside this set
# is treated as an explicit "skip the CJK scan" override (see despace()).
_CJK_LANGS = frozenset({"zh", "ja", "ko"})


def despace(text: str, language: str | None = None) -> tuple[str, dict]:
    """Collapse CAPEL-induced spaces between adjacent CJK chars (and between a
    CJK char and CJK punctuation), scoped to body prose. Also strips the
    `Per the rubric` scaffolding leak. Returns (text, stats)."""
    stats = {"cjk_space_collapsed": 0, "boilerplate_stripped": 0, "scaffold_stripped": 0}
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

    # Collapse CJK↔CJK and CJK↔CJK-punct spaces on the masked prose. A3: the
    # whitespace class is `_ABNORMAL_WS` (ASCII space/tab + NBSP/zero-width/
    # BOM/full-width/thin/narrow) so the model's invisible-space artifacts
    # between Hanzi are collapsed, not just ASCII spaces.
    masked, n1 = re.subn(rf"(?<=[{_CJK}])[{_ABNORMAL_WS}]+(?=[{_CJK}{_CJK_PUNCT}])", "", masked)
    masked, n2 = re.subn(rf"(?<=[{_CJK_PUNCT}])[{_ABNORMAL_WS}]+(?=[{_CJK}])", "", masked)
    stats["cjk_space_collapsed"] = n1 + n2

    # L5: strip leaked internal scaffolding tokens from CJK body prose (zh/ja/ko).
    masked, n3 = _CJK_SCAFFOLD_RE.subn("", masked)
    stats["scaffold_stripped"] = n3

    return _restore(masked), stats
