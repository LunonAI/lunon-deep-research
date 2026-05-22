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
    "subsections": [ {"id": "S1.1", "title": str} ... 2-5 ],
    "depth_target": "deep"|"broad", "depth_rationale": str } ... <=8 ],
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
- report_toc <=8 top-level; each 2-5 subsections. Match the prompt's language."""


def build(prompt: str, language: str, archetype: str, intents: list,
          landscape: dict, coverage_obligations: list) -> dict:
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
    plan = llm.call_json("architect", user, system=_SYSTEM, max_tokens=16000,
                         effort="low", think=True, note="architect")
    if not isinstance(plan, dict):  # B-13 defensive — plan structure is critical
        plan = plan[0] if isinstance(plan, list) and plan and isinstance(plan[0], dict) else {}
    _normalize(plan)
    return plan


def _normalize(plan: dict) -> None:
    """Attach specialist_role to every query; clamp obvious shape issues."""
    for q in plan.get("queries", []):
        t = str(q.get("type", "factual")).strip().lower()
        if t not in TYPE_TO_SPECIALIST:
            t = "factual"
        q["type"] = t
        q["specialist_role"] = TYPE_TO_SPECIALIST[t]
    plan.setdefault("acceptance_criteria", [])
    plan.setdefault("report_toc", [])
    plan.setdefault("queries", [])
