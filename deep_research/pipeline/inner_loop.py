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
    "metrics, hedging, scope drift, and truncation. Output ONLY JSON: "
    '{"scores": [{"dimension": str, "criterion": str, "score": number, '
    '"rationale": str}], "min_score": number}.'
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
    section_text: str, spec: dict, language: str, section_title: str = "", note: str = "inner_loop"
) -> dict:
    crits = _relevant_criteria(spec)
    user = (
        f"LANGUAGE: {language}\nSECTION TITLE: {section_title}\n\n"
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
        return {"ok": True, "scores": [], "min_score": None, "fail": [], "degraded": True}
    scores = obj.get("scores", []) if isinstance(obj, dict) else []
    nums = [float(s.get("score", 0)) for s in scores if isinstance(s, dict)]
    mn = min(nums) if nums else 10.0
    fail = [s for s in scores if isinstance(s, dict) and float(s.get("score", 0)) < THRESHOLD]
    return {"ok": mn >= THRESHOLD and not fail, "scores": scores, "min_score": mn, "fail": fail}


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
