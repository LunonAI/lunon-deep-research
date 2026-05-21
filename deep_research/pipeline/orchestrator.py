"""Orchestrator (p1-checklist items 8, 23).

Plan-once → research 3-5 cycles → one forced gap-review → ≤2 gap-fill → stop
(AI-Q orchestrator.j2 shape). Enforces:
- Hard tool-call budget = 24 (each Exa search = 1 tool call; halts, never exceeds).
- Forced reflection: a `think` gap-review marking each acceptance criterion
  SATISFIED/PARTIAL/UNSAT, picking ≤2 critical gaps.
- IterResearch compressed-report memory, bounded compaction every N=8 tool calls.
Specialists run in ISOLATED context (item 24); findings land in the WebWeaver
memory bank keyed by the producing query's target_sections (items 13/25).
"""
import json

from .. import llm
from .specialists import research
from .memory_bank import MemoryBank

BUDGET = 24
COMPACT_EVERY = 8

# Per-archetype researcher routing (W9 diagnostic + dev6 paired test 2026-05-21):
# SHIPPED CONFIG: Tongyi-DR routes list-all ONLY. dev6 showed +0.020 mean
# on list-all (n=2, both positive) but n=1 explain-mech regressed −0.031
# (id=56 was top-of-variance W9 outlier 0.586 → regression-to-mean likely).
# Reverted explain-mech to default Nemotron pending more data.
TONGYI_ROUTED_ARCHETYPES = {"list-all"}
TONGYI_MODEL = "alibaba/tongyi-deepresearch-30b-a3b"

_GAP_SYSTEM = (
    "You are the Orchestrator doing a gap review (think step). For EACH "
    "acceptance criterion, judge it against the evidence digest as SATISFIED, "
    "PARTIAL, or UNSAT. Then pick the <=2 MOST critical gaps to fill. Output "
    "ONLY JSON: {\"review\": [{\"id\": str, \"status\": "
    "\"SATISFIED\"|\"PARTIAL\"|\"UNSAT\", \"note\": str}], \"gap_fill\": "
    "[{\"brief\": str, \"specialist_role\": "
    "\"evidence_gatherer\"|\"mechanism_explorer\"|\"comparator\"|\"critic\"|"
    "\"horizon_scanner\"|\"generalist\"}] }. <=2 gap_fill items, only for true "
    "UNSAT/PARTIAL gaps that matter most for the prompt."
)

_COMPACT_SYSTEM = (
    "Compress these research findings into a dense evidence digest: keep every "
    "specific number, date, named entity, source, and causal chain; drop "
    "redundancy and filler. No new claims. Output plain text, grouped by "
    "subtopic. This is working memory, not the final report."
)

# archetype → specialist dispatch priority (which roles matter most first)
_ARCH_PRIORITY = {
    "list-all": ["evidence_gatherer", "comparator", "generalist"],
    "compare": ["comparator", "evidence_gatherer", "critic"],
    "trend": ["horizon_scanner", "evidence_gatherer", "mechanism_explorer"],
    "explain-mechanism": ["mechanism_explorer", "critic", "evidence_gatherer"],
    "predict": ["horizon_scanner", "mechanism_explorer", "critic",
                "evidence_gatherer"],
    "recommend": ["evidence_gatherer", "comparator", "critic",
                  "mechanism_explorer"],
}


def _groups_by_role(plan):
    """Group architect queries by specialist_role into query lists."""
    groups = {}
    for q in plan.get("queries", []):
        groups.setdefault(q.get("specialist_role", "generalist"), []).append(q)
    return groups


