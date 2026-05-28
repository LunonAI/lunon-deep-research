"""P3b-OPT2 (2026-05-27): decide INNER_CAP=2 vs 3 from dev4 telemetry — free.

INNER_CAP=3 (the W9 / 0.5229 baseline) allows up to 2 corrective passes per
section. The question this answers: does the 2nd/3rd corrective pass (loop
iteration index >=2, only reachable at cap=3) actually flip a section from
failing to passing, or raise its score meaningfully? If not, cap=2 is safe and
saves ~$15-19/dev4.

Reads the per-section `inner_loop_trajectory` that orchestrate._persist_drift
writes into p1_artifacts/inner_loop_drift.jsonl. Run AFTER a cap=3 dev4:

    .venv/bin/python scripts/inner_cap_ab_analysis.py [path-to-drift.jsonl]

Decision rule (printed at the end): of the sections that ACTUALLY reached the
3rd pass (i==2), if <10% flipped to passing AND the mean min_score gain at
index 2 is <0.2, cap=2 is empirically safe → ship the flip. Otherwise keep
cap=3. (If no section ever reached i==2, cap=2 is behavior-identical on this
sample — safe, but confirm on a larger run.)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_DRIFT = Path(__file__).resolve().parent.parent / "p1_artifacts" / "inner_loop_drift.jsonl"
# Of the sections that ACTUALLY reached the 3rd pass (i==2), fewer than this
# fraction flipping to passing → the pass is mostly wasted → cap=2 safe.
BENEFIT_RATE_THRESHOLD = 0.10
SCORE_GAIN_THRESHOLD = 0.2  # mean min_score gain at index 2 below this → negligible


def _iter_sections(drift_path: Path):
    """Yield every section's trajectory across all tasks in the drift file."""
    if not drift_path.exists():
        return
    for line in drift_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        for sec in rec.get("inner_loop_trajectory", []) or []:
            iters = sec.get("iters") or []
            if iters:
                yield sec.get("section", "?"), iters


def analyze(drift_path: Path) -> dict:
    total_sections = 0
    reached_idx2 = 0  # sections whose 3rd pass (i==2) ran AND was judgeable
    benefited_idx2 = 0  # of those, sections where the 3rd pass scored a pass
    degraded_idx2 = 0  # i==2 entries excluded because the inner-scorer LLM failed
    score_gains = []  # min_score(at i==2) - min_score(at i==1) when both scored

    for _sid, iters in _iter_sections(drift_path):
        total_sections += 1
        by_i = {it["i"]: it for it in iters if "i" in it}
        if 2 not in by_i:
            continue
        it2 = by_i[2]
        it1 = by_i.get(1)
        # Exclude degraded i==2 entries: score_section returns a synthetic
        # ok=True / min_score=10.0 when the inner-scorer LLM call fails. Counting
        # that as a genuine "the 3rd pass saved this section" would bias the
        # verdict toward KEEP cap=3. Drop from numerator AND denominator AND the
        # score-gain samples. (Greptile PR #50.)
        if it2.get("degraded"):
            degraded_idx2 += 1
            continue
        reached_idx2 += 1
        # A section reaches iteration index 2 ONLY because the earlier passes
        # did not break the loop (the loop breaks on score_ok). So "reached
        # i==2" already implies "not yet passing" — the benefit of the 3rd
        # pass is simply whether the 3rd pass itself scored a pass.
        if it2.get("scored") and it2.get("score_ok"):
            benefited_idx2 += 1
        # Score gain when both i==1 and i==2 carried a numeric min_score.
        if it1 and it1.get("min_score") is not None and it2.get("min_score") is not None:
            score_gains.append(float(it2["min_score"]) - float(it1["min_score"]))

    # Denominator is sections that ACTUALLY reached a judgeable 3rd pass — only
    # those can benefit from it. Dividing by total_sections would make the
    # verdict almost always "safe" since few sections reach i==2 (Greptile #50).
    benefit_rate = (benefited_idx2 / reached_idx2) if reached_idx2 else 0.0
    reached_fraction = (reached_idx2 / total_sections) if total_sections else 0.0
    mean_gain = (sum(score_gains) / len(score_gains)) if score_gains else 0.0
    # cap=2 is safe if the 3rd pass either NEVER runs, OR — when it runs —
    # rarely flips a section to passing AND barely moves the score. Lean
    # toward keeping cap=3 (the 0.5229 leaderboard-baseline value).
    cap2_safe = reached_idx2 == 0 or (benefit_rate < BENEFIT_RATE_THRESHOLD and mean_gain < SCORE_GAIN_THRESHOLD)

    return {
        "total_sections": total_sections,
        "reached_idx2": reached_idx2,
        "reached_fraction": round(reached_fraction, 4),
        "benefited_from_idx2": benefited_idx2,
        "benefit_rate": round(benefit_rate, 4),
        "degraded_idx2_excluded": degraded_idx2,
        "mean_score_gain_at_idx2": round(mean_gain, 3),
        "n_score_gain_samples": len(score_gains),
        "cap2_safe": cap2_safe,
    }


def main() -> None:
    drift_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DRIFT
    print(f"=== INNER_CAP A/B analysis @ {drift_path} ===")
    if not drift_path.exists():
        print(f"  drift file not found: {drift_path}")
        print("  (run a cap=3 dev4 first so orchestrate writes inner_loop_trajectory)")
        sys.exit(1)

    r = analyze(drift_path)
    print(f"  sections analyzed:              {r['total_sections']}")
    print(f"  degraded i==2 excluded:         {r['degraded_idx2_excluded']} (inner-scorer LLM failed → synthetic pass)")
    print(
        f"  reached the 3rd pass (i>=2):    {r['reached_idx2']} ({r['reached_fraction'] * 100:.1f}% of all sections; only possible at cap=3)"
    )
    print(
        f"  of those, benefited (flipped):  {r['benefited_from_idx2']} ({r['benefit_rate'] * 100:.1f}% of 3rd-pass sections)"
    )
    print(f"  mean min_score gain at idx2:    {r['mean_score_gain_at_idx2']} (n={r['n_score_gain_samples']})")
    print()
    if r["total_sections"] == 0:
        print("  VERDICT: no trajectory data — was this run produced post-OPT2?")
        sys.exit(1)
    if r["reached_idx2"] == 0:
        print("  VERDICT: the 3rd pass NEVER ran in this sample — cap=2 would have been")
        print("           behavior-identical here. Safe on this evidence, but the sample")
        print("           may be too clean to be representative; confirm on a larger run.")
    elif r["cap2_safe"]:
        print(f"  VERDICT: cap=2 is EMPIRICALLY SAFE — <{BENEFIT_RATE_THRESHOLD * 100:.0f}% of the sections that")
        print(f"           ran a 3rd pass benefited from it, and mean gain <{SCORE_GAIN_THRESHOLD}.")
        print("           → ship PR-C to flip DR_INNER_CAP default to 2.")
    else:
        print("  VERDICT: KEEP cap=3 — the 3rd corrective pass is earning its cost")
        print(
            f"           ({r['benefit_rate'] * 100:.1f}% of 3rd-pass sections benefited, mean gain {r['mean_score_gain_at_idx2']})."
        )
        print("           Do NOT flip to cap=2.")


if __name__ == "__main__":
    main()
