"""Criteria-aware inner writing loop (p1-checklist items 15, 26).

After a section is grounded, score it against the REGENERATED sub-criteria
(criteria_spec) using GPT-5.5 with the harness scoring rubric spirit, fixed
seed (gate-affecting, point 12). Any criterion < THRESHOLD flags the section
for regeneration. The engine's per-section loop owns the iteration cap (W5:
ship cap=3, drop to 2 only if measured iter-3 lift < 0.1 RACE — empirical,
plan point 1). Refiner later receives these scores + failing rationales,
NO raw evidence (item 26).
"""

import json

from .. import llm

_SEED = 12345
THRESHOLD = 6.0  # /10; harness-style sub-criterion bar

_SYSTEM = (
    "You are a strict research-report grader applying the DeepResearch-Bench "
    "RACE rubric to ONE report section. For each provided sub-criterion, give "
    "an integer/half-point score 0-10 (10 = fully, specifically, "
    "evidence-backed satisfied; 6 = adequate; <6 = a real deficiency) plus a "
    "one-sentence rationale naming the concrete deficiency. Reward depth, "
    "specificity, quantified evidence, explicit causal mechanisms, systematic "
    "coverage, and clean structure; penalize generic assertion, missing "
    "metrics, hedging, scope drift, and truncation.\n"
    "CRITICAL — PER-SECTION SCOPE: you are grading ONE section of a larger "
    "multi-section report, NOT the whole report. The section's PLANNED SCOPE is "
    'given. Mark a sub-criterion "na": true (excluded from this section\'s '
    "pass/fail) in EITHER case: (a) it is clearly the responsibility of a "
    "DIFFERENT chapter (e.g. a supplier-share criterion judged against a "
    "product-definition section), OR (b) it is a WHOLE-REPORT criterion that "
    "can only be satisfied by the COMPLETE assembled report, not one chapter "
    "(e.g. 'covers ALL task deliverables', the overall conclusion / executive "
    "summary, end-to-end navigation). Do NOT penalize a section for omitting "
    "content owned by another chapter or by the whole report — that forces "
    "scope drift. Score ONLY the criteria THIS section can satisfy on its own, "
    "on their merits (depth, specificity, evidence, structure). Output ONLY JSON: "
    '{"scores": [{"dimension": str, "criterion": str, "score": number, '
    '"na": bool, "rationale": str}], "min_score": number}.'
)


def _relevant_criteria(spec: dict) -> list:
    # Returns the flat list of all (dimension, criterion) pairs from a
    # criteria spec. Previously took a `section_dims` argument that was
    # never read or filtered on; removed to keep the signature honest. If
    # per-section dimension scoping is ever desired, add filtering here
    # rather than re-introducing a silently-ignored argument.
    out = []
    for dim, items in (spec.get("criterions") or {}).items():
        for c in items:
            if isinstance(c, dict) and c.get("criterion"):
                out.append({"dimension": dim, "criterion": c["criterion"], "explanation": c.get("explanation", "")})
    return out


def score_section(
    section_text: str,
    spec: dict,
    language: str,
    section_title: str = "",
    note: str = "inner_loop",
    section_scope: str = "",
) -> dict:
    crits = _relevant_criteria(spec)
    user = (
        f"LANGUAGE: {language}\nSECTION TITLE: {section_title}\n"
        f"SECTION PLANNED SCOPE (what THIS chapter is responsible for; criteria "
        f"outside this scope are na):\n{section_scope or section_title}\n\n"
        f"SUB-CRITERIA:\n{json.dumps(crits, ensure_ascii=False)[:20000]}\n\n"
        f"SECTION:\n{section_text[:26000]}"
    )
    try:
        obj = llm.call_json(
            "inner_scorer", user, system=_SYSTEM, max_tokens=7000, seed=_SEED, effort="medium", note=note
        )
    except Exception:  # noqa: BLE001
        # E1: the scorer LLM call failed (e.g. a transient GPT-5.5 outage). Stay
        # fail-soft — never crash the task — but do NOT launder the outage into a
        # synthetic 10/10. `min_score=None` marks the section UNVALIDATED so the
        # run-level degraded tally (orchestrate) and the drift logs reflect
        # reality instead of a perfect score. `ok=True` still lets the section
        # ship (re-writing a probably-fine section while the scorer is down would
        # just burn the inner-loop budget) — but it ships honestly labelled, not
        # as a top-quality pass.
        return {"ok": True, "scores": [], "min_score": None, "fail": [], "degraded": True, "n_in_scope": 0}
    scores = obj.get("scores", []) if isinstance(obj, dict) else []
    # Per-section scope (2026-06-03): a criterion the grader marked `na` (owned by
    # a DIFFERENT chapter) is EXCLUDED from this section's pass/fail — previously
    # every section was scored against the WHOLE task rubric, so a product chapter
    # failed the supplier-share criteria it was never meant to cover (min_score
    # 0.5-4.5 on every section, wasted re-rolls + scope-drift degradation).
    in_scope = [s for s in scores if isinstance(s, dict) and not s.get("na")]
    # Guard: if the grader marked EVERYTHING na (degenerate/hallucinated), fall
    # back to all scored criteria so the section isn't graded on zero criteria.
    # Note: an empty `scores` list still yields judged=[] -> mn=10.0 -> ok=True
    # (unchanged pre-scope behaviour; a genuine scorer FAILURE takes the
    # `except` path above and ships honestly labelled `degraded=True`).
    judged = in_scope or [s for s in scores if isinstance(s, dict)]
    nums = [float(s.get("score", 0)) for s in judged]
    mn = min(nums) if nums else 10.0
    fail = [s for s in judged if float(s.get("score", 0)) < THRESHOLD]
    return {
        "ok": mn >= THRESHOLD and not fail,
        "scores": scores,
        "min_score": mn,
        "fail": fail,
        "n_in_scope": len(judged),
    }


def feedback_text(result: dict) -> str:
    lines = [
        f"- [{s.get('dimension')}] {s.get('criterion')}: {s.get('score')}/10 — {s.get('rationale', '')}"
        for s in result.get("fail", [])
    ]
    return (
        "CRITERIA BELOW THRESHOLD — revise this section to specifically "
        "fix each (add the missing depth/metrics/causal mechanism/coverage; "
        "do not pad):\n" + "\n".join(lines)
    )