def run(plan, prompt, language, archetype, domain):
    bank = MemoryBank()
    groups = _groups_by_role(plan)
    tool_calls = 0
    digest_parts = []

    # research-cycle order: archetype priority first, then any remaining roles
    order = [r for r in _ARCH_PRIORITY.get(archetype, [])
             if r in groups] + [r for r in groups
                                 if r not in _ARCH_PRIORITY.get(archetype, [])]

    def ingest(res, role_groups):
        q_by_id = {q.get("id"): q for q in role_groups}
        for f in res.get("findings", []):
            qids = f.get("query_ids") or list(q_by_id)
            secs = []
            for qid in qids:
                secs += (q_by_id.get(qid, {}) or {}).get("target_sections", [])
            if not secs:  # fall back to all sections this role's queries target
                for q in role_groups:
                    secs += q.get("target_sections", [])
            bank.add(source_name=f.get("source_name", ""), url=f.get("url", ""),
                     title=f.get("source_name", ""), text=f.get("statement", "")
                     + (f"  «{f.get('quote','')}»" if f.get("quote") else ""),
                     query_id=",".join(map(str, qids)),
                     section_ids=sorted(set(secs)),
                     specialist=res.get("role"), language=language)
            digest_parts.append(f"[{res.get('role')}] {f.get('statement','')} "
                                 f"({f.get('source_name','')})")

    exa_mode = "deep" if archetype in ("explain-mechanism", "predict") else "auto"
    # Per-archetype researcher routing (W9 diagnostic decision)
    model_override = TONGYI_MODEL if archetype in TONGYI_ROUTED_ARCHETYPES else ""

    for role in order:
        if tool_calls >= BUDGET:
            break
        qlist = groups.get(role, [])
        # budget-aware: never let a dispatch push total past BUDGET
        qlist = qlist[:max(1, min(5, BUDGET - tool_calls))]
        try:
            res = research(role, qlist, language=language, domain=domain,
                           exa_mode=exa_mode, model_override=model_override)
        except Exception as e:  # noqa: BLE001  per-specialist resilience
            digest_parts.append(f"[{role}] (specialist failed: "
                                f"{type(e).__name__}; proceeding)")
            continue
        tool_calls += res.get("n_searches", 0)
        ingest(res, groups.get(role, []))
        if tool_calls and tool_calls % COMPACT_EVERY < res.get("n_searches", 1):
            digest_parts[:] = [_compact(digest_parts)]  # bounded compaction

    # forced reflection / gap review
    gap = _gap_review(plan, digest_parts)
    for g in (gap.get("gap_fill") or [])[:2]:
        if tool_calls >= BUDGET:
            break
        role = g.get("specialist_role", "generalist")
        gq = [{"id": "gapfill", "text": g.get("brief", ""),
               "target_sections": []}]
        try:
            res = research(role, gq, language=language, domain=domain,
                           exa_mode=exa_mode, model_override=model_override)
        except Exception:  # noqa: BLE001
            continue
        tool_calls += res.get("n_searches", 0)
        # gap-fill evidence is broadly relevant → tag all top-level sections
        top = [s.get("id") for s in plan.get("report_toc", [])]
        for f in res.get("findings", []):
            bank.add(source_name=f.get("source_name", ""),
                     url=f.get("url", ""), title=f.get("source_name", ""),
                     text=f.get("statement", ""), query_id="gapfill",
                     section_ids=top, specialist=role, language=language)

    if tool_calls > BUDGET:
        raise RuntimeError(f"tool-call budget exceeded ({tool_calls}>{BUDGET})")
    return {"memory_bank": bank, "gap_review": gap.get("review", []),
            "tool_calls": tool_calls, "digest": _compact(digest_parts)}


def _compact(parts):
    if not parts:
        return ""
    joined = "\n".join(parts)
    if len(joined) < 6000:
        return joined
    return llm.call("orchestrator", joined[:48000], system=_COMPACT_SYSTEM,
                    max_tokens=6000, note="orch.compact")


def _gap_review(plan, digest_parts):
    acs = [{"id": a.get("id"), "text": a.get("text"),
            "category": a.get("category")} for a in
           plan.get("acceptance_criteria", [])]
    user = ("ACCEPTANCE CRITERIA:\n" + json.dumps(acs, ensure_ascii=False)
            + "\n\nEVIDENCE DIGEST:\n" + _compact(digest_parts)[:40000])
    try:
        return llm.call_json("orchestrator", user, system=_GAP_SYSTEM,
                             max_tokens=8000, think=True, effort="low",
                             note="orch.gapreview")
    except Exception:  # noqa: BLE001
        return {"review": [], "gap_fill": []}
