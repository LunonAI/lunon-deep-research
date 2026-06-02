"""Orchestrator (p1-checklist items 8, 23).

Plan-once → research 3-5 cycles → one forced gap-review → ≤2 gap-fill → stop
(AI-Q orchestrator.j2 shape). Enforces:
- Hard tool-call budget BUDGET (each Exa search = 1 tool call; halts, never
  exceeds). Sized to fit 5 specialists × specialists._MAX_SEARCHES_PER_SPECIALIST
  + 2 gap-fill calls + 2 calls of headroom. Both BUDGET (default 64) and the
  per-specialist cap (default 12) are env-overridable (DR_TOOL_CALL_BUDGET /
  DR_MAX_SEARCHES_PER_SPECIALIST); a module-level invariant fails loud if BUDGET
  drops below 5×cap+2. Made safe by the per-specialist wall-clock timeout
  (_SPECIALIST_TIMEOUT_S) that bounds any single specialist's research() call —
  the 2026-05-25 CAPEL smoke incident proved the BUDGET bump alone was unsafe
  without it.
- Forced reflection: a `think` gap-review marking each acceptance criterion
  SATISFIED/PARTIAL/UNSAT, picking ≤2 critical gaps.
- IterResearch compressed-report memory, bounded compaction every N=8 tool calls.
Specialists run in ISOLATED context (item 24); findings land in the WebWeaver
memory bank keyed by the producing query's target_sections (items 13/25).
"""

import concurrent.futures
import json
import os
import sys

from .. import config, llm
from .._env import int_env
from . import specialists
from .memory_bank import MemoryBank
from .specialists import research

# Per-specialist wall-clock cap (2026-05-25 follow-up after the CAPEL smoke
# hang on id=56 where horizon_scanner hung mid-flight, stalling the whole
# task indefinitely). 4 min is sized to cover the worst nominal case at
# BUDGET=64 (12 Exa @ ~5s = 60s, + Nemotron extract @ up to 180s, + ~60s
# buffer for compaction / network jitter). When the timeout fires the
# specialist is dropped from the digest with no findings — the article
# still ships with degraded evidence for that role rather than hanging.
# Pre-fix the orchestrator's `for role in order` loop had no per-iteration
# wall-clock bound; only the OpenRouter HTTP layer's 180s × 3 retries
# capped any single LLM call, leaving inter-call hangs unbounded.
#
# Overridable via DR_SPECIALIST_TIMEOUT_S: the 1200s default is sized to
# avoid false drops under high concurrency (e.g. the full-100 at --workers 20)
# where the shared API slows every Exa/extract call. Pair with sane concurrency
# (6×4) rather than raising the timeout further; very long timeouts still cap
# true hangs via _SPECIALIST_TIMEOUT_MAX_S.
# PR-A (2026-05-29): raised 240→1200. The dev6 `lunon-p3b-v3-dev6` still dropped
# an `evidence_gatherer` at the 600s the runner exported, almost certainly slow-
# under-contention (concurrent `RemoteProtocolError` stream-drops) not hung — the
# research loop is bounded by the 64-tool-call budget so it can't spin forever.
# 1200s makes a single research call essentially never falsely dropped.
_SPECIALIST_TIMEOUT_DEFAULT_S = 1200
_SPECIALIST_TIMEOUT_MIN_S = 60
_SPECIALIST_TIMEOUT_MAX_S = 3600


def _specialist_timeout_from_env() -> int:
    """Resolve the specialist wall-clock cap from DR_SPECIALIST_TIMEOUT_S.

    Fail loud with a clear message on a misconfigured value rather than
    letting a bare ``int()`` raise a cryptic ValueError at module-import
    time. Guards the range so DR_SPECIALIST_TIMEOUT_S=0 / negative (every
    specialist times out instantly) or an absurdly large value (effectively
    unbounded — the hang the cap exists to prevent) can't slip through. The
    [60, 3600] band still admits the recommended high-concurrency bumps
    (e.g. 450, 1000)."""
    raw = os.environ.get("DR_SPECIALIST_TIMEOUT_S")
    if raw is None:
        return _SPECIALIST_TIMEOUT_DEFAULT_S
    try:
        val = int(raw)
    except ValueError:
        raise ValueError(f"DR_SPECIALIST_TIMEOUT_S must be an integer number of seconds; got {raw!r}") from None
    if not (_SPECIALIST_TIMEOUT_MIN_S <= val <= _SPECIALIST_TIMEOUT_MAX_S):
        raise ValueError(
            f"DR_SPECIALIST_TIMEOUT_S out of range [{_SPECIALIST_TIMEOUT_MIN_S}, {_SPECIALIST_TIMEOUT_MAX_S}]: {val}"
        )
    return val


