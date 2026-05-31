"""Full P1 pipeline wiring + per-section quality loop (updated for the
architecture-update directive — 4 new graph nodes + typed state).

Pipeline (LINK-Researcher-style, adapted; from `p1-architecture-update`):
  intent -> archetype -> role_play -> scout -> criteria_spec
  -> architect -> design_guide -> init_format
  -> orchestrator (5 specialists, isolated ctx, budget 24)
  -> writer.opening + per-section quality loop (grounding -> inner_loop)
  -> assemble -> refiner -> validation (cap 2 corrective refiner passes)
  -> [zh: zh_writer_pass]

State is a single PipelineState dataclass threaded through every node;
each phase emits cost-by-node ledger markers via `_phase(name, fn)` so we get
a free per-node cost breakdown at every milestone (item 36).
"""

import bisect
import json
import os
import pathlib
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# Inner-loop drift logging (separate from adapter task-output; purely additive)
_DRIFT_PATH = pathlib.Path(__file__).resolve().parent.parent / "p1_artifacts" / "inner_loop_drift.jsonl"
_DRIFT_LOCK = threading.Lock()


def _persist_drift(s, language: str, query: str) -> None:
    """Best-effort inner-loop drift logger. ALL exceptions swallowed —
    failure to log MUST NOT affect task outcome."""
    try:
        # Wave 1 §7.2 (2026-05-26): derive `inline_def_ratio` from
        # footnote_normalize_stats so analysers can spot the "writer is
        # making a fresh marker per cite, no reuse" failure mode without
        # recomputing the ratio every time downstream. Qianfan's ~7×
        # reuse pattern gives ratio ≈ 7; a degenerate 1:1 marker:def run
        # gives ratio ≈ 1 (= zero reuse).
        fn_stats = dict(getattr(s, "footnote_normalize_stats", {}) or {})
        n_inline = int(fn_stats.get("n_inline_markers", 0))
        n_defs = int(fn_stats.get("n_definitions", 0))
        fn_stats["inline_def_ratio"] = round(n_inline / n_defs, 3) if n_defs > 0 else None

        rec = {
            "task_fp": query[:120],  # fingerprint for cross-ref with query.jsonl
            "language": language,
            "archetype": (s.archetype or {}).get("archetype", ""),
            "domain": s.domain,
            "n_sections": len(s.section_scores or []),
            "section_scores": s.section_scores or [],
            "failing_rationales_count": len(s.failing_rationales or []),
            "refiner_passes": s.refiner_passes,
            "validation_log": s.validation_log or [],
            "article_chars": len(s.article or ""),
            "article_words": len((s.article or "").split()),
            "tool_calls": s.tool_calls,
            # Wave 1 §7.1: surface the orchestrator's per-task specialist-
            # timeout count so dev4 / W13 analysers can correlate timeout
            # pressure with quality drift. 0 = clean; > 0 = some
            # specialist hit _SPECIALIST_TIMEOUT_S and the orchestrator
            # fell back to partial content.
            "n_specialist_timeouts": int(getattr(s, "n_specialist_timeouts", 0) or 0),
            "numbering_fix": getattr(s, "numbering_fix_stats", {}),
            "refiner_gate": getattr(s, "refiner_gate_verdict", {}),
            "evidence_dedup": getattr(s, "evidence_dedup_stats", {}),
            "capel": getattr(s, "capel_stats", {}),
            "g_dedup_suppressed": getattr(s, "g_dedup_suppressed", False),
            # Greptile PR #24 follow-up (2026-05-25): forward
            # footnote_normalize_stats into the drift record alongside its
            # peer post-processor stats so per-run footnote volume
            # (n_definitions, n_inline_markers, n_orphans_stripped, etc.)
            # is visible in inner_loop_drift.jsonl when analysing dev4
            # output. Without this the stats lived only on PipelineState
            # and never reached the dev-run telemetry. Wave 1 §7.2 added
            # the derived `inline_def_ratio` field above.
            "footnote_normalize": fn_stats,
            # P3-W0a (2026-05-27): forward the architect's _outline_audit
            # (which now includes query_type_counts / query_type_fractions /
            # query_type_shortfalls in addition to the pre-existing structural
            # bound counts) into drift telemetry so dev4 / W13 analysers can
            # correlate query-type distribution with downstream specialist
            # evidence quality. The audit dict is small (a few hundred bytes
            # per task), and routing the whole thing through here means
            # future Phase 3 PRs that add architect-side audit fields (e.g.
            # P3-W1 micro-template instantiation_mode, P3-W2 framing-chapter
            # vocabulary count) inherit drift telemetry for free.
            "architect_audit": (getattr(s, "plan", {}) or {}).get("_outline_audit", {}),
            # P3-W4 (2026-05-27): mermaid post-pass stats. Tracks
            # per-task block emission + per-failure-mode repair counts
            # so analysers can monitor (a) writer's mermaid emission rate
            # under the _MERMAID_DIRECTIVE and (b) which of the 4 failure
            # modes the writer most often hits.
            "mermaid_validate": dict(getattr(s, "mermaid_validate_stats", {}) or {}),
            "cjk_despace": dict(getattr(s, "cjk_despace_stats", {}) or {}),
            # round 5 T1-PR1: leaked open CAPEL countdown markers removed from
            # the shipped article. Non-zero = the writer leaked a marker past
            # the per-section _capel_strip and this safety net caught it.
            "scaffold_strip": dict(getattr(s, "scaffold_strip_stats", {}) or {}),
            "completion": dict(getattr(s, "completion_stats", {}) or {}),
            # round 5 T1-PR2: final-section re-roll + deterministic-trim gate.
            # Non-empty/True = a final section ended mid-sentence and the gate
            # re-rolled and/or trimmed to guarantee a clean ending.
            "completion_repair": dict(getattr(s, "completion_repair_stats", {}) or {}),
            # round 5 T1-PR3: runaway-block clamp. blocks_clamped>0 = a chapter
            # ran away flat (didn't nest) and the safety net truncated it.
            "runaway_clamp": dict(getattr(s, "runaway_clamp_stats", {}) or {}),
            # 2026-05-29: advisory final-article metrics (heading profile,
            # frontload_ratio, spaced-CJK + scaffolding RESIDUAL, paragraph
            # density) — distance-from-Qianfan structural signals + round-2 fix
            # verification on the shipped article. See pipeline/article_metrics.py.
            "final_article_metrics": dict(getattr(s, "final_article_metrics", {}) or {}),
            # P3-W3.b (2026-05-27): xref_repair safety-net post-pass
            # stats {templates_repaired, dangling_refs_excised,
            # sentences_deleted}. The writer's in-prompt
            # _MID_PARAGRAPH_XREF_RULE is the primary force producing
            # clean cross-refs; non-zero stats here quantify how often
            # the safety net actually fires. All-zero stats across a
            # dev4 batch = writer directive is doing the work; > 0 =
            # writer occasionally regresses to "Building on §X"
            # templates or hallucinates dangling forward-refs.
            "xref_repair": dict(getattr(s, "xref_repair_stats", {}) or {}),
            # P3b-opt2 (2026-05-28): deterministic style-clamp stats so dev4 /
            # W13 analysers can confirm the rendered citation + em-dash rates
            # land in the Qianfan-corpus bands (and flag `floor_exceeded`,
            # which means a section cited so densely the clamp couldn't reach
            # the band without un-citing claims — it never does).
            "clamp_citations": dict(getattr(s, "clamp_citations_stats", {}) or {}),
            "clamp_emdash": dict(getattr(s, "clamp_emdash_stats", {}) or {}),
            # P3b-OPT2 (2026-05-27): per-section inner-loop trajectory so
            # scripts/inner_cap_ab_analysis.py can measure whether the 2nd/3rd
            # corrective pass (only reachable at INNER_CAP=3) earns its cost.
            "inner_loop_trajectory": list(getattr(s, "inner_loop_trajectory", []) or []),
        }
        _DRIFT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _DRIFT_LOCK, _DRIFT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — never break the caller
        pass


