"""P3b-opt2 (2026-05-28): measure Qianfan's actual style rates from the FRESH
corpus, so the writer's directive bands are set to Qianfan's real numbers
(not eyeballed). Output → qianfan_style_targets.json next to the corpus.

Rates that matter for the id=91 judge gap (readability + org-structure):
  - heading levels (Qianfan is flat ## — H3/H4 should be ~0)
  - paragraph median words (Qianfan ~160; ours ~79 → choppy)
  - citation markers per 1k words + marker reuse ratio
  - quant-range markers per 1k (we over-stuff 5.8×)
  - contrarian markers per 1k (we over-arg 5.3×)
  - em-dashes per 1k (we 2× over)
  - sections per 1k words, tables per 1k

Run:  .venv/bin/python scripts/qianfan_style_profile.py
Read-only over /tmp/qf_deepdive/*.md.
"""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

CORPUS = Path("/tmp/qf_deepdive")
OUT = CORPUS / "qianfan_style_targets.json"

# Crude but consistent markers (same patterns we'll measure ours against).
_CITE = re.compile(r"\[\^[^\]]+\]")
_CITE_DEF = re.compile(r"^\[\^[^\]]+\]:", re.M)
# quant range: "10-20", "3.5–7.2", "~40%", "12 to 15" — numeric span / approximation
_QUANT = re.compile(r"\b\d+(?:\.\d+)?\s*(?:[-–—]|to)\s*\d+(?:\.\d+)?\b|[~≈]\s*\d|\b\d+(?:\.\d+)?\s*%")
# contrarian / hedging argument markers
_CONTRA = re.compile(
    r"\b(?:however|conversely|on the other hand|contrarian|counter-?argument|"
    r"that said|nonetheless|yet,|but it is|critics?|skeptic|paradox)\b",
    re.I,
)
_EMDASH = re.compile(r"[—]")  # em-dash only (U+2014); en-dash is for numeric ranges


def _is_cjk(t: str) -> bool:
    cjk = len(re.findall(r"[一-鿿]", t))
    return cjk > 0.15 * max(len(t), 1)


def _words(t: str) -> int:
    """Word count. For CJK text `.split()` massively undercounts (no spaces),
    which explodes per-1k rates — approximate CJK words as chars/1.6 so the
    denominator is sane and rates are comparable to EN."""
    if _is_cjk(t):
        cjk = len(re.findall(r"[一-鿿]", t))
        latin = len(re.findall(r"[A-Za-z]+", t))
        return max(int(cjk / 1.6) + latin, 1)
    return max(len(t.split()), 1)


def profile_article(text: str) -> dict:
    w = max(_words(text), 1)
    per1k = lambda n: round(n / w * 1000, 2)  # noqa: E731
    markers = _CITE.findall(text)
    defs = _CITE_DEF.findall(text)
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip() and not p.strip().startswith("#")]
    para_lens = sorted(_words(p) for p in paras)
    h = {lvl: len(re.findall(rf"^{'#' * lvl}\s", text, re.M)) for lvl in (1, 2, 3, 4)}
    return {
        "words": w,
        "h2": h[2],
        "h3": h[3],
        "h4": h[4],
        "sections_per_1k": per1k(h[2]),
        "para_count": len(paras),
        "para_median_words": int(statistics.median(para_lens)) if para_lens else 0,
        "citations_per_1k": per1k(len(markers)),
        "citation_reuse": round(len(markers) / max(len(defs), 1), 2),
        "quant_per_1k": per1k(len(_QUANT.findall(text))),
        "contrarian_per_1k": per1k(len(_CONTRA.findall(text))),
        "emdash_per_1k": per1k(len(_EMDASH.findall(text))),
        "tables_per_1k": per1k(len(re.findall(r"\|[-: ]+\|", text))),
    }


def main() -> None:
    arts = sorted(CORPUS.glob("q*_article.md"))
    if not arts:
        print(f"no Qianfan articles in {CORPUS}")
        return
    per_article = {}
    for p in arts:
        txt = p.read_text(encoding="utf-8")
        prof = profile_article(txt)
        prof["lang"] = "zh" if _is_cjk(txt) else "en"
        per_article[p.stem] = prof

    keys = [
        "para_median_words",
        "citations_per_1k",
        "citation_reuse",
        "quant_per_1k",
        "contrarian_per_1k",
        "emdash_per_1k",
        "sections_per_1k",
        "tables_per_1k",
    ]

    def _targets(group: list[dict]) -> dict:
        t = {k: round(statistics.median([a[k] for a in group]), 2) for k in keys} if group else {}
        # Flatness is archetype/task-specific (q91 flat, q56/q89 nested); report
        # H3/H4 per-article rather than a misleading aggregate. H4 is ~0 across
        # the whole corpus → "cap at H3" is the universal rule.
        t["h4_total"] = sum(a["h4"] for a in group)
        t["n"] = len(group)
        return t

    en = [a for a in per_article.values() if a["lang"] == "en"]
    zh = [a for a in per_article.values() if a["lang"] == "zh"]
    out = {"targets_en": _targets(en), "targets_zh": _targets(zh), "per_article": per_article}
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"=== Qianfan style targets → {OUT} ===")
    print(f"EN (n={len(en)}):")
    for k, v in out["targets_en"].items():
        print(f"  {k:22} {v}")
    print(f"ZH (n={len(zh)}):")
    for k, v in out["targets_zh"].items():
        print(f"  {k:22} {v}")


if __name__ == "__main__":
    main()
