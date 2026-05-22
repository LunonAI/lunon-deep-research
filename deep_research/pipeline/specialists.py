"""Role-differentiated researcher specialists (p1-checklist items 7, 24).

5 specialists + Generalist fallback, all Nemotron-3-Super-120B via OpenRouter,
each in an ISOLATED context window scoped to its brief (item 24). Analytical-
function decomposition adapted from AI-Q researcher_agent prompts (technique 16).

Robustness (engine-smoke fix): Nemotron is a REASONING model — it cannot be
relied on to emit clean JSON for a query-planning step. So specialists search
the Architect's queries DIRECTLY (those are already well-formed; faster + more
faithful), then make ONE Nemotron extraction call with a generous budget and a
robust parser. If extraction still fails, fall back to snippet-derived findings
so a specialist never starves a task of evidence (AI-Q "proceed with what's
available").
"""

import json

from .. import llm
from ..retrieval import domain_routed

# Adapted from AI-Q researcher_agent/prompts/*.j2 (aiq_teardown.md §4).
_ROLE = {
    "evidence_gatherer": "EVIDENCE GATHERER. Concrete data, statistics, factual verification. "
    "Numerical precision; reconcile conflicting figures; trace to primary "
    "sources. Prefer datasets, filings, official statistics, named studies.",
    "mechanism_explorer": "MECHANISM EXPLORER. Causal-first: WHY it happens. Named theories/"
    "frameworks, step-by-step causal chains showing each intermediate "
    "link, feedback loops. Reject single-step assertions; require the "
    "intervening mechanism.",
    "comparator": "COMPARATOR. Head-to-head: benchmarks, rankings, trade-offs. Extract "
    "shared comparison dimensions; preserve tabular numbers exactly.",
    "critic": "CRITIC. Adversarial: counterarguments, limitations, failure cases, "
    "boundary conditions, where the mainstream narrative breaks.",
    "horizon_scanner": "HORIZON SCANNER. Recency-first: recent developments, trend evolution, "
    "dated milestones, named analysts' forward-looking commentary.",
    "generalist": "GENERALIST. Multi-mode fallback; let the question guide the method.",
}

_EXTRACT_SYSTEM = (
    "You are a research specialist. {role}\nFrom the search results, extract "
    "SOURCED findings that serve the brief. Think briefly if you must, "
    "but your FINAL output MUST be a single JSON object and nothing after it: "
    '{{"findings": [ {{"statement": str (one specific self-contained claim '
    'with concrete numbers/names/dates), "source_name": str (publication/'
    "institution, e.g. 'IEA 2025' — never a bare number), \"url\": str, "
    '"quote": str (verbatim support <=125 chars), "query_ids": [str]}} '
    "...8-14 findings ]}}. Only findings grounded in the results; reconcile "
    "conflicts in the statement; match the brief's language."
)


def _snippet_fallback(results, query_ids):
    """Degrade gracefully: turn raw search hits into evidence atoms."""
    out = []
    for r in results[:14]:
        txt = (r.get("text") or r.get("title") or "").strip()
        if not txt:
            continue
        out.append(
            {
                "statement": txt[:400],
                "source_name": (r.get("title") or r.get("url") or "")[:80],
                "url": r.get("url", ""),
                "quote": txt[:120],
                "query_ids": query_ids,
            }
        )
    return out


def research(role: str, queries: list, *, language: str, domain: str, exa_mode: str, model_override: str = "") -> dict:
    """queries: [{id,text,target_sections}] from the Architect plan for this
    specialist. Returns {role, findings:[...], n_searches}.

    model_override: optional model slug to use instead of role's configured
    model (used for per-archetype routing — e.g. Tongyi-DR for list-all).
    """
    role = role if role in _ROLE else "generalist"
    rdesc = _ROLE[role]
    qids = [str(q.get("id")) for q in queries]

    results, n = [], 0
    for q in queries[:5]:  # AI-Q: <=5 sequential searches per specialist
        qtext = q.get("text") or ""
        if not qtext:
            continue
        for h in domain_routed.search(qtext, language=language, domain=domain, mode=exa_mode, num_results=5):
            results.append(
                {
                    "title": h["title"],
                    "url": h["url"],
                    "text": h["text"][:1500],
                    "date": h.get("published_date", ""),
                    "qid": str(q.get("id")),
                }
            )
        n += 1

    if not results:
        return {"role": role, "findings": [], "n_searches": n}

    brief = "\n".join(f"[{q.get('id')}] {q.get('text', '')}" for q in queries)
    user = f"BRIEF ({language}):\n{brief}\n\nSEARCH RESULTS:\n" + json.dumps(results, ensure_ascii=False)[:42000]
    try:
        if model_override:
            # Route to override (Tongyi-DR for list-all/explain-mechanism)
            # via raw openrouter call; same system prompt, same JSON contract.
            from ..clients import openrouter_client

            sys_prompt = _EXTRACT_SYSTEM.format(role=rdesc)
            raw, _ = openrouter_client.raw_call(
                model_override, user, system=sys_prompt, max_tokens=14000, note=f"{role}.extract.override", provider=""
            )
            fobj = llm.extract_json(raw) if raw else {}
        else:
            fobj = llm.call_json(
                role,
                user,
                system=_EXTRACT_SYSTEM.format(role=rdesc),
                max_tokens=14000,
                note=f"{role}.extract",
                retries=1,
            )
        findings = fobj.get("findings") if isinstance(fobj, dict) else fobj
        findings = [f for f in (findings or []) if isinstance(f, dict) and f.get("statement")]
        if not findings:
            findings = _snippet_fallback(results, qids)
    except Exception:  # noqa: BLE001  reasoning model JSON failure → degrade
        findings = _snippet_fallback(results, qids)
    return {"role": role, "findings": findings, "n_searches": n}
