"""Scout subagent (p1-checklist item 5; adapts AI-Q scout.j2).

Wide-net landscape discovery — NOT the final plan. Opus 4.7 proposes ≥12
diverse angles, each issued as an Exa search (≥10 Exa calls), then Opus
synthesizes a landscape map: definitions / divergences, discovered tensions,
per-topic source-richness, a suggested title and high-level (sections-only) TOC.
"""
import json

from .. import llm
from ..retrieval import exa

_Q_SYSTEM = (
    "You are a research Scout. Given a prompt, produce 12-14 DIVERSE web search "
    "queries that map the whole landscape: core definitions, key entities, "
    "competing viewpoints, quantitative sources, recent developments, critiques, "
    "and boundary/edge cases. Queries must be short search strings (no URLs, no "
    "operators). Output ONLY JSON: {\"queries\": [str, ...]}. Match the prompt's "
    "language for at least half the queries when the prompt is non-English."
)

_SYNTH_SYSTEM = (
    "You are a research Scout synthesizing a LANDSCAPE MAP (not a plan, not a "
    "report). From the search snippets, produce ONLY JSON: {"
    "\"task_analysis\": str (intent, explicit+implicit requirements, scope, "
    "language), \"suggested_title\": str, \"high_level_toc\": [str, ...] "
    "(top-level sections only, no subsections), \"key_definitions\": "
    "[{\"term\": str, \"note\": str}], \"tensions\": [str, ...] (genuine "
    "source disagreements / unstated assumptions / term-definition divergence), "
    "\"source_richness\": [{\"subtopic\": str, \"richness\": "
    "\"high\"|\"medium\"|\"low\"}]}. Be specific; cite concrete entities/numbers "
    "seen in snippets. Match the prompt's language."
)


def run(prompt: str, language: str, exa_mode: str = "auto") -> dict:
    qobj = llm.call_json(
        "scout", f"PROMPT ({language}):\n{prompt}", system=_Q_SYSTEM,
        max_tokens=3000, note="scout.queries")
    if not isinstance(qobj, dict):  # B-13 defensive
        qobj = {"queries": qobj if isinstance(qobj, list) else []}
    queries = [q for q in (qobj.get("queries") or []) if isinstance(q, str)][:14]
    if len(queries) < 10:  # guarantee item-5 ">=10 Exa calls"
        queries += [f"{prompt[:80]} {kw}" for kw in
                    ("overview", "data statistics", "criticism", "recent 2025 2026",
                     "comparison", "future outlook")][: 10 - len(queries)]

    snippets = []
    for q in queries:
        for r in exa.search(q, mode=exa_mode, num_results=5, max_chars=1200):
            snippets.append({"q": q, "title": r["title"], "url": r["url"],
                             "text": r["text"], "date": r["published_date"]})

    land = llm.call_json(
        "scout",
        f"PROMPT ({language}):\n{prompt}\n\nSEARCH SNIPPETS "
        f"({len(snippets)} from {len(queries)} queries):\n"
        + json.dumps(snippets, ensure_ascii=False)[:60000],
        system=_SYNTH_SYSTEM, max_tokens=8000, note="scout.synth")
    # B-13 defensive: LLM intermittently emits a JSON array instead of object;
    # extract_json returns whatever shape it parsed. Coerce to dict.
    if not isinstance(land, dict):
        land = {"task_analysis": str(land)[:1200], "tensions": [],
                "key_definitions": [], "high_level_toc": [],
                "source_richness": []}
    land["_n_exa_calls"] = len(queries)
    land["_n_snippets"] = len(snippets)
    return land
