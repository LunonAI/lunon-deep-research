"""Phase A — Qianfan #1 leaderboard style profile.

Reads 10 Qianfan sample articles from `qianfan-dr-questions/` and computes
per-article metrics WITHOUT pulling full text into the calling agent's
context. Cross-references with our W9 articles for the 5 gate-verify IDs
({8, 20, 23, 56, 91}) so the diff between #1 and us is paired and visible.

Outputs:
- `p2_artifacts/qianfan_style_profile.md` — per-article rows + aggregate
  table + per-dim head-to-head against our W9 articles.
- `p2_artifacts/qianfan_profile.jsonl` — raw metrics (one row per article)
  for downstream tooling.

P2-Wave-2.5-D0 (2026-05-23): Fixed `.split()` CJK bug. Chinese text has no
whitespace between characters, so `len(text.split())` dramatically under-
counts ZH articles (id=23 reported 864 words but is actually ~16k word-
equivalents at 33,974 CJK chars). New `count_words_or_chars()` returns
true word count for EN and `n_cjk_chars / 2` word-equivalent for ZH. The
metrics dict now carries BOTH `n_words` (latin-style) and `n_cjk_chars`
(CJK count) so downstream consumers can pick the appropriate one.

Metrics extracted (all regex / counting; no LLM calls):
- word count, char count
- heading distribution by markdown depth (#, ##, ###, ####)
- top-level section count (lines matching `^\\d+ Title` or `^\\d+\\. Title`)
- paragraph length distribution (mean, median, p95)
- table count (markdown `|` separator lines)
- citation density: bare URL count, [n] markers, named source patterns
- date references: bare years 2020-2030, "Q[1-4]", "by 20XX", "by 年底"
- hedging vocab count (EN + ZH)
- forward-looking phrase count (EN + ZH)
- em-dash density
- opening structure check (first 200 words: contrarian? quantified? dated?)

Header parsing: each Qianfan file starts with `User Task 🎯 Task ID: <N>
Description: ... Generated Article 📖 <article>`. The article body starts
AFTER `Generated Article 📖`.
"""

from __future__ import annotations

import json

# Greptile follow-up (PR #16): paths resolved repo-relative so this script
# runs from any clone / CI. The W9 raw_results path remains overrideable via
# DR_W9_RESULTS to support the canonical DRB tree at /home/connor/dev/...
# on the dev box.
import os as _os
import re
import statistics
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
QIANFAN_DIR = _REPO_ROOT / "qianfan-dr-questions"
P1_FINAL = _REPO_ROOT / "p1_artifacts" / "p1_final.jsonl"
_DEFAULT_W9 = "/home/connor/dev/deep_research_bench/results/race/lunon-p1-2026-05-21-final/raw_results.jsonl"
W9_RAW = Path(_os.environ.get("DR_W9_RESULTS", _DEFAULT_W9))
OUT_MD = _REPO_ROOT / "p2_artifacts" / "qianfan_style_profile.md"
OUT_JSONL = _REPO_ROOT / "p2_artifacts" / "qianfan_profile.jsonl"

# Regex toolkit -------------------------------------------------------------

