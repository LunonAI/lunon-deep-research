"""Paired-Δ analyzer for two RACE-scored runs.

Given a baseline RACE result jsonl + a new RACE result jsonl, computes:
  - per-task overall ΔO (= new.overall_score − baseline.overall_score)
  - per-task per-dim Δ (Insight, Comp, InstFollow, Read)
  - cumulative mean ΔO across the paired tasks
  - gate decision per the Lunon discipline (see --gate-thresholds for the
    spec): cumulative ≥ +0.020 AND no single task regresses ≥ −0.030

Inputs are DRB harness `results/race/<run-tag>/raw_results.jsonl` files
(one row per task, fields: id, prompt, comprehensiveness, insight,
instruction_following, readability, overall_score). The script does NOT
re-weight the per-dim scores — it trusts the harness's `overall_score`
because the harness applies per-task weights from `criteria.jsonl` that
the operator-side overall-mean weights (Insight 0.352 / Comp 0.292 /
InstFollow 0.215 / Read 0.141 per handoff doc) approximate but don't
exactly reproduce.

Anti-hardcode discipline: gate thresholds are CLI arguments with the
handoff-doc default. Dim names are read from the actual data rather
than enumerated. If the harness changes its output shape in a future
version, this script surfaces it as a missing-field error rather than
silently mis-attributing.

Usage:
    # dev4 gate check (the Step A use case from the handoff doc)
    python3 scripts/p2_paired_delta.py \\
        --baseline /Users/hyattc/dev/deep_research_bench/results/race/lunon-w9-dev4-baseline/raw_results.jsonl \\
        --new /Users/hyattc/dev/deep_research_bench/results/race/lunon-p2-2026-05-26-option-a-dev4/raw_results.jsonl

    # W13 gate check, JSON output for downstream tooling
    python3 scripts/p2_paired_delta.py \\
        --baseline path/to/w9_full100_raw.jsonl \\
        --new path/to/w13_raw.jsonl \\
        --json-out p2_artifacts/w13_paired_delta.json \\
        --gate-cumulative 0.020 \\
        --gate-per-task-floor -0.030

Exit codes:
    0 = gate PASSED (cumulative ΔO ≥ floor AND no regressing task)
    1 = gate FAILED (operator decision: revert bundle as a unit OR diagnose)
    2 = no paired tasks (zero overlap on `id` between baseline and new)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

# The dim fields the DRB harness emits per task (see
# `/Users/hyattc/dev/deep_research_bench/deepresearch_bench_race.py`).
# Pinned here so a future harness rename surfaces as a missing-field
# error rather than a silent partial-Δ computation.
_DIM_FIELDS = ("comprehensiveness", "insight", "instruction_following", "readability")
_OVERALL_FIELD = "overall_score"


def _load_by_id(path: Path) -> dict[int, dict]:
    """Read a DRB raw_results jsonl into {task_id: row}."""
    out: dict[int, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        tid = row.get("id")
        if tid is None:
            continue
        # Allow either int or str ids — but normalize to whatever the
        # source file uses (mixed sources would silently mis-pair).
        out[int(tid) if isinstance(tid, (int, str)) and str(tid).isdigit() else tid] = row
    return out


def _delta_row(baseline_row: dict, new_row: dict) -> dict:
    """Per-task delta dict with overall + per-dim Δ + the raw scores
    on both sides for downstream rendering."""
    out = {
        "id": baseline_row.get("id"),
        "delta_overall": new_row[_OVERALL_FIELD] - baseline_row[_OVERALL_FIELD],
        "baseline_overall": baseline_row[_OVERALL_FIELD],
        "new_overall": new_row[_OVERALL_FIELD],
    }
    for dim in _DIM_FIELDS:
        b = baseline_row.get(dim)
        n = new_row.get(dim)
        if b is None or n is None:
            out[f"delta_{dim}"] = None
            continue
        out[f"delta_{dim}"] = n - b
    return out


def _gate_decision(per_task: list[dict], cumulative_floor: float, per_task_floor: float) -> dict:
    """Apply the handoff-doc gate logic. Returns a verdict dict.

    `cumulative_floor`: the mean ΔO across paired tasks must be ≥ this
        for the bundle to be considered a real lift (handoff doc default
        +0.020 for dev4; W13 has a separate three-band decision tree).
    `per_task_floor`: no single paired task may regress by more than
        |per_task_floor| — protects against a bundle that lifts on
        average but tanks one specific archetype. Default −0.030.
    """
    if not per_task:
        return {"status": "NO_DATA", "reason": "no paired tasks"}
    cumulative = statistics.mean(r["delta_overall"] for r in per_task)
    worst = min(per_task, key=lambda r: r["delta_overall"])
    worst_delta = worst["delta_overall"]
    if cumulative < cumulative_floor:
        return {
            "status": "FAIL",
            "reason": (
                f"cumulative ΔO {cumulative:+.4f} is below the gate floor "
                f"{cumulative_floor:+.4f} — bundle did not deliver the "
                f"expected lift"
            ),
            "cumulative": cumulative,
            "worst_task": worst["id"],
            "worst_delta": worst_delta,
        }
    if worst_delta < per_task_floor:
        return {
            "status": "FAIL",
            "reason": (
                f"task id={worst['id']} regressed by {worst_delta:+.4f}, "
                f"below the per-task floor {per_task_floor:+.4f} — even "
                f"though cumulative ΔO {cumulative:+.4f} cleared, the "
                f"bundle is unsafe to ship (one archetype is broken)"
            ),
            "cumulative": cumulative,
            "worst_task": worst["id"],
            "worst_delta": worst_delta,
        }
    return {
        "status": "PASS",
        "reason": (
            f"cumulative ΔO {cumulative:+.4f} ≥ floor {cumulative_floor:+.4f} "
            f"AND worst single-task Δ {worst_delta:+.4f} ≥ floor "
            f"{per_task_floor:+.4f} (task id={worst['id']})"
        ),
        "cumulative": cumulative,
        "worst_task": worst["id"],
        "worst_delta": worst_delta,
    }


def _render_human(per_task: list[dict], verdict: dict, baseline_path: Path, new_path: Path) -> str:
    """Human-readable per-task table + summary + gate verdict."""
    lines = []
    lines.append("=" * 78)
    lines.append("Paired-Δ analysis")
    lines.append(f"  baseline: {baseline_path}")
    lines.append(f"  new:      {new_path}")
    lines.append(f"  paired tasks: {len(per_task)}")
    lines.append("=" * 78)
    lines.append("")
    header = f"{'task':>5}  {'baseline':>9}  {'new':>9}  {'ΔO':>9}  {'ΔInsight':>9}  {'ΔComp':>9}  {'ΔInst':>9}  {'ΔRead':>9}"
    lines.append(header)
    lines.append("-" * len(header))
    for r in sorted(per_task, key=lambda x: x["id"]):
        cells = [
            f"{r['id']:>5}",
            f"{r['baseline_overall']:>9.4f}",
            f"{r['new_overall']:>9.4f}",
            f"{r['delta_overall']:>+9.4f}",
            f"{r.get('delta_insight') or 0:>+9.4f}",
            f"{r.get('delta_comprehensiveness') or 0:>+9.4f}",
            f"{r.get('delta_instruction_following') or 0:>+9.4f}",
            f"{r.get('delta_readability') or 0:>+9.4f}",
        ]
        lines.append("  ".join(cells))
    lines.append("-" * len(header))
    # Per-dim cumulative deltas (mean across tasks) — useful diagnostic
    # for spotting which dim moved most.
    if per_task:
        dim_means = {dim: statistics.mean(r.get(f"delta_{dim}") or 0 for r in per_task) for dim in _DIM_FIELDS}
        cumulative_overall = statistics.mean(r["delta_overall"] for r in per_task)
        cum_cells = [
            "  MEAN",
            "    -    ",
            "    -    ",
            f"{cumulative_overall:>+9.4f}",
            f"{dim_means['insight']:>+9.4f}",
            f"{dim_means['comprehensiveness']:>+9.4f}",
            f"{dim_means['instruction_following']:>+9.4f}",
            f"{dim_means['readability']:>+9.4f}",
        ]
        lines.append("  ".join(cum_cells))
    lines.append("")
    lines.append(f"GATE: {verdict['status']}")
    lines.append(f"      {verdict['reason']}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", required=True, type=Path, help="DRB raw_results.jsonl for the baseline run.")
    ap.add_argument("--new", required=True, type=Path, help="DRB raw_results.jsonl for the new run.")
    ap.add_argument(
        "--ids",
        default=None,
        help="Optional comma-separated id allowlist (default: every id present in BOTH files).",
    )
    ap.add_argument(
        "--gate-cumulative",
        type=float,
        default=0.020,
        help="Cumulative ΔO gate threshold (handoff-doc dev4 default: +0.020).",
    )
    ap.add_argument(
        "--gate-per-task-floor",
        type=float,
        default=-0.030,
        help="Per-task regression floor (handoff-doc default: -0.030; any task below fails the gate).",
    )
    ap.add_argument(
        "--json-out", type=Path, default=None, help="Optional path for machine-readable per-task deltas + verdict."
    )
    args = ap.parse_args()

    baseline = _load_by_id(args.baseline)
    new = _load_by_id(args.new)
    paired_ids = sorted(set(baseline.keys()) & set(new.keys()))

    if args.ids:
        allow = {int(s.strip()) if s.strip().isdigit() else s.strip() for s in args.ids.split(",") if s.strip()}
        paired_ids = [i for i in paired_ids if i in allow]

    if not paired_ids:
        print(
            f"error: no paired tasks between {args.baseline.name} ({len(baseline)} rows) and "
            f"{args.new.name} ({len(new)} rows)",
            file=sys.stderr,
        )
        sys.exit(2)

    per_task = [_delta_row(baseline[i], new[i]) for i in paired_ids]
    verdict = _gate_decision(per_task, args.gate_cumulative, args.gate_per_task_floor)

    print(_render_human(per_task, verdict, args.baseline, args.new))

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(
                {
                    "baseline_path": str(args.baseline),
                    "new_path": str(args.new),
                    "gate_cumulative": args.gate_cumulative,
                    "gate_per_task_floor": args.gate_per_task_floor,
                    "per_task": per_task,
                    "verdict": verdict,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\n[wrote] {args.json_out}", file=sys.stderr)

    sys.exit(0 if verdict["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