from . import archetype as _arch
from . import text_metrics
from ._env import assert_phase, log_usage
from .pipeline import (
    architect,
    article_metrics,
    cjk_despace,
    criteria_spec,
    design_guide,
    evidence_dedup,
    footnote_normalize,
    grounding,
    init_format,
    inner_loop,
    intent,
    mermaid_validate,
    numbering_fix,
    orchestrator,
    refiner,
    refiner_gate,
    role_play,
    scaffold_strip,
    scout,
    style_clamp,
    validation,
    writer,
    xref_repair,
    zh_writer_pass,
)
from .retrieval import domain_routed
from .state import PipelineState

# P3b-opt2 (2026-05-28): default 3→2. The id=91 graded smoke's trajectory
# telemetry (scripts/inner_cap_ab_analysis.py) proved the 3rd corrective pass
# is wasteful — 49/51 sections reached it, 0 flipped to passing, mean min_score
# gain 0.029. The 1st corrective pass (iter 0→1) still helps (+0.57 mean), so
# cap=2 keeps the useful pass and drops the wasteful one. DR_INNER_CAP env
# override preserved. Re-confirm across the full graded dev4 before W13.
INNER_CAP = int(os.environ.get("DR_INNER_CAP", "2"))
VALIDATION_CAP = 3  # loop limit; allows the documented max of 2 corrective
# refiner passes (item 35). refiner_passes starts at 1 after the initial
# refiner. The while loop iterates while refiner_passes <= VALIDATION_CAP,
# and the corrective branch fires while refiner_passes < VALIDATION_CAP
# (so cap=3 → corrective runs at rp=1 and rp=2, then logs+returns at rp=3).


def _phase(name: str, fn, *args, **kwargs):
    """Run an existing-module phase with node-boundary cost markers (item 36)."""
    t0 = time.time()
    log_usage(f"node:{name}", {}, note=f"node:{name} enter")
    try:
        return fn(*args, **kwargs)
    finally:
        log_usage(f"node:{name}", {}, note=f"node:{name} exit dur={round(time.time() - t0, 2)}s")


# ---- Phase 1: planning spine (existing + role_play insertion) ----
def plan_only(query: str, language: str, task_id: int | None = None) -> dict:
    assert_phase()
    arche = _phase("archetype", _arch.classify, query)
    domain = _phase("domain", domain_routed.classify_domain, query)
    intents = _phase("intent", intent.extract, query, language)
    persona = _phase(
        "role_play",
        role_play.run,
        role_play.RolePlayInput(query=query, language=language, archetype=arche["archetype"], domain=domain),
    ).persona
    land = _phase("scout", scout.run, query, language, "auto")
    spec = _phase("criteria_spec", criteria_spec.regenerate, query, language)
    cov = criteria_spec.as_coverage_obligations(spec)
    plan = _phase(
        "architect", _build_plan_with_persona, query, language, arche["archetype"], intents, land, cov, persona, task_id
    )
    return {
        "archetype": arche,
        "domain": domain,
        "intents": intents,
        "persona": persona,
        "landscape": land,
        "spec": spec,
        "plan": plan,
    }


def _build_plan_with_persona(query, language, archetype, intents, land, cov, persona, task_id=None):
    """Architect call with the role_play persona prepended (item 32 wiring)."""
    plan = architect.build(query, language, archetype, intents, land, cov, task_id=task_id)
    plan["_persona"] = persona  # carry forward for downstream nodes
    return plan


# ---- Phase 2: full pipeline (W2-W5 + new nodes) ----
def pipeline(query: str, language: str, task_id: int | None = None) -> str:
    return from_plan(plan_only(query, language, task_id=task_id), query, language, task_id=task_id)


