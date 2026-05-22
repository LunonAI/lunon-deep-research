"""W7: rationale mining + GEPA-pattern dev loop + human-in-the-loop notes.

- mine(model): flatten results/race/<model>/raw_results.jsonl judge_analysis
  (P0 patch) into per-criterion rows via p0_artifacts/rationale_miner.
- weakest(rows): rank sub-criteria by (target - reference) score gap → the
  GEPA-pattern dev-loop target (lowest sub-criterion; plan point 6: propose
  1-2 edits to ONE role's prompt, keep iff dev Overall lift > 0.5, cap 5-10).
- write_human_notes(model): p1_artifacts/human_pattern_notes.md structured for
  a ≤30-min Connor review — top 5 HIGH-CONFIDENCE + next 5 REVIEW REQUIRED,
  cross-referenced to the P0 judge_preferences / reference_weakness catalogs
  (decision #6).
"""

import collections
import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "p0_artifacts"))
import rationale_miner as rm  # noqa: E402

DRB = pathlib.Path("/home/connor/dev/deep_research_bench")


def mine(model: str) -> list:
    rr = DRB / "results/race" / model / "raw_results.jsonl"
    rows = []
    for line in rr.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        ja = d.get("judge_analysis")
        if not ja:
            continue
        rows += rm.mine_judge_json(ja, d.get("id"), d.get("language", ""), d.get("prompt", ""))
    return rows


def weakest(rows: list, top=8) -> list:
    """Rank (dimension, criterion) by mean (target-reference) gap, ascending
    (most negative = our biggest deficit vs the benchmark reference)."""
    agg = collections.defaultdict(list)
    for r in rows:
        try:
            gap = float(r.get("target_score", 0)) - float(r.get("reference_score", 0))
        except (TypeError, ValueError):
            continue
        agg[(r["dimension"], r["criterion"])].append(gap)
    ranked = sorted(
        (
            {"dimension": d, "criterion": c, "mean_gap": round(sum(v) / len(v), 3), "n": len(v)}
            for (d, c), v in agg.items()
            if v
        ),
        key=lambda x: x["mean_gap"],
    )
    return ranked[:top]


def dim_gaps(rows: list) -> dict:
    agg = collections.defaultdict(list)
    for r in rows:
        try:
            agg[r["dimension"]].append(float(r.get("target_score", 0)) - float(r.get("reference_score", 0)))
        except (TypeError, ValueError):
            pass
    return {d: round(sum(v) / len(v), 3) for d, v in agg.items() if v}


def write_human_notes(model: str, out="p1_artifacts/human_pattern_notes.md"):
    rows = mine(model)
    wk = weakest(rows, top=10)
    dg = dim_gaps(rows)
    # representative judge rationale per weak criterion (shortest informative)
    by_crit = collections.defaultdict(list)
    for r in rows:
        by_crit[(r["dimension"], r["criterion"])].append(r.get("analysis", ""))

    L = [
        "# P1 human-in-the-loop pattern notes (machine pass — decision #6)",
        "",
        f"Source: results/race/{model}/raw_results.jsonl judge_analysis "
        f"(P0 patch). {len(rows)} per-criterion rationales mined.",
        "Structured for a ≤30-min Connor review. Cross-referenced to "
        "`p0_artifacts/judge_preferences.md` + `reference_weakness_summary.md`.",
        "",
        "## Dimension gaps vs reference (target − reference, negative = we trail)",
        "",
    ]
    for d, g in sorted(dg.items(), key=lambda x: x[1]):
        L.append(f"- **{d}**: {g:+.3f}")
    L += ["", "## Top 5 — HIGH-CONFIDENCE (auto-actionable; fed to dev loop)", ""]
    for i, w in enumerate(wk[:5], 1):
        ex = sorted(by_crit[(w["dimension"], w["criterion"])], key=len)
        ex = next((e for e in ex if len(e) > 60), ex[0] if ex else "")
        L += [
            f"### {i}. [{w['dimension']}] {w['criterion']}  (gap {w['mean_gap']:+.3f}, n={w['n']})",
            f"> {ex[:600]}",
            "",
        ]
    L += ["## Next 5 — REVIEW REQUIRED (need Connor's eye: register / archetype-specific / phrasing)", ""]
    for i, w in enumerate(wk[5:10], 6):
        ex = sorted(by_crit[(w["dimension"], w["criterion"])], key=len)
        ex = next((e for e in ex if len(e) > 60), ex[0] if ex else "")
        L += [
            f"### {i}. [{w['dimension']}] {w['criterion']}  (gap {w['mean_gap']:+.3f}, n={w['n']})",
            f"> {ex[:600]}",
            "",
        ]
    L += [
        "## Residual sign-off for Connor",
        "",
        "- [ ] Confirm the REVIEW-REQUIRED patterns are real (not judge noise) before they drive prompt edits.",
        "- [ ] Spot-check 3-4 raw articles vs their rationale for register/cultural issues automation misses.",
        "",
    ]
    p = _ROOT / out
    p.write_text("\n".join(L), encoding="utf-8")
    return {"path": str(p), "n_rationales": len(rows), "dim_gaps": dg, "weakest": wk}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    a = ap.parse_args()
    print(json.dumps(write_human_notes(a.model), indent=2, ensure_ascii=False))
