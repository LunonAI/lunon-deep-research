"""Stage P1 engine output into the external DRB harness and run RACE.

- Stages p1_artifacts/<...>.jsonl -> {DRB}/data/test_data/raw_data/<model>.jsonl
- Runs the harness RACE scorer via its OWN venv + env.local.sh (GPT-5.5 judge;
  the harness does NOT read the engine .env — P0 handoff).
- Parses race_result.txt + raw_results.jsonl into Overall + per-dimension +
  per-archetype + EN/ZH split.

Model-name hygiene (plan point 10): unique date+iteration-stamped names only;
RESERVED names are refused so P0 trusted results are never clobbered.

Run: /usr/bin/python3 -m deep_research.eval_runner \
       --in p1_artifacts/<f>.jsonl --model lunon-p1-2026-05-19-dev1 [--limit N]
       [--only en|zh] [--workers 10]
"""

import argparse
import json
import pathlib
import subprocess
import sys

from ._env import drb_root

# DRB harness paths are resolved via drb_root() at each call site (not bound to
# module-level constants) so a caller that exports $DRB_REPO before running —
# even after this module is imported — is honored.
ARCH_MAP = pathlib.Path(__file__).resolve().parent.parent / "p0_artifacts/archetype_map.jsonl"
RESERVED = {"claude-3-7-sonnet-latest", "reference"}


def stage(in_jsonl: str, model: str) -> pathlib.Path:
    if model in RESERVED:
        raise RuntimeError(f"refusing reserved/clobber model name {model!r}")
    rows = [json.loads(x) for x in pathlib.Path(in_jsonl).read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:  # harness expects {id(str), prompt, article}
        r["id"] = str(r["id"])
    dst = drb_root() / "data/test_data/raw_data" / f"{model}.jsonl"
    dst.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return dst


def run_race(model: str, limit=None, only=None, workers=10, force=True) -> int:
    cmd = (
        f"./.venv/bin/python -u deepresearch_bench_race.py {model} "
        f"--raw_data_dir data/test_data/raw_data "
        f"--query_file data/prompt_data/query.jsonl "
        f"--output_dir results/race/{model} --max_workers {workers}"
    )
    if limit:
        cmd += f" --limit {int(limit)}"
    if only == "en":
        cmd += " --only_en"
    elif only == "zh":
        cmd += " --only_zh"
    if force:
        cmd += " --force"
    full = f"cd {drb_root()} && source env.local.sh && {cmd}"
    print(f"[eval] {full}", flush=True)
    return subprocess.call(["bash", "-lc", full])


def parse_result(model: str) -> dict:
    f = drb_root() / "results/race" / model / "race_result.txt"
    if not f.exists():
        return {}
    out = {}
    keymap = {
        "Comprehensiveness": "comprehensiveness",
        "Insight": "insight",
        "Instruction Following": "instruction_following",
        "Readability": "readability",
        "Overall Score": "overall",
    }
    for line in f.read_text().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip() in keymap:
                try:
                    out[keymap[k.strip()]] = float(v.strip())
                except ValueError:
                    pass
    return out


def breakdown(model: str) -> dict:
    drb = drb_root()
    rr = drb / "results/race" / model / "raw_results.jsonl"
    if not rr.exists():
        return {}
    rows = [json.loads(x) for x in rr.read_text().splitlines() if x.strip()]
    qlang = {}
    for q in (drb / "data/prompt_data/query.jsonl").read_text().splitlines():
        if q.strip():
            d = json.loads(q)
            qlang[str(d["id"])] = d["language"]
    arch = {}
    if ARCH_MAP.exists():
        for a in ARCH_MAP.read_text().splitlines():
            if a.strip():
                d = json.loads(a)
                arch[str(d["id"])] = d["archetype"]

    def agg(subset):
        if not subset:
            return {}
        n = len(subset)
        keys = ["comprehensiveness", "insight", "instruction_following", "readability", "overall_score"]
        return {"n": n, **{k: round(sum(r.get(k, 0) for r in subset) / n, 4) for k in keys}}

    by_lang = {lg: agg([r for r in rows if qlang.get(str(r["id"])) == lg]) for lg in ("en", "zh")}
    archset = sorted({arch.get(str(r["id"]), "?") for r in rows})
    by_arch = {a: agg([r for r in rows if arch.get(str(r["id"])) == a]) for a in archset}
    return {"n_total": len(rows), "overall": agg(rows), "by_language": by_lang, "by_archetype": by_arch}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", choices=["en", "zh"], default=None)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--no-run", action="store_true", help="stage+parse only (re-parse an existing run)")
    a = ap.parse_args()
    stage(a.inp, a.model)
    if not a.no_run:
        rc = run_race(a.model, a.limit, a.only, a.workers)
        if rc != 0:
            print(f"[eval] harness exited {rc}", file=sys.stderr)
    res = {"model": a.model, "race": parse_result(a.model), "breakdown": breakdown(a.model)}
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
