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
            "numbering_fix": getattr(s, "numbering_fix_stats", {}),
            "refiner_gate": getattr(s, "refiner_gate_verdict", {}),
            "evidence_dedup": getattr(s, "evidence_dedup_stats", {}),
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
    criteria_spec,
    design_guide,
    evidence_dedup,
    grounding,
    init_format,
    inner_loop,
    intent,
    numbering_fix,
    orchestrator,
    refiner,
    refiner_gate,
    role_play,
    scout,
    validation,
    writer,
    zh_writer_pass,
)
from .retrieval import domain_routed
from .state import PipelineState

INNER_CAP = int(os.environ.get("DR_INNER_CAP", "3"))
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
def plan_only(query: str, language: str) -> dict:
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
        "architect", _build_plan_with_persona, query, language, arche["archetype"], intents, land, cov, persona
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


def _build_plan_with_persona(query, language, archetype, intents, land, cov, persona):
    """Architect call with the role_play persona prepended (item 32 wiring)."""
    plan = architect.build(query, language, archetype, intents, land, cov)
    plan["_persona"] = persona  # carry forward for downstream nodes
    return plan


# ---- Phase 2: full pipeline (W2-W5 + new nodes) ----
def pipeline(query: str, language: str) -> str:
    return from_plan(plan_only(query, language), query, language)


def from_plan(ctx: dict, query: str, language: str) -> str:
    s = _state_from_ctx(ctx, query, language)

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
        "writer_opening", writer.write_opening, s.plan, query, language, s.archetype["archetype"], s.domain, s.digest
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

    # Deterministic post-edit (plan v3 §2a+2d+2c-validator): stop-list regex,
    # empty-section collapse, heading-tree renumber. NO LLM call. Closes the
    # bottom-10 cross-cutting judge complaints (inconsistent numbering, stage
    # directions, methodology meta-commentary leak).
    nfo = _phase("numbering_fix", numbering_fix.run, s.article)
    s.article = nfo.article
    s.numbering_fix_stats = {
        "strips": nfo.stage_directions_removed,
        "collapsed": nfo.sections_collapsed,
        "renumbered": nfo.headings_renumbered,
        "demoted": nfo.headings_demoted,
        "xref_rewritten": nfo.cross_refs_rewritten,
        "xref_orphaned": nfo.cross_refs_orphaned,
        "cap_violations": nfo.cap_violations,
        "skipped_reason": nfo.skipped_reason,
    }

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


def _run_section_loop(s: PipelineState, query, language):
    plan, bank, spec, archetype, domain = (s.plan, s.memory_bank, s.spec, s.archetype["archetype"], s.domain)
    units = writer.outline_units(plan)
    prior_titles = [u["title"] for u in units]

    def process_one(u):
        sid = u["id"]
        # Grounding needs the full (post-dedup) evidence block independent of
        # what `writer.write_section` ultimately fetches internally — keep this
        # call so grounding.check has its own deterministic evidence view.
        ev = bank.for_section(sid)
        draft_s = _write_with_guide(
            u, plan, bank, query, language, archetype, domain, prior_titles, s.design_guide, s.scaffold
        )
        last_scores = None
        for _ in range(INNER_CAP):
            g = grounding.check(draft_s, ev, language, archetype=archetype)
            if not g["ok"]:
                draft_s = _write_with_guide(
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
                    feedback=grounding.feedback_text(g),
                )
                continue
            r = inner_loop.score_section(draft_s, spec, language, u["title"])
            last_scores = r
            if r["ok"]:
                break
            draft_s = _write_with_guide(
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
                feedback=inner_loop.feedback_text(r),
            )
        return sid, u, draft_s, last_scores

    order_ix = {u["id"]: i for i, u in enumerate(units)}
    sec_workers = int(os.environ.get("DR_SECTION_WORKERS", "4"))
    with ThreadPoolExecutor(max_workers=sec_workers) as ex:
        results = list(ex.map(process_one, units))
    results.sort(key=lambda r: order_ix.get(r[0], 1e9))

    sections, score_summary, failing = [], [], []
    for sid, u, draft_s, last in results:
        sections.append(draft_s)
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
    return sections, score_summary, failing


def _write_with_guide(u, plan, bank, query, language, archetype, domain, prior_titles, guide, scaffold, feedback=""):
    """writer.write_section + design_guide block + scaffold expected-length."""
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
