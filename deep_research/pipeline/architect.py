"""Architect subagent (p1-checklist items 6 + 14; adapts AI-Q architect.j2).

Turns the Scout landscape + extracted intents + regenerated criteria into a
STRICT JSON plan: hierarchical TOC, 48-64 typed queries (1:1 mapped to the 5
researcher specialists; pre-#4 was 24-32, doubled to feed the depth_seeds
H4-leaf payload from PR #20), 24-32 acceptance criteria that FOLD IN every
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
    "list-all": "Exhaustive enumeration: a section/subsection or table row per "
    "required item; bias query mix to factual + comparative.",
    "compare": "Build an explicit entity×dimension comparison matrix as a core "
    "section; bias to comparative + factual; equal depth per entity.",
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
    "target_sections": ["S1", ...], "rationale": str } ... 48-64 ]
}

HARD RULES:
- EVERY regenerated sub-criterion provided becomes >=1 acceptance_criterion
  (source="criterion") with a concrete `verification` method.
- EVERY extracted intent becomes >=1 acceptance_criterion (source="intent").
- Prompt-enumerated terms/entities MUST appear verbatim as section or
  subsection titles (structural anchoring → instruction-following).
- 48-64 queries AND 24-32 acceptance_criteria. Every query maps to >=1 TOC
  section. Distribute query `type` to cover all needed analytical functions.
  (Query count doubled from 24-32 post-#4: the depth_seeds H4-leaf payload
  from PR #20 expects 200-450 leaves per article, each needing 3-5 evidence
  atoms = 600-2250 atoms total. Pre-#4 produced only ~40-70 atoms per task,
  leaving the depth contract structurally evidence-starved.)
- report_toc 8-12 top-level sections; each top section has 3-6 subsections;
  each subsection has 2-4 depth_seeds. (Calibrated to the #1-leaderboard
  the reference corpus structural profile: mean 9 top sections, 4 subsections per
  top section, ~2-3 sub-sub-sections per subsection. A shallower outline
  produces a shorter, lower-Comprehensiveness article.)
- depth_seeds are the WRITER'S H4-leaf-section seeds — concrete claims,
  named entities, data points, or comparisons. Avoid generic seeds like
  "Background" or "Conclusion"; each seed is a specific substantive payload.
- Match the prompt's language."""


# P2-Option-A-#1 calibration (mean of the 10 high-scoring the reference articles):
# 9.0 top sections, 4 subsections/top, 2-3 seeds/sub. The 8-12 / 3-6 / 2-4
# bounds bracket the natural variation across archetypes. Architect emissions
# outside these bounds are accepted (no fail-loud) but counted for diagnostics
# so we can see in telemetry whether the writer is being asked to populate a
# shallow tree.
#
# Greptile PR #23 round-2 follow-up (2026-05-25): moved this block above
# `_format_retry_feedback` so the LLM-facing retry feedback string can
# reference the same constants the audit uses. Previously the feedback
# hard-coded "8-12" / "3-6" / "2-4"; if anyone bumped a constant the
# architect would be coached toward a stale target while the actual code
# checks rejected the result, with no obvious source of the drift.
_TOP_SECTIONS_MIN = 8
_TOP_SECTIONS_MAX = 12
_SUBSECTIONS_MIN = 3
_SUBSECTIONS_MAX = 6
_SEEDS_MIN = 2
_SEEDS_MAX = 4
# P2-Option-A-#4 Greptile PR #22 follow-up (2026-05-25): query-count band
# enforced in the HARD RULES section of _SYSTEM. Tracked here next to the
# other structural bounds so a plan that silently regresses to the pre-#4
# 24-32 query band is visible in the audit log as a shortfall rather than
# passing without notice. Collocated with the other constants per PR #23's
# "_format_retry_feedback must reference the same source of truth" rule —
# if any future retry-feedback string interpolates the query band, it
# pulls from here.
_QUERIES_MIN = 48
_QUERIES_MAX = 64