_SPECIALIST_TIMEOUT_S = _specialist_timeout_from_env()


def _research_with_timeout(role, qlist, *, language, domain, exa_mode, model_override, timeout_s=None):
    """Wrap `research()` in a wall-clock cap and RETURN a findings dict.

    round 4 (2026-05-31): on timeout this no longer RAISES — it catches the
    `concurrent.futures.TimeoutError` internally and returns the PARTIAL findings
    the specialist wrote into its `sink` before the cut, flagged `timed_out=True`.
    Callers must inspect `res.get("timed_out")` (to bump timeout telemetry) and
    ingest the partial findings rather than dropping the whole role. Normal
    completion returns research()'s dict unchanged (no `timed_out` key). Any
    NON-timeout exception from research() still propagates to the caller.

    `timeout_s=None` resolves to the module-level `_SPECIALIST_TIMEOUT_S`
    at CALL time (not import time) so monkeypatching the constant in tests
    actually takes effect — and so a runtime tuning bump to the constant
    propagates to every call site without code changes.

    Thread lifecycle: on timeout the underlying network call cannot be safely
    cancelled (Python can't kill threads mid-syscall), so we
    `shutdown(wait=False)` the executor and let the hung thread continue
    in the background. It will eventually die when the adapter process
    exits. This is the right trade for our use case (single-task adapter
    runs that exit after writing the jsonl) — preferable to never
    completing the task.
    """
    if timeout_s is None:
        timeout_s = _SPECIALIST_TIMEOUT_S
    # round 4 (2026-05-31): a shared sink lets us recover the specialist's
    # PARTIAL findings on timeout instead of dropping its whole coverage. The
    # background thread writes findings/n_searches through this dict as it goes
    # (GIL-atomic); on TimeoutError we snapshot and return what was gathered,
    # flagged `timed_out` so the caller still bumps the timeout telemetry. This
    # turns a hard coverage loss (a dropped Insight/Comp specialist) into at
    # worst a slightly-thinner-than-full one.
    sink: dict = {"findings": [], "n_searches": 0}
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"specialist-{role}")
    try:
        fut = ex.submit(
            research,
            role,
            qlist,
            language=language,
            domain=domain,
            exa_mode=exa_mode,
            model_override=model_override,
            sink=sink,
        )
        return fut.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        return {
            "role": role,
            "findings": list(sink["findings"]),
            "n_searches": sink["n_searches"],
            "timed_out": True,
        }
    finally:
        # `wait=False` so we don't block on a hung worker thread. The thread
        # will continue running in the background until the process exits.
        ex.shutdown(wait=False)


# P2-Option-A-#4 dispatch budget re-engaged at 64 (2026-05-25, Stage 1c of
# the post-CAPEL-smoke follow-up). Sized to fit:
#   5 specialists × specialists._MAX_SEARCHES_PER_SPECIALIST (12) = 60 main-loop
#   + 2 gap-fill calls (max gap_fill items × 1 query each)         =  2
#   + 2 calls of headroom (rounding + safety margin)               =  2
#   total                                                          = 64
# Safe to re-engage because `_research_with_timeout` (above) now bounds any
# single specialist's research() call at _SPECIALIST_TIMEOUT_S (240s). The
# 2026-05-25 CAPEL smoke incident at BUDGET=64 without that bound hung
# indefinitely on horizon_scanner; with the bound, the worst case is one
# specialist's findings dropped (digest gets a TIMEOUT marker) and the
# task completes on the other 4 specialists' evidence.
# P3b-v5 (2026-05-29): env-overridable in lockstep with
# specialists.DR_MAX_SEARCHES_PER_SPECIALIST so the grounding arm can raise the
# tool-call ceiling for the longer ZH chapters. Default 64 = inert; dev6 arm
# sets =104 (fits 5×20 + 2 gap-fill). Fail-loud below the invariant rather than
# let the dispatch slice (min(cap, BUDGET-tool_calls)) silently re-clamp the
# per-specialist searches back down — the exact silent-drop the spec warns of.
BUDGET = int_env("DR_TOOL_CALL_BUDGET", 64)
_MIN_BUDGET = 5 * specialists._MAX_SEARCHES_PER_SPECIALIST + 2
if BUDGET < _MIN_BUDGET:
    raise RuntimeError(
        f"orchestrator.BUDGET={BUDGET} < 5×_MAX_SEARCHES_PER_SPECIALIST"
        f"({specialists._MAX_SEARCHES_PER_SPECIALIST})+2={_MIN_BUDGET}: raise "
        f"DR_TOOL_CALL_BUDGET to ≥{_MIN_BUDGET} or the per-specialist search "
        f"cap is silently clamped (no new grounded atoms gathered)."
    )

