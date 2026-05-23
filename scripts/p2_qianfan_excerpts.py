"""Phase B prep — extract opening / middle / closing excerpts from Qianfan
gate-verify articles and our W9 counterparts for paired close-reading.

For each id in {8, 20, 23, 56, 91} writes:
  p2_artifacts/qianfan_excerpts/id_{N}_qianfan.md
  p2_artifacts/qianfan_excerpts/id_{N}_lunon.md

Each file contains three sections (OPENING / MIDDLE / CLOSING) holding ~600
words sampled from a deterministic offset of the article body. The middle
section is selected at the article's midpoint, snapped to the nearest
heading boundary so we land at a coherent passage.

Why offsets, not full articles: a single Qianfan article is up to 80k+
words. Reading full articles for 5 pairs would burn ~500k tokens of context.
Targeted excerpts keep each pair under ~3k tokens.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

QIANFAN_DIR = Path("/home/connor/dev/lunon-deep-research/qianfan-dr-questions")
P1_FINAL = Path("/home/connor/dev/lunon-deep-research/p1_artifacts/p1_final.jsonl")
OUT_DIR = Path("/home/connor/dev/lunon-deep-research/p2_artifacts/qianfan_excerpts")

GATE_VERIFY = (8, 20, 23, 56, 91)
EXCERPT_WORDS = 600  # ~3-5kb per excerpt; small enough to read 6 in one pass

_ARTICLE_MARKER = "Generated Article 📖"
_TASK_ID_RE = re.compile(r"Task\s+ID:\s*(\d+)")
_HEADING = re.compile(r"^(?:#{1,4}\s+|\d+(?:\.\d+)*\.?\s+)\S", re.MULTILINE)


def extract_qianfan_article(path: Path) -> tuple[int | None, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    m = _TASK_ID_RE.search(text)
    tid = int(m.group(1)) if m else None
    idx = text.find(_ARTICLE_MARKER)
    if idx < 0:
        return tid, text
    body = text[idx + len(_ARTICLE_MARKER) :].lstrip()
    return tid, body


def load_lunon_w9() -> dict[int, str]:
    out: dict[int, str] = {}
    if not P1_FINAL.exists():
        return out
    for line in P1_FINAL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            out[int(d["id"])] = d.get("article", "")
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


def _take_words(text: str, n: int, start_word: int = 0) -> str:
    words = text.split()
    return " ".join(words[start_word : start_word + n])


def _middle_excerpt(text: str, n: int) -> str:
    """Snap the start to the heading nearest the midpoint, then take n words."""
    total_words = len(text.split())
    if total_words <= n * 2:
        # Article too short for a separate middle — take from one-third in.
        return _take_words(text, n, start_word=total_words // 3)
    # Find heading offsets (in chars), pick the heading closest to the
    # char-midpoint, then re-anchor in word space.
    mid_char = len(text) // 2
    heading_offsets = [m.start() for m in _HEADING.finditer(text)]
    if not heading_offsets:
        return _take_words(text, n, start_word=total_words // 2)
    best = min(heading_offsets, key=lambda o: abs(o - mid_char))
    # Convert char-offset to word-index.
    prefix_words = len(text[:best].split())
    return _take_words(text, n, start_word=prefix_words)


def build_excerpt(body: str) -> dict:
    return {
        "opening": _take_words(body, EXCERPT_WORDS, start_word=0),
        "middle": _middle_excerpt(body, EXCERPT_WORDS),
        "closing": _take_words(body, EXCERPT_WORDS, start_word=max(0, len(body.split()) - EXCERPT_WORDS)),
        "total_words": len(body.split()),
    }


def render_md(tid: int, source: str, ex: dict) -> str:
    return (
        f"# id={tid} · {source} · total_words={ex['total_words']}\n\n"
        f"## OPENING (first {EXCERPT_WORDS} words)\n\n"
        f"{ex['opening']}\n\n"
        f"---\n\n"
        f"## MIDDLE (heading nearest midpoint, {EXCERPT_WORDS} words)\n\n"
        f"{ex['middle']}\n\n"
        f"---\n\n"
        f"## CLOSING (last {EXCERPT_WORDS} words)\n\n"
        f"{ex['closing']}\n"
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    qianfan_by_id: dict[int, str] = {}
    for path in QIANFAN_DIR.glob("*.txt"):
        if path.name.endswith(".Identifier"):
            continue
        tid, body = extract_qianfan_article(path)
        if tid is not None:
            qianfan_by_id[tid] = body
    lunon_by_id = load_lunon_w9()

    written = []
    for tid in GATE_VERIFY:
        q = qianfan_by_id.get(tid)
        L = lunon_by_id.get(tid)
        if q:
            ex = build_excerpt(q)
            path = OUT_DIR / f"id_{tid}_qianfan.md"
            path.write_text(render_md(tid, "Qianfan #1", ex), encoding="utf-8")
            written.append(path.name)
        if L:
            ex = build_excerpt(L)
            path = OUT_DIR / f"id_{tid}_lunon.md"
            path.write_text(render_md(tid, "Lunon W9", ex), encoding="utf-8")
            written.append(path.name)

    print(f"wrote {len(written)} excerpt files to {OUT_DIR}")
    for n in written:
        print(f"  {n}")


if __name__ == "__main__":
    main()
