"""P3b-OPT3 (2026-05-27): deterministic tier-ranking scores at architect time.

The architect emits `tier_ranking` with `weights` + `tiers` but NO per-entity
scores. Pre-this-module the WRITER LLM hallucinated every dimension score, the
S_final arithmetic, and the tier assignment — inconsistent numbers a judge can
catch, and the exact "writer is computationally weak" failure W7.b documented.

This module splits the work the right way:
- LLM judgment (ONE scoring call): rate each entity 0-10 on each rubric
  dimension. This is a qualitative assessment that genuinely needs a model.
- Python arithmetic (deterministic): S_final = Σ(normalized_weight × dim_score),
  rounded to 2 decimals; tier assigned by the declared thresholds.

The writer then RENDERS these pre-computed values instead of inventing them.
Quality goes up (consistent, grounded-in-one-judgment numbers); the 2-decimal
validator passes by construction (the writer block formats to "X.XX").

Fail-soft: any problem (no tier_ranking, no entities, malformed LLM JSON)
returns None, and the writer falls back to its prior compute-it-yourself
directive — so a scorer failure never breaks article generation.
"""

from __future__ import annotations

import json

from .. import llm

_SYSTEM = (
    "You are a rigorous research analyst scoring entities against a published "
    "rubric. For EACH entity, assign an integer-or-half-point score from 0.0 to "
    "10.0 on EACH rubric dimension (10 = exemplary on that dimension, 0 = "
    "absent). Base scores on the entity's standing in the field. Be calibrated "
    "and discriminating — do NOT cluster every entity at 7-8. Output ONLY a "
    "JSON object mapping each entity name to its per-dimension scores: "
    '{"<entity name>": {"R-1": <score>, "R-2": <score>, ...}, ...}. '
    "Use the EXACT entity names and dimension ids given. No prose, no markdown."
)


def _parse_threshold(thr: str):
    """Parse a tier threshold like '>=8.0' / '<6.0' into (op, value).

    Returns None if unparseable (caller skips that tier)."""
    thr = (thr or "").strip()
    for op in (">=", "<=", ">", "<"):  # longest operators first
        if thr.startswith(op):
            try:
                return op, float(thr[len(op) :].strip())
            except ValueError:
                return None
    return None


def _assign_tier(s_final: float, tiers: list[dict]) -> str:
    """First tier (in declared order — highest first by convention) whose
    threshold `s_final` satisfies. Falls back to the last (lowest) tier."""
    for t in tiers:
        parsed = _parse_threshold(str(t.get("threshold", "")))
        if not parsed:
            continue
        op, val = parsed
        if (
            (op == ">=" and s_final >= val)
            or (op == ">" and s_final > val)
            or (op == "<=" and s_final <= val)
            or (op == "<" and s_final < val)
        ):
            return t.get("name", "")
    return tiers[-1].get("name", "") if tiers else ""


def _clean_weights(tr: dict) -> dict:
    """Extract numeric weights, dropping bools (bool is an int subclass), and
    renormalize to sum to 1.0 so S_final lands on the 0-10 tier scale even if
    the architect's raw weights don't sum to exactly 1."""
    raw = tr.get("weights") if isinstance(tr.get("weights"), dict) else {}
    weights = {k: float(v) for k, v in raw.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in weights.items()}


def score_entities(plan: dict, language: str, task_id: int | None = None) -> list[dict] | None:
    """Return a list of per-entity score dicts, or None to fall back to the
    writer's compute-it-yourself path.

    Each dict: {"name": str, "dimension_scores": {dim_id: float(2dp)},
                "S_final": float(2dp), "tier": str}.
    """
    tr = plan.get("tier_ranking")
    if not isinstance(tr, dict):
        return None
    em = plan.get("entity_matrix")
    entities = (
        [e for e in (em.get("entities") or []) if isinstance(e, str) and e.strip()] if isinstance(em, dict) else []
    )
    if not entities:
        return None
    weights = _clean_weights(tr)
    tiers = [t for t in (tr.get("tiers") or []) if isinstance(t, dict) and t.get("name")]
    if not weights or not tiers:
        return None

    # Human-readable dimension labels from the §1 framing rubric (falls back to
    # the weight key id when a label is absent) — gives the scorer context.
    fc = plan.get("framing_chapter") if isinstance(plan.get("framing_chapter"), dict) else {}
    rubric = {
        item["id"]: item.get("label", item["id"])
        for item in (fc.get("published_rubric_items") or [])
        if isinstance(item, dict) and item.get("id")
    }
    dim_labels = {k: rubric.get(k, k) for k in weights}

    user = (
        f"LANGUAGE CONTEXT: {language}\n"
        f"RUBRIC DIMENSIONS (id → meaning):\n{json.dumps(dim_labels, ensure_ascii=False, indent=2)}\n\n"
        f"ENTITIES TO SCORE (use these EXACT names as JSON keys):\n"
        f"{json.dumps(entities, ensure_ascii=False, indent=2)}\n\n"
        f"Score every entity on every dimension id above (0.0-10.0)."
    )
    note = "tier_ranking.score" if task_id is None else f"tier_ranking.score.{task_id}"
    try:
        obj = llm.call_json("architect", user, system=_SYSTEM, max_tokens=4000, effort="medium", note=note)
    except Exception:  # noqa: BLE001 — scorer failure must never break planning
        return None
    if not isinstance(obj, dict):
        return None

    scored: list[dict] = []
    for ent in entities:
        raw = obj.get(ent)
        if not isinstance(raw, dict):
            continue
        dim_scores = {}
        for dim in weights:
            v = raw.get(dim)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                dim_scores[dim] = round(float(v), 2)
        if not dim_scores:
            continue
        s_final = round(sum(weights[d] * dim_scores.get(d, 0.0) for d in weights), 2)
        scored.append(
            {
                "name": ent,
                "dimension_scores": dim_scores,
                "S_final": s_final,
                "tier": _assign_tier(s_final, tiers),
            }
        )
    return scored or None