# P3b-v5 (2026-05-29): co-knob #2 invariant, fail-loud — completes the trio
# alongside BUDGET (#1, above) and specialists._RESULTS_SERIALISATION_CAP (#3).
# The per-specialist search cap and the specialist wall-clock are co-dependent:
# at the raised cap (=20) a single research() call runs ~100s Exa + ~180s
# extract + buffer ≈ 340s, past the 240s default — _research_with_timeout then
# drops that specialist SILENTLY (TIMEOUT marker), the exact CAPEL-smoke
# degradation specialists.py co-knob #2 warns of. Without this guard a developer
# who follows the two OTHER explicit guards (raises BUDGET + the serialisation
# cap) but forgets DR_SPECIALIST_TIMEOUT_S passes every import-time check yet
# re-creates the incident at runtime. Enforce the documented ≥360s floor
# whenever the search cap is raised above its inert default so the
# misconfiguration surfaces at import, not as silently-dropped specialists.
_SPECIALIST_SEARCH_CAP_INERT_DEFAULT = specialists._MAX_SEARCHES_PER_SPECIALIST_DEFAULT  # single source of truth
_SPECIALIST_TIMEOUT_FLOOR_S = 360
if (
    specialists._MAX_SEARCHES_PER_SPECIALIST > _SPECIALIST_SEARCH_CAP_INERT_DEFAULT
    and _SPECIALIST_TIMEOUT_S < _SPECIALIST_TIMEOUT_FLOOR_S
):
    raise RuntimeError(
        f"orchestrator: DR_SPECIALIST_TIMEOUT_S={_SPECIALIST_TIMEOUT_S}s < "
        f"{_SPECIALIST_TIMEOUT_FLOOR_S}s while "
        f"specialists._MAX_SEARCHES_PER_SPECIALIST="
        f"{specialists._MAX_SEARCHES_PER_SPECIALIST} > "
        f"{_SPECIALIST_SEARCH_CAP_INERT_DEFAULT}: at the raised search cap a "
        f"specialist's wall-clock (~100s Exa + ~180s extract + buffer ≈ 340s) "
        f"exceeds the 240s default and _research_with_timeout drops it silently "
        f"(the CAPEL smoke incident). Raise DR_SPECIALIST_TIMEOUT_S to "
        f"≥{_SPECIALIST_TIMEOUT_FLOOR_S}."
    )
COMPACT_EVERY = 8

# Per-archetype researcher routing (W9 diagnostic + dev6 paired test 2026-05-21):
# SHIPPED CONFIG: Tongyi-DR routes list-all ONLY. dev6 showed +0.020 mean
# on list-all (n=2, both positive) but n=1 explain-mech regressed −0.031
# (id=56 was top-of-variance W9 outlier 0.586 → regression-to-mean likely).
# Reverted explain-mech to default Nemotron pending more data.
TONGYI_ROUTED_ARCHETYPES = {"list-all"}
TONGYI_MODEL = "alibaba/tongyi-deepresearch-30b-a3b"

_GAP_SYSTEM = (
    "You are the Orchestrator doing a gap review (think step). For EACH "
    "acceptance criterion, judge it against the evidence digest as SATISFIED, "
    "PARTIAL, or UNSAT. Then pick the <=2 MOST critical gaps to fill. Output "
    'ONLY JSON: {"review": [{"id": str, "status": '
    '"SATISFIED"|"PARTIAL"|"UNSAT", "note": str}], "gap_fill": '
    '[{"brief": str, "specialist_role": '
    '"evidence_gatherer"|"mechanism_explorer"|"comparator"|"critic"|'
    '"horizon_scanner"|"generalist"}] }. <=2 gap_fill items, only for true '
    "UNSAT/PARTIAL gaps that matter most for the prompt."
)

_COMPACT_SYSTEM = (
    "Compress these research findings into a dense evidence digest: keep every "
    "specific number, date, named entity, source, and causal chain; drop "
    "redundancy and filler. No new claims. Output plain text, grouped by "
    "subtopic. This is working memory, not the final report."
)

