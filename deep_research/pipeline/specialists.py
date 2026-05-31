"""Role-differentiated researcher specialists (p1-checklist items 7, 24).

5 specialists + Generalist fallback, all Nemotron-3-Super-120B via OpenRouter,
each in an ISOLATED context window scoped to its brief (item 24). Analytical-
function decomposition adapted from AI-Q researcher_agent prompts (technique 16).

Robustness (engine-smoke fix): Nemotron is a REASONING model — it cannot be
relied on to emit clean JSON for a query-planning step. So specialists search
the Architect's queries DIRECTLY (those are already well-formed; faster + more
faithful), then make ONE Nemotron extraction call with a generous budget and a
robust parser. If extraction still fails, fall back to snippet-derived findings
so a specialist never starves a task of evidence (AI-Q "proceed with what's
available").
"""

import json
import sys

from .. import llm
from .._env import int_env
from ..retrieval import domain_routed

# Adapted from AI-Q researcher_agent/prompts/*.j2 (aiq_teardown.md §4).
_ROLE = {
    "evidence_gatherer": "EVIDENCE GATHERER. Concrete data, statistics, factual verification. "
    "Numerical precision; reconcile conflicting figures; trace to primary "
    "sources. Prefer datasets, filings, official statistics, named studies.",
    "mechanism_explorer": "MECHANISM EXPLORER. Causal-first: WHY it happens. Named theories/"
    "frameworks, step-by-step causal chains showing each intermediate "
    "link, feedback loops. Reject single-step assertions; require the "
    "intervening mechanism.",
    "comparator": "COMPARATOR. Head-to-head: benchmarks, rankings, trade-offs. Extract "
    "shared comparison dimensions; preserve tabular numbers exactly.",
    "critic": "CRITIC. Adversarial: counterarguments, limitations, failure cases, "
    "boundary conditions, where the mainstream narrative breaks.",
    "horizon_scanner": "HORIZON SCANNER. Recency-first: recent developments, trend evolution, "
    "dated milestones, named analysts' forward-looking commentary.",
    "generalist": "GENERALIST. Multi-mode fallback; let the question guide the method.",
}

# P2-Option-A-#4 (2026-05-23): per-specialist finding ceiling raised from
# 8-14 to 14-24 to feed the depth_seeds H4-leaf payload from PR #20. With 5
# specialists each producing 14-24 atoms, total per-task evidence volume
# reaches ~70-120 atoms — still below the 600-2250 the depth contract wants
# but a ~2.4× improvement over the pre-#4 floor.
_EXTRACT_SYSTEM = (
    "You are a research specialist. {role}\nFrom the search results, extract "
    "SOURCED findings that serve the brief. Think briefly if you must, "
    "but your FINAL output MUST be a single JSON object and nothing after it: "
    '{{"findings": [ {{"statement": str (one specific self-contained claim '
    'with concrete numbers/names/dates), "source_name": str (publication/'
    "institution, e.g. 'IEA 2025' — never a bare number), \"url\": str, "
    '"quote": str (verbatim support <=125 chars), "query_ids": [str], '
    '"chain": [str, ...] (OPTIONAL — use ONLY when this finding describes a '
    'multi-step causal mechanism: 2-6 ordered short clauses like "X results '
    'in Y", "Y enables Z" naming the intervening links. OMIT this field '
    "entirely if the finding is not multi-step causal. mechanism_explorer "
    "specialist should populate this whenever possible; other specialists "
    "leave it absent.)}} "
    "...14-24 findings ]}}. Only findings grounded in the results; reconcile "
    "conflicts in the statement; match the brief's language."
)