def from_plan(ctx: dict, query: str, language: str, task_id: int | None = None) -> str:
    s = _state_from_ctx(ctx, query, language)
    s.task_id = task_id

    # New nodes: design_guide → init_format (after architect, before writer)
    s.design_guide = _phase(
        "design_guide",
        design_guide.run,
        design_guide.DesignGuideInput(
            query=query,
            language=language,
            archetype=s.archetype["archetype"],
            domain=s.domain,
            persona=s.persona,
            plan=s.plan,
        ),
    ).guide
    s.scaffold = _phase(
        "init_format", init_format.run, init_format.InitFormatInput(plan=s.plan, language=language, domain=s.domain)
    ).scaffold

    # Research dispatch (W2)
    res = _phase("orchestrator", orchestrator.run, s.plan, query, language, s.archetype["archetype"], s.domain)
    s.memory_bank = res["memory_bank"]
    s.digest = res["digest"]
    s.tool_calls = res["tool_calls"]
    # Wave 1 §7.1 (2026-05-26): capture specialist-timeout telemetry so it
    # flows into _persist_drift below. Fail-soft: pre-PR-26 orchestrator
    # outputs won't have this key, so default to 0 rather than KeyError.
    s.n_specialist_timeouts = int(res.get("n_specialist_timeouts", 0))

    # P2-Wave-1-D: evidence-layer dedup. Hardcoded default `url+embedding`
    # post-validation (Wave-1 D sanity-4 passed 2026-05-23: paired ΔO +0.046 vs
    # W9, +0.012 vs B0; dedup firing 20-40% of evidence per task with no
    # gate-verify regressions). DR_EVIDENCE_DEDUP env-var override is kept as
    # an operational kill-switch (set to "off" or "url" for debug / fall-back
    # if embeddings API misbehaves) — D1 is also fail-soft internally.
    _dedup_mode = os.environ.get("DR_EVIDENCE_DEDUP", "url+embedding")
    s.evidence_dedup_stats = _phase("evidence_dedup", evidence_dedup.dedup_bank, s.memory_bank, mode=_dedup_mode)

    # Writer opening + per-section quality loop (W3 + W5)
    s.opening = _phase(
        "writer_opening",
        writer.write_opening,
        s.plan,
        query,
        language,
        s.archetype["archetype"],
        s.domain,
        s.digest,
        task_id=s.task_id,
    )
    s.sections, s.section_scores, s.failing_rationales = _phase(
        "writer_sections_loop", _run_section_loop, s, query, language
    )

    # round 5 T1-PR2 layer 1: re-roll a final section that ends mid-sentence
    # BEFORE assembly, so the regenerated synthesis flows through refiner /
    # post-passes like any section (layer 2 deterministic trim is the guarantee).
    _repair_final_section(s, query, language)

    draft = writer.assemble(s.opening, s.sections)
    draft = refiner.strip_meta(draft)

    # PRE-refiner snapshot for ART-style gate (plan v3 §3b, Branch B monitor)
    pre_refiner_draft = draft

    # Refiner (W4) — feeds design_guide as system context now
    refined = _phase(
        "refiner",
        _refine_with_guide,
        draft,
        s.archetype["archetype"],
        language,
        s.section_scores,
        s.failing_rationales,
        s.design_guide,
    )
    s.article = refined["article"]
    s.refiner_passes = 1

    # ART-style refiner gate (monitor-mode in P1): compare pre vs post and
    # log the would-be decision. Cost ~$0.05/task. Result captured in
    # cost_tracking/ledger.jsonl for post-hoc audit.
    gate_mode = os.environ.get("DR_REFINER_GATE", "monitor")
    if gate_mode != "off":
        verdict = _phase(
            "refiner_gate",
            refiner_gate.compare,
            pre_refiner_draft,
            s.article,
            language=language,
            archetype=s.archetype.get("archetype", ""),
            task_fp=query[:120],
            mode=gate_mode,
        )
        s.refiner_gate_verdict = verdict
        # In active mode, the gate may revert; in monitor mode, decision is
        # always "keep_post" by construction
        if verdict.get("decision") == "revert_to_pre":
            s.article = pre_refiner_draft

    # NEW: validation gate with cap-2 corrective refiner passes (item 35)
    s = _validation_loop(s, language)

    # round 5 T1-PR3: deterministic runaway-block clamp (safety net for a flat
    # chapter the budget didn't prevent). Runs early so footnote_normalize /
    # numbering_fix see the clamped article.
    clamped_r, cr_stats = _phase("runaway_clamp", _clamp_runaway_blocks, s.article)
    s.article = clamped_r
    s.runaway_clamp_stats = cr_stats

    # ZH writer-pass (item 27)
    if language == "zh":
        zp = _phase("zh_writer_pass", zh_writer_pass.zh_pass, s.article, query)
        s.article = zp["article"]

    # P3-W3.b (2026-05-27): xref_repair safety-net post-pass. The
    # writer's in-prompt `_MID_PARAGRAPH_XREF_RULE` (writing_rules.py) is
    # the primary force producing clean mid-paragraph cross-references;
    # this post-pass repairs the residual two failure modes the
    # directive can't fully suppress: (1) chapter-opening "Building on
    # §X established in §Y" templates that occasionally leak through
    # despite the §12.A.v4 amendment, and (2) dangling forward-refs
    # (§N where N isn't in the article's heading set). Placed BEFORE
    # mermaid_validate so any sentence deletions that happen here don't
    # leave orphan mermaid fence tokens for the next pass to mishandle;
    # placed BEFORE footnote_normalize so any `[^N]` markers inside a
    # deleted sentence are pulled out of the article before global
    # renumbering, preventing phantom def-line slots in References.
    repaired_x, xr_stats = _phase("xref_repair", xref_repair.repair, s.article)
    s.article = repaired_x
    s.xref_repair_stats = xr_stats

    # P3-W4 (2026-05-27): mermaid post-pass repair. The writer's
    # `_MERMAID_DIRECTIVE` (writing_rules.py) opts the model into emitting
    # semantic diagrams on every section call; this runs the syntactic
    # validator over the assembled article. Placed BEFORE footnote_normalize
    # so any `[^N]` markers the writer accidentally embedded inside a
    # mermaid node label are stripped before the global renumber pass —
    # otherwise footnote_normalize would mis-count them as inline cites
    # and assign global numbers to nonexistent diagram-internal references.
    repaired, mv_stats = _phase("mermaid_validate", mermaid_validate.repair, s.article)
    s.article = repaired
    s.mermaid_validate_stats = mv_stats

    # P3b-opt2 (2026-05-28): deterministic style clamps. Run AFTER
    # mermaid_validate (so any markers in node labels are already gone) and
    # BEFORE footnote_normalize (markers are still per-section `[^Sx-N]` with
    # inline defs, so a marker the clamp removes leaves an unused def that
    # footnote_normalize auto-drops — no orphan/dangling refs). The writer
    # ignores density directives; these ENFORCE the Qianfan-corpus bands.
    clamped_c, cc_stats = _phase("clamp_citations", style_clamp.clamp_citations, s.article, language=language)
    s.article = clamped_c
    s.clamp_citations_stats = cc_stats
    clamped_e, ce_stats = _phase("clamp_emdash", style_clamp.clamp_emdash, s.article, language=language)
    s.article = clamped_e
    s.clamp_emdash_stats = ce_stats
    # round 4 W4: deterministic paragraph-density clamp. The dev8 judge's #1
    # readability complaint was "wall of text / suffocating equal-intensity
    # density"; the L6/L8 PROMPT rules were already active and didn't move it.
    # Splits overlong prose paragraphs at existing sentence boundaries (zero
    # grammar/content risk — protects code/tables/headings/refs, skips lists).
    # Env-gated via DR_PARA_CLAMP=off as a kill-switch.
    if os.environ.get("DR_PARA_CLAMP", "on") != "off":
        clamped_p, cp_stats = _phase("clamp_paragraphs", style_clamp.clamp_paragraphs, s.article, language=language)
        s.article = clamped_p
        s.clamp_paragraphs_stats = cp_stats

    # P2-Option-A-#6 (2026-05-23): footnote_normalize runs BEFORE
    # numbering_fix so the renumber step sees the final article shape
    # (including the appended `## References` block) when it assigns
    # H2 numbers. Merges per-section `[^section_id-N]` footnote tokens
    # into one global `[^1], [^2], ...` block at article end.
    fno = _phase("footnote_normalize", footnote_normalize.normalize, s.article)
    s.article = fno.article
    s.footnote_normalize_stats = {
        "n_definitions": fno.n_definitions,
        "n_inline_markers": fno.n_inline_markers,
        "n_orphans_stripped": fno.n_orphans_stripped,
        "n_unused_dropped": fno.n_unused_dropped,
        "n_renumbered": fno.n_renumbered,
        # Wave 1 §2.1a (2026-05-26): writer-emitted ## References sections
        # the pre-strip pass removed before normalize processing.
        "n_writer_refs_sections_stripped": fno.n_writer_refs_sections_stripped,
    }

    # Deterministic post-edit (plan v3 §2a+2d+2c-validator): stop-list regex,
    # empty-section collapse, heading-tree renumber. NO LLM call. Closes the
    # bottom-10 cross-cutting judge complaints (inconsistent numbering, stage
    # directions, methodology meta-commentary leak).
    # Flatten cap = H3 for ALL archetypes (Qianfan's universal h4=0). round 5
    # T2-PR4: list-all changed 2→3. The old `2` was for the FLAT list-all shape
    # (entities as top sections, no nesting); now list-all GROUPS entities into
    # ~9 chapters and NESTS them as subsections/seeds, which render at H2/H3
    # after Wave-B promotion (Qianfan id=23 has 102 H3). A cap of 2 would
    # collapse that nested enumeration back to flat H2, defeating the fix.
    nfo = _phase("numbering_fix", numbering_fix.run, s.article, flatten_max_depth=3)
    s.article = nfo.article
    s.numbering_fix_stats = {
        "strips": nfo.stage_directions_removed,
        "collapsed": nfo.sections_collapsed,
        "renumbered": nfo.headings_renumbered,
        "flattened": nfo.headings_flattened,
        "promoted": nfo.headings_promoted,
        "promotion_skipped": nfo.promotion_skipped,
        "demoted": nfo.headings_demoted,
        "hash_normalized": nfo.headings_hash_normalized,
        "xref_rewritten": nfo.cross_refs_rewritten,
        "xref_orphaned": nfo.cross_refs_orphaned,
        "cap_violations": nfo.cap_violations,
        "skipped_reason": nfo.skipped_reason,
    }

    # round 5 T1-PR1 (2026-05-31): residual-scaffolding strip. Runs AFTER
    # numbering_fix (so it sees the final renumbered prose, incl. any marker
    # left at a truncation seam) and BEFORE cjk_despace. Removes leaked open
    # CAPEL countdown markers (`<dddd` at a line end with no closing `>`, which
    # _capel_strip misses) the judge reads as raw scaffolding. Span-masked +
    # idempotent; the writer-side capel_directive is the primary defense.
    stripped_sc, sc_stats = _phase("scaffold_strip", scaffold_strip.strip_residual_scaffolding, s.article)
    s.article = stripped_sc
    s.scaffold_strip_stats = sc_stats

    # G7 (2026-05-28): ZH-aware de-spacing. Runs LAST (after numbering_fix /
    # footnote_normalize) on the final article so it only sees shipped prose;
    # it masks link/anchor/footnote/code spans before collapsing CAPEL-induced
    # CJK↔CJK spaces, so it cannot touch headings, numbers, or citation tokens.
    despaced, dc_stats = _phase("cjk_despace", cjk_despace.despace, s.article, language=language)
    s.article = despaced
    s.cjk_despace_stats = dc_stats

    # round 5 T1-PR2 layer 2: deterministic completion guarantee. After EVERY
    # post-pass, ensure the shipped body never ends mid-sentence (trim the
    # incomplete tail if the re-roll didn't converge / a pass re-truncated).
    s.article = _guarantee_complete_ending(s)

    # Advisory final-article metrics on the SHIPPED article (after every
    # post-pass). Pure read — no gating, no mutation — so it cannot confound the
    # dev6 A/B. Fail-soft: a metrics error must never break a completed run.
    try:
        s.final_article_metrics = article_metrics.compute(s.article, language=language)
    except Exception:  # noqa: BLE001
        s.final_article_metrics = {}

    # Drift instrumentation — captured AFTER all post-edits so the artifact
    # reflects the actually-shipped article.
    _persist_drift(s, language, query)

    return s.article


