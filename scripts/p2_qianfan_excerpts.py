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

# Greptile follow-up (PR #16): paths resolved repo-relative so the script
# runs from any clone / CI without requiring absolute paths. The repo root
# is two levels up from this scripts/ file.
_REPO_ROOT = Path(__file__).resolve().parent.parent
QIANFAN_DIR = _REPO_ROOT / "qianfan-dr-questions"
P1_FINAL = _REPO_ROOT / "p1_artifacts" / "p1_final.jsonl"
OUT_DIR = _REPO_ROOT / "p2_artifacts" / "qianfan_excerpts"

GATE_VERIFY = (8, 20, 23, 56, 91)
EXCERPT_UNITS = 600  # ~3-5kb per excerpt; small enough to read 6 in one pass

_ARTICLE_MARKER = "Generated Article 📖"
_TASK_ID_RE = re.compile(r"Task\s+ID:\s*(\d+)")
_HEADING = re.compile(r"^(?:#{1,4}\s+|\d+(?:\.\d+)*\.?\s+)\S", re.MULTILINE)
# CJK Unified Ideographs + ext-A + compat range. Matches actual Chinese
# characters but not punctuation/whitespace. Used for the EN/ZH detection
# heuristic + the ZH char-slicing fallback.
_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


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


# Greptile follow-up (PR #16): unit-aware length helpers. Pre-fix, every
# length calculation used `text.split()` which dramatically under-counted
# ZH (no whitespace between CJK characters). `_is_mostly_cjk` chooses the
# unit scheme; `count_units` returns the unit-comparable length; `take_units`
# slices by the correct unit. This is the same fix that landed in
# scripts/p2_qianfan_profile.py for the profiler.


def _is_mostly_cjk(text: str) -> bool:
    """True iff the text is dominated by CJK characters (a heuristic ZH
    detector). We pick the threshold liberally (>= 10% CJK chars by char
    count) so partially-translated ZH-EN tasks still trigger the CJK path."""
    if not text:
        return False
    cjk = len(_CJK_RE.findall(text))
    return cjk >= max(50, len(text) // 10)


def count_units(text: str) -> int:
    """Unit-comparable length: latin-word count for EN, CJK chars / 2 for ZH.
    Mixed text returns the max of the two so neither path under-reports."""
    latin = len(text.split())
    cjk = len(_CJK_RE.findall(text))
    return max(latin, cjk // 2) if cjk else latin


def take_units(text: str, n: int, start_unit: int = 0) -> str:
    """Take `n` units starting at `start_unit`. For EN text, units = latin
    words. For ZH-dominated text, units = pairs of CJK chars (~word-equiv).

    The ZH path slices on CHARACTERS, not whitespace tokens, so the excerpt
    actually contains content rather than collapsing to ~one paragraph-break
    token (the pre-fix failure mode flagged by Greptile)."""
    if _is_mostly_cjk(text):
        # 1 unit ≈ 2 CJK chars (matches D0's word-equivalent heuristic).
        start_char = max(0, start_unit * 2)
        end_char = max(0, start_char + n * 2)
        return text[start_char:end_char]
    words = text.split()
    return " ".join(words[start_unit : start_unit + n])


def _middle_excerpt(text: str, n: int) -> str:
    """Snap the start to the heading nearest the midpoint, then take n units."""
    total = count_units(text)
    if total <= n * 2:
        # Article too short for a separate middle — take from one-third in.
        return take_units(text, n, start_unit=total // 3)
    # Find heading offsets (in chars), pick the heading closest to the
    # char-midpoint, then re-anchor in unit space.
    mid_char = len(text) // 2
    heading_offsets = [m.start() for m in _HEADING.finditer(text)]
    if not heading_offsets:
        return take_units(text, n, start_unit=total // 2)
    best = min(heading_offsets, key=lambda o: abs(o - mid_char))
    # Convert char-offset to unit-index (same EN/ZH dispatch as count_units).
    prefix = text[:best]
    prefix_units = count_units(prefix)
    return take_units(text, n, start_unit=prefix_units)


def build_excerpt(body: str) -> dict:
    total = count_units(body)
    return {
        "opening": take_units(body, EXCERPT_UNITS, start_unit=0),
        "middle": _middle_excerpt(body, EXCERPT_UNITS),
        "closing": take_units(body, EXCERPT_UNITS, start_unit=max(0, total - EXCERPT_UNITS)),
        "total_units": total,
    }


def render_md(tid: int, source: str, ex: dict) -> str:
    return (
        f"# id={tid} · {source} · total_units={ex['total_units']}\n\n"
        f"## OPENING (first {EXCERPT_UNITS} units)\n\n"
        f"{ex['opening']}\n\n"
        f"---\n\n"
        f"## MIDDLE (heading nearest midpoint, {EXCERPT_UNITS} units)\n\n"
        f"{ex['middle']}\n\n"
        f"---\n\n"
        f"## CLOSING (last {EXCERPT_UNITS} units)\n\n"
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
