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

import json
import os
import pathlib
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
        # recomputing the ratio every time downstream. the reference's ~7×
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
            "completion": dict(getattr(s, "completion_stats", {}) or {}),
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
            # land in the reference-corpus bands (and flag `floor_exceeded`,
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
from ._env import assert_phase, log_usage
from .pipeline import (
    architect,
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
    # ignores density directives; these ENFORCE the reference-corpus bands.
    clamped_c, cc_stats = _phase("clamp_citations", style_clamp.clamp_citations, s.article, language=language)
    s.article = clamped_c
    s.clamp_citations_stats = cc_stats
    clamped_e, ce_stats = _phase("clamp_emdash", style_clamp.clamp_emdash, s.article, language=language)
    s.article = clamped_e
    s.clamp_emdash_stats = ce_stats

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
    # P3b-opt2 (2026-05-28): reference-verified flatten. list-all renders fully
    # flat `##` (q91 has H3=H4=0); other archetypes cap at H3 (the reference's
    # universal h4=0). Deterministic safety-net for when the writer ignores
    # the flat-structure directive.
    _arch_name = (s.archetype or {}).get("archetype", "") if isinstance(s.archetype, dict) else ""
    _flat_depth = 2 if _arch_name == "list-all" else 3
    nfo = _phase("numbering_fix", numbering_fix.run, s.article, flatten_max_depth=_flat_depth)
    s.article = nfo.article
    s.numbering_fix_stats = {
        "strips": nfo.stage_directions_removed,
        "collapsed": nfo.sections_collapsed,
        "renumbered": nfo.headings_renumbered,
        "flattened": nfo.headings_flattened,
        "demoted": nfo.headings_demoted,
        "hash_normalized": nfo.headings_hash_normalized,
        "xref_rewritten": nfo.cross_refs_rewritten,
        "xref_orphaned": nfo.cross_refs_orphaned,
        "cap_violations": nfo.cap_violations,
        "skipped_reason": nfo.skipped_reason,
    }

    # G7 (2026-05-28): ZH-aware de-spacing. Runs LAST (after numbering_fix /
    # footnote_normalize) on the final article so it only sees shipped prose;
    # it masks link/anchor/footnote/code spans before collapsing CAPEL-induced
    # CJK↔CJK spaces, so it cannot touch headings, numbers, or citation tokens.
    despaced, dc_stats = _phase("cjk_despace", cjk_despace.despace, s.article, language=language)
    s.article = despaced
    s.cjk_despace_stats = dc_stats

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
# section passes — the "hollow late chapter" failure the reference head-to-head
# flagged (id38 §5 = 185 chars vs a multi-thousand-token target; id44 forecast
# chapter = logic skeleton). We gate acceptance on a minimum content ratio vs
# the section's own declared length target and, when too thin, retry with an
# explicit expand directive (bounded by INNER_CAP). A section still thin after
# retries is surfaced in completion telemetry — a signal of an upstream coverage
# gap (which the enumerate-and-expand / deliverable-mapping levers address).
_COMPLETION_MIN_RATIO = 0.5  # below the 0.7x stated target — only SEVERE shortfalls fire


def _approx_tokens(text: str) -> int:
    """Rough token estimate robust across ZH/EN, body only (heading lines
    stripped). CJK ~1.6 chars/token, other text ~4 chars/token."""
    if not text:
        return 0
    body = "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("#"))
    # Count CJK Unified Ideographs (U+4E00–U+9FFF) AND Extension A (U+3400–U+4DBF).
    # Greptile PR #69 round-1 (2026-05-29): the second range was missing, so Ext A
    # Hanzi were billed at the ~4 chars/token "other" rate (≈0.25 tok/char) instead
    # of the ~1.6 CJK rate — an Ext-A-heavy section under-counts and could be held
    # as thin longer than warranted. These two ranges mirror `cjk_despace._CJK`.
    cjk = sum(1 for ch in body if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿")
    other = len(body) - cjk
    return int(cjk / 1.6 + other / 4)


def _section_too_thin(text: str, expected_tok: int) -> bool:
    if not expected_tok or expected_tok <= 0:
        return False
    return _approx_tokens(text) < _COMPLETION_MIN_RATIO * expected_tok


def _expand_feedback(expected_tok: int) -> str:
    return (
        f"COMPLETENESS — this section is far below its declared depth target "
        f"(~{expected_tok} tokens). Fully develop EVERY sub-topic the section's "
        f"plan declares; do NOT emit a skeleton/intro-only stub or defer content "
        f"to other sections. Expand with concrete, evidence-bearing detail."
    )


def _expected_tok_for(scaffold, sid: str) -> int:
    if scaffold:
        for sec in scaffold.sections:
            if sec.section_id == sid:
                return sec.expected_length_tokens
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
                    feedback=grounding.feedback_text(g),
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
                    # score_section returns a synthetic ok=True / min_score=10.0
                    # when the inner-scorer LLM call fails. Forward that flag so
                    # the analysis script can exclude these from the cap=2
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
        return sid, u, draft_s, last_scores, agg_stats, traj, final_thin

    order_ix = {u["id"]: i for i, u in enumerate(units)}
    sec_workers = int(os.environ.get("DR_SECTION_WORKERS", "4"))
    with ThreadPoolExecutor(max_workers=sec_workers) as ex:
        results = list(ex.map(process_one, units))
    results.sort(key=lambda r: order_ix.get(r[0], 1e9))

    sections, score_summary, failing = [], [], []
    completion = {"n_sections": 0, "n_hollow_final": 0, "hollow_sections": []}
    for sid, u, draft_s, last, stats, traj, final_thin in results:
        sections.append(draft_s)
        completion["n_sections"] += 1
        if final_thin:
            completion["n_hollow_final"] += 1
            completion["hollow_sections"].append(sid)
        if traj:
            s.inner_loop_trajectory.append({"section": sid, "iters": traj})
        if stats and (stats.get("n_markers_stripped") or stats.get("n_violations")):
            s.capel_stats[sid] = stats
        if last:
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
    expected_tok = 1200
    if scaffold:
        for sec in scaffold.sections:
            if sec.section_id == u["id"]:
                expected_tok = sec.expected_length_tokens
                break
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