# P3-W0b (2026-05-27): sanitize specialist-emitted `chain` field. The LLM
# extraction schema accepts an optional `chain` list of strings for multi-
# step causal findings; without sanitation a malformed value (single string,
# dict, list-of-dicts, 50-item hallucination) would propagate through
# memory_bank and into the writer's evidence pack as JSON-serialized noise.
# Returns a clean list[str] or empty list — never None, never a non-list.
def _sanitize_chain(value) -> list:
    """Normalize an LLM-emitted `chain` value to a clean list-of-strings.

    Accepts: a list of non-empty strings (trimmed, each link capped at
    240 chars, full chain capped at 6 links to bound the prompt budget
    a single hallucinated finding can consume).
    Rejects (returns []): anything else — non-list types, mixed-type
    lists, lists of dicts. Greptile pre-scan item: optional fields
    with loose contracts attract malformed inputs, so we reject the
    whole field on the first non-string element rather than partial-
    accept (which would create silent data corruption downstream).
    """
    if not isinstance(value, list):
        return []
    out: list = []
    for link in value[:6]:  # cap chain length — a 50-link hallucination is noise
        if not isinstance(link, str):
            return []  # mixed-type chain: reject whole field; no partial-accept
        s = link.strip()
        if s:
            out.append(s[:240])
    return out


# P2-Option-A-#4: per-specialist max search calls and per-search result count.
# Pre-#4: 5 searches × 5 results × 5 specialists = 125 raw hits → ~40-70
# extracted atoms per task. Post-#4: 12 × 10 × 5 = 600 raw hits → ~70-120
# extracted atoms (extraction is the binding constraint after this raise).
# The AI-Q "<=5 sequential searches per specialist" guideline reflected the
# original 24-32-query budget; with #4's 48-64 query budget, each specialist
# is assigned ~10-13 queries and the cap moves to match.
# P3b-v5 (2026-05-29): env-overridable to GROUND the leaf-aware length lever
# (PR-1). The Qianfan-replication build needs ~1.5-2× more grounded atoms to
# fill the longer ZH chapters with named/dated/cited primaries instead of prose
# padding. Default 12 = inert (PR lands dark); the dev6 arm sets =20. NOTE:
# raising this >12 requires THREE co-knobs moved together or results are
# silently lost:
#   1. orchestrator.BUDGET ≥ 5×this + 2 (enforced fail-loud there) or the
#      dispatch silently re-clamps the per-specialist slice.
#   2. DR_SPECIALIST_TIMEOUT_S ≥ 360s — at =20 the specialist wall-clock is
#      ~100s Exa + ~180s Nemotron + ~60s buffer ≈ 340s, past the 240s default
#      (the CAPEL smoke incident dropped specialists exactly this way).
#   3. DR_RESULTS_SERIALISATION_CAP — enforced fail-loud at the cap definition
#      below (cap ≥ searches×results×~1,600); at =20 that floor is ~320k, past
#      the 240k default, so set ≥~400k for headroom.
# Single source of truth for the inert default — orchestrator's co-knob #2
# timeout guard imports this constant so the "is the cap raised above inert?"
# threshold can never drift from the default applied here.
_MAX_SEARCHES_PER_SPECIALIST_DEFAULT = 12
_MAX_SEARCHES_PER_SPECIALIST = int_env("DR_MAX_SEARCHES_PER_SPECIALIST", _MAX_SEARCHES_PER_SPECIALIST_DEFAULT)
_RESULTS_PER_SEARCH = 10