def _format_retry_feedback(audit: dict) -> str:
    """Turn `_outline_audit` shortfalls into a feedback string for the
    architect's retry call. Lists each specific bound violation so the
    architect knows exactly what to fix, not just that 'something is wrong'.

    Bound numerals are interpolated from the module-level
    `_TOP_SECTIONS_*` / `_SUBSECTIONS_*` / `_SEEDS_*` constants so the LLM
    feedback can never drift away from the actual audit-check thresholds.
    """
    lines = [
        "SHORTFALL FEEDBACK — your previous plan did NOT meet the structural contract.",
        f"It returned {audit['n_top_sections']} top sections "
        f"(need {_TOP_SECTIONS_MIN}-{_TOP_SECTIONS_MAX}), "
        f"{audit['n_subsections_total']} total subsections, "
        f"{audit['n_seeds_total']} total depth_seeds.",
        "",
        "Specific bound violations the audit detected:",
    ]
    for s in audit.get("shortfalls", []):
        lines.append(f"  - {s}")
    lines.extend(
        [
            "",
            "REGENERATE the FULL plan, fixing every shortfall above. The "
            f"structural contract ({_TOP_SECTIONS_MIN}-{_TOP_SECTIONS_MAX} top "
            f"sections, {_SUBSECTIONS_MIN}-{_SUBSECTIONS_MAX} subsections each, "
            f"{_SEEDS_MIN}-{_SEEDS_MAX} depth_seeds each) is the highest-priority "
            "constraint — it directly drives output depth and "
            "Comprehensiveness/Insight scores. "
            f"If you cannot find enough material for {_TOP_SECTIONS_MIN} top "
            "sections on this prompt, break broader sections into narrower "
            "ones; if you have too many, merge near-duplicates. Same logic "
            "for subsections and seeds.",
        ]
    )
    return "\n".join(lines)


def _coerce_to_dict(plan) -> dict:
    """Defensive shape-fix: ensure we always return a dict from an LLM call
    that might respond with a list of one dict or some other near-miss."""
    if isinstance(plan, dict):
        return plan
    if isinstance(plan, list) and plan and isinstance(plan[0], dict):
        return plan[0]
    return {}


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
    # Token budget calibration:
    # - PR #20 bumped 16k → 24k for the depth_seeds payload (200-450 seeds).
    # - PR #22 (#4) bumps 24k → 32k for the doubled query count (48-64) on
    #   top of the existing payload. 32k leaves headroom for verbose
    #   query rationales without truncation.
    plan = llm.call_json(
        "architect", user, system=_SYSTEM, max_tokens=32000, effort="low", think=True, note="architect"
    )
    plan = _coerce_to_dict(plan)
    _normalize(plan)

    # P2-Option-A-#5 (2026-05-23): outline retry-on-shortfall. The fail-soft
    # `_outline_audit` from PR #20 was telemetry-only — if the architect
    # emitted 5 top sections instead of 8-12, the pipeline silently ran with
    # a shallow plan and the depth contract was structurally unenforceable.
    # Now: when the audit detects ANY shortfall, send the specific bound
    # violations back to the architect as feedback and regenerate ONCE.
    # If the retry still has shortfalls, accept it (cap at 1 retry to bound
    # cost) and record the persistent gap in `audit.retry_attempted` so a
    # dev-run reader can see whether the retry path was effective.
    audit = plan.get("_outline_audit") or {}
    audit["retry_attempted"] = False
    audit["pre_retry_shortfalls"] = list(audit.get("shortfalls", []))
    if audit.get("shortfalls"):
        retry_user = _format_retry_feedback(audit) + "\n\n" + user
        retry = llm.call_json(
            "architect",
            retry_user,
            system=_SYSTEM,
            max_tokens=24000,
            effort="low",
            think=True,
            note="architect.retry",
        )
        retry = _coerce_to_dict(retry)
        # Greptile PR #23 follow-up (2026-05-25): mark `retry_attempted=True`
        # BEFORE the `if retry:` guard. The LLM was called at this point; if
        # `_coerce_to_dict` returns `{}` (uncoercible response) the entire
        # `if retry:` block is skipped, but a dev-run reader scanning
        # `retry_attempted` should still see the trigger fired. Without this,
        # a real LLM failure looks identical to "audit had no shortfalls".
        audit["retry_attempted"] = True
        # Run the retry through the same _normalize so its audit is computed
        # the same way; pick whichever plan is structurally better.
        if retry:
            _normalize(retry)
            if _retry_is_better(retry["_outline_audit"], audit):
                retry["_outline_audit"]["retry_attempted"] = True
                retry["_outline_audit"]["pre_retry_shortfalls"] = audit["pre_retry_shortfalls"]
                plan = retry
            else:
                # Keep original; record that retry was attempted but rejected.
                # Greptile PR #23 follow-up: renamed from
                # `retry_rejected_for_more_shortfalls`. _retry_is_better has
                # three distinct rejection rules and the empty-retry path
                # (rule 1, n_top_sections==0) actually produces FEWER
                # shortfalls than the original — the old name fired on that
                # path too, misleading anyone reading telemetry about WHY.
                audit["retry_rejected"] = True

    return plan