# ---- helpers ----
def _state_from_ctx(ctx, query, language):
    s = PipelineState(query=query, language=language)
    s.archetype = ctx.get("archetype", {}) or {}
    s.domain = ctx.get("domain", "default")
    s.intents = ctx.get("intents", []) or []
    s.persona = ctx.get("persona", "") or (ctx.get("plan", {}) or {}).get("_persona", "")
    s.landscape = ctx.get("landscape", {}) or {}
    s.spec = ctx.get("spec", {}) or {}
    s.plan = ctx.get("plan", {}) or {}
    return s


# L1 (2026-05-29): chapter-completion gate. The inner loop accepts a section on
# grounding + quality SCORE but never on COMPLETENESS, so a thin-but-coherent
# section passes — the "hollow late chapter" failure the Qianfan head-to-head
# flagged (id38 §5 = 185 chars vs a multi-thousand-token target; id44 forecast
# chapter = logic skeleton). We gate acceptance on a minimum content ratio vs
# the section's own declared length target and, when too thin, retry with an
# explicit expand directive (bounded by INNER_CAP). A section still thin after
# retries is surfaced in completion telemetry — a signal of an upstream coverage
# gap (which the enumerate-and-expand / deliverable-mapping levers address).
_COMPLETION_MIN_RATIO = 0.5  # below the 0.7x stated target — only SEVERE shortfalls fire
# PR-A (2026-05-29): a draft that ends mid-sentence AND is severely thin is an
# infra CUT (stream-drop / truncated response), not a quality shortfall — the
# dev6 hollow sections were 36-57-token mid-sentence stubs with full evidence,
# correlated with `RemoteProtocolError` stream-drops under 6×6 contention, that
# the client accepted because the text was non-empty. Re-roll such a draft FRESH
# (no feedback) before the grounding/score loop, bounded by this cap, so a cut
# generation never reaches acceptance. The quality (expand/grounding) loop then
# handles genuine under-production (thin BUT sentence-complete) as before.
_TRUNC_RETRY_CAP_DEFAULT = 2
_TRUNC_RETRY_CAP_MIN = 0  # 0 = explicit kill-switch (re-rolls disabled)
_TRUNC_RETRY_CAP_MAX = 5  # bound cost: each re-roll is a full section regeneration


def _trunc_retry_cap_from_env() -> int:
    """Resolve the cut-generation re-roll cap from DR_TRUNC_RETRY_CAP.

    Mirrors `_specialist_timeout_from_env()` (pipeline/orchestrator.py): fail
    loud with a clear message on a non-integer value rather than letting a bare
    ``int()`` raise a cryptic ValueError at module-import time (which would crash
    the whole orchestrate module), and guard the range so a negative value
    (silently disables re-rolls from the first ``trunc_retries < cap`` check) or
    an absurdly large one (e.g. 50 — up to 50 full-section regenerations per
    section under persistent stream-drops, exactly the high-contention case this
    feature addresses) can't slip through. 0 is allowed as an explicit
    kill-switch; the [0, 5] band still admits modest bumps above the default."""
    raw = os.environ.get("DR_TRUNC_RETRY_CAP")
    if raw is None:
        return _TRUNC_RETRY_CAP_DEFAULT
    try:
        val = int(raw)
    except ValueError:
        raise ValueError(f"DR_TRUNC_RETRY_CAP must be a non-negative integer; got {raw!r}") from None
    if not (_TRUNC_RETRY_CAP_MIN <= val <= _TRUNC_RETRY_CAP_MAX):
        raise ValueError(f"DR_TRUNC_RETRY_CAP out of range [{_TRUNC_RETRY_CAP_MIN}, {_TRUNC_RETRY_CAP_MAX}]: {val}")
    return val


_TRUNC_RETRY_CAP = _trunc_retry_cap_from_env()


def _approx_tokens(text: str) -> int:
    """Rough token estimate robust across ZH/EN, body only (heading lines
    stripped). Delegates the CJK-aware count to the shared `text_metrics`
    estimator (audit E2) so this chapter-completion gate and validation's
    length gate use one formula instead of disagreeing ~2.5× on CJK."""
    if not text:
        return 0
    body = "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("#"))
    return text_metrics.approx_tokens(body)


def _section_too_thin(text: str, expected_tok: int) -> bool:
    if not expected_tok or expected_tok <= 0:
        return False
    return _approx_tokens(text) < _COMPLETION_MIN_RATIO * expected_tok


# True sentence-ENDING punctuation only (EN + CJK), no closing brackets/quotes.
_SENT_ENDERS = "。！？.!?…"
# Closing brackets/quotes that may legitimately TRAIL a sentence-ender (`."`,
# `.)`, `。」`). A complete prose tail may end on one of these, but on its own a
# bare closer is NOT a sentence boundary.
_SENT_CLOSERS = "）)】」』》”’\"'"
# Sentence-terminal punctuation a complete prose tail may legitimately end on —
# enders OR a trailing closer. Used by `_ends_mid_sentence` to decide whether a
# tail looks complete. `_trim_to_last_sentence` deliberately scans for an ENDER
# (not this full set) so it never cuts at a bare inline closing paren/quote.
_SENT_TERMINALS = _SENT_ENDERS + _SENT_CLOSERS