# P2-Option-A-#4 Greptile PR #22 follow-up (2026-05-25): named cap on the
# serialised SEARCH RESULTS string sent to the extraction LLM. Pre-#4 the
# inline `[:42000]` truncation was fine because 5×5 raw hits × ~1,600 chars
# ≈ 40k chars fit comfortably under 42k. Post-#4 the same 5×5 → 12×10 raise
# pushes the payload to ~192k chars (12 searches × 10 results × ~1,600
# chars/result; per-result text is already capped at 1500 chars on line ~111
# plus title/url/date/qid + JSON syntax ≈ 1,600). With the cap still at 42k,
# only the first ~25 results — barely 2-3 of the 12 specialist searches —
# survived into the extraction LLM context; the remaining 8-9 searches' hits
# were silently dropped despite Exa cost having been incurred for them. Only
# the degraded `_snippet_fallback` path actually saw them.
#
# Raise the cap to fit the full expected post-#4 payload with ~25% headroom:
# 192k × 1.25 ≈ 240k chars. At ~4 chars/token, that's ~60k input tokens,
# well within Nemotron-3-Super-120B's 128k context (system+brief add ~5k
# tokens; output budget is 14k; total ~79k < 128k).
#
# P3b-v5 (2026-05-29): env-overridable alongside DR_MAX_SEARCHES_PER_SPECIALIST.
# At =20 searches the payload is 20×10×~1,600 ≈ 320k chars, overflowing the 240k
# default and silently slicing the last ~5 searches at json.dumps(results)[:cap]
# below (the exact PR #22 failure). The dev6 arm must set
# DR_RESULTS_SERIALISATION_CAP ≥ 320k × 1.25 ≈ 400k; both _MODEL_PAYLOAD_CAP_CHARS
# entries reference this constant, so the override propagates to the Nemotron +
# Tongyi caps (400k ≈ 100k input tokens — still within both models' 128k/131k
# contexts).
_RESULTS_SERIALISATION_CAP = int_env("DR_RESULTS_SERIALISATION_CAP", 240_000)

# P3b-v5 (2026-05-29): co-knob invariant, fail-loud — mirrors orchestrator.BUDGET.
# The cap and _MAX_SEARCHES_PER_SPECIALIST are co-dependent: the
# json.dumps(results)[:payload_cap] slice below truncates SILENTLY, so raising the
# search cap without raising the serialisation cap drops the tail searches' hits
# AFTER Exa cost was incurred (the PR #22 failure mode). Enforce cap ≥ the maximal
# expected payload (searches × results × ~1,600 chars/result) at import so the
# misconfiguration surfaces before any search runs, not silently mid-extraction.
_MIN_SERIALISATION_CAP = _MAX_SEARCHES_PER_SPECIALIST * _RESULTS_PER_SEARCH * 1_600
if _RESULTS_SERIALISATION_CAP < _MIN_SERIALISATION_CAP:
    raise RuntimeError(
        f"specialists._RESULTS_SERIALISATION_CAP={_RESULTS_SERIALISATION_CAP} < "
        f"_MAX_SEARCHES_PER_SPECIALIST({_MAX_SEARCHES_PER_SPECIALIST})×"
        f"_RESULTS_PER_SEARCH({_RESULTS_PER_SEARCH})×1600={_MIN_SERIALISATION_CAP}: "
        f"raise DR_RESULTS_SERIALISATION_CAP to ≥{_MIN_SERIALISATION_CAP} or the "
        f"json.dumps(results) slice silently drops the tail searches' hits with "
        f"Exa cost already incurred."
    )

# P2-Option-A-#4 Greptile PR #22 follow-up round 2 (2026-05-25):
# Per-model serialised-payload cap (chars). Sized so the payload fits
# within the model's advertised context window after reserving system
# prompt (~3k tokens) + brief (~2k tokens) + output (~14k tokens, see
# `max_tokens=14000` on the extraction call below):
#
#   safe_payload_chars ≤ (context_tokens - 3k_sys - 2k_brief - 14k_out) * 4
#
# Empty string `""` = no override = default specialists model
# (Nemotron-3-Super-120B). Greptile flagged that the single 240k cap was
# Nemotron-calibrated but applied uniformly to the model_override path, so
# a narrower override could silently truncate at its API layer or fall
# through to `_snippet_fallback` — Exa cost incurred with no extraction
# benefit. Making the cap per-model puts the context check at the same
# diff site as any new route added in orchestrator.py: adding a route
# without an entry here trips the unknown-override warning below.
_MODEL_PAYLOAD_CAP_CHARS = {
    # Nemotron-3-Super-120B: 128k ctx (≈109k tokens free after reservation
    # → ~436k chars available). We use the calibrated 240k (per #4
    # commentary above; cap is "what we actually need", not "what fits").
    "": _RESULTS_SERIALISATION_CAP,
    # Tongyi-DeepResearch-30B-A3B: 131k ctx (verified via OpenRouter model
    # card 2026-05-25 — https://openrouter.ai/alibaba/tongyi-deepresearch-30b-a3b).
    # ~112k tokens free after reservation → ~448k chars available;
    # symmetric to Nemotron, use the same 240k cap.
    "alibaba/tongyi-deepresearch-30b-a3b": _RESULTS_SERIALISATION_CAP,
}

