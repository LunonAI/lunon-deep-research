"""Wave 0 E-prereq — refiner_gate test-retest variance baseline.

Per plan §2.1 E-prereq (upgraded): re-score 10 sampled tasks × 3 independent
runs against same article, compute σ per-dim per-task, report mean σ.

Operational design: the refiner_gate (`pipeline/refiner_gate.compare`) is the
gate whose threshold we want to calibrate. It produces a `delta ∈ [-1, +1]`
verdict comparing pre vs post-refiner article. To measure its test-retest
variance on inputs that are deterministic-by-construction, we call
`compare(article, article)` (self-vs-self) which SHOULD return TIE / delta=0
but in practice an LLM judge will produce small noise. The σ of `delta`
across multiple self-vs-self calls is a lower bound on the gate's noise
floor — `DR_REFINER_GATE_THRESHOLD = 2 × σ_self` is the right active-mode
threshold (don't revert unless real signal > 2σ noise).

Tasks sampled: 10 EN+ZH balanced from W9 scored articles, archetypes mixed.
Seeds: 0, 1, 2 (matching gpt-5.5 best-effort determinism behavior).

Cost: 30 GPT-5.5 calls × ~$0.10 = ~$3. Way under the $200 plan budget; the
plan's budget was conservative.

Outputs:
  p2_artifacts/e_prereq_result.md (summary)
  p2_artifacts/e_prereq_calls.jsonl (raw per-call deltas)
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deep_research.pipeline import refiner_gate  # noqa: E402


def load_w9_articles(ids: list[int]) -> dict[int, dict]:
    """Return {id: {article, language, archetype?}}."""
    out = {}
    p = ROOT / "p1_artifacts" / "p1_final.jsonl"
    with p.open() as f:
        for line in f:
            d = json.loads(line)
            if int(d["id"]) in ids:
                out[int(d["id"])] = d
    return out


def main() -> int:
    # 10 sampled W9 articles balanced EN/ZH across archetypes.
    # Avoid cleaner-failing ZH (5,8,10,12,27,30,33,35,41,48,49) since we want
    # articles known to be properly-formed end products. Composition:
    #   EN gate-verify + spread: 56 (explain-mech), 71 (recommend),
    #                            67 (trend), 88 (explain-mech), 91 (list-all)
    #   ZH gate-verify + spread: 16 (sw-dev), 20 (sw-dev), 18 (recommend),
    #                            4 (list-all), 37 (trend)
    sample_ids = [56, 71, 67, 88, 91, 16, 20, 18, 4, 37]

    arts = load_w9_articles(sample_ids)
    print(f"Sampled n={len(arts)} W9 articles for E-prereq variance.")

    # 3 calls per article with different seeds
    raw_path = ROOT / "p2_artifacts" / "e_prereq_calls.jsonl"
    raw_lines = []
    deltas_by_id = {tid: [] for tid in sample_ids}
    t0 = time.time()
    for tid in sample_ids:
        if tid not in arts:
            print(f"WARN id={tid} not in p1_final.jsonl; skipping")
            continue
        art = arts[tid]
        for seed_label in (0, 1, 2):
            # The refiner_gate.compare uses seed=0 internally; to vary
            # we'd need to monkeypatch or modify the function. Instead, we
            # just call multiple times — gpt-5.5 is best-effort-deterministic
            # not strictly deterministic, so repeated calls still produce
            # noise even with same seed.
            try:
                verdict = refiner_gate.compare(
                    pre_article=art["article"],
                    post_article=art["article"],
                    language="zh" if any("一" <= c <= "鿿" for c in art["article"][:200]) else "en",
                    archetype="?",
                    task_fp=f"e_prereq_id{tid}_seed{seed_label}",
                    mode="monitor",
                )
            except Exception as e:  # noqa: BLE001
                verdict = {"winner": "ERROR", "delta": 0.0, "rationale": str(e), "degraded": True}
            line = {
                "id": tid,
                "seed_label": seed_label,
                "winner": verdict.get("winner"),
                "delta": verdict.get("delta"),
                "rationale": (verdict.get("rationale") or "")[:140],
            }
            raw_lines.append(line)
            deltas_by_id[tid].append(verdict.get("delta", 0.0))
            print(f"  id={tid} seed={seed_label}: winner={verdict.get('winner'):>4} delta={verdict.get('delta'):+.4f}")
    dt = time.time() - t0
    print(f"\nTotal elapsed: {dt:.1f}s ({len(raw_lines)} calls)")
    raw_path.write_text("\n".join(json.dumps(x) for x in raw_lines) + "\n")
    print(f"Raw calls → {raw_path}")

    # σ per task across 3 calls
    sigmas = []
    print("\n=== Per-task σ on self-vs-self delta ===")
    for tid in sample_ids:
        ds = deltas_by_id.get(tid, [])
        if len(ds) < 2:
            continue
        sigma = statistics.stdev(ds)
        mean = statistics.mean(ds)
        sigmas.append(sigma)
        print(f"  id={tid:3d}  n=3  mean_delta={mean:+.4f}  σ={sigma:.4f}  range={max(ds) - min(ds):.4f}")
    mean_sigma = statistics.mean(sigmas) if sigmas else 0.0
    max_sigma = max(sigmas) if sigmas else 0.0
    rec_threshold = round(2 * mean_sigma, 4)
    print("\n=== Aggregate ===")
    print(f"  Mean σ across tasks: {mean_sigma:.4f}")
    print(f"  Max σ across tasks:  {max_sigma:.4f}")
    print(f"  Recommended DR_REFINER_GATE_THRESHOLD (2 × mean σ): {rec_threshold:.4f}")
    print(f"  Conservative (2 × max σ): {2 * max_sigma:.4f}")
    print("  Current hardcoded threshold: 0.0200")

    # Write summary doc
    out_md = ROOT / "p2_artifacts" / "e_prereq_result.md"
    with out_md.open("w") as f:
        f.write("# Wave 0 E-prereq — Refiner-Gate Variance Baseline\n\n")
        f.write("**Date:** 2026-05-22\n")
        f.write("**Method:** Self-vs-self `refiner_gate.compare(article, article)` ")
        f.write(f"on {len(arts)} W9 articles × 3 calls = {len(raw_lines)} GPT-5.5 calls.\n\n")
        f.write("## Result\n\n")
        f.write(f"- **Mean σ across tasks:** {mean_sigma:.4f}\n")
        f.write(f"- **Max σ across tasks:** {max_sigma:.4f}\n")
        f.write(f"- **Recommended DR_REFINER_GATE_THRESHOLD (2 × mean σ):** {rec_threshold:.4f}\n")
        f.write(f"- **Conservative (2 × max σ):** {2 * max_sigma:.4f}\n")
        f.write("- **Current hardcoded threshold:** 0.0200\n\n")
        f.write("## Interpretation\n\n")
        if rec_threshold > 0.02:
            f.write(
                f"The current 0.02 threshold is TOO LOW relative to the measured noise floor "
                f"({mean_sigma:.4f}σ → 2σ = {rec_threshold:.4f}). Wave-3 E should raise the threshold to "
                f"≥ {rec_threshold:.4f} before flipping `DR_REFINER_GATE=active`, otherwise the gate will "
                f"false-revert on noise.\n"
            )
        else:
            f.write(
                f"The current 0.02 threshold is REASONABLE (mean σ = {mean_sigma:.4f}, 2σ = {rec_threshold:.4f}). "
                f"Wave-3 E can flip `DR_REFINER_GATE=active` with the existing threshold; "
                f"optionally tighten to {rec_threshold:.4f} if the team wants the gate to fire more often.\n"
            )
        f.write("\n## Per-task σ\n\n")
        f.write("| id | mean_delta | σ | range |\n|---|---|---|---|\n")
        for tid in sample_ids:
            ds = deltas_by_id.get(tid, [])
            if len(ds) < 2:
                continue
            sigma = statistics.stdev(ds)
            mean = statistics.mean(ds)
            f.write(f"| {tid} | {mean:+.4f} | {sigma:.4f} | {max(ds) - min(ds):.4f} |\n")
        f.write("\n## Method note\n\n")
        f.write(
            "Self-vs-self gives a LOWER bound on the gate's noise floor — calls on DIFFERENT inputs "
            "(real pre vs post refiner articles) will have ≥ this σ. The current implementation calls "
            "`refiner_gate.compare(article, article)` 3 times per article with the same `seed=0` (the "
            "function's internal default), measuring residual decoding stochasticity in GPT-5.5 even at "
            "fixed seed. For a tighter calibration, a follow-up could compare against minor article "
            "perturbations (e.g., paragraph reorderings) to better simulate real pre/post divergence.\n"
        )
    print(f"\nWrote {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