def _ends_mid_sentence(text: str) -> bool:
    """Advisory: True if the section's prose tail looks truncated mid-sentence —
    an unclosed code fence, or a final prose line ending without sentence-terminal
    punctuation. Distinguishes a TOKEN-CEILING cutoff (raise max_tokens) from a
    short-but-complete section (research starvation → L1b). Structural tails
    (table rows, list items, headings) legitimately lack terminal punctuation
    and are NOT flagged."""
    if not text or not text.strip():
        return False
    if text.count("```") % 2 == 1:  # odd fence count ⇒ truncated inside a block
        return True
    last = text.rstrip()
    tail = last.splitlines()[-1].strip()
    # Structural tails legitimately lack terminal punctuation: table rows,
    # headings, unordered bullets (-, *, +, >) — and ordered list items
    # ("3. point" / "3) point"), which _prose_paragraphs also excludes.
    if not tail or tail[0] in "|#-*+>" or tail.endswith("|"):
        return False
    if re.match(r"^\d+[.)]\s", tail):
        return False
    return last[-1] not in _SENT_TERMINALS


def _is_cut_generation(text: str, expected_tok: int) -> bool:
    """True if a draft looks like a CUT generation (stream-drop / truncated
    response) rather than a quality shortfall: it ends mid-sentence AND is
    severely below its declared target. Such a draft can't be fixed by the
    grounding/expand loop (there's nothing to ground/expand) — re-roll it fresh.
    A thin-but-sentence-complete draft is genuine under-production and is left
    for the expand path."""
    return _ends_mid_sentence(text) and _section_too_thin(text, expected_tok)


def _expand_feedback(expected_tok: int) -> str:
    return (
        f"COMPLETENESS — this section is far below its declared depth target "
        f"(~{expected_tok} tokens). Fully develop EVERY sub-topic the section's "
        f"plan declares; do NOT emit a skeleton/intro-only stub or defer content "
        f"to other sections. Expand with concrete, evidence-bearing detail."
    )


# round 5 T1-PR2 (2026-05-31): article-completion gate. The per-section CUT
# re-roll (_is_cut_generation) only fires on mid-sentence AND thin; a final
# section that ends mid-sentence but is NOT thin (a long section truncated at
# the writer.sec ceiling, or after a runaway starved the budget) ships the WHOLE
# ARTICLE ending mid-sentence — the id=89 "unfinished sentences" the judge
# scored grammar 4.0. Two layers: (1) re-roll just the final section
# (content-preserving — flows through refiner/post-passes, protects the
# Comprehensiveness/Insight we win); (2) a deterministic last-resort trim so the
# SHIPPED body never ends mid-sentence (the readability guarantee, even if the
# re-roll didn't converge or a later pass re-truncated).
_COMPLETION_REPAIR_CAP_DEFAULT = 1
_COMPLETION_REPAIR_CAP_MIN = 0  # 0 = disable re-roll (deterministic trim still guarantees a clean tail)
_COMPLETION_REPAIR_CAP_MAX = 3


def _completion_repair_cap_from_env() -> int:
    """Resolve the final-section re-roll cap from DR_COMPLETION_REPAIR_CAP.

    Mirrors `_trunc_retry_cap_from_env`: fail loud on a non-integer / out-of-range
    value at import rather than a cryptic crash mid-run."""
    raw = os.environ.get("DR_COMPLETION_REPAIR_CAP")
    if raw is None:
        return _COMPLETION_REPAIR_CAP_DEFAULT
    try:
        val = int(raw)
    except ValueError:
        raise ValueError(f"DR_COMPLETION_REPAIR_CAP must be a non-negative integer; got {raw!r}") from None
    if not (_COMPLETION_REPAIR_CAP_MIN <= val <= _COMPLETION_REPAIR_CAP_MAX):
        raise ValueError(
            f"DR_COMPLETION_REPAIR_CAP out of range [{_COMPLETION_REPAIR_CAP_MIN}, {_COMPLETION_REPAIR_CAP_MAX}]: {val}"
        )
    return val


_COMPLETION_REPAIR_CAP = _completion_repair_cap_from_env()

# References block: footnote_normalize appends `## References`; numbering_fix may
# renumber it to `## N References` and Wave-B promotion may lift it to `# References`.
# Anchored to end-of-heading-line so a body heading like "## References to prior
# work" is NOT mistaken for the bibliography (prefix-collision guard).
_REFS_HEADING_RE = re.compile(r"(?m)^[ \t]*#{1,3}[ \t]+\d*\.?[ \t]*References?[ \t]*$")


def _trim_to_last_sentence(body: str) -> str | None:
    """Trim a mid-sentence body tail back to its last complete sentence.

    Operates on the FINAL paragraph only: cut after its last sentence-ENDER
    (`_SENT_ENDERS`, keeping any closing bracket/quote that trails it so `."` /
    `.)` survive intact), or — if that paragraph has no complete sentence at all
    — drop the whole fragment paragraph. Scanning for an ender (not the full
    `_SENT_TERMINALS` set) means an inline `"…(Smith 2023) continues the"` tail
    is dropped wholesale rather than cut at the bare paren into a fragment.

    Fence-aware in two ways: (1) an unclosed ``` fence (odd count) means a code
    block was truncated mid-stream — sentence scanning can never close it, and
    the lone opening fence breaks Markdown — so the partial block (from its
    opening fence onward) is dropped first. (2) Even with balanced fences, a
    sentence-ender can sit INSIDE a properly-closed block (e.g. the `.` in
    `{"version": 2.0}`); cutting there would keep the opening fence but drop its
    close. The cut is therefore accepted only when the candidate slice has an
    EVEN ``` count, else the scan continues to an earlier (out-of-block) ender.

    Returns the trimmed body, or None if nothing safe remains (no complete
    sentence anywhere)."""
    stripped = body.rstrip()
    if stripped.count("```") % 2 == 1:
        stripped = stripped[: stripped.rfind("```")].rstrip()
    para_start = stripped.rfind("\n\n")
    head = stripped[: para_start + 2] if para_start >= 0 else ""
    para = stripped[para_start + 2 :] if para_start >= 0 else stripped
    # Fence parity of the candidate slice = head_fences + (complete ``` fences
    # within para[:i+1]). `fence_ends[k]` is the last-char index of the k-th
    # fence in para, so bisect_right(fence_ends, i) counts fences fully closed
    # at or before i — O(log n) per ender instead of recounting the slice.
    head_fences = head.count("```")
    fence_ends = [m.end() - 1 for m in re.finditer("```", para)]
    cut = -1
    for i in range(len(para) - 1, -1, -1):
        if para[i] not in _SENT_ENDERS:
            continue
        if (head_fences + bisect.bisect_right(fence_ends, i)) % 2 == 1:
            continue  # ender sits inside a code block -> slice would be unbalanced
        cut = i
        # Keep any closing bracket/quote that belongs to this sentence
        # (`."`, `.)`, `。」`) so a legitimate closer isn't stripped.
        while cut + 1 < len(para) and para[cut + 1] in _SENT_CLOSERS:
            cut += 1
        break
    if cut >= 0:
        return (head + para[: cut + 1]).rstrip()
    if head.strip():
        return head.rstrip()
    return None


