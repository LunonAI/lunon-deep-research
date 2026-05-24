"""Architect subagent (p1-checklist items 6 + 14; adapts AI-Q architect.j2).

Turns the Scout landscape + extracted intents + regenerated criteria into a
STRICT JSON plan: hierarchical TOC, 24-32 typed queries (1:1 mapped to the 5
researcher specialists), 24-32 acceptance criteria that FOLD IN every
regenerated sub-criterion and every extracted intent as an explicit coverage
obligation, and per-section depth targets. Archetype-aware (item 16).
"""

import json

from .. import llm

# query.type -> researcher specialist (1:1, per AI-Q + technique 16)
TYPE_TO_SPECIALIST = {
    "factual": "evidence_gatherer",
    "causal": "mechanism_explorer",
    "comparative": "comparator",
    "critical": "critic",
    "trend": "horizon_scanner",
}

# Archetype-specific Architect emphasis (item 16: per-archetype planner template).
_ARCH_EMPHASIS = {
    "list-all": "Exhaustive enumeration: populate the REQUIRED entity_matrix "
    "with every prompt-enumerated entity AND the dimensions a reader would "
    "compare them on. The writer renders the matrix as a table near the "
    "article's start. Bias query mix to factual + comparative.",
    "compare": "Build an explicit entity×dimension comparison matrix as the "
    "article's core deliverable: populate the REQUIRED entity_matrix with "
    "every entity the prompt asks to compare AND the dimensions of comparison. "
    "The writer renders this matrix as a table near the article's start AND "
    "gives each entity equal-depth treatment downstream. Bias to comparative "
    "+ factual.",
    "trend": "Chronological evolution + current state + forward signal; bias to "
    "trend + causal; demand dated developments.",
    "explain-mechanism": "Causal spine: step-by-step chains showing each "
    "intermediate link, named theories/frameworks; bias "
    "to causal + critical; reject single-step assertions.",
    "predict": "Evidence-grounded forecast with scenarios, drivers, confidence "
    "ranges, time horizons; bias to trend + causal + critical.",
    "recommend": "Lead to a decisive ranked recommendation with a rationale "
    "table; bias to factual + comparative + critical.",
}

_SYSTEM = """You are the Architect. Convert the landscape + intents + evaluation \
criteria into a STRICT JSON research plan. Output ONLY this JSON object:

{
 "task_analysis": str,
 "report_title": str,
 "entity_matrix": {                /* REQUIRED for list-all and compare; */
   "entities": [str, ...],         /* omit (or set to null) for others. */
   "dimensions": [str, ...]
 },                                /* 5-20 entities (rows), 4-8 dimensions
                                      (columns). The article's spine is an
                                      explicit entity×dimension matrix that
                                      the writer renders as a table early on
                                      AND uses to ensure EQUAL depth per
                                      entity (no entity dropped, no entity
                                      over-weighted vs siblings).            */
 "report_toc": [ {"id": "S1", "title": str,
    "subsections": [ {"id": "S1.1", "title": str,
                      "depth_seeds": [str, ...] /* 2-4 specific
                          claims/entities/data points/comparisons that the
                          writer must populate as H4 sub-sub-sections under
                          this H3 subsection. Each seed is one focused
                          treatment, NOT a section title — write seeds as
                          short noun phrases or claim fragments, e.g.
                          "Pegasus Cloth evolution mechanics from V1→V2",
                          "Mu's Crystal Wall vs. Aiolia's Lightning Plasma
                           damage ratio". */
                     } ... 3-6 ],
    "depth_target": "deep"|"broad", "depth_rationale": str } ... 8-12 ],
 "acceptance_criteria": [ {"id": "AC1", "category":
    "content"|"source"|"structure"|"depth"|"format"|"exclusion",
    "text": str, "rationale": str, "verification": str,
    "source": "criterion"|"intent"|"prompt",
    "target_sections": ["S1", ...]} ... 24-32 ],
 "queries": [ {"id": "Q1", "text": str,
    "type": "factual"|"causal"|"comparative"|"critical"|"trend",
    "target_sections": ["S1", ...], "rationale": str } ... 24-32 ]
}

HARD RULES:
- EVERY regenerated sub-criterion provided becomes >=1 acceptance_criterion
  (source="criterion") with a concrete `verification` method.
- EVERY extracted intent becomes >=1 acceptance_criterion (source="intent").
- Prompt-enumerated terms/entities MUST appear verbatim as section or
  subsection titles (structural anchoring → instruction-following).
- 24-32 queries AND 24-32 acceptance_criteria. Every query maps to >=1 TOC
  section. Distribute query `type` to cover all needed analytical functions.
- report_toc 8-12 top-level sections; each top section has 3-6 subsections;
  each subsection has 2-4 depth_seeds. (Calibrated to the #1-leaderboard
  Qianfan corpus structural profile: mean 9 top sections, 4 subsections per
  top section, ~2-3 sub-sub-sections per subsection. A shallower outline
  produces a shorter, lower-Comprehensiveness article.)
- depth_seeds are the WRITER'S H4-leaf-section seeds — concrete claims,
  named entities, data points, or comparisons. Avoid generic seeds like
  "Background" or "Conclusion"; each seed is a specific substantive payload.
- entity_matrix REQUIRED for list-all and compare archetypes. Populate
  entities with EVERY entity the prompt names (verbatim where possible),
  AND choose 4-8 dimensions a reader would compare them across (the
  "columns" of the table the writer will render). Omit entity_matrix (or
  set to null) for other archetypes.
- Match the prompt's language."""


