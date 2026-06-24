"""W8: AI-Q-style minimum bar (p1-checklist item 28; decision #4).

NOT our engine, NOT real AI-Q. Deliberately minimal AI-Q-shaped scaffold to
isolate "AI-Q-style scaffold + frontier writer" as a comparison bar:
  scout landscape → 3-5 Nemotron(OpenRouter) research cycles → GPT-5.5 writes
  the report directly (AI-Q orchestrator Phase-6 style, 5000-8000 words) →
  AI-Q REWRITE_PROMPT refiner (single pass).
NONE of the P1 differentiators (criteria-as-spec, per-section quality loop,
archetype router, WebWeaver, length governor) — that is the point: it is the
control, the engine is the treatment. Framed everywhere as a minimum bar, not
a floor (net direction vs real AI-Q unclear; decision #4).
"""

import json

from . import llm
from .pipeline import refiner, scout, specialists
from .retrieval import domain_routed

_WRITER_SYSTEM = (
    "You are an expert research analyst writing a comprehensive deep-research "
    "report (AI-Q orchestrator Phase-6 style): 5000-8000+ words, mirror a "
    "logical TOC, dedicated section per user-named item, flowing analytical "
    "prose with tables where useful, no meta-commentary. Attribute sources "
    "inline by name. Match the prompt's language."
)


def run(query: str, language: str) -> str:
    domain = domain_routed.classify_domain(query)
    land = scout.run(query, language, exa_mode="auto")

    # 3-5 generalist Nemotron research cycles (AI-Q researcher, not specialized)
    briefs = [query] + [str(t) for t in (land.get("high_level_toc") or [])[:4]]
    qlist = [{"id": f"A{i}", "text": b, "target_sections": []} for i, b in enumerate(briefs[:5])]
    findings = []
    for q in qlist:
        r = specialists.research("generalist", [q], language=language, domain=domain, exa_mode="auto")
        findings += r.get("findings", [])

    ev = json.dumps(findings, ensure_ascii=False)[:60000]
    draft = llm.call(
        "intent",  # role 'intent' = GPT-5.5 (writer for the baseline)
        f"PROMPT ({language}):\n{query}\n\nLANDSCAPE:\n"
        f"{json.dumps(land, ensure_ascii=False)[:12000]}\n\nEVIDENCE:\n{ev}\n\n"
        f"Write the full report now.",
        system=_WRITER_SYSTEM,
        max_tokens=32000,
        effort="medium",
        note="aiq.writer",
    )

    out = refiner.refine(draft, archetype="recommend", language=language)
    return out["article"]


if __name__ == "__main__":
    import argparse
    import pathlib

    from . import assert_phase
    from ._env import drb_root

    assert_phase()
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--query-file", default=str(drb_root() / "data" / "prompt_data" / "query.jsonl"))
    a = ap.parse_args()
    import threading
    from concurrent.futures import ThreadPoolExecutor

    qs = [json.loads(x) for x in pathlib.Path(a.query_file).read_text().splitlines() if x.strip()]
    if a.limit:
        qs = qs[: a.limit]
    outp = pathlib.Path(a.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if outp.exists():
        for ln in outp.read_text().splitlines():
            try:
                done.add(str(json.loads(ln)["id"]))
            except Exception:  # noqa: BLE001
                pass
    lock = threading.Lock()

    def one(q):
        if str(q["id"]) in done:
            return
        try:
            art = run(q["prompt"], q.get("language", "en"))
        except Exception as e:  # noqa: BLE001
            print(f"id={q['id']} FAIL {e}", flush=True)
            return
        with lock, outp.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": str(q["id"]), "prompt": q["prompt"], "article": art}, ensure_ascii=False) + "\n")
        print(f"wrote id={q['id']}", flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, qs))