_HEADING_MD = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)
# Qianfan-style numbered headings: `1 Title`, `1.1 Title`, `1.1.1 Title`.
# Allow either `1 ` or `1. ` (dot optional).
_HEADING_NUM = re.compile(r"^(\d+(?:\.\d+){0,3})\.?\s+\S", re.MULTILINE)
# Top-level section opener: single-digit prefix, possibly with a dot.
_TOP_SECTION = re.compile(r"^(\d+)\.?\s+[^\d]", re.MULTILINE)
# Markdown table row marker: starts with `|` and contains another `|`.
_TABLE_ROW = re.compile(r"^\|.*\|.*$", re.MULTILINE)
# URLs.
_URL = re.compile(r"https?://[^\s)\]<>]+")
# [n] or [^n] footnote markers.
_FOOTNOTE_MARKER = re.compile(r"\[\^?\d+\]")
# Named-source-style citation: "<Capitalized> 20XX" e.g. "McKinsey 2024".
_NAMED_SOURCE = re.compile(r"\b[A-Z][A-Za-z&\-]+(?:\s+[A-Z][A-Za-z&\-]+)?\s+20\d\d\b")
# Bare year in document body.
_BARE_YEAR = re.compile(r"\b20\d\d\b")
# Forward-looking dates: "by Q[1-4]", "by 20XX", "through 20XX", "在 20XX 年".
_FORWARD_DATE = re.compile(
    r"\b(?:by\s+Q[1-4]|by\s+20\d\d|through\s+20\d\d|until\s+20\d\d)\b"
    r"|到\s*20\d\d\s*年"
    r"|至\s*20\d\d",
    re.I,
)
# Hedging vocabulary.
_HEDGE_EN = re.compile(
    r"\b(?:may|might|could|possibly|perhaps|likely|appears\s+to|seems\s+to|suggests|"
    r"approximately|roughly|broadly|tend\s+to|in\s+general|generally)\b",
    re.I,
)
_HEDGE_ZH = re.compile(r"(?:可能|或许|大致|大约|约|通常|一般|似乎|看起来|倾向于|趋势|预计|约莫)")
# Forward-looking phrases.
_FWD_EN = re.compile(
    r"\b(?:will\s+\w+|forecast|projected|expected\s+to|anticipated|on\s+track|"
    r"trajectory|trend|by\s+20\d\d|over\s+the\s+next|will\s+continue|likely\s+to)\b",
    re.I,
)
_FWD_ZH = re.compile(
    r"(?:未来|将\s*[一-鿿]|预计|预测|发展\s*趋势|趋势|展望|前景|前瞻|"
    r"预期|有望|逐步)"
)
# Em-dash (used heavily in Qianfan analytical prose).
_EMDASH = re.compile(r"——|—")
# Contrarian / framing vocabulary.
_CONTRARIAN_EN = re.compile(
    r"\b(?:despite|contrary\s+to|however|in\s+contrast|whereas|on\s+the\s+other\s+hand|"
    r"surprisingly|counter-?intuitive)\b",
    re.I,
)
_CONTRARIAN_ZH = re.compile(r"(?:尽管|然而|与之相反|相反|相比|对比|相对而言|与普遍|并非)")
# Causal-chain markers.
_CAUSAL_EN = re.compile(r"\b(?:because\s+\w+\s+then|leads\s+to\s+\w+\s+which|thereby|in\s+turn)\b", re.I)
_CAUSAL_ZH = re.compile(r"(?:导致.*进而|从而|因此|由此)")
# Quantified-range patterns.
_QUANT_RANGE = re.compile(r"\d+\s*[-–~至到]\s*\d+\s*(?:%|倍|x|×|year|个|月)?", re.I)

# Article extraction --------------------------------------------------------

_ARTICLE_MARKER = "Generated Article 📖"
_TASK_ID_RE = re.compile(r"Task\s+ID:\s*(\d+)")


