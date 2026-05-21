"""Benchmark adapter (p1-checklist item 2).

query.jsonl line in  ->  {id, prompt, article} line out.

- Resumable: skips ids already present with a valid record; appends incrementally
  so a killed process loses at most the in-flight task.
- Resume integrity check (plan point 11): every existing output line must parse
  as JSON with non-empty {id, prompt, article}; malformed/partial lines are
  dropped and that id re-runs.
- DRB_PHASE asserted at startup (fail-loud, plan point 9).

Run: DRB_PHASE=P1 /usr/bin/python3 -m deep_research.adapter \
        --query-file /home/connor/dev/deep_research_bench/data/prompt_data/query.jsonl \
        --out p1_artifacts/<name>.jsonl [--limit N] [--only-en|--only-zh] [--ids 1,2,3]
"""
import argparse
import json
import pathlib
import sys

from . import assert_phase, deep_research

DEFAULT_QUERY = "/home/connor/dev/deep_research_bench/data/prompt_data/query.jsonl"


def _load_queries(path):
    rows = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _valid_record(obj) -> bool:
    return (
        isinstance(obj, dict)
        and obj.get("id") is not None
        and isinstance(obj.get("prompt"), str) and obj["prompt"].strip()
        and isinstance(obj.get("article"), str) and obj["article"].strip()
    )


def _scan_existing(out_path: pathlib.Path):
    """Return (done_ids:set, clean_lines:list[str]) — drops corrupt/partial lines."""
    done, clean = set(), []
    if not out_path.exists():
        return done, clean
    for line in out_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # partial/corrupt line from a killed process -> drop, re-run
        if _valid_record(obj):
            done.add(str(obj["id"]))
            clean.append(json.dumps(obj, ensure_ascii=False))
    return done, clean


def run(query_file, out, limit=None, only_en=False, only_zh=False, ids=None,
        workers=1):
    assert_phase()
    out_path = pathlib.Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    queries = _load_queries(query_file)
    if only_en:
        queries = [q for q in queries if q.get("language") == "en"]
    if only_zh:
        queries = [q for q in queries if q.get("language") == "zh"]
    if ids:
        want = {int(x) for x in ids}
        queries = [q for q in queries if q["id"] in want]
    if limit:
        queries = queries[:limit]

    done, clean = _scan_existing(out_path)
    # Rewrite the file with only clean lines (drops any corrupt tail).
    out_path.write_text(
        ("\n".join(clean) + "\n") if clean else "", encoding="utf-8")

    total = len(queries)
    todo = [q for q in queries if str(q["id"]) not in done]
    print(f"[adapter] {total} selected, {len(done)} already valid, "
          f"{len(todo)} to run -> {out_path} (workers={workers})", flush=True)

    import threading
    write_lock = threading.Lock()
    counter = {"n": 0}

    def _one(q):
        qid, prompt, lang = q["id"], q["prompt"], q.get("language", "en")
        article = None
        for attempt in range(2):  # one retry on any exception (intermittent
            try:                  # malformed LLM JSON or transient API blip)
                article = deep_research(prompt, lang)["article"]
                break
            except Exception as e:  # noqa: BLE001
                import traceback
                tag = "RETRY" if attempt == 0 else "FINAL"
                print(f"[adapter] id={qid} {tag} FAILED: "
                      f"{type(e).__name__}: {e}",
                      file=sys.stderr, flush=True)
                traceback.print_exc(file=sys.stderr)
        if article is None:
            return
        rec = {"id": str(qid), "prompt": prompt, "article": article}
        with write_lock:
            counter["n"] += 1
            with out_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[adapter] ({counter['n']}/{len(todo)}) wrote id={qid} "
                  f"lang={lang} words={len(article.split())}", flush=True)

    if workers <= 1:
        for q in todo:
            _one(q)
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_one, todo))
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query-file", default=DEFAULT_QUERY)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only-en", action="store_true")
    ap.add_argument("--only-zh", action="store_true")
    ap.add_argument("--ids", default=None, help="comma-separated id allowlist")
    ap.add_argument("--workers", type=int, default=1,
                    help="concurrent tasks (milestone runs: 4-8)")
    a = ap.parse_args()
    run(a.query_file, a.out, a.limit, a.only_en, a.only_zh,
        a.ids.split(",") if a.ids else None, a.workers)


if __name__ == "__main__":
    main()