def build(
    prompt: str, language: str, archetype: str, intents: list, landscape: dict, coverage_obligations: list
) -> dict:
    emphasis = _ARCH_EMPHASIS.get(archetype, "")
    user = (
        f"PROMPT ({language}):\n{prompt}\n\n"
        f"ARCHETYPE: {archetype}\nARCHETYPE EMPHASIS: {emphasis}\n\n"
        f"EXTRACTED INTENTS (each must become an acceptance criterion):\n"
        f"{json.dumps(intents, ensure_ascii=False)}\n\n"
        f"REGENERATED EVALUATION SUB-CRITERIA (each must become an acceptance "
        f"criterion with a verification method):\n"
        f"{json.dumps(coverage_obligations, ensure_ascii=False)[:24000]}\n\n"
        f"SCOUT LANDSCAPE:\n{json.dumps(landscape, ensure_ascii=False)[:20000]}\n\n"
        f"Produce the STRICT JSON plan now."
    )
    # Adaptive thinking on, effort=low: the structured prompt does the heavy
    # lifting; medium effort added ~5min/task for no plan-quality gain in the
    # W1 smoke. Latency decision (logged).
    # Bumped from 16k to 24k tokens to fit the new depth_seeds payload:
    # 8-12 top sections × 3-6 subsections × 2-4 depth_seeds ≈ 200-450 seeds
    # per plan, plus the existing 24-32 acceptance_criteria + 24-32 queries.
    plan = llm.call_json(
        "architect", user, system=_SYSTEM, max_tokens=24000, effort="low", think=True, note="architect"
    )
    if not isinstance(plan, dict):  # B-13 defensive — plan structure is critical
        plan = plan[0] if isinstance(plan, list) and plan and isinstance(plan[0], dict) else {}
    _normalize(plan, archetype=archetype)
    return plan


# P2-Option-A-#1 calibration (mean of the 10 high-scoring Qianfan articles):
# 9.0 top sections, 4 subsections/top, 2-3 seeds/sub. The 8-12 / 3-6 / 2-4
# bounds bracket the natural variation across archetypes. Architect emissions
# outside these bounds are accepted (no fail-loud) but counted for diagnostics
# so we can see in telemetry whether the writer is being asked to populate a
# shallow tree.
_TOP_SECTIONS_MIN = 8
_TOP_SECTIONS_MAX = 12
_SUBSECTIONS_MIN = 3
_SUBSECTIONS_MAX = 6
_SEEDS_MIN = 2
_SEEDS_MAX = 4

# P2-Option-A-#7 entity_matrix bounds (list-all and compare archetypes only).
# The 5-20 entity range covers the corpus distribution: id=91 Saint Seiya
# (~15 named entities), id=8 ML materials (~7 method classes), id=20 Streamable
# HTTP (~5 transport variants). 4-8 dimensions covers a useful comparison
# table without overwhelming reader cognition.
_ENTITY_MATRIX_ENTITIES_MIN = 5
_ENTITY_MATRIX_ENTITIES_MAX = 20
_ENTITY_MATRIX_DIMENSIONS_MIN = 4
_ENTITY_MATRIX_DIMENSIONS_MAX = 8