def extract_article(path: Path) -> tuple[int | None, str]:
    """Return (task_id, article_body) from a Qianfan .txt file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    m = _TASK_ID_RE.search(text)
    tid = int(m.group(1)) if m else None
    idx = text.find(_ARTICLE_MARKER)
    if idx < 0:
        return tid, text
    body = text[idx + len(_ARTICLE_MARKER) :].lstrip()
    return tid, body


# Metric computation --------------------------------------------------------


_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def count_cjk_chars(text: str) -> int:
    """P2-Wave-2.5-D0: count CJK Unified Ideographs (and ext-A + compat) in
    `text`. Excludes punctuation, latin chars, and whitespace.

    Chinese-language articles have no whitespace between characters, so
    `text.split()` dramatically under-counts their length. This counts the
    actual ideographs, which approximately corresponds to "words" at
    ~2 CJK chars per word-equivalent (matching the `length_target` heuristic).
    """
    return len(_CJK_RE.findall(text))


def word_equivalents(text: str) -> int:
    """Return a unit-comparable length figure for EN/ZH/mixed text.

    EN: returns `text.split()` count.
    ZH (or mixed): returns max(latin_word_count, n_cjk_chars / 2).

    The max() handles mixed text where neither pure-split nor pure-CJK is
    correct (e.g. a ZH article with EN section titles, or vice versa).
    """
    latin = len(text.split())
    cjk = count_cjk_chars(text)
    # If text is mostly CJK, the latin count is misleading; if mostly latin,
    # the CJK count is zero. Use whichever is larger.
    return max(latin, cjk // 2)


def compute_metrics(article: str) -> dict:
    """Return a flat dict of style metrics for one article body."""
    words = article.split()
    n_words = len(words)
    n_chars = len(article)
    n_cjk = count_cjk_chars(article)
    # `length` is the unit-comparable figure used by aggregate tables.
    n_length = word_equivalents(article)

    # Heading distribution
    md_headings = _HEADING_MD.findall(article)
    md_depths = Counter(len(h) for h in md_headings)  # {1: count of '#', 2: of '##', ...}
    num_headings = _HEADING_NUM.findall(article)
    num_depths = Counter(h.count(".") + 1 for h in num_headings)

    # Top-level sections (numbered)
    top_sections = _TOP_SECTION.findall(article)
    n_top_sections = len(set(top_sections))

    # Paragraphs (blank-line split)
    paras = [p.strip() for p in re.split(r"\n\s*\n", article) if p.strip()]
    para_lengths = [len(p.split()) for p in paras]
    para_median = statistics.median(para_lengths) if para_lengths else 0
    para_p95 = statistics.quantiles(para_lengths, n=20)[-1] if len(para_lengths) >= 20 else max(para_lengths or [0])

    # Tables
    table_lines = _TABLE_ROW.findall(article)
    # Heuristic: every ~2 lines = 1 table row (header + separator + N body rows).
    # Count distinct table BLOCKS by gap-grouping table-row line numbers.
    table_blocks = 0
    if table_lines:
        # Use line indexing of original article to spot contiguous runs.
        line_is_table = [bool(_TABLE_ROW.match(line)) for line in article.splitlines()]
        in_block = False
        for is_t in line_is_table:
            if is_t and not in_block:
                table_blocks += 1
                in_block = True
            elif not is_t:
                in_block = False

    # Citation patterns
    n_urls = len(_URL.findall(article))
    n_footnotes = len(_FOOTNOTE_MARKER.findall(article))
    n_named_sources = len(_NAMED_SOURCE.findall(article))

    # Dates
    bare_years = _BARE_YEAR.findall(article)
    fwd_dates = _FORWARD_DATE.findall(article)

    # Hedging / forward-looking
    hedge_en = len(_HEDGE_EN.findall(article))
    hedge_zh = len(_HEDGE_ZH.findall(article))
    fwd_en = len(_FWD_EN.findall(article))
    fwd_zh = len(_FWD_ZH.findall(article))

    # Other style markers
    em_dashes = len(_EMDASH.findall(article))
    contrarian = len(_CONTRARIAN_EN.findall(article)) + len(_CONTRARIAN_ZH.findall(article))
    causal = len(_CAUSAL_EN.findall(article)) + len(_CAUSAL_ZH.findall(article))
    quant_ranges = len(_QUANT_RANGE.findall(article))

    # Opening analysis (first 200 words)
    head_words = words[:200]
    head_text = " ".join(head_words)
    head_has_thesis_sentence = bool(re.search(r"[.。!?！？]", head_text)) and len(head_words) > 10
    head_has_number = bool(re.search(r"\d", head_text))
    head_has_contrarian = bool(_CONTRARIAN_EN.search(head_text) or _CONTRARIAN_ZH.search(head_text))
    head_has_fwd_date = bool(_FORWARD_DATE.search(head_text) or _FWD_ZH.search(head_text))

    return {
        "n_words": n_words,
        "n_chars": n_chars,
        "n_cjk_chars": n_cjk,
        "n_length": n_length,
        "n_paragraphs": len(paras),
        "para_len_median": para_median,
        "para_len_p95": para_p95,
        "md_h1": md_depths.get(1, 0),
        "md_h2": md_depths.get(2, 0),
        "md_h3": md_depths.get(3, 0),
        "md_h4plus": sum(c for d, c in md_depths.items() if d >= 4),
        "num_h1": num_depths.get(1, 0),
        "num_h2": num_depths.get(2, 0),
        "num_h3": num_depths.get(3, 0),
        "num_h4plus": sum(c for d, c in num_depths.items() if d >= 4),
        "n_top_sections": n_top_sections,
        "n_table_blocks": table_blocks,
        "n_table_rows": len(table_lines),
        "n_urls": n_urls,
        "n_footnotes": n_footnotes,
        "n_named_sources": n_named_sources,
        "bare_years": len(bare_years),
        "fwd_dates": len(fwd_dates),
        "hedge_total": hedge_en + hedge_zh,
        "hedge_per_1k": round(1000 * (hedge_en + hedge_zh) / max(1, n_length), 2),
        "fwd_total": fwd_en + fwd_zh,
        "fwd_per_1k": round(1000 * (fwd_en + fwd_zh) / max(1, n_length), 2),
        "em_dashes": em_dashes,
        "contrarian_count": contrarian,
        "causal_count": causal,
        "quant_range_count": quant_ranges,
        "open_thesis": head_has_thesis_sentence,
        "open_quant": head_has_number,
        "open_contrarian": head_has_contrarian,
        "open_fwd_date": head_has_fwd_date,
    }


# Our W9 article extraction -------------------------------------------------


def load_p1_articles() -> dict[int, str]:
    """Load our W9 articles keyed by task_id."""
    out: dict[int, str] = {}
    if not P1_FINAL.exists():
        return out
    for line in P1_FINAL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            tid = int(d.get("id", -1))
        except (TypeError, ValueError):
            continue
        out[tid] = d.get("article", "")
    return out


def load_w9_scores() -> dict[int, dict]:
    """Load W9 per-task dim scores keyed by task_id."""
    out: dict[int, dict] = {}
    if not W9_RAW.exists():
        return out
    for line in W9_RAW.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            out[int(d["id"])] = d
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


# Report rendering ----------------------------------------------------------


def render_md(qianfan_rows: list[dict], lunon_rows: list[dict], w9_scores: dict[int, dict]) -> str:
    out: list[str] = []
    out.append("# Qianfan #1 Leaderboard — Style Profile (Phase A)")
    out.append("")
    out.append(
        "Programmatic style metrics for 10 Qianfan articles (5 matched to our gate-verify IDs, "
        "5 bonus high-scoring). Compares against our W9 articles on the same IDs where available. "
        "Cell values are absolute counts unless suffixed with `/1k` (per 1000 words) or `%`."
    )
    out.append("")

    # Per-article comparison table for gate-verify IDs
    gate_ids = {8, 20, 23, 56, 91}
    gate_rows = [q for q in qianfan_rows if q["task_id"] in gate_ids]
    gate_rows.sort(key=lambda r: r["task_id"])
    lunon_by_id = {r["task_id"]: r for r in lunon_rows}

    out.append("## Head-to-head: 5 gate-verify tasks (Qianfan vs Lunon W9)")
    out.append("")
    out.append(
        "`length` is word-count for EN; for ZH it's `max(latin_words, "
        "n_cjk_chars / 2)` — a unit-comparable word-equivalent that matches "
        "the D1 `length_target()` heuristic. The pre-D0 column reported raw "
        "`.split()` which under-counted ZH dramatically (id=23 was 864; "
        "actual word-equivalent is ~16k)."
    )
    out.append("")
    out.append(
        "| id | lang | length(Q) | length(L) | × | top_sec(Q) | top_sec(L) | tables(Q) | tables(L) | URLs(Q) | URLs(L) | hedge/1k(Q) | hedge/1k(L) | fwd/1k(Q) | fwd/1k(L) | W9 Read |"
    )
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for q in gate_rows:
        tid = q["task_id"]
        L = lunon_by_id.get(tid, {})
        w9 = w9_scores.get(tid, {})
        ratio = round(q["n_length"] / max(1, L.get("n_length", 1)), 1) if L else "—"
        out.append(
            f"| {tid} | {q['lang']} | {q['n_length']:>5} | {L.get('n_length', '—'):>5} | "
            f"{ratio}× | {q['n_top_sections']} | {L.get('n_top_sections', '—')} | "
            f"{q['n_table_blocks']} | {L.get('n_table_blocks', '—')} | "
            f"{q['n_urls']} | {L.get('n_urls', '—')} | "
            f"{q['hedge_per_1k']} | {L.get('hedge_per_1k', '—')} | "
            f"{q['fwd_per_1k']} | {L.get('fwd_per_1k', '—')} | "
            f"{round(w9.get('readability', 0), 3)} |"
        )
    out.append("")

    # All Qianfan articles raw metrics
    out.append("## All 10 Qianfan articles — raw metrics")
    out.append("")
    out.append(
        "| id | lang | length | paras | p_med | top_sec | h1 | h2 | h3 | h4+ | tables | URLs | [n] | named_src | em— | yrs | fwd_dt | hedge/1k | fwd/1k | open(t,q,c,f) |"
    )
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for q in sorted(qianfan_rows, key=lambda r: r["task_id"]):
        flags = (
            ("Y" if q["open_thesis"] else ".")
            + ("Y" if q["open_quant"] else ".")
            + ("Y" if q["open_contrarian"] else ".")
            + ("Y" if q["open_fwd_date"] else ".")
        )
        # Headings: prefer numbered if present, else markdown.
        h_used = "num" if (q["num_h1"] + q["num_h2"] + q["num_h3"]) > (q["md_h2"] + q["md_h3"]) else "md"
        h1 = q[f"{h_used}_h1"]
        h2 = q[f"{h_used}_h2"]
        h3 = q[f"{h_used}_h3"]
        h4 = q[f"{h_used}_h4plus"]
        out.append(
            f"| {q['task_id']} | {q['lang']} | {q['n_length']:>6} | {q['n_paragraphs']:>4} | "
            f"{int(q['para_len_median'])} | {q['n_top_sections']} | "
            f"{h1} | {h2} | {h3} | {h4} | {q['n_table_blocks']} | {q['n_urls']} | "
            f"{q['n_footnotes']} | {q['n_named_sources']} | {q['em_dashes']} | "
            f"{q['bare_years']} | {q['fwd_dates']} | {q['hedge_per_1k']} | {q['fwd_per_1k']} | "
            f"{flags} |"
        )
    out.append("")
    out.append(
        "**Opening flags legend:** `t` = thesis sentence in first 200 words, `q` = number/quantification, "
        "`c` = contrarian framing, `f` = forward-looking date. `Y` = present, `.` = absent."
    )
    out.append("")

    # Aggregate vs Lunon
    def avg(rows: list[dict], key: str) -> float:
        vals = [r[key] for r in rows if key in r]
        return round(sum(vals) / max(1, len(vals)), 2) if vals else 0

    out.append("## Aggregates: Qianfan vs Lunon W9 (paired on 5 gate-verify IDs)")
    out.append("")
    out.append("| metric | Qianfan mean | Lunon mean | Δ (Q − L) |")
    out.append("|---|---|---|---|")
    for label, key in [
        ("length (EN words / ZH word-equivalents)", "n_length"),
        ("paragraphs", "n_paragraphs"),
        ("paragraph median words", "para_len_median"),
        ("top-level sections", "n_top_sections"),
        ("table blocks", "n_table_blocks"),
        ("URLs", "n_urls"),
        ("named-source cites", "n_named_sources"),
        ("[n] footnotes", "n_footnotes"),
        ("bare years referenced", "bare_years"),
        ("forward-looking dates", "fwd_dates"),
        ("hedging per 1k words", "hedge_per_1k"),
        ("forward-looking per 1k words", "fwd_per_1k"),
        ("em-dashes", "em_dashes"),
        ("contrarian markers", "contrarian_count"),
        ("causal-chain markers", "causal_count"),
        ("quantified ranges", "quant_range_count"),
    ]:
        q_mean = avg(gate_rows, key)
        l_mean = avg(lunon_rows, key)
        d = round(q_mean - l_mean, 2)
        sign = "+" if d > 0 else ""
        out.append(f"| {label} | {q_mean} | {l_mean} | {sign}{d} |")
    out.append("")

    # Bonus articles only (high-scoring, no pairing)
    bonus_rows = [q for q in qianfan_rows if q["task_id"] not in gate_ids]
    out.append("## Bonus high-scoring articles (5)")
    out.append("")
    out.append(
        "Same per-article table format for: "
        + ", ".join(str(r["task_id"]) for r in sorted(bonus_rows, key=lambda r: r["task_id"]))
        + "."
    )
    out.append("")
    out.append(
        "Means: length="
        + str(int(avg(bonus_rows, "n_length")))
        + ", paragraphs="
        + str(int(avg(bonus_rows, "n_paragraphs")))
        + ", top_sections="
        + str(round(avg(bonus_rows, "n_top_sections"), 1))
        + ", table_blocks="
        + str(round(avg(bonus_rows, "n_table_blocks"), 1))
        + ", URLs="
        + str(int(avg(bonus_rows, "n_urls")))
        + ", fwd_dates="
        + str(round(avg(bonus_rows, "fwd_dates"), 1))
        + ", em_dashes="
        + str(round(avg(bonus_rows, "em_dashes"), 1))
        + "."
    )
    out.append("")

    out.append("## Quick read of the obvious gaps")
    out.append("")
    out.append(
        "This is mechanical — Phase B/C will do the close-reading. Use the table for hypothesis seeds, not conclusions."
    )

    return "\n".join(out) + "\n"


# Main ----------------------------------------------------------------------


def main() -> None:
    # Detect language by ID: 23 is the short ZH; 8, 14, 20, 37, 38, 44 are ZH; 56, 89, 91 are EN.
    LANG_OVERRIDES = {
        8: "zh",
        14: "zh",
        20: "zh",
        23: "zh",
        37: "zh",
        38: "zh",
        44: "zh",
        56: "en",
        89: "en",
        91: "en",
    }

    qianfan_rows: list[dict] = []
    for path in sorted(QIANFAN_DIR.glob("*.txt")):
        if path.name.endswith(".Identifier"):
            continue
        tid, body = extract_article(path)
        if tid is None or not body:
            continue
        m = compute_metrics(body)
        m["task_id"] = tid
        m["source"] = "qianfan"
        m["lang"] = LANG_OVERRIDES.get(tid, "?")
        qianfan_rows.append(m)

    # Pair with our W9 articles on gate-verify IDs.
    p1_articles = load_p1_articles()
    w9_scores = load_w9_scores()
    lunon_rows: list[dict] = []
    for tid in {q["task_id"] for q in qianfan_rows}:
        body = p1_articles.get(tid)
        if not body:
            continue
        m = compute_metrics(body)
        m["task_id"] = tid
        m["source"] = "lunon-w9"
        m["lang"] = LANG_OVERRIDES.get(tid, "?")
        lunon_rows.append(m)

    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with OUT_JSONL.open("w", encoding="utf-8") as fh:
        for r in qianfan_rows + lunon_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    md = render_md(qianfan_rows, lunon_rows, w9_scores)
    OUT_MD.write_text(md, encoding="utf-8")

    print(f"qianfan articles: {len(qianfan_rows)}")
    print(f"lunon-w9 paired:  {len(lunon_rows)}")
    print(f"wrote: {OUT_MD}")
    print(f"wrote: {OUT_JSONL}")


if __name__ == "__main__":
    main()