# archetype → specialist dispatch priority (which roles matter most first)
_ARCH_PRIORITY = {
    "list-all": ["evidence_gatherer", "comparator", "generalist"],
    "compare": ["comparator", "evidence_gatherer", "critic"],
    "trend": ["horizon_scanner", "evidence_gatherer", "mechanism_explorer"],
    "explain-mechanism": ["mechanism_explorer", "critic", "evidence_gatherer"],
    "predict": ["horizon_scanner", "mechanism_explorer", "critic", "evidence_gatherer"],
    "recommend": ["evidence_gatherer", "comparator", "critic", "mechanism_explorer"],
}


def _groups_by_role(plan):
    """Group architect queries by specialist_role into query lists."""
    groups = {}
    for q in plan.get("queries", []):
        groups.setdefault(q.get("specialist_role", "generalist"), []).append(q)
    return groups


def run(plan, prompt, language, archetype, domain):
    bank = MemoryBank()
    groups = _groups_by_role(plan)
    tool_calls = 0
    digest_parts = []

    # research-cycle order: archetype priority first, then any remaining roles
    order = [r for r in _ARCH_PRIORITY.get(archetype, []) if r in groups] + [
        r for r in groups if r not in _ARCH_PRIORITY.get(archetype, [])
    ]

    def ingest(res, role_groups):
        q_by_id = {q.get("id"): q for q in role_groups}
        for f in res.get("findings", []):
            qids = f.get("query_ids") or list(q_by_id)
            secs = []
            for qid in qids:
                secs += (q_by_id.get(qid, {}) or {}).get("target_sections", [])
            if not secs:  # fall back to all sections this role's queries target
                for q in role_groups:
                    secs += q.get("target_sections", [])
            bank.add(
                source_name=f.get("source_name", ""),
                url=f.get("url", ""),
                title=f.get("source_name", ""),
                text=f.get("statement", "") + (f"  «{f.get('quote', '')}»" if f.get("quote") else ""),
                query_id=",".join(map(str, qids)),
                section_ids=sorted(set(secs)),
                specialist=res.get("role"),
                language=language,
                # P3-W0b (2026-05-27): preserve specialist-extracted causal
                # chain through to the writer's evidence pack. Already
                # sanitized to list[str] by specialists._sanitize_chain;
                # absent or empty for non-mechanism findings.
                chain=f.get("chain") or [],
            )
            digest_parts.append(f"[{res.get('role')}] {f.get('statement', '')} ({f.get('source_name', '')})")

    exa_mode = "deep" if archetype in ("explain-mechanism", "predict") else "auto"
    # Per-archetype researcher routing (W9 diagnostic decision)
    model_override = TONGYI_MODEL if archetype in TONGYI_ROUTED_ARCHETYPES else ""

    n_specialist_timeouts = 0  # telemetry for the post-2026-05-25 timeout layer
    for role in order:
        if tool_calls >= BUDGET:
            break
        qlist = groups.get(role, [])
        # Budget-aware: never let a dispatch push total past BUDGET. The
        # per-specialist cap is sourced from `specialists._MAX_SEARCHES_PER_SPECIALIST`
        # so both the orchestrator BUDGET and per-specialist cap move from
        # a single source of truth (re-engaged 2026-05-25 Stage 1c after
        # the timeout layer above made BUDGET=64 safe to ship).
        qlist = qlist[: max(1, min(specialists._MAX_SEARCHES_PER_SPECIALIST, BUDGET - tool_calls))]
        try:
            res = _research_with_timeout(
                role, qlist, language=language, domain=domain, exa_mode=exa_mode, model_override=model_override
            )
        except Exception as e:  # noqa: BLE001  per-specialist resilience
            digest_parts.append(f"[{role}] (specialist failed: {type(e).__name__}; proceeding)")
            continue
        if res.get("timed_out"):
            # round 4 (2026-05-31): the hard cap no longer DROPS the specialist —
            # `_research_with_timeout` returns the partial findings gathered before
            # the cut, so we ingest them below. Still bump telemetry + print to
            # stderr (real-time operator signal; the digest entry can be _compact'd
            # away at the COMPACT_EVERY boundary) so a dev-run reader sees the
            # degradation in the moment.
            n_specialist_timeouts += 1
            n_kept = len(res.get("findings", []))
            print(
                f"[orchestrator] main-loop role={role} TIMEOUT after {_SPECIALIST_TIMEOUT_S}s; "
                f"kept {n_kept} partial findings",
                file=sys.stderr,
                flush=True,
            )
            digest_parts.append(
                f"[{role}] (specialist TIMEOUT after {_SPECIALIST_TIMEOUT_S}s; kept {n_kept} partial findings)"
            )
        tool_calls += res.get("n_searches", 0)
        ingest(res, groups.get(role, []))
        if tool_calls and tool_calls % COMPACT_EVERY < res.get("n_searches", 1):
            digest_parts[:] = [_compact(digest_parts)]  # bounded compaction

    # forced reflection / gap review
    gap = _gap_review(plan, digest_parts)
    for g in (gap.get("gap_fill") or [])[:2]:
        if tool_calls >= BUDGET:
            break
        role = g.get("specialist_role", "generalist")
        gq = [{"id": "gapfill", "text": g.get("brief", ""), "target_sections": []}]
        try:
            # Gap-fill also gets the wall-clock cap — same hang surface as
            # the main loop (single Exa + Nemotron call), just smaller scope.
            res = _research_with_timeout(
                role, gq, language=language, domain=domain, exa_mode=exa_mode, model_override=model_override
            )
        except Exception:  # noqa: BLE001
            continue
        if res.get("timed_out"):
            # round 4: gap-fill timeout keeps partial findings too (parity with
            # the main loop). Telemetry + real-time stderr signal retained.
            n_specialist_timeouts += 1
            n_kept = len(res.get("findings", []))
            print(
                f"[orchestrator] gap-fill role={role} TIMEOUT after {_SPECIALIST_TIMEOUT_S}s; "
                f"kept {n_kept} partial findings",
                file=sys.stderr,
                flush=True,
            )
            digest_parts.append(
                f"[{role}] (gap-fill TIMEOUT after {_SPECIALIST_TIMEOUT_S}s; kept {n_kept} partial findings)"
            )
        tool_calls += res.get("n_searches", 0)
        # gap-fill evidence is broadly relevant → tag all top-level sections
        top = [s.get("id") for s in plan.get("report_toc", [])]
        for f in res.get("findings", []):
            bank.add(
                source_name=f.get("source_name", ""),
                url=f.get("url", ""),
                title=f.get("source_name", ""),
                text=f.get("statement", ""),
                query_id="gapfill",
                section_ids=top,
                specialist=role,
                language=language,
                # P3-W0b (2026-05-27): same chain pass-through as the
                # main-loop ingest path above.
                chain=f.get("chain") or [],
            )

    if tool_calls > BUDGET:
        raise RuntimeError(f"tool-call budget exceeded ({tool_calls}>{BUDGET})")
    return {
        "memory_bank": bank,
        "gap_review": gap.get("review", []),
        "tool_calls": tool_calls,
        "digest": _compact(digest_parts),
        # Telemetry for the post-2026-05-25 timeout layer. Downstream nodes
        # (orchestrate._persist_drift) can forward this into inner_loop_drift.jsonl
        # to track how often specialists are hitting the wall-clock cap in
        # production — non-zero values indicate either a specific specialist
        # role is degraded (rate-limited / consistently slow) or BUDGET=64
        # is sized too aggressively for current infra.
        "n_specialist_timeouts": n_specialist_timeouts,
    }


