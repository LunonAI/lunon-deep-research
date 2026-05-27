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
                                      order (the reference's verified corpus-wide
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
#
# Wave 2 §1.2 (2026-05-26): the uniform 8-12 / 3-6 / 2-4 bounds are the
# DEFAULT, used when the archetype is unknown or has no preset. Per-
# archetype bounds in `_ARCHETYPE_OUTLINE_SHAPE` override these for the
# archetypes whose the reference articles show structurally
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


# Wave 2 §1.2 (2026-05-26): per-archetype outline shape preset.
# Calibrated against the 10-doc reference corpus (profiled
# 2026-05-26 via scripts/p2_reference_profile + p2_reference_distance
# semantic-depth scan). Key findings:
#   - id=91 (list-all, Saint Seiya armors): 78 H2 / 0 H3 — flat enumeration
#   - id=14 (list-all, math/quantum research): 81 H2 / 0 H3 — flat
#   - id=8 (list-all, ML methods): 63 H2 / 0 H3 — flat
#   - id=56 (explain-mechanism, auction theory): 70 H2 / 135 H3 — deep
#   - id=20 (explain-mechanism, HTTP): 55 H2 / 138 H3 — deep
#   - id=89 (explain-mechanism, biology): 53 H2 / 221 H3 — deep
#   - id=38 (predict/trend, jewelry trends): 58 H2 / 115 H3 — medium
# ZERO of the 10 reference docs use H4+ headings. The pre-Wave-2 outline
# spec produced 8-12 H2 × 3-6 H3 × 2-4 H4 leaves = 48-288 H4 leaves;
# this misaligns with the reference's no-H4 convention. Wave 2 keeps H4 for
# explain-mechanism / predict (where deep hierarchy still helps the
# judge see depth) but drops H4 for list-all / compare (where the reference's
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
    # explain-mechanism: deepest archetype. the reference refs show 50-70 H2
    # with 130-220 H3 leaves. Our pre-Wave-2 8-12 × 4-8 H3 produces
    # 32-96 H3 leaves, fewer than the reference's ~135. Bump the top-section
    # band to 8-14 + sub band to 4-8 + keep H4 (2-4 seeds) so total
    # H3+H4 leaf count approaches the reference's per-article density.
    "explain-mechanism": {
        "top_min": 8,
        "top_max": 14,
        "sub_min": 4,
        "sub_max": 8,
        "seed_min": 2,
        "seed_max": 4,
    },
    # predict / trend / recommend: forward-looking analysis archetypes.
    # the reference id=38 (trends): 58 H2 / 115 H3. Use the default-shape
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
    lines.extend(
        [
            "",
            f"REGENERATE the FULL plan, fixing every shortfall above. The "
            f"structural contract for archetype `{archetype or 'default'}` "
            f"({b['top_min']}-{b['top_max']} top sections, "
            f"{b['sub_min']}-{b['sub_max']} subsections each, "
            f"{seed_clause}) is the highest-priority constraint — it "
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
    # whose the reference shape is structurally different.
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
        f"calibration against the 10-doc reference corpus showed "
        f"archetype-specific shapes:\n"
        f"  • report_toc: {b['top_min']}-{b['top_max']} top-level sections\n"
        f"  • subsections per top section: {b['sub_min']}-{b['sub_max']}\n"
        f"  • {seed_clause}\n"
        f"These bounds are ENFORCED by the audit + retry-on-shortfall "
        f"loop. A plan outside these bounds for this archetype will be "
        f"rejected and you'll be asked to regenerate.\n"
    )
    user = (
        f"PROMPT ({language}):\n{prompt}\n\n"
        f"ARCHETYPE: {archetype}\nARCHETYPE EMPHASIS: {emphasis}\n\n"
        f"{archetype_outline_block}\n"
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
# list-all where the reference id=91 has 25-28 knights and id=89 has similar
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


def _max_entities_for_archetype(archetype: str | None) -> int:
    """Return the per-archetype upper bound on entity_matrix.entities.

    Falls back to the legacy `_ENTITY_MATRIX_ENTITIES_MAX` (20) when the
    archetype isn't in the per-archetype dict — preserves back-compat
    with any caller that imports the flat constant. P3-W1 raises list-all
    to 30 per the reference id=91 verified-25-28-knight pattern.
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
        # or contains CJK content (Chinese proper nouns are unambiguous by
        # context), or contains a quoted name. Conservative check — we
        # don't want to fire on generic structural titles like "Background"
        # or "Methodology".
        proper_count = 0
        for sub in subs:
            title = str(sub.get("title", ""))
            if not title:
                continue
            # CJK detection — every Chinese title is "proper-noun-like" for our purposes
            if any("一" <= c <= "鿿" for c in title):
                proper_count += 1
                continue
            # English: at least one Title-Case token that's not a common stopword
            import re as _re

            tokens = _re.findall(r"\b[A-Z][a-zA-Z]+\b", title)
            stopwords = {"The", "And", "Of", "For", "In", "To", "A", "An", "Is", "Are"}
            content_tokens = [t for t in tokens if t not in stopwords]
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
    if is_required or should_promote:
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
        em.setdefault("instantiation_mode", "prose_subheaders")
        em.setdefault("min_axes_per_entity", 3)

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

    plan["_outline_audit"] = audit


def _normalize_dimensions(dims: list) -> list:
    """Coerce dimensions to canonical object form.

    P3-W1 (2026-05-27): the entity_matrix schema now uses ordered objects
    `{axis_name, render_order, content_template}` so the writer can
    mechanically instantiate each entity with byte-identical sub-headers
    in declared order (the reference's verified corpus-wide pattern). Legacy
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
            out.append(
                {
                    "axis_name": name,
                    "render_order": int(raw.get("render_order", i + 1)),
                    "content_template": str(raw.get("content_template", "facts + analysis (3-6 sentences)")),
                }
            )
        # Other types (int, None, list) silently dropped — malformed
        # entries shouldn't crash the writer; the dimensions-count audit
        # will reflect the reduced count if any were dropped.
    return out
