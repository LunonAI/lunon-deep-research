"""Structural similarity diff: does an experiment article move our output
TOWARD or AWAY from the #1 reference corpus on methodology-relevant metrics?

Re-uses the metric extraction from `p2_reference_profile.compute_metrics`
and surfaces a per-metric distance vs the reference's per-task figure. Tracks
both the absolute delta and the SIGN of movement (toward the reference = +,
away = −) for each metric.

Combined with the within-task A/B verdict, structural-sim provides a
second-signal sanity check:
  - A/B says experiment wins AND moves toward the reference → high confidence
  - A/B says experiment wins BUT moves away from the reference → judge variance
  - A/B says baseline wins AND we moved toward the reference → calibration
    failure: methodology hypothesis wrong (Wave 2.5's failure mode)

Usage:
  python3 scripts/p2_structural_sim.py \\
    --jsonl p2_artifacts/e1_articles.jsonl \\
    --out p2_artifacts/e1_struct_sim.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p2_reference_profile import compute_metrics, extract_article  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REFERENCE_DIR = _REPO_ROOT / "reference-dr-questions"


def _reference_metrics_by_id() -> dict[int, dict]:
    """Pre-compute the reference corpus metrics, keyed by task_id."""
    out: dict[int, dict] = {}
    if not _REFERENCE_DIR.exists():
        return out
    for path in _REFERENCE_DIR.glob("*.txt"):
        if path.name.endswith(".Identifier"):
            continue
        tid, body = extract_article(path)
        if tid is None or not body:
            continue
        out[tid] = compute_metrics(body)
    return out


# Metrics where MOVING TOWARD the reference is the methodology-aligned direction.
# Each entry is (metric_name, reference_is_typically_higher: bool). For the
# few metrics where direction is mixed across the corpus, we leave them out.
_DIRECTIONAL_METRICS = [
    ("n_length", True),  # the reference articles run longer overall
    ("n_top_sections", True),  # the reference has 12-14 top sections; we have 3-9
    ("em_dashes", True),  # analytical-prose marker
    ("contrarian_count", True),  # "despite/however" framing throughout
    ("quant_range_count", True),  # quantified bands
    ("n_named_sources", False),  # we OVER-use; the reference uses fewer
    ("n_footnotes", True),  # but VERIFY per-task — id=23 has 0
]


def diff_one(experiment_metrics: dict, reference_metrics: dict) -> dict:
    """Per-task structural-similarity diff. Returns:
    {metric: {ours, reference, delta_absolute, sign_toward_reference}}
    """
    out: dict = {}
    for metric, reference_higher in _DIRECTIONAL_METRICS:
        ours = experiment_metrics.get(metric, 0)
        theirs = reference_metrics.get(metric, 0)
        gap = theirs - ours
        if abs(gap) < 1e-9:
            sign = "tie"
        elif reference_higher:
            sign = "toward_reference" if ours < theirs else "away_from_reference"
        else:
            sign = "toward_reference" if ours > theirs else "away_from_reference"
        out[metric] = {
            "ours": ours,
            "reference": theirs,
            "gap": gap,
            "movement_target": "lower" if not reference_higher else "higher",
            "sign": sign,
        }
    return out


def run(jsonl: Path) -> dict:
    reference = _reference_metrics_by_id()
    per_task: list[dict] = []
    aggregate_toward = 0
    aggregate_away = 0
    aggregate_tie = 0
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        try:
            tid = int(d["id"])
        except (KeyError, ValueError):
            continue
        article = d.get("article", "")
        if not article:
            continue
        if tid not in reference:
            per_task.append({"task_id": tid, "error": "no the reference baseline available"})
            continue
        ours_metrics = compute_metrics(article)
        diff = diff_one(ours_metrics, reference[tid])
        per_task.append({"task_id": tid, "diff": diff})
        for d_row in diff.values():
            if d_row["sign"] == "toward_reference":
                aggregate_toward += 1
            elif d_row["sign"] == "away_from_reference":
                aggregate_away += 1
            else:
                aggregate_tie += 1
    total = aggregate_toward + aggregate_away + aggregate_tie
    return {
        "n_articles_paired": sum(1 for r in per_task if "diff" in r),
        "n_articles_unpaired": sum(1 for r in per_task if "error" in r),
        "aggregate": {
            "toward_reference": aggregate_toward,
            "away_from_reference": aggregate_away,
            "tie": aggregate_tie,
            "toward_rate": round(aggregate_toward / max(1, total), 3),
        },
        "per_task": per_task,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True, help="adapter output jsonl to score against the reference")
    ap.add_argument("--out", required=True, help="output JSON path for the diff report")
    args = ap.parse_args()

    out = run(Path(args.jsonl))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    agg = out["aggregate"]
    print(f"[struct-sim] paired={out['n_articles_paired']}  unpaired={out['n_articles_unpaired']}")
    print(f"             toward_reference={agg['toward_reference']}  away={agg['away_from_reference']}  tie={agg['tie']}")
    print(f"             toward-rate = {agg['toward_rate']}")


if __name__ == "__main__":
    main()