# Conservative fallback for an unknown model_override. Sized for a 32k-ctx
# model (the smallest a commercial frontier extraction model is likely to
# advertise): 32k - 19k reservation = 13k input tokens free ≈ 52k chars,
# rounded down for safety. Better to under-fill the context (degraded
# extraction quality, but findings still produced) than to silently exceed
# it (API-layer truncation → `_snippet_fallback` catches the JSON parse
# failure → Exa cost incurred for nothing).
_UNKNOWN_OVERRIDE_PAYLOAD_CAP_CHARS = 48_000

# Dedupe set so the unknown-override warning fires once per (process,
# model) rather than once per task per specialist (would be ~30 lines of
# noise per dev4 run).
_warned_unknown_overrides: set[str] = set()


def _payload_cap_for(model_override: str) -> int:
    """Resolve the serialised-payload cap (chars) for the extraction call,
    keyed on the active `model_override`. Unknown override → emits a
    one-shot stderr warning and returns the conservative 48k cap.

    Operator action on hitting the warning: add the new model's entry to
    `_MODEL_PAYLOAD_CAP_CHARS` above with its verified context window
    BEFORE routing additional traffic through it.
    """
    if model_override in _MODEL_PAYLOAD_CAP_CHARS:
        return _MODEL_PAYLOAD_CAP_CHARS[model_override]
    if model_override not in _warned_unknown_overrides:
        _warned_unknown_overrides.add(model_override)
        print(
            f"[specialists] model_override={model_override!r} not in "
            f"_MODEL_PAYLOAD_CAP_CHARS — using conservative "
            f"{_UNKNOWN_OVERRIDE_PAYLOAD_CAP_CHARS}-char cap (sized for "
            f"32k-ctx model). Add this model's verified context window "
            f"to the registry to lift the cap.",
            file=sys.stderr,
            flush=True,
        )
    return _UNKNOWN_OVERRIDE_PAYLOAD_CAP_CHARS


# Cap on the degraded snippet-fallback path. Held to match
# _EXTRACT_SYSTEM's 14-24 finding ceiling so the fallback path doesn't
# produce more atoms than the LLM-extract path's upper bound (avoids
# inconsistent atom counts between tasks depending on which path fired).
_FALLBACK_CAP = 24


def _snippet_fallback(results, query_ids):
    """Degrade gracefully: turn raw search hits into evidence atoms."""
    out = []
    # Cap matches the new _EXTRACT_SYSTEM finding ceiling (14-24); fallback
    # path should not produce more atoms than the LLM extract path would.
    for r in results[:_FALLBACK_CAP]:
        txt = (r.get("text") or r.get("title") or "").strip()
        if not txt:
            continue
        out.append(
            {
                "statement": txt[:400],
                "source_name": (r.get("title") or r.get("url") or "")[:80],
                "url": r.get("url", ""),
                "quote": txt[:120],
                "query_ids": query_ids,
            }
        )
    return out


