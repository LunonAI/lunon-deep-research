"""Architect subagent (p1-checklist items 6 + 14; adapts AI-Q architect.j2).

Turns the Scout landscape + extracted intents + regenerated criteria into a
STRICT JSON plan: hierarchical TOC, 48-64 typed queries (1:1 mapped to the 5
researcher specialists; pre-#4 was 24-32, doubled to feed the depth_seeds
H4-leaf payload from PR #20), 24-32 acceptance criteria that FOLD IN every
regenerated sub-criterion and every extracted intent as an explicit coverage
obligation, and per-section depth targets. Archetype-aware (item 16).
"""

import json
import re

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
    # Greptile PR #25 follow-up round 2 (2026-05-25): "near the article's
    # start" was synced to "immediately under the §1 heading (S1's body;
    # the executive opening frame is written separately and does not
    # include the table)" so the architect's planning prompt matches the
    # canonical placement now enforced in writer.write_section's S1-only
    # render-as-table directive. The prior wording would have led the
    # architect to embed contradictory placement guidance into task_analysis.
    "list-all": "Exhaustive enumeration: populate the REQUIRED entity_matrix "
    "with every prompt-enumerated entity AND the dimensions a reader would "
    "compare them on. The writer renders the matrix as a markdown table "
    "immediately under the §1 heading (S1's body; the executive opening "
    "frame is written separately and does not include the table). "
    "Bias query mix to factual + comparative.",
    "compare": "Build an explicit entity×dimension comparison matrix as the "
    "article's core deliverable: populate the REQUIRED entity_matrix with "
    "every entity the prompt asks to compare AND the dimensions of comparison. "
    "The writer renders this matrix as a markdown table immediately under "
    "the §1 heading AND gives each entity equal-depth treatment downstream. "
    "Bias to comparative + factual.",
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
 "entity_matrix": {                /* REQUIRED for list-all and compare. */
   "entities": [str, ...],         /* OPTIONAL for predict/explain-mechanism/ */
   "dimensions": [                  /* trend/recommend — populate when the */
     {                              /* outline contains >=3 sibling sub-chapters */
       "axis_name": str,            /* whose titles each name a distinct entity. */
       "render_order": int,         /* For other prompts, set to null. */
       "content_template": str
     }, ...
   ],
   "instantiation_mode": "prose_subheaders"|"table_columns_only",
   "min_axes_per_entity": int
 },                                /* 5-30 entities (rows; per-archetype: list-all
                                      up to 30, compare up to 20, others up
                                      to 15), 4-8 dimensions (columns +
                                      bolded per-entity sub-headers).
                                      P3-W1 (2026-05-27): dimensions are
                                      ordered objects with `axis_name`,
                                      `render_order`, and `content_template`
                                      so the writer can mechanically
                                      instantiate each entity with byte-
                                      identical sub-headers in declared
                                      order (Qianfan's verified corpus-wide
                                      pattern). Legacy `[str, ...]` form is
                                      auto-wrapped to object form during
                                      _normalize for backward compat.
                                      `instantiation_mode` controls writer
                                      render: "prose_subheaders" (default,
                                      P3-W1) emits the axes as bolded
                                      sub-headers per entity; "table_columns_only"
                                      preserves the legacy S1-only table render.
                                      `min_axes_per_entity` (default 3) is
                                      the writer compliance floor — every
                                      entity must instantiate at least this
                                      many axes from the dimensions list.   */
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
    "target_sections": ["S1", ...], "rationale": str } ... 48-64 ],
 "framing_chapter": {              /* P3-W2 (2026-05-27): §1 contract.
                                      Populated for ALL archetypes EXCEPT
                                      single-axis trend tasks (where the
                                      prompt has one clear axis and a
                                      methodology chapter would just
                                      delay substantive content). */
   "title": str,                    /* e.g. "Research Framework, Scope &
                                       Methodology" — should be the §1
                                       title in report_toc */
   "sub_sections": [
     {"id": "S1.1", "type": "scope",
      "title": str, "content_directive": str},
     {"id": "S1.2", "type": "rubric",
      "title": str, "content_directive": str},
     {"id": "S1.3", "type": "roadmap",
      "title": str, "content_directive": str},
     {"id": "S1.4", "type": "vocabulary",
      "title": str, "content_directive": str}
   ],
   "published_vocabulary": [str, ...]  /* 5-10 NAMED terms/axioms that
                                          downstream chapters reuse
                                          UNMODIFIED. Examples: Qianfan
                                          q3 uses "五篇大文章", "新质生产力";
                                          q14 uses "Rubric P-1..P-6";
                                          q56 uses "Level of solution
                                          (4-level taxonomy)". */,
   "published_rubric_items": [        /* 4-6 items WHEN applicable
                                          (compare/predict/recommend
                                          archetypes; omit or empty for
                                          others). Each item is referenced
                                          by id from downstream entity
                                          evaluations.                  */
     {"id": "R-1", "label": str, "weight": float}, ...
   ]
 } | null,
 "tier_ranking": {                /* P3-W7 (2026-05-27): compare/predict
                                     archetypes with ≥5 entities in
                                     entity_matrix. Publishes a weighted-
                                     scoring formula + tier thresholds +
                                     ±10pp sensitivity check. Qianfan-
                                     verified pattern: q14 §7.3-§7.6 tier-
                                     ranks 10 teams with S_base/RBM/S_final;
                                     q3 §8.1 tier-ranks 11 sub-sectors.
                                     When tier_ranking is populated, its
                                     `weights` SHOULD mirror the
                                     framing_chapter.published_rubric_items
                                     weights — the rubric is published in
                                     §1 and consumed by the tier-ranking
                                     scoring chapter downstream. */
   "title": str,                   /* e.g. "Tier Ranking" */
   "scoring_formula": str,         /* e.g. "S_final = Σ(weight_i × dim_i)" */
   "weights": {"R-1": float, "R-2": float, ...},   /* sum ≈ 1.0 ± 0.01 */
   "tiers": [
     {"name": "Tier 1", "threshold": ">=8.0"},
     {"name": "Tier 2", "threshold": ">=6.0"},
     {"name": "Tier 3", "threshold": "<6.0"}
   ],
   "sensitivity_check": {
     "perturbation_pp": 10,         /* ±10 percentage points by default */
     "report": "rank_stability"     /* what the sensitivity sub-section reports */
   }
 } | null,
 "limitations_chapter": {          /* P3-W5 (2026-05-27): penultimate
                                      chapter for predict / compare /
                                      explain-mechanism / list-all
                                      archetypes. Omit / null for trend
                                      and recommend. Engineering-grade
                                      falsification — Qianfan-verified
                                      pattern (6/11 articles). The
                                      scenario_stress_test sub-node
                                      recomputes tier_ranking under
                                      base/optimistic/pessimistic scenarios
                                      for the predict archetype. */
   "title": str,                    /* e.g. "Limitations and Future
                                       Research Directions" */
   "sub_sections": [
     {"id": "SN.1", "type": "data_granularity",
      "title": str, "content_directive": str},
     {"id": "SN.2", "type": "scope_cap",
      "title": str, "content_directive": str},
     {"id": "SN.3", "type": "time_validity",
      "title": str, "content_directive": str},
     {"id": "SN.4", "type": "sampling",
      "title": str, "content_directive": str},
     {"id": "SN.5", "type": "falsifiers",
      "title": str, "content_directive": str}
   ],
   "scenario_stress_test": null     /* predict archetype ONLY: 3-scenario
                                       (base/optimistic/pessimistic)
                                       recompute of the article's main
                                       ranking (typically tier_ranking).
                                       Null for other archetypes. */
 } | null
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
  Qianfan corpus structural profile: mean 9 top sections, 4 subsections per
  top section, ~2-3 sub-sub-sections per subsection. A shallower outline
  produces a shorter, lower-Comprehensiveness article.)
