"""Validate the P2-Option-A-#2 heading-depth fix on the full Lunon W9 corpus.

Runs `numbering_fix.run(...)` over every Lunon W9 article and reports:
  - before-fix: count of multi-H1 articles + hash-vs-number-depth mismatches
  - after-fix:  same counts after the new `_normalize_hash_from_number` pre-pass

W9 audit (2026-05-23) showed 99/100 articles had >1 H1 and 100/100 had
depth mismatches. The fix is deterministic; this script confirms the
after-fix numbers go to ~0/100.

Usage:
  python3 scripts/p2_validate_heading_depth_fix.py \\
    --jsonl /home/connor/dev/deep_research_bench/data/test_data/cleaned_data/lunon-p1-2026-05-21-final.jsonl \\
    --out p2_artifacts/p2_heading_depth_validation.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Make repo-root importable so we can pull numbering_fix without a `pip install -e .`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deep_research.pipeline.numbering_fix import run as numbering_fix_run  # noqa: E402

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_LEADING_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)")


def _audit_article(article: str) -> dict:
    """Count H1s + depth-vs-number mismatches in an article."""
    headings = _HEADING_RE.findall(article)
    depth_counts = Counter(len(h) for h, _ in headings)
    h1_count = depth_counts.get(1, 0)
    mismatches = 0
    for hashes, title in headings:
        depth = len(hashes)
        if depth == 1:
            continue
        m = _LEADING_NUM_RE.match(title)
        if not m:
            continue
        num_dots = m.group(1).count(".") + 1
        expected_depth = num_dots + 1
        if depth != expected_depth:
            mismatches += 1
    return {
        "h1_count": h1_count,
        "depth_mismatches": mismatches,
        "total_headings": len(headings),
        "depth_dist": dict(depth_counts),
    }


def run(jsonl_path: Path) -> dict:
    before_multi_h1 = 0
    before_mismatch = 0
    after_multi_h1 = 0
    after_mismatch = 0
    per_article = []
    n = 0
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        tid = d.get("id")
        article = d.get("article", "")
        if not article:
            continue
        n += 1
        before = _audit_article(article)
        nfo = numbering_fix_run(article)
        after = _audit_article(nfo.article)
        if before["h1_count"] > 1:
            before_multi_h1 += 1
        if before["depth_mismatches"] > 0:
            before_mismatch += 1
        if after["h1_count"] > 1:
            after_multi_h1 += 1
        if after["depth_mismatches"] > 0:
            after_mismatch += 1
        per_article.append(
            {
                "id": tid,
                "before": before,
                "after": after,
                "hash_normalized": nfo.headings_hash_normalized,
                "renumbered": nfo.headings_renumbered,
            }
        )
    return {
        "n_articles": n,
        "before": {
            "multi_h1": before_multi_h1,
            "depth_mismatch": before_mismatch,
        },
        "after": {
            "multi_h1": after_multi_h1,
            "depth_mismatch": after_mismatch,
        },
        "per_article": per_article,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--jsonl",
        required=True,
        help="adapter-output jsonl with `article` field per row (e.g. Lunon W9 final)",
    )
    ap.add_argument("--out", required=True, help="output JSON report path")
    args = ap.parse_args()

    out = run(Path(args.jsonl))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[heading-depth-fix] n={out['n_articles']} articles audited")
    print(f"  BEFORE: multi-H1 = {out['before']['multi_h1']:>3} / {out['n_articles']}")
    print(f"          depth-mismatch articles = {out['before']['depth_mismatch']:>3} / {out['n_articles']}")
    print(f"  AFTER:  multi-H1 = {out['after']['multi_h1']:>3} / {out['n_articles']}")
    print(f"          depth-mismatch articles = {out['after']['depth_mismatch']:>3} / {out['n_articles']}")


if __name__ == "__main__":
    main()