def research(
    role: str,
    queries: list,
    *,
    language: str,
    domain: str,
    exa_mode: str,
    model_override: str = "",
    sink: dict | None = None,
) -> dict:
    """queries: [{id,text,target_sections}] from the Architect plan for this
    specialist. Returns {role, findings:[...], n_searches}.

    model_override: optional model slug to use instead of role's configured
    model (used for per-archetype routing — e.g. Tongyi-DR for list-all).

    sink (round 4, 2026-05-31): an optional caller-owned dict with keys
    "findings" (list) and "n_searches" (int). When provided, this loop writes
    its progress THROUGH the sink as it searches — after each search the sink's
    findings are refreshed to the snippet-fallback of the hits gathered so far,
    and on a successful extract the richer extracted findings overwrite them.
    A caller that wall-clock-times-out the call (orchestrator
    `_research_with_timeout`) can then recover the partial coverage gathered
    before the cut (as snippets) instead of dropping the whole specialist's
    role. The search loop dominates wall-clock, so a mid-search timeout still
    yields the completed searches' evidence. Dict mutation is GIL-atomic and the
    caller snapshots, so the worst case is missing the single in-flight search.
    """
    role = role if role in _ROLE else "generalist"
    rdesc = _ROLE[role]
    qids = [str(q.get("id")) for q in queries]

    results, n = [], 0
    for q in queries[:_MAX_SEARCHES_PER_SPECIALIST]:  # bumped to 12 in #4
        qtext = q.get("text") or ""
        if not qtext:
            continue
        for h in domain_routed.search(
            qtext, language=language, domain=domain, mode=exa_mode, num_results=_RESULTS_PER_SEARCH
        ):
            results.append(
                {
                    "title": h["title"],
                    "url": h["url"],
                    "text": h["text"][:1500],
                    "date": h.get("published_date", ""),
                    "qid": str(q.get("id")),
                }
            )
        n += 1
        # Partial-progress write: refresh the sink with the best-available
        # (snippet-fallback) findings + search count so a timeout mid-loop
        # recovers the searches done so far rather than dropping the role.
        if sink is not None:
            sink["n_searches"] = n
            sink["findings"] = _snippet_fallback(results, qids) if results else []

    if not results:
        return {"role": role, "findings": [], "n_searches": n}

    brief = "\n".join(f"[{q.get('id')}] {q.get('text', '')}" for q in queries)
    # Greptile PR #22 follow-up round 2 (2026-05-25): resolve the cap per
    # active extraction model. See `_payload_cap_for` above for the registry
    # and the unknown-override fallback rationale.
    payload_cap = _payload_cap_for(model_override)
    user = f"BRIEF ({language}):\n{brief}\n\nSEARCH RESULTS:\n" + json.dumps(results, ensure_ascii=False)[:payload_cap]
    try:
        if model_override:
            # Route to override (Tongyi-DR for list-all/explain-mechanism)
            # via raw openrouter call; same system prompt, same JSON contract.
            from ..clients import openrouter_client

            sys_prompt = _EXTRACT_SYSTEM.format(role=rdesc)
            raw, _ = openrouter_client.raw_call(
                model_override, user, system=sys_prompt, max_tokens=14000, note=f"{role}.extract.override", provider=""
            )
            fobj = llm.extract_json(raw) if raw else {}
        else:
            fobj = llm.call_json(
                role,
                user,
                system=_EXTRACT_SYSTEM.format(role=rdesc),
                max_tokens=14000,
                note=f"{role}.extract",
                retries=1,
            )
        findings = fobj.get("findings") if isinstance(fobj, dict) else fobj
        findings = [f for f in (findings or []) if isinstance(f, dict) and f.get("statement")]
        # P3-W0b (2026-05-27): sanitize the optional `chain` field on
        # every finding. Findings without `chain` are unaffected; findings
        # with a malformed `chain` get it dropped (sanitized to []). A
        # field that survives sanitization is guaranteed to be list[str]
        # downstream — no type-checks needed in orchestrator.ingest or
        # writer.ev_view construction.
        for f in findings:
            f["chain"] = _sanitize_chain(f.get("chain"))
        if not findings:
            findings = _snippet_fallback(results, qids)
    except Exception:  # noqa: BLE001  reasoning model JSON failure → degrade
        findings = _snippet_fallback(results, qids)
    # Upgrade the sink to the richer extracted findings now that they exist
    # (the in-loop writes only had snippet fallbacks).
    if sink is not None:
        sink["findings"] = findings
        sink["n_searches"] = n
    return {"role": role, "findings": findings, "n_searches": n}