def _repair_final_section(s: PipelineState, query, language) -> None:
    """Layer 1 — content-preserving re-roll. If the FINAL section ends
    mid-sentence (so the whole article body would), re-roll JUST that section
    (bounded) so the regenerated synthesis flows through refiner/post-passes.
    Best-effort: never raises (DRB needs an article per task). Mutates
    s.sections + s.completion_repair_stats."""
    sections = list(s.sections or [])
    stats = {"final_mid_sentence": False, "reroll_attempts": 0, "reroll_fixed": False, "trimmed": False}
    s.completion_repair_stats = stats
    if not sections or not _ends_mid_sentence(sections[-1]):
        return
    stats["final_mid_sentence"] = True
    if _COMPLETION_REPAIR_CAP <= 0:
        return
    units = writer.outline_units(s.plan)
    if not units or len(units) != len(sections):
        return  # can't safely map units→sections; the trim guarantee still fires later
    archetype = s.archetype.get("archetype", "") if isinstance(s.archetype, dict) else ""
    prior_titles = [u["title"] for u in units]
    best = sections[-1]
    for _ in range(_COMPLETION_REPAIR_CAP):
        stats["reroll_attempts"] += 1
        try:
            draft, _ = _write_with_guide(
                units[-1],
                s.plan,
                s.memory_bank,
                query,
                language,
                archetype,
                s.domain,
                prior_titles,
                s.design_guide,
                s.scaffold,
                task_id=s.task_id,
            )
        except Exception:  # noqa: BLE001 — best-effort; fall through to the trim guarantee
            break
        if draft:
            best = draft
            if not _ends_mid_sentence(draft):
                stats["reroll_fixed"] = True
                break
    sections[-1] = best
    s.sections = sections


def _guarantee_complete_ending(s: PipelineState) -> str:
    """Layer 2 — deterministic last-resort guarantee. After ALL post-passes, if
    the shipped body (excluding the appended References block) still ends
    mid-sentence, trim the incomplete tail. Fail-loud: a fired trim is recorded
    in completion_repair_stats and warned to stderr so it is never silent."""
    article = s.article
    stats = dict(getattr(s, "completion_repair_stats", {}) or {})
    if not article or not article.strip():
        s.completion_repair_stats = stats
        return article
    refs_start = None
    for m in _REFS_HEADING_RE.finditer(article):
        refs_start = m.start()  # the LAST References heading is the bibliography
    body = article if refs_start is None else article[:refs_start]
    refs = "" if refs_start is None else article[refs_start:]
    if not _ends_mid_sentence(body):
        s.completion_repair_stats = stats
        return article
    trimmed = _trim_to_last_sentence(body)
    if not trimmed or trimmed == body.rstrip():
        stats["still_incomplete"] = True
        print(
            "[orchestrate] WARNING: article body ends mid-sentence and no safe "
            "trim boundary was found — shipping as-is. A final section truncated "
            "and the completion re-roll did not recover it.",
            file=sys.stderr,
            flush=True,
        )
        s.completion_repair_stats = stats
        return article
    stats["trimmed"] = True
    print(
        "[orchestrate] WARNING: article body ended mid-sentence after all "
        "post-passes; deterministically trimmed to the last complete sentence "
        "(completion guarantee). Inspect completion_repair_stats + the runaway / "
        "re-roll layers if this fires often.",
        file=sys.stderr,
        flush=True,
    )
    s.completion_repair_stats = stats
    result = trimmed.rstrip()
    if refs:
        result += "\n\n" + refs.lstrip()
    return result


# round 5 T1-PR3 (2026-05-31): runaway-block clamp. id=89's §2.3 was a single
# FLAT 18,544-word block (50% of the body) the writer never subdivided — the
# "disorganized collection of excerpts / wall of text" the judge scored
# formatting 2.0. The init_format SECTION_BUDGET_CEILING (now 18000) prevents
# the BUDGET; this is the deterministic post-assembly backstop for a block that
# ran away anyway (inner-loop expand accumulation). It truncates ONLY a single
# inter-heading block that is pathologically long — the threshold (default
# 12000 tokens ≈ 9k EN words / ~19k CJK chars) is several× any legitimate
# Qianfan section (its largest H2 is ~1.8k words), so it never trims real depth;
# a flat block that large is structurally broken regardless of content value.
# Cuts at the last sentence boundary; the following heading is preserved.
_RUNAWAY_BLOCK_TOKENS_DEFAULT = 12_000
_RUNAWAY_BLOCK_TOKENS_MIN = 4_000  # never below ~3k words — would risk legit deep sections
_RUNAWAY_BLOCK_TOKENS_MAX = 40_000
_HEADING_LINE_RE = re.compile(r"(?m)^#{1,6}[ \t]+\S")


def _runaway_block_tokens() -> int:
    """Resolve the per-block runaway threshold from DR_RUNAWAY_BLOCK_TOKENS.
    Fail loud on a non-integer / out-of-range value rather than silently
    clamping legit content (too low) or never firing (too high)."""
    raw = os.environ.get("DR_RUNAWAY_BLOCK_TOKENS")
    if raw is None:
        return _RUNAWAY_BLOCK_TOKENS_DEFAULT
    try:
        val = int(raw)
    except ValueError:
        raise ValueError(f"DR_RUNAWAY_BLOCK_TOKENS must be a non-negative integer; got {raw!r}") from None
    if not (_RUNAWAY_BLOCK_TOKENS_MIN <= val <= _RUNAWAY_BLOCK_TOKENS_MAX):
        raise ValueError(
            f"DR_RUNAWAY_BLOCK_TOKENS out of range [{_RUNAWAY_BLOCK_TOKENS_MIN}, {_RUNAWAY_BLOCK_TOKENS_MAX}]: {val}"
        )
    return val


def _truncate_to_token_budget(text: str, max_tokens: int) -> str | None:
    """Largest prefix of `text` at a sentence boundary within ~`max_tokens`.
    Uses a proportional char estimate (O(n), avoids per-sentence recount) then
    backs up to the last sentence terminal. Returns None if no boundary fits.

    Approximate ceiling, NOT a strict bound: `char_budget` uses the block's
    AVERAGE chars-per-token, so a prefix denser in CJK than the block average
    (CJK ≈1.6 chars/tok vs non-CJK ≈4) can carry somewhat more than `max_tokens`
    (≈15% over for a 50/50 block at 2× threshold). The only caller is the
    runaway-clamp safety net, which fires on pathological walls where a few-%
    overshoot on already-truncated content is immaterial; callers must not rely
    on the returned prefix being strictly within `max_tokens`."""
    total = text_metrics.approx_tokens(text)
    if total <= max_tokens:
        return text
    # Average chars/token across the whole block — see the docstring caveat on
    # CJK-dense prefixes slightly overshooting the budget.
    char_budget = max(1, int(len(text) * max_tokens / total))
    head = text[:char_budget]
    for i in range(len(head) - 1, -1, -1):
        if head[i] in _SENT_TERMINALS:
            return text[: i + 1]
    return None


def _clamp_runaway_blocks(article: str) -> tuple[str, dict]:
    """Deterministic safety net: truncate any single inter-heading block whose
    body exceeds the runaway threshold. Env-gated (DR_RUNAWAY_CLAMP=off to
    disable), fail-loud. The heading lines and all other blocks are untouched.

    Language-agnostic: the threshold is token-based and `_SENT_TERMINALS` covers
    both EN and CJK terminals, so no `language` arg is needed (it was dead input
    that implied language-specific logic that does not exist)."""
    stats = {"blocks_clamped": 0, "tokens_removed": 0}
    if os.environ.get("DR_RUNAWAY_CLAMP", "on") == "off" or not article or not article.strip():
        return article, stats
    threshold = _runaway_block_tokens()
    heads = [m.start() for m in _HEADING_LINE_RE.finditer(article)]
    if not heads:
        return article, stats
    bounds = [*heads, len(article)]
    out = [article[: heads[0]]]  # preamble before the first heading, left as-is
    for i in range(len(heads)):
        block = article[heads[i] : bounds[i + 1]]
        nl = block.find("\n")
        if nl < 0:
            out.append(block)
            continue
        heading_line, body = block[: nl + 1], block[nl + 1 :]
        body_tok = text_metrics.approx_tokens(body)
        if body_tok <= threshold:
            out.append(block)
            continue
        trimmed = _truncate_to_token_budget(body, threshold)
        if trimmed is None or trimmed == body:
            out.append(block)  # no safe boundary — leave intact rather than hard-cut
            continue
        stats["blocks_clamped"] += 1
        stats["tokens_removed"] += body_tok - text_metrics.approx_tokens(trimmed)
        out.append(heading_line + trimmed.rstrip() + "\n\n")
    if stats["blocks_clamped"]:
        print(
            f"[orchestrate] WARNING: clamped {stats['blocks_clamped']} runaway "
            f"block(s) (~{stats['tokens_removed']} tokens) that exceeded the "
            f"{threshold}-token per-section ceiling — a chapter ran away flat "
            f"instead of nesting. Check the architect outline / runaway budget.",
            file=sys.stderr,
            flush=True,
        )
    return "".join(out), stats


