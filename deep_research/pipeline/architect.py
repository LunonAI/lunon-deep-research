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
    "target_sections": ["S1", ...], "rationale": str } ... 48-64 ],
 "stakeholder_chapter": {          /* P3-W6 (2026-05-27): closing chapter
                                      that splits recommendations into
                                      3-5 stakeholder addressee blocks
                                      with NON-OVERLAPPING content.
                                      Populate when prompt signals
                                      plural audience; null otherwise. */
   "title": str,                    /* e.g. "Strategic Recommendations
                                       by Stakeholder" */
   "stakeholders": [
     {"id": str, "label": str, "content_directive": str}, ...
   ]
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
- entity_matrix REQUIRED for list-all and compare archetypes. Populate
  entities with EVERY entity the prompt names (verbatim where possible),
  AND choose 4-8 dimensions a reader would compare them across (the
  "columns" of the table the writer will render). Omit entity_matrix (or
  set to null) for other archetypes.
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
_ENTITY_MATRIX_ENTITIES_MIN = 5
_ENTITY_MATRIX_ENTITIES_MAX = 20
_ENTITY_MATRIX_DIMENSIONS_MIN = 4
_ENTITY_MATRIX_DIMENSIONS_MAX = 8

# P3-W6 (2026-05-27): stakeholder chapter bounds. Qianfan corpus pattern
# (6/11 articles): closing chapter splits recommendations into 3-5
# addressee blocks (q23 §8.4-§8.10 has 7 sub-blocks; q3 §8.7 has 4;
# q14 §9.6-§9.9 has 4). We require ≥3 and cap at 5 to prevent the
# closing chapter from becoming a long enumeration of overlapping
# advice (the Comprehensiveness signal is in CONTENT, not COUNT).
_STAKEHOLDER_COUNT_MIN = 3
_STAKEHOLDER_COUNT_MAX = 5

# Plural-audience detection: regex patterns that signal "the prompt is
# asking for advice addressed to multiple parties." When at least ONE
# fires, the architect should populate stakeholder_chapter. The regex
# is intentionally conservative (precision over recall) — false-positive
# stakeholder chapters bloat the article for prompts that have a single
# audience, while false-negatives mean the chapter is omitted and the
# closing recommendations stay generic (acceptable; not a regression).
_PLURAL_AUDIENCE_PATTERNS = (
    r"\binvestors?\s+and\s+(?:policymakers?|regulators?|researchers?|consumers?|users?)\b",
    r"\b(?:policymakers?|regulators?|researchers?|practitioners?|industry)\s+and\s+(?:investors?|practitioners?|industry|stakeholders?)\b",
    r"\bfor\s+(?:both|each\s+of)\s+\w+\s+(?:and|&)\s+\w+",
    r"\brecommendations?\s+(?:for|to|targeting|aimed\s+at)\s+(?:investors?|policymakers?|regulators?|researchers?|practitioners?|industry|stakeholders?)",
    r"\bguidance\s+(?:for|to)\s+(?:investors?|policymakers?|practitioners?|industry|stakeholders?)",
    # ZH patterns: "面向多元主体" / "为投资者和决策者" / "对不同利益相关方"
    r"面向[多种各]+[元方主体]+",
    r"为(?:投资者|决策者|监管者|研究人员|从业者|产业|消费者)[和与、](?:投资者|决策者|监管者|研究人员|从业者|产业|消费者|读者|用户)",
    r"对(?:不同|各类|各个|多个)?(?:利益相关方|stakeholder|读者|受众)",
)


def _prompt_signals_plural_audience(prompt: str) -> bool:
    """Return True when the prompt signals advice for multiple audiences.

    Used by `_normalize` to decide whether stakeholder_chapter should be
    populated. Conservative — false-negative is acceptable (chapter
    becomes generic single-audience), false-positive bloats the article.
    """
    import re as _re

    if not prompt or not isinstance(prompt, str):
        return False
    for pat in _PLURAL_AUDIENCE_PATTERNS:
        if _re.search(pat, prompt, _re.I):
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
    # list-all and compare archetypes. The matrix is the article's spine
    # (rendered as a table near the article start) and the writer uses it
    # to ensure equal-depth treatment per entity.
    em = plan.get("entity_matrix")
    if archetype in {"list-all", "compare"}:
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
        # Only emit count shortfalls when the matrix was actually present —
        # the "missing" shortfall already captures the entire failure mode
        # when the LLM omitted the field. (Upper-bound count shortfalls
        # remain gated the same way: if the matrix was missing we backfilled
        # to {entities: [], dimensions: []} which can't trip the >MAX path.)
        if not matrix_was_missing:
            if len(ents) < _ENTITY_MATRIX_ENTITIES_MIN:
                audit["shortfalls"].append(f"entity_matrix.entities={len(ents)}<{_ENTITY_MATRIX_ENTITIES_MIN}")
            if len(ents) > _ENTITY_MATRIX_ENTITIES_MAX:
                audit["shortfalls"].append(f"entity_matrix.entities={len(ents)}>{_ENTITY_MATRIX_ENTITIES_MAX}")
            if len(dims) < _ENTITY_MATRIX_DIMENSIONS_MIN:
                audit["shortfalls"].append(f"entity_matrix.dimensions={len(dims)}<{_ENTITY_MATRIX_DIMENSIONS_MIN}")
            if len(dims) > _ENTITY_MATRIX_DIMENSIONS_MAX:
                audit["shortfalls"].append(f"entity_matrix.dimensions={len(dims)}>{_ENTITY_MATRIX_DIMENSIONS_MAX}")

    # P3-W6 (2026-05-27): stakeholder_chapter audit. Unlike other Phase 3
    # artifacts, this one is OPTIONAL — only populated when the prompt
    # signals a plural audience. The architect chooses to populate it
    # based on the prompt; we audit COUNT bounds when present but never
    # flag missing-chapter as a shortfall (avoids forcing single-audience
    # prompts to have a useless 3-stakeholder section).
    sc = plan.get("stakeholder_chapter")
    if isinstance(sc, dict):
        stakeholders = sc.get("stakeholders") if isinstance(sc.get("stakeholders"), list) else []
        # Normalize to a clean list.
        sc["stakeholders"] = [s for s in stakeholders if isinstance(s, dict) and s.get("id")]
        audit["stakeholder_chapter_count"] = len(sc["stakeholders"])
        if sc["stakeholders"]:
            if len(sc["stakeholders"]) < _STAKEHOLDER_COUNT_MIN:
                audit["shortfalls"].append(
                    f"stakeholder_chapter.count={len(sc['stakeholders'])}<{_STAKEHOLDER_COUNT_MIN}"
                )
            if len(sc["stakeholders"]) > _STAKEHOLDER_COUNT_MAX:
                audit["shortfalls"].append(
                    f"stakeholder_chapter.count={len(sc['stakeholders'])}>{_STAKEHOLDER_COUNT_MAX}"
                )

    plan["_outline_audit"] = audit
