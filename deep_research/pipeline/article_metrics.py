"""Advisory final-article metrics (2026-05-29).

Deterministic, read-only structural/cleanliness signals computed on the
ACTUALLY-SHIPPED article (after every post-pass). PURELY telemetry: this
module measures, it never gates or mutates — so adding it cannot change
pipeline output and therefore cannot confound the dev6 before/after A/B.

The signals and their reference-corpus reference values (measured 2026-05-29
across all 100 leaderboard articles; Lunon prior-dev6 in parentheses) — used
to read the numbers, NOT baked into any logic:

  heading_profile  the reference chapters live at H1 (~11.2 H1, H4+ ~0.05);
                   Lunon put chapters at H2 (1 H1) — the +1 hash-depth gap.
  frontload_ratio  mean first-third-chapter chars / last-third-chapter chars.
                   the reference 0.47 (late chapters RICHER); Lunon 1.5, max 2.53 —
                   the hollow-late-chapter signature, the cleanest structural
                   proxy for the Comprehensiveness gap. <1 good, >1 hollow tail.
  spaced_cjk_rate  fraction of CJK↔CJK adjacencies carrying whitespace.
                   the reference ~0.0006 (max .012); Lunon id37 hit 0.064 — verifies
                   the G7/A3 de-spacer on shipped output.
  scaffold_residual leaked internal scaffolding remaining in shipped prose.
                   the reference ~0; Lunon prior-dev6 had bare_R_n 134 (id91: 341),
                   where_one_might_expect 12 (id91: 55) — verifies the round-2
                   A1/A2/A5/L5 source fixes held end-to-end.
  para density     para_chars_p90 / frac_para_over_400c / para_sent_p90.
                   the reference p90 ~827c, 40% >400c; Lunon ZH is already leaner —
                   interpret archetype-aware (only EN list-all runs dense).

Fail-soft: any error → returns whatever was computed so far (never raises).
"""

import re
import statistics as _st

# Reuse the de-spacer's single-source-of-truth character classes so the
# spaced-CJK measurement can never drift from what the de-spacer actually
# collapses.
from .cjk_despace import _ABNORMAL_WS, _CJK

_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*$")
# Overlapping (zero-width lookahead) CJK-boundary counters. Greptile PR #70:
# a CONSUMING findall over `[CJK][CJK]` yields only ⌊N/2⌋ matches across a run
# of N adjacent CJK chars instead of the N−1 true boundaries — and the same
# under-count hits consecutive SPACED boundaries ("中 文 字"). Both numerator
# (spaced: ≥1 abnormal-ws) and denominator (all: ≥0 abnormal-ws) use lookaheads
# so every adjacency is counted exactly once. _ABNORMAL_WS excludes "\n", so a
# line break is not a boundary (matches the de-spacer's own scoping).
_CJK_ALL_ADJ_RE = re.compile(rf"(?=[{_CJK}][{_ABNORMAL_WS}]*[{_CJK}])")
_CJK_SPACED_ADJ_RE = re.compile(rf"(?=[{_CJK}][{_ABNORMAL_WS}]+[{_CJK}])")
_LEADING_INT_RE = re.compile(r"^(?:§\s*)?\d+(?:[.\s]|$)")
_CHAPTER_NUM_RE = re.compile(r"(?m)^#{1,6}\s+(?:§\s*)?(\d+)")
_SENT_SPLIT_RE = re.compile(r"[。！？.!?]+")

# Leaked internal scaffolding the round-2 source fixes were meant to remove.
# bare_R_n / AC_n are guarded so they do not match inside markdown links or
# alphanumeric runs (mirrors cjk_despace._CJK_SCAFFOLD_RE intent).
_SCAFFOLD_PATTERNS = {
    "per_the_rubric": re.compile(r"[Pp]er the rubric"),
    "where_one_might_expect": re.compile(r"[Ww]here one might expect"),
    "bare_R_n": re.compile(r"(?<![A-Za-z0-9\]])R-\d{1,2}\b"),
    "AC_n": re.compile(r"(?<![A-Za-z0-9])AC\d{1,3}\b"),
}
_CONTRACT_PHRASE = "本报告的契约"


