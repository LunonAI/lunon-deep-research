"""Within-task A/B judge harness for small-effect experiment evaluation.

Replaces cross-task paired RACE eval (paired SE ±0.02-0.05 on n=3-8) with
within-task pairwise judging (signal:noise ~10× cleaner because each task
serves as its own control).

Workflow:
  1. Produce two adapter outputs (baseline.jsonl + experiment.jsonl) on
     identical task IDs via separate engine versions.
  2. For each matched (task_id) pair, call an LLM judge with both articles
     and ask which is better PER-DIMENSION (Comprehensiveness, Insight,
     Instruction-Following, Readability). Returns A / B / Tie per dim.
  3. Aggregate paired wins to detect even +0.005-class effects that
     blind RACE eval can't surface at this sample size.

Usage:
  # Either set DRB_REPO so --query-file is auto-derived:
  DRB_REPO=/path/to/deep_research_bench \\
    python3 scripts/p2_within_task_ab.py \\
      --a p2_artifacts/baseline.jsonl \\
      --b p2_artifacts/experiment.jsonl \\
      --out p2_artifacts/ab_result.json
  # ...or pass --query-file explicitly.

Cost: ~$1-2 per pair judged (one call with both articles as input; actual cost
depends on the model configured for the `inner_scorer` role in config.py).
The judge uses `inner_scorer` so pairwise verdicts should correlate with
RACE scores without re-running the full RACE pipeline.

Honest caveat: the judge is the SAME model as the harness judge but called
differently (pairwise comparison instead of per-dimension absolute scoring).
A/B preference is the strongest within-task signal available short of
running the full RACE harness, but it's not a perfect proxy. Treat agreement
between A/B + structural-similarity + compliance as the gate; treat A/B
alone as suggestive.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure repo-root on path so we can import deep_research.llm.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deep_research import llm  # noqa: E402

_JUDGE_SYSTEM = """You are an expert judge for DeepResearch Bench articles. You will see TWO articles answering the same research prompt. The articles are labelled A and B; their order is randomized — do NOT use position as a signal.

Score each article per dimension using the DeepResearch Bench RACE rubric:

- Comprehensiveness: does the article cover the prompt's required scope, all enumerated entities, every requested dimension? Penalize missing required content; penalize off-scope filler.

- Insight: does the article deliver useful synthesis — forward-looking analysis, named alternatives, causal chains, quantified uncertainty — beyond mere enumeration? Penalize paranoid restraint that announces evidence boundaries instead of synthesizing.

- Instruction-Following: does the article structurally satisfy the prompt's explicit instructions (sections requested, format requested, language requested, archetype implied)? Penalize structural mis-matches.

- Readability: does the article read as coherent, well-paced, properly numbered, free of repetition and meta-commentary? Penalize duplicated headings, broken numbering, restated drivers across sections, stage-direction phrases.

Return a STRICT JSON object — no preamble, no markdown, just JSON:

{
  "comp": "A" | "B" | "Tie",
  "insight": "A" | "B" | "Tie",
  "inst": "A" | "B" | "Tie",
  "read": "A" | "B" | "Tie",
  "overall_winner": "A" | "B" | "Tie",
  "comp_margin": 0|1|2|3,
  "insight_margin": 0|1|2|3,
  "inst_margin": 0|1|2|3,
  "read_margin": 0|1|2|3,
  "rationale": "1-3 sentences explaining the per-dim verdicts"
}