def _expected_tok_for(scaffold, sid: str) -> int:
    if scaffold:
        for sec in scaffold.sections:
            if sec.section_id == sid:
                # Greptile PR #69 round-2: go through the single-source-of-truth
                # property so an unset/None/0 field falls back to 1200 (honoring
                # the `-> int` contract) the SAME way validation.run does — never
                # leak None to arithmetic callers like _write_with_guide.
                return sec.effective_length_tokens
    return 1200


def _run_section_loop(s: PipelineState, query, language):
    plan, bank, spec, archetype, domain = (s.plan, s.memory_bank, s.spec, s.archetype["archetype"], s.domain)
    units = writer.outline_units(plan)
    prior_titles = [u["title"] for u in units]

    # P2-Wave-2-G telemetry: record once (per task) whether the W9-readability
    # fragile-density auto-suppression of `_DEDUP_RULE` fires. The actual prompt
    # change is made inside writer_system; this side-channel only mirrors that
    # decision into drift logs for dev10 attribution.
    if os.environ.get("DR_CAPEL_G", "on") != "off" and archetype == "explain-mechanism" and s.task_id is not None:
        try:
            from .cache import fragile_tasks as _ft

            s.g_dedup_suppressed = bool(_ft.is_fragile_density_task(s.task_id))
        except Exception:  # noqa: BLE001
            s.g_dedup_suppressed = False

    def process_one(u):
        sid = u["id"]
        # L1: the section's declared depth target — used to gate acceptance on
        # completeness so a thin-but-coherent draft can't pass as "done".
        expected_tok = _expected_tok_for(s.scaffold, sid)
        # Per-section CAPEL telemetry: sum strip + violation counts across
        # every writer call this section sees (initial draft + grounding/
        # inner-loop retries). Recording only the final attempt's stats would
        # hide violations the model emitted on prior retries — dev10's
        # `marker-violation rate < 5%` gate must reflect the full generation
        # cost, not just the accepted draft.
        agg_stats = {"n_markers_stripped": 0, "n_violations": 0, "n_calls": 0}

        def _accum(local_stats: dict) -> None:
            if not local_stats:
                return
            agg_stats["n_markers_stripped"] += int(local_stats.get("n_markers_stripped", 0))
            agg_stats["n_violations"] += int(local_stats.get("n_violations", 0))
            agg_stats["n_calls"] += 1

        # Grounding needs the full (post-dedup) evidence block independent of
        # what `writer.write_section` ultimately fetches internally — keep this
        # call so grounding.check has its own deterministic evidence view.
        ev = bank.for_section(sid)
        # L1b smoking gun: how many evidence blocks did the research phase route
        # to THIS section? A hollow section with an empty slice = research
        # starvation (→ L1b); a hollow section with a full slice = writer-budget
        # (L1a's job) or a token-ceiling cutoff (→ raise max_tokens).
        evidence_blocks = len(ev or [])
        draft_s, stats = _write_with_guide(
            u,
            plan,
            bank,
            query,
            language,
            archetype,
            domain,
            prior_titles,
            s.design_guide,
            s.scaffold,
            task_id=s.task_id,
        )
        _accum(stats)
        # PR-A: re-roll an obviously-CUT draft FRESH before the quality loop. A
        # mid-sentence + severely-thin draft is a transient infra failure (the
        # client returns truncated text without checking stop_reason); a clean
        # re-roll — especially at lower concurrency — recovers the full section,
        # whereas the grounding/expand loop can't fix a truncated generation and
        # would burn its bounded budget on it. No-op for complete drafts.
        # NOTE: if all _TRUNC_RETRY_CAP re-rolls also return cut drafts (persistent
        # stream contention), the quality loop runs on the last cut draft — the
        # cap bounds re-roll cost, not acceptance.
        trunc_retries = 0
        while trunc_retries < _TRUNC_RETRY_CAP and _is_cut_generation(draft_s, expected_tok):
            trunc_retries += 1
            draft_s, stats = _write_with_guide(
                u,
                plan,
                bank,
                query,
                language,
                archetype,
                domain,
                prior_titles,
                s.design_guide,
                s.scaffold,
                task_id=s.task_id,
            )
            _accum(stats)
        last_scores = None
        # P3b-OPT2: per-iteration trajectory telemetry. INNER_CAP now defaults
        # to 2 (see the definition above) after this telemetry proved the 3rd
        # corrective pass is wasteful. We keep recording, per iteration, whether
        # grounding passed and what the inner-loop score was so
        # scripts/inner_cap_ab_analysis.py can re-confirm the cost/benefit of
        # each corrective pass across future graded runs.
        traj = []
        for iter_index in range(INNER_CAP):
            g = grounding.check(draft_s, ev, language, archetype=archetype)
            if not g["ok"]:
                traj.append(
                    {
                        "i": iter_index,
                        "grounding_ok": False,
                        "scored": False,
                        "score_ok": None,
                        "min_score": None,
                        "degraded": False,
                    }
                )
                # L1 (Greptile PR #69 round-2): a draft that is BOTH grounding-
                # deficient AND hollow must hear BOTH signals. Previously this
                # branch rewrote on grounding-only feedback and `continue`d, so a
                # thin+ungrounded section could burn every INNER_CAP pass on
                # grounding rewrites and never be told to expand — it surfaced in
                # final_thin telemetry but the targeted expand prompt was never
                # injected. Combine the directives exactly as the scoring branch
                # does below.
                gfb = grounding.feedback_text(g)
                if _section_too_thin(draft_s, expected_tok):
                    gfb = (gfb + " " + _expand_feedback(expected_tok)).strip()
                draft_s, stats = _write_with_guide(
                    u,
                    plan,
                    bank,
                    query,
                    language,
                    archetype,
                    domain,
                    prior_titles,
                    s.design_guide,
                    s.scaffold,
                    task_id=s.task_id,
                    feedback=gfb,
                )
                _accum(stats)
                continue
            r = inner_loop.score_section(draft_s, spec, language, u["title"], note=f"inner_loop.{sid}")
            last_scores = r
            traj.append(
                {
                    "i": iter_index,
                    "grounding_ok": True,
                    "scored": True,
                    "score_ok": bool(r.get("ok")),
                    "min_score": r.get("min_score"),
                    # score_section returns ok=True / min_score=None (UNVALIDATED)
                    # when the inner-scorer LLM call fails (E1 fix, PR #81). Forward
                    # that flag so the analysis script can exclude these from the cap=2
                    # verdict — a degraded "pass" is not a genuine one and would
                    # otherwise bias toward KEEP cap=3. (Greptile PR #50.)
                    "degraded": bool(r.get("degraded")),
                }
            )
            # L1: accept only when quality-ok AND not hollow. A thin section
            # (well below its declared depth target) retries with an explicit
            # expand directive even if it scored ok — bounded by INNER_CAP.
            thin = _section_too_thin(draft_s, expected_tok)
            if r["ok"] and not thin:
                break
            fb = inner_loop.feedback_text(r) if not r["ok"] else ""
            if thin:
                fb = (fb + " " + _expand_feedback(expected_tok)).strip()
            draft_s, stats = _write_with_guide(
                u,
                plan,
                bank,
                query,
                language,
                archetype,
                domain,
                prior_titles,
                s.design_guide,
                s.scaffold,
                task_id=s.task_id,
                feedback=fb,
            )
            _accum(stats)
        # L1 telemetry: is the section STILL hollow after the inner loop?
        # A persistent hollow chapter signals an upstream coverage gap.
        final_thin = _section_too_thin(draft_s, expected_tok)
        draft_tok = _approx_tokens(draft_s)
        sec_meta = {
            "evidence_blocks": evidence_blocks,
            "expected_tok": expected_tok,
            "draft_tok": draft_tok,
            "thin_ratio": round(draft_tok / expected_tok, 3) if expected_tok else None,
            "mid_sentence": _ends_mid_sentence(draft_s),
            "trunc_retries": trunc_retries,
        }
        return sid, u, draft_s, last_scores, agg_stats, traj, final_thin, sec_meta

    order_ix = {u["id"]: i for i, u in enumerate(units)}
    sec_workers = int(os.environ.get("DR_SECTION_WORKERS", "4"))
    with ThreadPoolExecutor(max_workers=sec_workers) as ex:
        results = list(ex.map(process_one, units))
    results.sort(key=lambda r: order_ix.get(r[0], 1e9))

    sections, score_summary, failing = [], [], []
    # E1: n_degraded counts sections whose FINAL inner-loop score came from a
    # degraded (failed) scorer call — they shipped unvalidated, not at a genuine
    # quality bar. Surfaced in completion_stats + a run-level stderr warning so a
    # scorer outage is visible instead of laundered into silent passes.
    completion = {"n_sections": 0, "n_hollow_final": 0, "hollow_sections": [], "n_degraded": 0, "sections": []}
    for idx, (sid, u, draft_s, last, stats, traj, final_thin, sec_meta) in enumerate(results):
        sections.append(draft_s)
        completion["n_sections"] += 1
        # L1b: per-section record correlating hollowness with the routed evidence
        # count and chapter POSITION (idx) — so the dev6 shows whether hollow
        # chapters cluster late (Qianfan's late chapters stay rich) and whether
        # they were starved of evidence vs merely written short.
        completion["sections"].append({"section": sid, "idx": idx, "final_thin": final_thin, **sec_meta})
        if final_thin:
            completion["n_hollow_final"] += 1
            completion["hollow_sections"].append(sid)
        if traj:
            s.inner_loop_trajectory.append({"section": sid, "iters": traj})
        if stats and (stats.get("n_markers_stripped") or stats.get("n_violations")):
            s.capel_stats[sid] = stats
        if last:
            if last.get("degraded"):
                completion["n_degraded"] += 1
            score_summary.append(
                {
                    "section": sid,
                    "title": u["title"],
                    "min_score": last.get("min_score"),
                    "fail": [f.get("criterion") for f in last.get("fail", [])],
                }
            )
            for f in last.get("fail", []):
                failing.append(f"[{sid}] {f.get('criterion')}: {f.get('rationale', '')}")
    # E1: a degraded scorer ships sections unvalidated. Keep the run fail-soft,
    # but make the outage loud at run level rather than invisible-except-in-drift.
    if completion["n_degraded"]:
        print(
            f"[orchestrate] WARNING: inner-scorer degraded for "
            f"{completion['n_degraded']}/{completion['n_sections']} sections — "
            f"they shipped UNVALIDATED (scorer outage), not at a verified quality "
            f"bar. Check the scorer model/availability before trusting this run's "
            f"quality gate.",
            file=sys.stderr,
            flush=True,
        )
    s.completion_stats = completion
    return sections, score_summary, failing