def _headings(article):
    return [(len(m.group(1)), m.group(2).strip()) for m in _HEADING_RE.finditer(article)]


def _heading_profile(headings):
    prof = {"h1": 0, "h2": 0, "h3": 0, "h4plus": 0}
    for lvl, _ in headings:
        if lvl == 1:
            prof["h1"] += 1
        elif lvl == 2:
            prof["h2"] += 1
        elif lvl == 3:
            prof["h3"] += 1
        else:
            prof["h4plus"] += 1
    return prof


def _top_chapters(article, headings):
    """Split the article into top-level chapter bodies. The chapter level is the
    shallowest heading level whose text starts with an integer (the reference '# 1' →
    H1; Lunon '## 1' → H2). When chapters are numbered, slicing happens at the
    NUMBERED headings only — so a non-numbered title/preamble sharing that hash
    level (the reference's '# Title') is excluded from the chapter list rather than
    counted as a spurious tiny first chapter. Falls back to every shallowest-
    level heading when nothing is numbered."""
    if not headings:
        return [article]
    numbered = [lvl for lvl, t in headings if _LEADING_INT_RE.match(t)]
    if numbered:
        chap_lvl = min(numbered)
        slicer = re.compile(r"(?m)^" + ("#" * chap_lvl) + r"(?!#)\s+(?:§\s*)?\d+")
    else:
        chap_lvl = min(lvl for lvl, _ in headings)
        slicer = re.compile(r"(?m)^" + ("#" * chap_lvl) + r"(?!#)\s+.+$")
    idxs = [m.start() for m in slicer.finditer(article)]
    if len(idxs) < 2:
        return [article]
    idxs.append(len(article))
    return [article[idxs[i] : idxs[i + 1]] for i in range(len(idxs) - 1)]