def _compact(parts):
    if not parts:
        return ""
    joined = "\n".join(parts)
    if len(joined) < 6000:
        return joined
    # max_tokens 6000 -> 8000 (round 7): round-6/7 logs showed orch.compact hitting
    # stop_reason=max_tokens (4x), i.e. the evidence-digest summary was itself being
    # truncated, silently dropping research context fed to the writer/gap-review.
    return llm.call("orchestrator", joined[:48000], system=_COMPACT_SYSTEM, max_tokens=8000, note="orch.compact")


def _gap_review(plan, digest_parts):
    acs = [
        {"id": a.get("id"), "text": a.get("text"), "category": a.get("category")}
        for a in plan.get("acceptance_criteria", [])
    ]
    user = (
        "ACCEPTANCE CRITERIA:\n"
        + json.dumps(acs, ensure_ascii=False)
        + "\n\nEVIDENCE DIGEST:\n"
        + _compact(digest_parts)[:40000]
    )
    try:
        return llm.call_json(
            "orchestrator",
            user,
            system=_GAP_SYSTEM,
            max_tokens=32000,
            think=True,
            effort=config.effort_for("orchestrator"),
            note="orch.gapreview",
        )
    except Exception:  # noqa: BLE001
        return {"review": [], "gap_fill": []}
