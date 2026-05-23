"""Wave 0 B0a/B0b analysis: paired Δ vs W9 same-ids.

Reads two harness raw_results.jsonl files (the new dev10 + W9) and produces
per-task + aggregate paired ΔOverall + ΔComp + ΔInsight + ΔInstFollow +
ΔRead. Maps results to the plan §7.2 scenario selection logic:
  paired ΔO ≥ +0.020 → optimistic
  paired ΔO ∈ [+0.005, +0.020] → central
  paired ΔO ∈ [-0.005, +0.005] → pessimistic
  paired ΔO < -0.005 → very-pessimistic + diagnostic fork

Usage:
  python3 scripts/p2_analyze_b0.py <model_name>
e.g.:
  python3 scripts/p2_analyze_b0.py lunon-p2-2026-05-22-b0a
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

_DEFAULT_RESULTS_BASE = "/home/connor/dev/deep_research_bench/results/race"
RESULTS_BASE = Path(os.environ.get("DRB_RESULTS_BASE") or _DEFAULT_RESULTS_BASE)
if not RESULTS_BASE.exists():
    print(
        f"WARNING: DRB results base not found ({RESULTS_BASE}). "
        f"Set DRB_RESULTS_BASE to the deep_research_bench/results/race path on your machine. "
        f"The script will FileNotFoundError shortly.",
        file=sys.stderr,
    )
W9_MODEL = os.environ.get("P2_W9_MODEL", "lunon-p1-2026-05-21-final")
ROOT = Path(__file__).resolve().parent.parent


def load_results(model: str) -> dict[str, dict]:
    """Return {str(id): {comp, insight, instr, read, overall}} for a model run."""
    p = RESULTS_BASE / model / "raw_results.jsonl"
    if not p.exists():
        raise FileNotFoundError(f"Results not found: {p}")
    out = {}
    with p.open() as f:
        for line in f:
            d = json.loads(line)
            if "error" in d:
                continue
            tid = str(d.get("id"))
            out[tid] = {
                "comp": d.get("comprehensiveness", 0.0),
                "insight": d.get("insight", 0.0),
                "instr": d.get("instruction_following", 0.0),
                "read": d.get("readability", 0.0),
                "overall": d.get("overall_score", 0.0),
                "lang": d.get("language", "?"),
            }
    return out


def detect_lang(prompt: str) -> str:
    return "zh" if sum(1 for c in prompt if "一" <= c <= "鿿") > 5 else "en"


# Verified RACE dim weights from harness criteria.jsonl (n=100).
DIM_WEIGHTS = {"insight": 0.352, "comp": 0.292, "instr": 0.215, "read": 0.141}


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python3 scripts/p2_analyze_b0.py <model_name>", file=sys.stderr)
        return 2
    model = sys.argv[1]
    w9 = load_results(W9_MODEL)
    cur = load_results(model)
    common = sorted(set(w9) & set(cur), key=int)
    if not common:
        print(f"No id overlap between {model} and {W9_MODEL}.", file=sys.stderr)
        return 3
    print(f"=== Paired Δ analysis: {model} vs {W9_MODEL} ===")
    print(f"Overlap: {len(common)} ids (cur={len(cur)}, w9={len(w9)})")

    # Per-task table
    print(f"\n{'id':>4} {'lang':>4} | {'ΔO':>8} {'ΔC':>8} {'ΔI':>8} {'ΔIF':>8} {'ΔR':>8} | {'cur_O':>8} {'w9_O':>8}")
    print("-" * 92)
    rows = []
    for tid in common:
        c = cur[tid]
        w = w9[tid]
        d = {
            "id": tid,
            "lang": c["lang"],
            "do": c["overall"] - w["overall"],
            "dc": c["comp"] - w["comp"],
            "di": c["insight"] - w["insight"],
            "dif": c["instr"] - w["instr"],
            "dr": c["read"] - w["read"],
            "cur_o": c["overall"],
            "w9_o": w["overall"],
        }
        rows.append(d)
        print(
            f"{tid:>4} {c['lang']:>4} | {d['do']:>+8.4f} {d['dc']:>+8.4f} {d['di']:>+8.4f} "
            f"{d['dif']:>+8.4f} {d['dr']:>+8.4f} | {d['cur_o']:>8.4f} {d['w9_o']:>8.4f}"
        )

    # Aggregates
    def agg(key, sign_thr=0.0):
        vals = [r[key] for r in rows]
        return {
            "mean": statistics.mean(vals),
            "median": statistics.median(vals),
            "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0,
            "sign_pos": sum(1 for v in vals if v > sign_thr),
        }

    print("\n=== Aggregates (paired Δ across overlap) ===")
    for k, label in [("do", "ΔOverall"), ("dc", "ΔComp"), ("di", "ΔInsight"), ("dif", "ΔInstFollow"), ("dr", "ΔRead")]:
        a = agg(k)
        print(
            f"  {label:>12}: mean={a['mean']:+.4f}  median={a['median']:+.4f}  stdev={a['stdev']:.4f}  sign={a['sign_pos']}/{len(rows)}"
        )

    # Per-language
    print("\n=== Per-language ===")
    for lang in ("en", "zh"):
        sub = [r for r in rows if r["lang"] == lang]
        if not sub:
            continue
        mean_o = statistics.mean([r["do"] for r in sub])
        mean_i = statistics.mean([r["di"] for r in sub])
        print(f"  {lang}: n={len(sub)} ΔO={mean_o:+.4f} ΔI={mean_i:+.4f}")

    # Weighted-Δ-Overall decomposition (using verified dim weights)
    print("\n=== Weighted-ΔO decomposition (using mean dim weights) ===")
    contribs = {}
    for k, dim_key in [("dc", "comp"), ("di", "insight"), ("dif", "instr"), ("dr", "read")]:
        mean_d = statistics.mean([r[k] for r in rows])
        contribs[dim_key] = mean_d * DIM_WEIGHTS[dim_key]
        print(
            f"  {dim_key:>10}: meanΔ={mean_d:+.4f}  ×weight={DIM_WEIGHTS[dim_key]:.3f}  contrib={contribs[dim_key]:+.4f}"
        )
    total = sum(contribs.values())
    raw_o = statistics.mean([r["do"] for r in rows])
    print(f"  TOTAL weighted-ΔO (sum): {total:+.4f}")
    print(f"  Raw ΔO mean (harness):   {raw_o:+.4f}")
    print("  (Discrepancy if any reflects per-task-weight variation; dim weights are means.)")

    # §7.2 scenario selection
    raw_o = statistics.mean([r["do"] for r in rows])
    print("\n=== §7.2 baseline scenario for B0 lock ===")
    if raw_o >= 0.020:
        scenario = "OPTIMISTIC"
    elif raw_o >= 0.005:
        scenario = "CENTRAL"
    elif raw_o >= -0.005:
        scenario = "PESSIMISTIC"
    else:
        scenario = "VERY-PESSIMISTIC (fork to diagnostic)"
    print(f"  Mean paired ΔO = {raw_o:+.4f} → {scenario}")

    # Fragile-task gate check
    print("\n=== Gate-verify check (per-task ΔO ≥ -0.030) ===")
    fails = [r for r in rows if r["do"] < -0.030]
    if fails:
        print(f"  FAIL: {len(fails)} tasks regressed > -0.030:")
        for r in fails:
            print(f"    id={r['id']} ΔO={r['do']:+.4f}")
    else:
        print("  PASS: all tasks ≥ -0.030 paired ΔO")

    return 0


if __name__ == "__main__":
    sys.exit(main())