def _frontload_ratio(chapters):
    """mean(first-third chapter chars) / mean(last-third chapter chars).
    >1 ⇒ later chapters are thinner (hollow tail). None if <3 chapters."""
    lens = [len(c) for c in chapters]
    n = len(lens)
    if n < 3:
        return None
    third = max(1, n // 3)
    back = _st.mean(lens[-third:])
    if not back:
        return None
    return round(_st.mean(lens[:third]) / back, 3)


def _numbering_anomalies(chapters):
    nums = []
    for c in chapters:
        m = _CHAPTER_NUM_RE.match(c)
        if m:
            nums.append(int(m.group(1)))
    if not nums:
        return 0
    n = 0
    if len(nums) != len(set(nums)):
        n += 1  # repeated chapter number
    if nums != list(range(nums[0], nums[0] + len(nums))):
        n += 1  # gap / out-of-order
    return n


def _prose_paragraphs(article):
    out = []
    for blk in re.split(r"\n\s*\n", article):
        b = blk.strip()
        if not b:
            continue
        first = b.splitlines()[0].lstrip()
        if first.startswith(("#", "|", "```", ">", "- ", "* ", "+ ")) or re.match(r"^\d+\.\s", first):
            continue
        if b.startswith("![") or b.startswith("[^"):
            continue
        out.append(b)
    return out


def _percentile(sorted_vals, q):
    if not sorted_vals:
        return 0
    return sorted_vals[min(len(sorted_vals) - 1, int(len(sorted_vals) * q))]


def _spaced_cjk_rate(article):
    """fraction of CJK↔CJK adjacencies that carry abnormal whitespace.
    None when the article has no adjacent CJK (e.g. an EN report)."""
    total = len(_CJK_ALL_ADJ_RE.findall(article))
    if not total:
        return None
    bad = len(_CJK_SPACED_ADJ_RE.findall(article))
    return round(bad / total, 5)


def _scaffold_residual(article):
    res = {k: len(p.findall(article)) for k, p in _SCAFFOLD_PATTERNS.items()}
    res["contract_phrase"] = article.count(_CONTRACT_PHRASE)
    return res


# P3b-v5 #2: a terminal LEAF = an H3+ heading with NO deeper child before the next
# heading. A STUB leaf has a near-empty body — the dev6 found 17-33% of Lunon's
# leaves were <120 chars (announce a number/table/timeline, deliver nothing),
# while the reference's leaves are full ~700-1000 CJK essays. The length lever (PR #74)
# should drive this toward 0 at the source; this measures whether it did.
_STUB_LEAF_MIN_CONTENT_CHARS = 120
# Distinct from _HEADING_RE (which captures the title text for the heading list).
# _leaf_stub_stats slices each leaf's body by character offset, so it needs the
# match SPAN (m.start()/m.end()), not the title — hence a separate pattern with no
# capture group. [ \t]+ (vs _HEADING_RE's \s+) keeps the match on a single line so
# m.end() lands at the heading's line end, exactly where the leaf body begins.
_HEADING_LINE_RE = re.compile(r"(?m)^(#{1,6})[ \t]+.+$")


def _leaf_stub_stats(article):
    """Return (n_leaves, n_stub_leaves) over H3+ TERMINAL leaves (a heading whose
    next heading is same-or-shallower, i.e. it has no child). A leaf is a stub if
    its body has fewer than _STUB_LEAF_MIN_CONTENT_CHARS non-whitespace chars."""
    heads = [(m.start(), m.end(), len(m.group(1))) for m in _HEADING_LINE_RE.finditer(article)]
    n_leaves = n_stub = 0
    for i, (_s, e, lvl) in enumerate(heads):
        if lvl < 3:
            continue
        # container check: if the next heading is DEEPER, this heading has a child
        # and is not a terminal leaf — skip it (its content lives in its children).
        if i + 1 < len(heads) and heads[i + 1][2] > lvl:
            continue
        body_end = heads[i + 1][0] if i + 1 < len(heads) else len(article)
        content = "".join(article[e:body_end].split())  # non-whitespace body chars
        n_leaves += 1
        if len(content) < _STUB_LEAF_MIN_CONTENT_CHARS:
            n_stub += 1
    return n_leaves, n_stub


def compute(article, *, language=None):
    """Compute advisory final-article metrics. Returns a flat dict; never
    raises (returns partial results on any internal error)."""
    metrics = {}
    if not isinstance(article, str) or not article.strip():
        return metrics
    try:
        headings = _headings(article)
        metrics["heading_profile"] = _heading_profile(headings)
        chapters = _top_chapters(article, headings)
        metrics["n_top_chapters"] = len(chapters)
        metrics["frontload_ratio"] = _frontload_ratio(chapters)
        metrics["numbering_anomalies"] = _numbering_anomalies(chapters)
        n_leaves, n_stub = _leaf_stub_stats(article)
        metrics["n_leaves"] = n_leaves
        metrics["stub_leaf_frac"] = round(n_stub / n_leaves, 3) if n_leaves else 0.0

        paras = _prose_paragraphs(article)
        plens = sorted(len(p) for p in paras)
        psent = sorted(len(_SENT_SPLIT_RE.findall(p)) for p in paras)
        metrics["n_prose_paragraphs"] = len(paras)
        metrics["para_chars_p90"] = _percentile(plens, 0.9)
        metrics["frac_para_over_400c"] = round(sum(1 for x in plens if x > 400) / len(plens), 3) if plens else 0.0
        metrics["para_sent_p90"] = _percentile(psent, 0.9)

        metrics["spaced_cjk_rate"] = _spaced_cjk_rate(article)
        metrics["scaffold_residual"] = _scaffold_residual(article)
    except Exception:  # noqa: BLE001 — advisory telemetry must never break the run
        pass
    return metrics