Margins: 0 = Tie, 1 = slight, 2 = clear, 3 = decisive.
"""

_ARTICLE_CHAR_LIMIT = 60_000  # ~15k tokens per article; ample for most DRB outputs


def _load_jsonl(path: Path) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        try:
            out[int(d["id"])] = d
        except (KeyError, ValueError):
            continue
    return out


def _load_queries(path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        try:
            out[int(d["id"])] = d["prompt"]
        except (KeyError, ValueError):
            continue
    return out


def judge_pair(prompt: str, article_a: str, article_b: str) -> dict:
    """Run one within-task A/B comparison. Returns the parsed JSON verdict."""
    user = (
        f"PROMPT:\n{prompt[:6_000]}\n\n"
        f"=== ARTICLE A ===\n{article_a[:_ARTICLE_CHAR_LIMIT]}\n\n"
        f"=== ARTICLE B ===\n{article_b[:_ARTICLE_CHAR_LIMIT]}\n\n"
        "Output the JSON verdict per the system rubric — no preamble."
    )
    try:
        out = llm.call_json(
            "inner_scorer",
            user,
            system=_JUDGE_SYSTEM,
            max_tokens=2_000,
            seed=0,
            effort="medium",
            note="within_task_ab",
        )
    except Exception as exc:  # noqa: BLE001 — A/B is best-effort
        return {"error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(out, dict):
        return {"error": "judge returned non-dict", "raw": str(out)[:500]}
    return out


def run_ab(a_path: Path, b_path: Path, queries_path: Path, swap_order: bool = True) -> dict:
    """Compare every matched (task_id) pair from a and b; return aggregate."""
    a = _load_jsonl(a_path)
    b = _load_jsonl(b_path)
    queries = _load_queries(queries_path)
    matched = sorted(set(a) & set(b))
    if not matched:
        return {"error": "no matching task_ids between A and B", "a_ids": list(a), "b_ids": list(b)}

    per_task: list[dict] = []
    for tid in matched:
        prompt = queries.get(tid, "")
        if not prompt:
            per_task.append({"task_id": tid, "error": "prompt not found in query file"})
            continue
        # Randomize order to control for position bias: even task_ids get
        # baseline as A, odd get baseline as B. Caller passes baseline=a and
        # experiment=b; the result fields use the SHOWN labels.
        if swap_order and (tid % 2 == 1):
            shown_a, shown_b = b[tid]["article"], a[tid]["article"]
            baseline_is_A = False
        else:
            shown_a, shown_b = a[tid]["article"], b[tid]["article"]
            baseline_is_A = True
        verdict = judge_pair(prompt, shown_a, shown_b)
        verdict["task_id"] = tid
        verdict["baseline_is_A"] = baseline_is_A
        per_task.append(verdict)

    # Aggregate: convert "A"/"B" to "baseline"/"experiment" using baseline_is_A.
    def remap(v: str, is_a: bool) -> str:
        if v == "Tie":
            return "tie"
        if v == "A":
            return "baseline" if is_a else "experiment"
        if v == "B":
            return "experiment" if is_a else "baseline"
        return v

    tally = {
        "comp": {"baseline": 0, "experiment": 0, "tie": 0, "err": 0},
        "insight": {"baseline": 0, "experiment": 0, "tie": 0, "err": 0},
        "inst": {"baseline": 0, "experiment": 0, "tie": 0, "err": 0},
        "read": {"baseline": 0, "experiment": 0, "tie": 0, "err": 0},
        "overall": {"baseline": 0, "experiment": 0, "tie": 0, "err": 0},
    }
    for r in per_task:
        if "error" in r:
            for d in tally.values():
                d["err"] += 1
            continue
        is_a = r.get("baseline_is_A", True)
        for src, dst in (
            ("comp", "comp"),
            ("insight", "insight"),
            ("inst", "inst"),
            ("read", "read"),
            ("overall_winner", "overall"),
        ):
            v = remap(r.get(src, "Tie"), is_a)
            tally[dst][v if v in tally[dst] else "err"] += 1

    return {"n_pairs": len(matched), "per_task": per_task, "tally": tally}


def _default_query_file() -> str | None:
    """Greptile follow-up PR #18: avoid hardcoded /home/connor/... default.
    Derive query-file from `DRB_REPO` env var (the same pattern the shell
    pilot scripts use). Returns None if DRB_REPO isn't set so argparse
    treats the arg as required-with-clear-error instead of silently
    FileNotFoundError-ing at read time on someone else's machine."""
    drb_repo = os.environ.get("DRB_REPO")
    if not drb_repo:
        return None
    return str(Path(drb_repo) / "data" / "prompt_data" / "query.jsonl")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="baseline articles jsonl")
    ap.add_argument("--b", required=True, help="experiment articles jsonl")
    _default_qf = _default_query_file()
    ap.add_argument(
        "--query-file",
        default=_default_qf,
        required=_default_qf is None,
        help=(
            "DRB query.jsonl source for prompts. Defaults to "
            "$DRB_REPO/data/prompt_data/query.jsonl when DRB_REPO is set; "
            "otherwise --query-file is required."
        ),
    )
    ap.add_argument("--out", required=True, help="output JSON path for verdicts + tally")
    ap.add_argument("--no-swap", action="store_true", help="disable position-bias randomization")
    args = ap.parse_args()

    out = run_ab(Path(args.a), Path(args.b), Path(args.query_file), swap_order=not args.no_swap)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    if "error" in out:
        print(f"[ab] FAILED: {out['error']}", file=sys.stderr)
        sys.exit(2)

    t = out["tally"]
    print(f"[ab] n_pairs = {out['n_pairs']}")
    for dim in ("comp", "insight", "inst", "read", "overall"):
        b = t[dim]["baseline"]
        e = t[dim]["experiment"]
        tie = t[dim]["tie"]
        err = t[dim]["err"]
        print(f"  {dim:>8}:  baseline={b}  experiment={e}  tie={tie}  err={err}")


if __name__ == "__main__":
    main()