def _normalize(plan: dict, *, archetype: str | None = None) -> None:
    """Attach specialist_role to every query; backfill depth_seeds default;
    backfill entity_matrix default for list-all/compare archetypes; record
    outline-depth diagnostics for downstream telemetry.

    Fail-soft: a plan that comes back with too-few top sections or missing
    depth_seeds is NOT rejected — the writer still runs on whatever the
    architect emitted. We record the shortfall in `plan["_outline_audit"]`
    so the orchestrate-layer can log it and we can see in dev runs whether
    the architect is honoring the new contract.

    `archetype` is optional for back-compat with tests that call _normalize
    directly without a plan-build cycle. When provided, the audit also
    surfaces entity_matrix shortfalls for list-all/compare archetypes.
    """
    for q in plan.get("queries", []):
        t = str(q.get("type", "factual")).strip().lower()
        if t not in TYPE_TO_SPECIALIST:
            t = "factual"
        q["type"] = t
        q["specialist_role"] = TYPE_TO_SPECIALIST[t]
    plan.setdefault("acceptance_criteria", [])
    plan.setdefault("report_toc", [])
    plan.setdefault("queries", [])

    toc = plan.get("report_toc", [])
    audit = {
        "n_top_sections": len(toc),
        "n_subsections_total": 0,
        "n_seeds_total": 0,
        "subsections_missing_seeds": 0,
        "shortfalls": [],
    }
    if len(toc) < _TOP_SECTIONS_MIN:
        audit["shortfalls"].append(f"top_sections={len(toc)}<{_TOP_SECTIONS_MIN}")
    if len(toc) > _TOP_SECTIONS_MAX:
        audit["shortfalls"].append(f"top_sections={len(toc)}>{_TOP_SECTIONS_MAX}")
    for sec in toc:
        subs = sec.get("subsections", []) or []
        audit["n_subsections_total"] += len(subs)
        if len(subs) < _SUBSECTIONS_MIN:
            audit["shortfalls"].append(f"{sec.get('id')}.subs={len(subs)}<{_SUBSECTIONS_MIN}")
        if len(subs) > _SUBSECTIONS_MAX:
            audit["shortfalls"].append(f"{sec.get('id')}.subs={len(subs)}>{_SUBSECTIONS_MAX}")
        for sub in subs:
            seeds = sub.get("depth_seeds")
            if not isinstance(seeds, list):
                # Backfill so the writer always sees a list. Pre-#1 plans
                # had no depth_seeds field at all; post-#1 plans that flunk
                # the schema can also arrive here. Both flow into the same
                # diagnostic path below — see Greptile PR #20 issue 2.
                sub["depth_seeds"] = []
                seeds = sub["depth_seeds"]
            # An absent-field subsection and an explicit `"depth_seeds": []`
            # subsection are writer-observably identical (writer sees empty
            # list in both cases). Count them identically in the audit so
            # diagnostics are comparable across plan vintages.
            if not seeds:
                audit["subsections_missing_seeds"] += 1
            audit["n_seeds_total"] += len(seeds)
            if len(seeds) < _SEEDS_MIN:
                audit["shortfalls"].append(f"{sub.get('id')}.seeds={len(seeds)}<{_SEEDS_MIN}")
            if len(seeds) > _SEEDS_MAX:
                audit["shortfalls"].append(f"{sub.get('id')}.seeds={len(seeds)}>{_SEEDS_MAX}")

    # P2-Option-A-#7 (2026-05-23): entity_matrix audit + backfill for
    # list-all and compare archetypes. The matrix is the article's spine
    # (rendered as a table near the article start) and the writer uses it
    # to ensure equal-depth treatment per entity.
    em = plan.get("entity_matrix")
    if archetype in {"list-all", "compare"}:
        if not isinstance(em, dict):
            # Backfill so writer never crashes on `entity_matrix["entities"]`.
            em = {"entities": [], "dimensions": []}
            plan["entity_matrix"] = em
            audit["shortfalls"].append("entity_matrix=missing(required-for-archetype)")
        ents = em.get("entities") if isinstance(em.get("entities"), list) else None
        dims = em.get("dimensions") if isinstance(em.get("dimensions"), list) else None
        if ents is None:
            em["entities"] = []
            ents = em["entities"]
        if dims is None:
            em["dimensions"] = []
            dims = em["dimensions"]
        audit["entity_matrix_entities"] = len(ents)
        audit["entity_matrix_dimensions"] = len(dims)
        if len(ents) < _ENTITY_MATRIX_ENTITIES_MIN:
            audit["shortfalls"].append(f"entity_matrix.entities={len(ents)}<{_ENTITY_MATRIX_ENTITIES_MIN}")
        if len(ents) > _ENTITY_MATRIX_ENTITIES_MAX:
            audit["shortfalls"].append(f"entity_matrix.entities={len(ents)}>{_ENTITY_MATRIX_ENTITIES_MAX}")
        if len(dims) < _ENTITY_MATRIX_DIMENSIONS_MIN:
            audit["shortfalls"].append(f"entity_matrix.dimensions={len(dims)}<{_ENTITY_MATRIX_DIMENSIONS_MIN}")
        if len(dims) > _ENTITY_MATRIX_DIMENSIONS_MAX:
            audit["shortfalls"].append(f"entity_matrix.dimensions={len(dims)}>{_ENTITY_MATRIX_DIMENSIONS_MAX}")

    plan["_outline_audit"] = audit