- depth_seeds are the WRITER'S H4-leaf-section seeds — concrete claims,
  named entities, data points, or comparisons. Avoid generic seeds like
  "Background" or "Conclusion"; each seed is a specific substantive payload.
- entity_matrix REQUIRED for list-all and compare archetypes; OPTIONAL
  for predict/explain-mechanism/trend/recommend (populate when the
  outline contains >=3 sibling sub-chapters whose titles each name a
  distinct entity; otherwise set to null). Populate entities with EVERY
  entity the prompt names (verbatim where possible). Choose 4-8 dimensions
  a reader would compare them across — these are BOTH the columns of the
  matrix table AND the bolded sub-headers the writer instantiates per
  entity. Each dimension is an object:
    {"axis_name": "<short Title-Case label, used verbatim as bolded
                    sub-header for every entity>",
     "render_order": <1-indexed integer>,
     "content_template": "<1-clause hint about content type for this
                          axis, e.g. 'founding date + 2-3 numeric facts'
                          or 'causal mechanism + named falsifier'>"}
  Set `instantiation_mode` to "prose_subheaders" (default; writer emits
  the dimensions as bolded sub-headers per entity AND a §1 table) or
  "table_columns_only" (legacy; only the §1 table — use when the
  archetype doesn't have a per-entity expansion in body chapters).
  Set `min_axes_per_entity` to 3 unless you have a reason to require
  every entity to instantiate every axis (then set equal to len(dimensions)).
- framing_chapter REQUIRED for all archetypes EXCEPT single-axis trend
  tasks. The framing chapter §1 publishes (a) scope/boundary, (b) an
  evaluation rubric (4-6 items with weights, applicable for compare/
  predict/recommend), (c) a roadmap that names what each downstream
  chapter (§2-§N) addresses, and (d) 5-10 named vocabulary terms that
  downstream chapters reuse UNMODIFIED. The framing chapter §1 title
  MUST match the report_toc[0] title. The framing chapter is the article's
  contract with the reader — Qianfan's verified corpus-wide pattern
  (10/11 articles) and the single most distinguishing structural move
  separating their record-class scores from a survey-style report.
- Match the prompt's language."""


# P2-Option-A-#1 calibration (mean of the 10 high-scoring Qianfan articles):
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
#
# Wave 2 §1.2 (2026-05-26): the uniform 8-12 / 3-6 / 2-4 bounds are the
# DEFAULT, used when the archetype is unknown or has no preset. Per-
# archetype bounds in `_ARCHETYPE_OUTLINE_SHAPE` override these for the
# archetypes whose Qianfan reference articles show structurally
# different shapes (list-all wants flat 30-80 H2 with no H3/H4 per
# id=91's verified 78 H2 / 0 H3; compare wants moderate 15-30 H2;
# explain-mechanism stays at the deeper hierarchical shape).
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

# P3-W0a (2026-05-27): per-archetype `query.type` minimum proportions.
# The HARD RULES bullet "Distribute query type to cover all needed analytical
# functions" was structurally too vague — when the architect under-allocated
# causal queries to the mechanism_explorer specialist (or critical queries to
# the critic), the writer's evidence pack lost the substrate needed for RACE
# Insight criteria 2 (Causal Reasoning) and 3 (Problem Insight). These per-
# archetype minimums are sourced from the W3-Insight-Bundle spec, which
# itself was derived from per-archetype query-type distributions in 14
# Qianfan #1 reference articles (see transfer/p2_artifacts/phase3_engine_plan.md
# §1 + transfer/p2_artifacts/wave3_insight_bundle_spec.md).
#
# Each row sums to ≤ 1.0 (pytest pins this; small residual lets the architect
# choose where the marginal queries go). Values are FLOORS, not exact targets.
# A plan that emits more `causal` queries than the minimum is accepted; a plan
# below the minimum gets an audit shortfall (advisory, same pattern as outline
# shape — fail-soft, surfaced in drift telemetry, not a retry trigger).
_ARCHETYPE_QUERY_TYPE_MIN_PCT: dict[str, dict[str, float]] = {
    "list-all": {"factual": 0.40, "comparative": 0.20, "causal": 0.10, "critical": 0.10, "trend": 0.10},
    "compare": {"factual": 0.30, "comparative": 0.30, "causal": 0.10, "critical": 0.15, "trend": 0.10},
    "explain-mechanism": {"factual": 0.25, "causal": 0.30, "comparative": 0.10, "critical": 0.20, "trend": 0.10},
    "predict": {"factual": 0.20, "causal": 0.20, "trend": 0.25, "critical": 0.15, "comparative": 0.15},
    "trend": {"factual": 0.20, "trend": 0.35, "causal": 0.15, "critical": 0.10, "comparative": 0.15},
    "recommend": {"factual": 0.25, "comparative": 0.25, "critical": 0.20, "causal": 0.15, "trend": 0.10},
}

# Default for unknown archetype: a balanced floor that doesn't starve any
# specialist. Sum = 0.95 — matches the ~5-10% headroom every named archetype
# leaves so the integer query-count rounding (48-64 queries → 2-3 free) can
# satisfy every floor simultaneously. Greptile PR #35 round-2 follow-up: the
# previous sum=1.0 default fired advisory shortfalls on every unknown-archetype
# run because integer rounding pushes ceilings above 100% (e.g., 48 queries:
# 0.20 → ceil(9.6)=10, 4 types × 10 + 1 type × 12 = 52 > 48). Lowering
# `critical` 0.15 → 0.10 (matches list-all / explain-mech / recommend floors)
# preserves balance while creating a satisfiable distribution.
_DEFAULT_QUERY_TYPE_MIN_PCT: dict[str, float] = {
    "factual": 0.25,
    "comparative": 0.20,
    "causal": 0.20,
    "critical": 0.10,
    "trend": 0.20,
}


def _query_type_mins_for_archetype(archetype: str | None) -> dict[str, float]:
    """Return the per-archetype query-type minimum-proportion dict.

    Falls back to `_DEFAULT_QUERY_TYPE_MIN_PCT` when archetype is unknown
    (parallel pattern to `_bounds_for_archetype`). Returns a fresh dict so
    callers mutating the result don't corrupt the module-level constant
    (mirrors PR #23 round-2 fix on `_bounds_for_archetype`).
    """
    return dict(_ARCHETYPE_QUERY_TYPE_MIN_PCT.get(archetype or "", _DEFAULT_QUERY_TYPE_MIN_PCT))


# Wave 2 §1.2 (2026-05-26): per-archetype outline shape preset.
# Calibrated against the 10-doc Qianfan reference corpus (profiled
# 2026-05-26 via scripts/p2_qianfan_profile + p2_qianfan_distance
# semantic-depth scan). Key findings:
#   - id=91 (list-all, Saint Seiya armors): 78 H2 / 0 H3 — flat enumeration
#   - id=14 (list-all, math/quantum research): 81 H2 / 0 H3 — flat
#   - id=8 (list-all, ML methods): 63 H2 / 0 H3 — flat
#   - id=56 (explain-mechanism, auction theory): 70 H2 / 135 H3 — deep
#   - id=20 (explain-mechanism, HTTP): 55 H2 / 138 H3 — deep
#   - id=89 (explain-mechanism, biology): 53 H2 / 221 H3 — deep
#   - id=38 (predict/trend, jewelry trends): 58 H2 / 115 H3 — medium
# ZERO of the 10 Qianfan docs use H4+ headings. The pre-Wave-2 outline
# spec produced 8-12 H2 × 3-6 H3 × 2-4 H4 leaves = 48-288 H4 leaves;
# this misaligns with Qianfan's no-H4 convention. Wave 2 keeps H4 for
# explain-mechanism / predict (where deep hierarchy still helps the
# judge see depth) but drops H4 for list-all / compare (where Qianfan's
# flat shape is the high-scoring template).
_ARCHETYPE_OUTLINE_SHAPE: dict[str, dict[str, int]] = {
    # list-all: flat enumeration. 30-80 top sections (one per entity in
    # the matrix is the common pattern), minimal subsections (0-2 for
    # cross-cutting framing), no H4 leaves.
    "list-all": {
        "top_min": 30,
        "top_max": 80,
        "sub_min": 0,
        "sub_max": 2,
        "seed_min": 0,
        "seed_max": 0,
    },
    # compare: comparison-table archetype. Moderate top-section count
    # (15-30) for the entities + framing sections, 2-5 subsections per
    # top (cross-cutting dimensions), no H4.
    "compare": {
        "top_min": 15,
        "top_max": 30,
        "sub_min": 2,
        "sub_max": 5,
        "seed_min": 0,
        "seed_max": 0,
    },
    # explain-mechanism: deepest archetype. Qianfan refs show 50-70 H2
    # with 130-220 H3 leaves. Our pre-Wave-2 8-12 × 4-8 H3 produces
    # 32-96 H3 leaves, fewer than Qianfan's ~135. Bump the top-section
    # band to 8-14 + sub band to 4-8 + keep H4 (2-4 seeds) so total
    # H3+H4 leaf count approaches Qianfan's per-article density.
    "explain-mechanism": {
        "top_min": 8,
        "top_max": 14,
        "sub_min": 4,
        "sub_max": 8,
        "seed_min": 2,
        "seed_max": 4,
    },
    # predict / trend / recommend: forward-looking analysis archetypes.
    # Qianfan id=38 (trends): 58 H2 / 115 H3. Use the default-shape
    # bounds (closer to the historical 8-12 / 3-6 / 2-4) since these
    # archetypes show wide structural variance across the corpus.
    "predict": {
        "top_min": 8,
        "top_max": 12,
        "sub_min": 3,
        "sub_max": 6,
        "seed_min": 2,
        "seed_max": 4,
    },
    "trend": {
        "top_min": 8,
        "top_max": 12,
        "sub_min": 3,
        "sub_max": 6,
        "seed_min": 2,
        "seed_max": 4,
    },
    "recommend": {
        "top_min": 8,
        "top_max": 12,
        "sub_min": 3,
        "sub_max": 6,
        "seed_min": 2,
        "seed_max": 4,
    },
}

# Default outline shape — used when archetype is unknown / missing
# from `_ARCHETYPE_OUTLINE_SHAPE`. Matches the pre-Wave-2 uniform
# 8-12 / 3-6 / 2-4 bounds for backward compat.
_DEFAULT_OUTLINE_SHAPE: dict[str, int] = {
    "top_min": _TOP_SECTIONS_MIN,
    "top_max": _TOP_SECTIONS_MAX,
    "sub_min": _SUBSECTIONS_MIN,
    "sub_max": _SUBSECTIONS_MAX,
    "seed_min": _SEEDS_MIN,
    "seed_max": _SEEDS_MAX,
}


def _bounds_for_archetype(archetype: str | None) -> dict[str, int]:
    """Return the per-archetype outline-shape bounds dict.

    Falls back to `_DEFAULT_OUTLINE_SHAPE` when archetype is unknown
    (back-compat with callers that don't pass archetype, e.g. tests
    of `_normalize` that don't run the full build cycle).

    Greptile PR #30 round-3 follow-up (2026-05-26): wraps the `.get()`
    result in `dict(...)` so the return is ALWAYS a fresh copy.
    Pre-fix the known-archetype path returned the actual module-level
    dict object — a caller mutating the returned dict (e.g.
    `b = _bounds_for_archetype('predict'); b['top_min'] = 99`) would
    silently corrupt the constant. Mirrors the
    `writing_rules.insight_distribution` fix from PR #30 round-2.
    """
    return dict(_ARCHETYPE_OUTLINE_SHAPE.get(archetype or "", _DEFAULT_OUTLINE_SHAPE))


def _format_retry_feedback(audit: dict, archetype: str | None = None) -> str:
    """Turn `_outline_audit` shortfalls into a feedback string for the
    architect's retry call. Lists each specific bound violation so the
    architect knows exactly what to fix, not just that 'something is wrong'.

    Bound numerals are interpolated from `_bounds_for_archetype(archetype)`
    so the LLM feedback always matches the actual audit-check thresholds
    for the specific archetype this retry is for (Wave 2 §1.2). Falls
    back to default uniform bounds when archetype is None.
    """
    b = _bounds_for_archetype(archetype)
    lines = [
        "SHORTFALL FEEDBACK — your previous plan did NOT meet the structural contract.",
        f"It returned {audit['n_top_sections']} top sections "
        f"(need {b['top_min']}-{b['top_max']}), "
        f"{audit['n_subsections_total']} total subsections, "
        f"{audit['n_seeds_total']} total depth_seeds.",
        "",
        "Specific bound violations the audit detected:",
    ]
    for s in audit.get("shortfalls", []):
        lines.append(f"  - {s}")
    seed_clause = (
        f"{b['seed_min']}-{b['seed_max']} depth_seeds each"
        if b["seed_max"] > 0
        else "ZERO depth_seeds per subsection (this archetype uses flat outline, no H4 leaves)"
    )
    # P3-W0a: include the per-archetype query-type floor in the retry
    # feedback so the regenerator sees the SAME contract that the audit
    # was checking against. Without this the architect would refresh the
    # outline but leave the query-type distribution untouched.
    q_mins = _query_type_mins_for_archetype(archetype)
    q_floor_clause = "; ".join(f"{qt}≥{int(round(pct * 100))}%" for qt, pct in q_mins.items())
    lines.extend(
        [
            "",
            f"REGENERATE the FULL plan, fixing every shortfall above. The "
            f"structural contract for archetype `{archetype or 'default'}` "
            f"({b['top_min']}-{b['top_max']} top sections, "
            f"{b['sub_min']}-{b['sub_max']} subsections each, "
            f"{seed_clause}; query-type floors: {q_floor_clause}) "
            "is the highest-priority constraint — it "
            "directly drives output depth and Comprehensiveness/Insight "
            f"scores. If you cannot find enough material for {b['top_min']} "
            "top sections on this prompt, break broader sections into "
            "narrower ones; if you have too many, merge near-duplicates. "
            "Same logic for subsections and seeds.",
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
    # Wave 2 §1.2: inject the per-archetype outline-shape preset into the
    # user prompt so the LLM sees the right bounds upfront. The _SYSTEM
    # prompt above still describes the DEFAULT 8-12 / 3-6 / 2-4 contract
    # for back-compat; this block OVERRIDES those defaults for archetypes
    # whose Qianfan reference shape is structurally different.
    b = _bounds_for_archetype(archetype)
    seed_clause = (
        f"{b['seed_min']}-{b['seed_max']} depth_seeds per subsection (one H4 leaf per seed)"
        if b["seed_max"] > 0
        else "ZERO depth_seeds — this archetype renders as a FLAT outline. "
        "Set `depth_seeds: []` on every subsection. Do NOT invent H4 leaves."
    )
    archetype_outline_block = (
        f"OUTLINE SHAPE FOR THIS ARCHETYPE (`{archetype}`) — OVERRIDE the "
        f"8-12 / 3-6 / 2-4 default in the HARD RULES above. Wave 2 §1.2 "
        f"calibration against the 10-doc Qianfan reference corpus showed "
        f"archetype-specific shapes:\n"
        f"  • report_toc: {b['top_min']}-{b['top_max']} top-level sections\n"
        f"  • subsections per top section: {b['sub_min']}-{b['sub_max']}\n"
        f"  • {seed_clause}\n"
        f"These bounds are ENFORCED by the audit + retry-on-shortfall "
        f"loop. A plan outside these bounds for this archetype will be "
        f"rejected and you'll be asked to regenerate.\n"
    )

    # P3-W0a (2026-05-27): per-archetype query.type distribution floor.
    # The HARD RULES bullet "distribute query type to cover all needed
    # analytical functions" was structurally vague. RACE Insight criteria
    # 2 (causal reasoning) + 3 (problem insight) depend on the writer
    # receiving enough causal + critical evidence from mechanism_explorer +
    # critic respectively. The architect was the upstream bottleneck — if
    # it allocated 5/50 causal queries on an explain-mechanism task, the
    # whole pipeline starved. These minimum proportions are FLOORS sourced
    # from the per-archetype distributions in 14 Qianfan #1 reference
    # articles; the architect may exceed them.
    q_mins = _query_type_mins_for_archetype(archetype)
    q_dist_lines = "; ".join(f"{qt}≥{int(round(pct * 100))}%" for qt, pct in q_mins.items())
    archetype_query_type_block = (
        f"QUERY TYPE DISTRIBUTION FLOOR FOR THIS ARCHETYPE (`{archetype}`) — "
        f"each `query.type` must reach at least the minimum proportion "
        f"shown. These floors are sourced from the per-archetype "
        f"distributions in 14 Qianfan #1 reference articles, which "
        f"underwrite RACE Insight criteria 2 (causal reasoning) and 3 "
        f"(problem insight):\n"
        f"  {q_dist_lines}\n"
        f"Across all 48-64 queries combined, the FRACTIONS (not the absolute "
        f"counts) must satisfy each floor. The audit surfaces shortfalls "
        f"as advisory drift entries — they do not currently trigger a retry, "
        f"but they ARE measured against this contract by the post-write "
        f"compliance scorer.\n"
    )
    user = (
        f"PROMPT ({language}):\n{prompt}\n\n"
        f"ARCHETYPE: {archetype}\nARCHETYPE EMPHASIS: {emphasis}\n\n"
        f"{archetype_outline_block}\n"
        f"{archetype_query_type_block}\n"
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
    # - PR #22 (#4) tried 24k → 32k for the doubled query count (48-64) but
    #   2026-05-25 reverted: the 32k cap with think=True produced ~17-min
    #   streaming responses that Anthropic's edge consistently cut with
    #   `httpx.RemoteProtocolError: peer closed connection without sending
    #   complete message body`. Each architect attempt burned the full 17min
    #   then failed; both adapter-level retries hit the same wall.
    # - At 24k the architect's expected output (48-64 queries × ~100 tok +
    #   24-32 ACs × ~80 tok + report_toc + entity_matrix + depth_seeds ≈
    #   12-15k tok) fits with 1.5-2× headroom, and the call typically
    #   completes in 5-8 min — well inside Anthropic's stream-duration
    #   tolerance.
    plan = llm.call_json(
        "architect", user, system=_SYSTEM, max_tokens=24000, effort="low", think=True, note="architect"
    )
    plan = _coerce_to_dict(plan)
    _normalize(plan, archetype=archetype)

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
        # Wave 2 §1.2: pass archetype so the retry feedback interpolates
        # per-archetype bounds (otherwise the feedback would use the
        # default 8-12 / 3-6 / 2-4 numbers, which mismatch the audit
        # for non-default archetypes — exactly the drift PR #23 was
        # written to prevent).
        retry_user = _format_retry_feedback(audit, archetype=archetype) + "\n\n" + user
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
        # PR #25 + #23 merge resolution (2026-05-25): the retry must also
        # receive `archetype=archetype` so list-all/compare retries get
        # entity_matrix backfilled + audited the same way the original plan
        # does. Without it, a retry on a list-all task with a missing matrix
        # would skip the `entity_matrix=missing` shortfall, making
        # `_retry_is_better` mis-judge it as "no new shortfalls" relative to
        # the original.
        if retry:
            _normalize(retry, archetype=archetype)
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


# P2-Option-A-#7 entity_matrix bounds (list-all and compare archetypes only).
# The 5-20 entity range covers the corpus distribution: id=91 Saint Seiya
# (~15 named entities), id=8 ML materials (~7 method classes), id=20 Streamable
# HTTP (~5 transport variants). 4-8 dimensions covers a useful comparison
# table without overwhelming reader cognition.
#
# P3-W1 (2026-05-27): the flat 5-20 entity range was too conservative for
# list-all where Qianfan id=91 has 25-28 knights and id=89 has similar
# depth. Per-archetype cap dict raises list-all to 30; compare unchanged
# at 20; new entries for predict/explain-mechanism/trend/recommend (which
# also benefit from entity matrix when ≥3 sibling sub-chapters each name
# a distinct entity — see _should_promote_entity_matrix below).
_ENTITY_MATRIX_ENTITIES_MIN = 5
_ENTITY_MATRIX_ENTITIES_MAX = 20  # back-compat; tests reference this directly
_ENTITY_MATRIX_ENTITIES_MAX_BY_ARCHETYPE: dict[str, int] = {
    "list-all": 30,
    "compare": 20,
    "predict": 15,
    "explain-mechanism": 15,
    "trend": 15,
    "recommend": 15,
}
_ENTITY_MATRIX_DIMENSIONS_MIN = 4
_ENTITY_MATRIX_DIMENSIONS_MAX = 8

# P3-W2 (2026-05-27): framing_chapter bounds. The §1 chapter publishes the
# scope, rubric, roadmap, and vocabulary contract that downstream chapters
# reuse. 4 required sub-sections (scope / rubric / roadmap / vocabulary);
# 5-10 vocabulary terms; 4-6 rubric items (compare/predict/recommend only).
# Calibrated against Qianfan's 10/11-article corpus pattern.
_FRAMING_VOCABULARY_MIN = 5
_FRAMING_VOCABULARY_MAX = 10
_FRAMING_RUBRIC_MIN = 4
_FRAMING_RUBRIC_MAX = 6
_FRAMING_SUBSECTION_TYPES: tuple[str, ...] = ("scope", "rubric", "roadmap", "vocabulary")

# Archetypes for which framing_chapter is REQUIRED. Trend tasks with a
# single axis (e.g. "track the evolution of X over time") often don't
# benefit from a methodology preamble; we OFFER but don't require it.
_FRAMING_CHAPTER_REQUIRED_ARCHETYPES = frozenset({"list-all", "compare", "explain-mechanism", "predict", "recommend"})

# Archetypes that should produce a non-empty `published_rubric_items` list
# (the rubric is referenced downstream when entities are scored). Trend and
# list-all may have rubrics but they're less load-bearing.
_FRAMING_RUBRIC_REQUIRED_ARCHETYPES = frozenset({"compare", "predict", "recommend"})

# P3-W7 (2026-05-27): tier_ranking bounds + archetype gating.
# Qianfan q14 §7.3-§7.6 ranks 10 teams across 6 rubric items (Direction
# 20% / Paper 22% / Collab 13% / Funding 18% / Industry 15% / Talent 12%).
# q3 §8.1 ranks 11 sub-sectors across 6 dimensions. Both run a ±10pp
# weight perturbation in a sensitivity sub-section to report rank
# stability. The tier_ranking weights SHOULD mirror the framing_chapter's
# published_rubric_items weights (§1 publishes the rubric; the tier-
# ranking chapter consumes it) but `_normalize` does not pin equality —
# downstream review catches divergence rather than coupling the two
# audits.
_TIER_RANKING_REQUIRED_ARCHETYPES = frozenset({"compare", "predict"})
_TIER_RANKING_MIN_TIERS = 2
_TIER_RANKING_MAX_TIERS = 5
_TIER_RANKING_DEFAULT_PERTURBATION_PP = 10
# Weights must sum to ~1.0 ± tolerance. Tolerance accommodates rounding
# (LLMs frequently emit 0.20+0.20+0.20+0.20+0.18 = 0.98 instead of 1.0).
_TIER_RANKING_WEIGHT_TOTAL_TOLERANCE = 0.05
# Acceptable band for `sensitivity_check.perturbation_pp` around the default.
# Qianfan q14/q3 both use ±10pp; anything in [5, 20] still produces a
# meaningful sensitivity sub-section. Values outside this band (e.g., 1pp →
# trivial perturbation, 50pp → no longer "sensitivity" so much as
# re-weighting) get an audit shortfall. Missing/wrong-type values are
# backfilled with the default and flagged. Greptile PR #43 round-2 fix:
# the default constant was previously dead documentation — wiring it into
# runtime audit + backfill removes that gap.
_TIER_RANKING_PERTURBATION_PP_MIN = 5
_TIER_RANKING_PERTURBATION_PP_MAX = 20

# P3-W5 (2026-05-27): limitations chapter sub-section types. Qianfan's
# 6/11-article pattern (q14 §9.10 / q23 §8.11 / q56 §10.7.5 / q3 §8.4 /
# q44 §6+ / q89 §close) all enumerate 5 limitation dimensions: data
# granularity, scope cap, time validity, sampling, falsifiers. The
# scenario_stress_test sub-node (predict archetype only) recomputes the
# article's main ranking (typically tier_ranking, the §N analytic block
# from PR #43) under 3 scenarios.
_LIMITATIONS_SUBSECTION_TYPES: tuple[str, ...] = (
    "data_granularity",
    "scope_cap",
    "time_validity",
    "sampling",
    "falsifiers",
)
_LIMITATIONS_REQUIRED_ARCHETYPES = frozenset({"predict", "compare", "explain-mechanism", "list-all"})
_LIMITATIONS_STRESS_TEST_ARCHETYPES = frozenset({"predict"})


def _max_entities_for_archetype(archetype: str | None) -> int:
    """Return the per-archetype upper bound on entity_matrix.entities.

    Falls back to the legacy `_ENTITY_MATRIX_ENTITIES_MAX` (20) when the
    archetype isn't in the per-archetype dict — preserves back-compat
    with any caller that imports the flat constant. P3-W1 raises list-all
    to 30 per the Qianfan id=91 verified-25-28-knight pattern.
    """
    return _ENTITY_MATRIX_ENTITIES_MAX_BY_ARCHETYPE.get(archetype or "", _ENTITY_MATRIX_ENTITIES_MAX)


# P3-W1: archetypes for which entity_matrix is REQUIRED. Others may have it
# but the architect chooses on its own (auto-promoted by _normalize when
# the outline has the entity-list shape — see _should_promote_entity_matrix).
_ENTITY_MATRIX_REQUIRED_ARCHETYPES = frozenset({"list-all", "compare"})
_ENTITY_MATRIX_OPTIONAL_ARCHETYPES = frozenset({"predict", "explain-mechanism", "trend", "recommend"})


# P3-W1: detection heuristic for "this outline has the entity-list shape".
# Used to OFFER the entity_matrix contract to optional archetypes when
# they're naturally entity-iterating. Conservative (under-promotes rather
# than over-promotes) since false-positive promotion forces the writer
# into a rigid template that may not fit the prompt.

# Title-Case English tokens that are common function/article words — present
# in an entity title but not themselves entity-indicative.
_ENTITY_TITLE_STOPWORDS = frozenset({"The", "And", "Of", "For", "In", "To", "A", "An", "Is", "Are"})

# Token pattern: Title-Case English word (capital + lowercase tail). Used to
# detect proper-noun-like tokens in section titles.
_TITLE_CASE_TOKEN_RE = re.compile(r"\b[A-Z][a-zA-Z]+\b")


# CJK script ranges treated as "proper-noun-like" by the entity-list heuristic.
# Chinese Hanzi, Japanese Hiragana/Katakana, and Korean Hangul all carry
# entity-name signal without Title-Case markers, so any character in these
# blocks counts the title as proper-noun-like.
def _has_cjk_char(s: str) -> bool:
    for c in s:
        cp = ord(c)
        if (
            0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs (Chinese, Kanji)
            or 0x3040 <= cp <= 0x309F  # Hiragana
            or 0x30A0 <= cp <= 0x30FF  # Katakana
            or 0xAC00 <= cp <= 0xD7AF  # Hangul Syllables
        ):
            return True
    return False


def _should_promote_entity_matrix(plan: dict, archetype: str | None) -> bool:
    """Return True when an optional-archetype plan looks like it should
    use entity_matrix (≥3 sibling sub-chapters with proper-noun-like
    titles under a shared parent).

    Returns False when the plan already has a populated entity_matrix
    (don't re-suggest), when the archetype is required (caller already
    handles it), or when the outline doesn't have the entity-list shape.
    """
    if archetype not in _ENTITY_MATRIX_OPTIONAL_ARCHETYPES:
        return False
    em = plan.get("entity_matrix")
    if isinstance(em, dict) and (em.get("entities") or []):
        return False
    toc = plan.get("report_toc") or []
    for sec in toc:
        subs = sec.get("subsections") or []
        if len(subs) < 3:
            continue
        # "proper-noun-like": at least one capitalized non-stopword token,
        # or contains CJK content (Hanzi/Kana/Hangul carry entity signal
        # without Title-Case markers), or contains a quoted name.
        # Conservative check — we don't want to fire on generic structural
        # titles like "Background" or "Methodology".
        proper_count = 0
        for sub in subs:
            title = str(sub.get("title", ""))
            if not title:
                continue
            # CJK detection — any Hanzi/Kana/Hangul title is "proper-noun-like"
            if _has_cjk_char(title):
                proper_count += 1
                continue
            # English: at least one Title-Case token that's not a common stopword
            tokens = _TITLE_CASE_TOKEN_RE.findall(title)
            content_tokens = [t for t in tokens if t not in _ENTITY_TITLE_STOPWORDS]
            if content_tokens:
                proper_count += 1
        if proper_count >= 3:
            return True
    return False


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
    # Wave 2 §1.2: dispatch to per-archetype bounds. `archetype=None`
    # falls back to the default uniform 8-12 / 3-6 / 2-4 bounds via
    # _bounds_for_archetype, preserving back-compat with callers that
    # don't pass archetype (the existing test suite + any pre-Wave-2
    # script invocations).
    b = _bounds_for_archetype(archetype)
    audit["archetype"] = archetype or ""
    audit["bounds"] = dict(b)
    if len(toc) < b["top_min"]:
        audit["shortfalls"].append(f"top_sections={len(toc)}<{b['top_min']}")
    if len(toc) > b["top_max"]:
        audit["shortfalls"].append(f"top_sections={len(toc)}>{b['top_max']}")
    if len(queries) < _QUERIES_MIN:
        audit["shortfalls"].append(f"queries={len(queries)}<{_QUERIES_MIN}")
    if len(queries) > _QUERIES_MAX:
        audit["shortfalls"].append(f"queries={len(queries)}>{_QUERIES_MAX}")

    # P3-W0a (2026-05-27): per-archetype query.type distribution audit.
    # Tallies actual fractions, compares against the archetype's minimum-
    # proportion floor. Shortfalls are surfaced advisory-style (same pattern
    # as outline shape: visible in drift telemetry, NOT a retry trigger).
    # The retry-on-shortfall loop is gated on structural counts (top_min,
    # sub_min, seed_min) — adding a query-type retry would be a separate
    # decision and is out of scope here.
    q_type_mins = _query_type_mins_for_archetype(archetype)
    type_counts: dict[str, int] = {t: 0 for t in TYPE_TO_SPECIALIST}
    for q in queries:
        t = str(q.get("type", "factual")).strip().lower()
        if t in type_counts:
            type_counts[t] += 1
    n_q = len(queries)
    type_fractions: dict[str, float] = (
        {t: round(type_counts[t] / n_q, 3) for t in TYPE_TO_SPECIALIST}
        if n_q > 0
        else dict.fromkeys(TYPE_TO_SPECIALIST, 0.0)
    )
    audit["query_type_counts"] = dict(type_counts)
    audit["query_type_fractions"] = dict(type_fractions)
    audit["query_type_min_pct"] = dict(q_type_mins)
    audit["query_type_shortfalls"] = []
    if n_q > 0:
        for qtype, min_pct in q_type_mins.items():
            actual = type_fractions.get(qtype, 0.0)
            if actual < min_pct:
                shortfall = f"query_type.{qtype}={actual:.2%}<{min_pct:.0%}"
                audit["query_type_shortfalls"].append(shortfall)
    # Query-type shortfalls are ADVISORY-ONLY: they're surfaced in
    # `_outline_audit["query_type_shortfalls"]` and forwarded to drift
    # telemetry, but NOT added to the global `shortfalls` list because
    # that list is the retry-trigger and we don't want a 9-vs-10% query-
    # type miss to cost a retry while the outline is structurally fine.
    # The post-write compliance scorer + retry-feedback string (which
    # interpolates the floors when a retry IS triggered for a separate
    # reason) jointly enforce the contract.
    for sec in toc:
        subs = sec.get("subsections", []) or []
        audit["n_subsections_total"] += len(subs)
        if len(subs) < b["sub_min"]:
            audit["shortfalls"].append(f"{sec.get('id')}.subs={len(subs)}<{b['sub_min']}")
        if len(subs) > b["sub_max"]:
            audit["shortfalls"].append(f"{sec.get('id')}.subs={len(subs)}>{b['sub_max']}")
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
            #
            # Wave 2 §1.2: archetypes that disallow H4 (seed_max == 0,
            # e.g. list-all / compare) treat an empty depth_seeds list
            # as CORRECT rather than as a missing-seeds shortfall.
            if b["seed_max"] == 0:
                # No H4 tier for this archetype; only flag the upper bound
                # if the architect emitted seeds against contract.
                audit["n_seeds_total"] += len(seeds)
                if len(seeds) > b["seed_max"]:
                    audit["shortfalls"].append(
                        f"{sub.get('id')}.seeds={len(seeds)}>{b['seed_max']} (archetype `{archetype}` is flat — no H4 leaves)"
                    )
                continue
            if not seeds:
                audit["subsections_missing_seeds"] += 1
            audit["n_seeds_total"] += len(seeds)
            if len(seeds) < b["seed_min"]:
                audit["shortfalls"].append(f"{sub.get('id')}.seeds={len(seeds)}<{b['seed_min']}")
            if len(seeds) > b["seed_max"]:
                audit["shortfalls"].append(f"{sub.get('id')}.seeds={len(seeds)}>{b['seed_max']}")

    # P2-Option-A-#7 (2026-05-23): entity_matrix audit + backfill for
    # list-all and compare archetypes. P3-W1 (2026-05-27): extended to
    # optional-archetype auto-promotion + per-archetype entity cap +
    # dimensions object-form normalization + instantiation_mode contract.
    em = plan.get("entity_matrix")
    is_required = archetype in _ENTITY_MATRIX_REQUIRED_ARCHETYPES
    should_promote = (not is_required) and _should_promote_entity_matrix(plan, archetype)
    # Greptile PR #37 round-4: optional-archetype + LLM-populated path.
    # `_should_promote_entity_matrix` early-exits with False when entities
    # are already non-empty (line ~876: "don't re-suggest"). Without this
    # third gate, an optional-archetype plan where the LLM correctly
    # populated entities but omitted `instantiation_mode` would skip the
    # whole normalize block — leaving instantiation_mode unset, which
    # makes the writer's `em_active` check fail (archetype not in
    # {list-all, compare} AND instantiation_mode != "prose_subheaders")
    # and the entity matrix block is silently dropped. This third
    # condition lets the LLM-populated path through so the normalize
    # backstop (dimensions, instantiation_mode default, min_axes default)
    # still applies. Audit's `entity_matrix_auto_promoted` remains False
    # for this path — the LLM populated it, not auto-promotion.
    em_optional_populated = (
        archetype in _ENTITY_MATRIX_OPTIONAL_ARCHETYPES and isinstance(em, dict) and bool(em.get("entities"))
    )
    if is_required or should_promote or em_optional_populated:
        # Greptile PR #25 follow-up round 2 (2026-05-25): track whether the
        # matrix was entirely absent vs present-but-underpopulated. A
        # missing matrix necessarily has zero entities and zero dimensions,
        # so emitting all three of (missing + entities=0<5 + dimensions=0<4)
        # would inflate the shortfall count for ONE root cause — and PR #23's
        # retry-on-shortfall logic could waste a retry attempt trying to fix
        # three independent failures when there's only one underlying gap.
        matrix_was_missing = not isinstance(em, dict)
        if matrix_was_missing:
            # Backfill so writer never crashes on `entity_matrix["entities"]`.
            em = {"entities": [], "dimensions": []}
            plan["entity_matrix"] = em
            # Only flag as a shortfall when REQUIRED. Optional-archetype
            # auto-promotion path treats missing matrix as "architect didn't
            # populate it" without shortfall — the writer still benefits
            # from the empty-matrix passthrough.
            if is_required:
                audit["shortfalls"].append("entity_matrix=missing(required-for-archetype)")
        ents = em.get("entities") if isinstance(em.get("entities"), list) else None
        dims = em.get("dimensions") if isinstance(em.get("dimensions"), list) else None
        if ents is None:
            em["entities"] = []
            ents = em["entities"]
        if dims is None:
            em["dimensions"] = []
            dims = em["dimensions"]

        # P3-W1: normalize legacy string-form dimensions to object form.
        # Pre-W1 plans had `dimensions: [str, ...]`; new plans should emit
        # `[{"axis_name": str, "render_order": int, "content_template": str}, ...]`.
        # Auto-wrap so the writer sees one canonical form.
        em["dimensions"] = _normalize_dimensions(dims)
        dims = em["dimensions"]

        # P3-W1: instantiation_mode + min_axes_per_entity defaults.
        # Use `or`-based assignment, NOT setdefault: setdefault only
        # writes on a missing key, so an explicit `"min_axes_per_entity":
        # null` from the LLM would survive normalize and crash the
        # writer's `int(None)` coercion downstream. `or` collapses
        # missing-key / None / 0 / "" all to the default — the same
        # pattern PR #37 round-2 applied to render_order in
        # `_normalize_dimensions`. Greptile PR #37 round-3 finding.
        em["instantiation_mode"] = em.get("instantiation_mode") or "prose_subheaders"
        em["min_axes_per_entity"] = em.get("min_axes_per_entity") or 3

        audit["entity_matrix_entities"] = len(ents)
        audit["entity_matrix_dimensions"] = len(dims)
        audit["entity_matrix_instantiation_mode"] = em["instantiation_mode"]
        audit["entity_matrix_min_axes_per_entity"] = em["min_axes_per_entity"]
        audit["entity_matrix_auto_promoted"] = bool(should_promote)
        # Only emit count shortfalls when the matrix was actually present —
        # the "missing" shortfall already captures the entire failure mode
        # when the LLM omitted the field. (Upper-bound count shortfalls
        # remain gated the same way: if the matrix was missing we backfilled
        # to {entities: [], dimensions: []} which can't trip the >MAX path.)
        if not matrix_was_missing:
            entity_max = _max_entities_for_archetype(archetype)
            if len(ents) < _ENTITY_MATRIX_ENTITIES_MIN:
                audit["shortfalls"].append(f"entity_matrix.entities={len(ents)}<{_ENTITY_MATRIX_ENTITIES_MIN}")
            if len(ents) > entity_max:
                audit["shortfalls"].append(f"entity_matrix.entities={len(ents)}>{entity_max}")
            if len(dims) < _ENTITY_MATRIX_DIMENSIONS_MIN:
                audit["shortfalls"].append(f"entity_matrix.dimensions={len(dims)}<{_ENTITY_MATRIX_DIMENSIONS_MIN}")
            if len(dims) > _ENTITY_MATRIX_DIMENSIONS_MAX:
                audit["shortfalls"].append(f"entity_matrix.dimensions={len(dims)}>{_ENTITY_MATRIX_DIMENSIONS_MAX}")

    # P3-W2 (2026-05-27): framing_chapter audit. For required archetypes,
    # check that the §1 contract artifact exists with the 4 required
    # sub-sections, 5-10 vocabulary terms, and (when applicable) 4-6
    # rubric items. Same advisory-only pattern as entity_matrix —
    # shortfalls visible in drift telemetry; only the missing/required
    # case is a global retry-trigger.
    fc = plan.get("framing_chapter")
    fc_is_required = archetype in _FRAMING_CHAPTER_REQUIRED_ARCHETYPES
    if fc_is_required:
        fc_was_missing = not isinstance(fc, dict)
        if fc_was_missing:
            # Backfill so writer never crashes on `fc["sub_sections"]`.
            fc = {
                "title": "",
                "sub_sections": [],
                "published_vocabulary": [],
                "published_rubric_items": [],
            }
            plan["framing_chapter"] = fc
            audit["shortfalls"].append("framing_chapter=missing(required-for-archetype)")
        # Normalize fields so downstream consumers see canonical shape.
        if not isinstance(fc.get("sub_sections"), list):
            fc["sub_sections"] = []
        if not isinstance(fc.get("published_vocabulary"), list):
            fc["published_vocabulary"] = []
        if not isinstance(fc.get("published_rubric_items"), list):
            fc["published_rubric_items"] = []
        sub_types = [str(s.get("type", "")).strip().lower() for s in fc["sub_sections"] if isinstance(s, dict)]
        missing_types = [t for t in _FRAMING_SUBSECTION_TYPES if t not in sub_types]
        audit["framing_chapter_sub_section_types"] = sub_types
        audit["framing_chapter_missing_sub_section_types"] = missing_types
        audit["framing_chapter_vocabulary_count"] = len(fc["published_vocabulary"])
        audit["framing_chapter_rubric_count"] = len(fc["published_rubric_items"])
        if not fc_was_missing:
            if missing_types:
                audit["shortfalls"].append(f"framing_chapter.missing_sub_section_types={','.join(missing_types)}")
            if len(fc["published_vocabulary"]) < _FRAMING_VOCABULARY_MIN:
                audit["shortfalls"].append(
                    f"framing_chapter.vocabulary={len(fc['published_vocabulary'])}<{_FRAMING_VOCABULARY_MIN}"
                )
            if len(fc["published_vocabulary"]) > _FRAMING_VOCABULARY_MAX:
                audit["shortfalls"].append(
                    f"framing_chapter.vocabulary={len(fc['published_vocabulary'])}>{_FRAMING_VOCABULARY_MAX}"
                )
            if archetype in _FRAMING_RUBRIC_REQUIRED_ARCHETYPES:
                if len(fc["published_rubric_items"]) < _FRAMING_RUBRIC_MIN:
                    audit["shortfalls"].append(
                        f"framing_chapter.rubric={len(fc['published_rubric_items'])}<{_FRAMING_RUBRIC_MIN}"
                    )
                if len(fc["published_rubric_items"]) > _FRAMING_RUBRIC_MAX:
                    audit["shortfalls"].append(
                        f"framing_chapter.rubric={len(fc['published_rubric_items'])}>{_FRAMING_RUBRIC_MAX}"
                    )

    # P3-W7 (2026-05-27): tier_ranking audit. Required for compare/predict
    # when entity_matrix has ≥5 entities (otherwise the ranking has too few
    # rows to be meaningful). Audits: scoring_formula presence, weights
    # sum-to-1.0 ± tolerance, tier count 2-5, sensitivity_check populated.
    tr = plan.get("tier_ranking")
    em = plan.get("entity_matrix")
    # Greptile PR #43 round-2: previous `(em.get("entities") if isinstance(em, dict) else []) or []`
    # only handled `em` being a non-dict OR `entities` being falsy. A non-empty,
    # non-list `entities` value (e.g. a comma-separated string `"E1, E2, E3, E4, E5"`)
    # would pass through and `len()` would return the character count (18), spuriously
    # triggering `tr_is_required=True` for "predict" archetype plans where the
    # entity_matrix block doesn't run pre-normalization. Explicit isinstance(list)
    # guard fixes this; "compare" was already safe because the entity_matrix
    # normalization block (~lines 641-653) coerces `entities` to list before this
    # check runs.
    _em_entities_raw = em.get("entities") if isinstance(em, dict) else []
    em_entities = _em_entities_raw if isinstance(_em_entities_raw, list) else []
    tr_is_required = archetype in _TIER_RANKING_REQUIRED_ARCHETYPES and len(em_entities) >= _ENTITY_MATRIX_ENTITIES_MIN
    if tr_is_required:
        tr_was_missing = not isinstance(tr, dict)
        if tr_was_missing:
            tr = {
                "title": "",
                "scoring_formula": "",
                "weights": {},
                "tiers": [],
                "sensitivity_check": None,
            }
            plan["tier_ranking"] = tr
            audit["shortfalls"].append("tier_ranking=missing(required-for-archetype-and-entity-count)")
        if not isinstance(tr.get("weights"), dict):
            tr["weights"] = {}
        if not isinstance(tr.get("tiers"), list):
            tr["tiers"] = []
        # Greptile PR #43 round-3: `bool` is a subclass of `int` in Python, so
        # the prior `isinstance(v, (int, float))` filter silently admitted
        # boolean weights — a dict like `{"R-1": True}` would compute
        # weights_sum=1.0 and pass the ±0.05 tolerance check, masking an LLM
        # type error. The perturbation_pp guard below already excludes bool
        # explicitly; this restores consistency by doing the same here.
        weights_sum = sum(
            float(v) for v in tr["weights"].values() if isinstance(v, (int, float)) and not isinstance(v, bool)
        )
        n_tiers = len(tr["tiers"])
        audit["tier_ranking_weights_sum"] = round(weights_sum, 4)
        audit["tier_ranking_n_tiers"] = n_tiers
        audit["tier_ranking_has_sensitivity_check"] = isinstance(tr.get("sensitivity_check"), dict)
        if not tr_was_missing:
            if abs(weights_sum - 1.0) > _TIER_RANKING_WEIGHT_TOTAL_TOLERANCE:
                audit["shortfalls"].append(
                    f"tier_ranking.weights_sum={weights_sum:.3f}!=1.0±{_TIER_RANKING_WEIGHT_TOTAL_TOLERANCE}"
                )
            if n_tiers < _TIER_RANKING_MIN_TIERS:
                audit["shortfalls"].append(f"tier_ranking.tiers={n_tiers}<{_TIER_RANKING_MIN_TIERS}")
            if n_tiers > _TIER_RANKING_MAX_TIERS:
                audit["shortfalls"].append(f"tier_ranking.tiers={n_tiers}>{_TIER_RANKING_MAX_TIERS}")
            if not audit["tier_ranking_has_sensitivity_check"]:
                audit["shortfalls"].append("tier_ranking.sensitivity_check=missing")
            else:
                # Greptile PR #43 round-2: validate sensitivity_check.perturbation_pp
                # against the default constant + acceptable band. Backfills with
                # default when missing/wrong-type so downstream readers always
                # see a usable value; emits shortfall on backfill OR
                # out-of-band so the audit trail is honest.
                sc = tr["sensitivity_check"]
                pp = sc.get("perturbation_pp")
                if not isinstance(pp, (int, float)) or isinstance(pp, bool):
                    sc["perturbation_pp"] = _TIER_RANKING_DEFAULT_PERTURBATION_PP
                    audit["tier_ranking_sensitivity_perturbation_pp"] = _TIER_RANKING_DEFAULT_PERTURBATION_PP
                    audit["shortfalls"].append(
                        "tier_ranking.sensitivity_check.perturbation_pp=missing"
                        f"(backfilled-to-{_TIER_RANKING_DEFAULT_PERTURBATION_PP})"
                    )
                else:
                    audit["tier_ranking_sensitivity_perturbation_pp"] = pp
                    if pp < _TIER_RANKING_PERTURBATION_PP_MIN or pp > _TIER_RANKING_PERTURBATION_PP_MAX:
                        audit["shortfalls"].append(
                            f"tier_ranking.sensitivity_check.perturbation_pp={pp}"
                            f"!in[{_TIER_RANKING_PERTURBATION_PP_MIN},"
                            f"{_TIER_RANKING_PERTURBATION_PP_MAX}]"
                        )
            if not tr.get("scoring_formula"):
                audit["shortfalls"].append("tier_ranking.scoring_formula=empty")

    # P3-W5 (2026-05-27): limitations_chapter audit. For required
    # archetypes, check the chapter exists with all 5 sub-section types
    # and (for predict) a populated scenario_stress_test. Same advisory-
    # only pattern as entity_matrix / framing_chapter / tier_ranking.
    lc = plan.get("limitations_chapter")
    lc_is_required = archetype in _LIMITATIONS_REQUIRED_ARCHETYPES
    if lc_is_required:
        lc_was_missing = not isinstance(lc, dict)
        if lc_was_missing:
            lc = {"title": "", "sub_sections": [], "scenario_stress_test": None}
            plan["limitations_chapter"] = lc
            audit["shortfalls"].append("limitations_chapter=missing(required-for-archetype)")
        if not isinstance(lc.get("sub_sections"), list):
            lc["sub_sections"] = []
        # Greptile PR #41 round-2: gate ALL per-sub-section audit keys on
        # `not lc_was_missing`, symmetric with the stress-test gate below.
        # When the chapter is entirely absent the backfilled `sub_sections=[]`
        # would otherwise emit `sub_section_types=[]` + `missing_sub_section_
        # types=<all 5>` — values indistinguishable from "chapter present but
        # all 5 sub-types missing." A targeted-retry consumer reading those
        # keys could fire 5 sub-section retries for a single root cause
        # (chapter entirely absent), already captured by the
        # `limitations_chapter=missing` shortfall.
        if not lc_was_missing:
            sub_types = [str(s.get("type", "")).strip().lower() for s in lc["sub_sections"] if isinstance(s, dict)]
            missing_types = [t for t in _LIMITATIONS_SUBSECTION_TYPES if t not in sub_types]
            audit["limitations_chapter_sub_section_types"] = sub_types
            audit["limitations_chapter_missing_sub_section_types"] = missing_types
            if missing_types:
                audit["shortfalls"].append(f"limitations_chapter.missing_sub_section_types={','.join(missing_types)}")
            # Stress-test sub-node check (predict archetype only today; the
            # set may grow). Same gate rationale as the sub-section audit
            # keys above: avoid emitting an ambiguous `False` when the
            # chapter was absent. The shortfall message interpolates the
            # actual `archetype` so a future addition to
            # `_LIMITATIONS_STRESS_TEST_ARCHETYPES` doesn't silently emit a
            # misleading "required-for-predict" tag for the new archetype.
            if archetype in _LIMITATIONS_STRESS_TEST_ARCHETYPES:
                sst = lc.get("scenario_stress_test")
                has_sst = isinstance(sst, dict) and bool(sst.get("scenarios"))
                audit["limitations_chapter_has_stress_test"] = has_sst
                if not has_sst:
                    audit["shortfalls"].append(
                        f"limitations_chapter.scenario_stress_test=missing(required-for-{archetype})"
                    )

    plan["_outline_audit"] = audit


def _normalize_dimensions(dims: list) -> list:
    """Coerce dimensions to canonical object form.

    P3-W1 (2026-05-27): the entity_matrix schema now uses ordered objects
    `{axis_name, render_order, content_template}` so the writer can
    mechanically instantiate each entity with byte-identical sub-headers
    in declared order (Qianfan's verified corpus-wide pattern). Legacy
    string-form `[str, ...]` is auto-wrapped here for backward compat.

    - List-of-strings → wrap each in {axis_name, render_order, content_template}
      with render_order = 1-indexed position and a generic content_template.
    - List-of-objects → preserved; missing fields filled with defaults.
    - Empty / non-list → returned as [].
    """
    if not isinstance(dims, list):
        return []
    out: list = []
    for i, raw in enumerate(dims):
        if isinstance(raw, str):
            name = raw.strip()
            if not name:
                continue
            out.append(
                {
                    "axis_name": name,
                    "render_order": i + 1,
                    "content_template": "facts + analysis (3-6 sentences)",
                }
            )
        elif isinstance(raw, dict):
            name = str(raw.get("axis_name", "")).strip()
            if not name:
                # Skip object-form dimensions without an axis_name (writer
                # would render an empty sub-header otherwise).
                continue
            # `dict.get()` returns an explicit `None` (not the default) when
            # the key is present-but-null, and the LLM occasionally emits
            # `"render_order": null` or a non-numeric string. Both must
            # fall back to the positional index instead of raising — this
            # path is the malformed-input resilience guarantee for the
            # whole normalize step.
            ro_raw = raw.get("render_order")
            try:
                ro = int(float(ro_raw)) if ro_raw is not None else i + 1
            except (TypeError, ValueError):
                ro = i + 1
            out.append(
                {
                    "axis_name": name,
                    "render_order": ro,
                    "content_template": str(raw.get("content_template", "facts + analysis (3-6 sentences)")),
                }
            )
        # Other types (int, None, list) silently dropped — malformed
        # entries shouldn't crash the writer; the dimensions-count audit
        # will reflect the reduced count if any were dropped.
    return out