def _retry_is_better(retry_audit: dict, orig_audit: dict) -> bool:
    """Decide whether the retry's plan should replace the original.

    "Better" = strictly closer to the structural contract. We can't just
    compare shortfall counts: an empty retry plan (n_top_sections=0) has
    only ONE shortfall (`top_sections=0<8`), while a 1-section original
    might have one for `top_sections=1<8` plus subsection/seed shortfalls
    under that one section — so the empty retry would look "better" by
    raw count even though it's strictly worse content.

    Rules, in order:
      1. An empty retry (n_top_sections == 0) is never better.
      2. If retry has strictly FEWER top sections than the original, the
         retry walked backward — reject it.
      3. Otherwise, prefer the retry only if it has fewer-or-equal total
         shortfalls AND at least as many top sections.
    """
    if retry_audit.get("n_top_sections", 0) == 0:
        return False
    if retry_audit.get("n_top_sections", 0) < orig_audit.get("n_top_sections", 0):
        return False
    retry_sf = len(retry_audit.get("shortfalls", []))
    orig_sf = len(orig_audit.get("shortfalls", []))
    return retry_sf <= orig_sf


def _normalize(plan: dict) -> None:
    """Attach specialist_role to every query; backfill depth_seeds default;
    record outline-depth diagnostics for downstream telemetry.

    Fail-soft: a plan that comes back with too-few top sections or missing
    depth_seeds is NOT rejected — the writer still runs on whatever the
    architect emitted. We record the shortfall in `plan["_outline_audit"]`
    so the orchestrate-layer can log it and we can see in dev runs whether
    the architect is honoring the new contract.
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
    queries = plan.get("queries", [])
    audit = {
        "n_top_sections": len(toc),
        "n_subsections_total": 0,
        "n_seeds_total": 0,
        "subsections_missing_seeds": 0,
        # Greptile PR #22 follow-up: track query count alongside the other
        # structural counts so a plan that emits fewer than the post-#4
        # HARD RULE band (48-64) is visible in the audit log instead of
        # passing silently. Without this, a model fallback to the pre-#4
        # 24-32 range would leave specialists evidence-starved without
        # any diagnostic surfacing the cause.
        "n_queries": len(queries),
        "shortfalls": [],
    }
    if len(toc) < _TOP_SECTIONS_MIN:
        audit["shortfalls"].append(f"top_sections={len(toc)}<{_TOP_SECTIONS_MIN}")
    if len(toc) > _TOP_SECTIONS_MAX:
        audit["shortfalls"].append(f"top_sections={len(toc)}>{_TOP_SECTIONS_MAX}")
    if len(queries) < _QUERIES_MIN:
        audit["shortfalls"].append(f"queries={len(queries)}<{_QUERIES_MIN}")
    if len(queries) > _QUERIES_MAX:
        audit["shortfalls"].append(f"queries={len(queries)}>{_QUERIES_MAX}")
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
    plan["_outline_audit"] = audit