def _write_with_guide(
    u,
    plan,
    bank,
    query,
    language,
    archetype,
    domain,
    prior_titles,
    guide,
    scaffold,
    *,
    task_id: int | None = None,
    feedback: str = "",
):
    """writer.write_section + design_guide block + scaffold expected-length.

    Returns (text, capel_stats). Stats are non-zero only when CAPEL is active
    (env `DR_CAPEL_G != off`); callers either record them in `s.capel_stats`
    or discard.
    """
    # Source-of-truth: reuse _expected_tok_for so the lookup + None→1200 fallback
    # live in ONE place. The old inline copy here could assign None (unset
    # expected_length_tokens), which then crashed at `int(0.7 * expected_tok)`
    # below. (Greptile PR #69 round-2.)
    expected_tok = _expected_tok_for(scaffold, u["id"])
    extra = ""
    if guide:
        extra = f"\n\nDESIGN GUIDE (apply to this section):\n{guide.as_writer_block()}"
    extra += f"\n\nSECTION LENGTH TARGET: ~{expected_tok} tokens (minimum {int(0.7 * expected_tok)})."
    return writer.write_section(
        u,
        plan,
        bank,
        prompt=query,
        language=language,
        archetype=archetype,
        domain=domain,
        prior_titles=prior_titles,
        feedback=(feedback or "") + extra,
        task_id=task_id,
        target_tokens=expected_tok,
    )


def _refine_with_guide(draft, archetype, language, section_scores, failing_rationales, guide, extra=""):
    feedback_text = ""
    if guide:
        feedback_text += "\n\nDESIGN GUIDE TO APPLY:\n" + guide.as_writer_block()
    if extra:
        feedback_text += "\n\n" + extra
    out = refiner.refine(
        draft,
        archetype=archetype,
        language=language,
        section_scores=json.dumps(section_scores, ensure_ascii=False)[:8000] + feedback_text,
        failing_rationales="\n".join(failing_rationales)[:8000],
    )
    return out


def _validation_loop(s: PipelineState, language: str) -> PipelineState:
    """Cap-2 corrective refiner passes; on cap-exhaustion log + proceed
    (never block adapter — DRB needs an article per task)."""
    while s.refiner_passes <= VALIDATION_CAP:
        vout = _phase(
            "validation",
            validation.run,
            validation.ValidationInput(
                article=s.article,
                plan=s.plan,
                scaffold=s.scaffold,
                design_guide=s.design_guide,
                language=language,
                domain=s.domain,
                archetype=s.archetype.get("archetype", "") if isinstance(s.archetype, dict) else "",
            ),
        )
        s.validation_log.append(
            {"pass": s.refiner_passes, "ok": vout.ok, "counts": vout.counts, "failures": vout.failures}
        )
        if vout.ok:
            return s
        if s.refiner_passes >= VALIDATION_CAP:
            validation.log_failures(task_id="", vout=vout)
            return s
        # corrective refiner pass — feedback is STRUCTURED (validation.feedback_text)
        refined = _phase(
            f"refiner_corrective_{s.refiner_passes}",
            _refine_with_guide,
            s.article,
            s.archetype["archetype"],
            language,
            s.section_scores,
            s.failing_rationales,
            s.design_guide,
            extra=vout.feedback_text,
        )
        # min-ratio guard: if refiner reverted, accept current as best
        if not refined.get("applied"):
            return s
        s.article = refined["article"]
        s.refiner_passes += 1
    return s
