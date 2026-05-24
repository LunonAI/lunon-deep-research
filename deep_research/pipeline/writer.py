"""WebWeaver hierarchical writer (p1-checklist items 13, 25; arXiv 2509.13312).

Writes the report PER SECTION. For each section it retrieves ONLY that
section's evidence from the WebWeaver memory bank (by citation ID) — the writer
never sees the full evidence corpus (item 25 context boundary). Opus 4.7.
Applies the differentiator writing rules (opening template, insight minimums,
cleaning-resistant attribution, length governor) via writing_rules.writer_system.

P2-Wave-2-A wires CAPEL inline countdown markers (writing_rules.capel_directive)
into each section prompt, then strips them via `_capel_strip.strip_capel_markers`
before returning. P2-Wave-2-G propagates `task_id` to `writer_system` so the
W9-readability fragile-density heuristic can omit `_DEDUP_RULE` when appropriate.
Both default on post-sanity-4 hardcode; set `DR_CAPEL_G=off` to disable
(kill-switch for debug / fall-back).
"""

import json
import os

from .. import llm
from .. import writing_rules as wr
from ._capel_strip import strip_capel_markers


def _capel_g_on() -> bool:
    # P2-Wave-2 hardcoded post-sanity-4 (2026-05-23: paired ΔO +0.0034 vs B0
    # on n=3, 0 marker leaks, ΔReadability +0.0213 firing as designed across
    # both EN+ZH). `DR_CAPEL_G=off` retained as a kill-switch only — set to
    # disable CAPEL countdown markers + G's W9-readability dedup-rule
    # suppression in one go (debug / fall-back path).
    return os.environ.get("DR_CAPEL_G", "on") != "off"


def outline_units(plan):
    """Flatten the Architect TOC into ordered section units.

    Each subsection includes its `depth_seeds` (post-P2-Option-A-#1): 2-4
    short claim/entity/data-point phrases that the writer should populate
    as H4 sub-sub-sections under the H3 subsection. Pre-#1 plans had no
    depth_seeds field — architect._normalize backfills an empty list, which
    the writer treats as "no architect guidance, populate as you see fit".
    """
    units = []
    for s in plan.get("report_toc", []):
        subs = []
        for sub in s.get("subsections", []) or []:
            subs.append(
                {
                    "id": sub.get("id"),
                    "title": sub.get("title", ""),
                    "depth_seeds": sub.get("depth_seeds", []) or [],
                }
            )
        units.append(
            {
                "id": s.get("id"),
                "title": s.get("title", ""),
                "level": 1,
                "subs": subs,
                "depth": s.get("depth_target", "broad"),
            }
        )
    return units


def _acs_for_section(plan, sid):
    out = []
    for a in plan.get("acceptance_criteria", []):
        ts = a.get("target_sections", [])
        if sid in ts or sid.split(".")[0] in ts or not ts:
            out.append({"id": a.get("id"), "text": a.get("text"), "verification": a.get("verification", "")})
    return out[:14]


def write_opening(plan, prompt, language, archetype, domain, digest, *, task_id=None):
    """Position-1 opening / executive frame (item 17). Uses the compressed
    digest (a synthesis input, not a full per-section evidence dump).

    Opening NEVER gets CAPEL markers — the position-1 template is already
    tightly length-controlled (~200 tokens) and CAPEL counter-overhead is
    not worth it for such a small target. `task_id` propagates for parity
    with `write_section` but the opening's `_DEDUP_RULE` decision matches
    section behavior (G suppresses there too for consistency).
    """
    sys = wr.writer_system(
        archetype,
        domain,
        language,
        [s.get("title") for s in plan.get("report_toc", [])],
        task_id=task_id,
    )
    user = (
        f"PROMPT ({language}):\n{prompt}\n\nREPORT TITLE: "
        f"{plan.get('report_title', '')}\n\nEVIDENCE DIGEST (synthesis "
        f"input):\n{digest[:18000]}\n\nWrite ONLY the report title (as "
        f"'# Title') followed by the OPENING per the position-1 rule "
        f"(~200 tokens, hard max ~300). Then STOP — sections follow "
        f"separately."
    )
    return llm.call("writer", user, system=sys, max_tokens=1400, note="writer.open")


def write_section(
    unit,
    plan,
    bank,
    *,
    prompt,
    language,
    archetype,
    domain,
    prior_titles,
    feedback="",
    task_id=None,
    target_tokens=None,
):
    """Write one section using ONLY this section's memory-bank evidence.

    Returns (text, stats) where stats = {n_markers_stripped, n_violations}
    when CAPEL is active, else stats has all zeros. Callers may discard
    stats with `text, _ = write_section(...)` when telemetry is not needed.
    """
    sid = unit["id"]
    evidence = bank.for_section(sid)
    ev_view = [{"eid": e["eid"], "source_name": e["source_name"], "url": e["url"], "text": e["text"]} for e in evidence]
    sys = wr.writer_system(
        archetype,
        domain,
        language,
        [s.get("title") for s in plan.get("report_toc", [])],
        task_id=task_id,
    )

    capel_block = ""
    capel_active = _capel_g_on() and target_tokens and target_tokens > 0
    if capel_active:
        capel_block = "\n\n" + wr.capel_directive(int(target_tokens))

    # SUBSECTIONS payload (P2-Option-A-#1): each subsection carries its
    # depth_seeds list. The writer renders each subsection as an H3 and
    # populates each depth_seed as an H4 sub-sub-section. Old plans without
    # depth_seeds present an empty list, in which case the writer is told
    # to choose its own H4 leaves (back-compat).
    has_any_seeds = any(sub.get("depth_seeds") for sub in unit["subs"])
    depth_block = (
        "DEPTH POPULATION — REQUIRED:\n"
        "For each H3 subsection above, render ALSO each of its depth_seeds "
        "as an H4 sub-sub-section (####). Each H4 leaf = a focused 400-800 "
        "word treatment of one depth_seed (named entity, claim, data point, "
        "or comparison). If a subsection has no depth_seeds, pick 2-4 H4 "
        "leaves yourself based on the prompt + evidence — do not skip the "
        "depth tier.\n"
        if has_any_seeds
        else "DEPTH POPULATION: pick 2-4 H4 sub-sub-sections per H3 subsection "
        "(architect did not pre-seed them). Each H4 leaf = a focused 400-800 "
        "word treatment of a specific entity, claim, or comparison.\n"
    )

    # P2-Option-A-#7: surface the entity_matrix (when present) to the writer
    # for list-all/compare archetypes. The matrix is the article's structural
    # spine; the writer renders it as a table early in the article (typically
    # in the first or second top section) AND uses it to enforce equal-depth
    # treatment per entity downstream. Other archetypes don't see the matrix.
    entity_matrix_block = ""
    em = plan.get("entity_matrix")
    if archetype in {"list-all", "compare"} and isinstance(em, dict) and em.get("entities"):
        entity_matrix_block = (
            f"\nENTITY MATRIX (article spine for this archetype) — "
            f"render this as a markdown table near the article start and "
            f"give EACH entity equal-depth treatment in the downstream "
            f"sections (no entity dropped, no entity over-weighted vs "
            f"siblings):\n"
            f"{json.dumps(em, ensure_ascii=False)}\n"
        )

    user = (
        f"PROMPT ({language}):\n{prompt}\n\n"
        f"You are writing ONLY this section of the report (other sections are "
        f"written separately — do not write them, do not repeat the opening).\n"
        f"SECTION {sid}: {unit['title']}\n"
        f"SUBSECTIONS (with depth_seeds for H4 leaves): "
        f"{json.dumps(unit['subs'], ensure_ascii=False)}\n"
        f"DEPTH TARGET: {unit['depth']}\n"
        f"{depth_block}"
        f"{entity_matrix_block}"
        f"REPORT OUTLINE (titles only, for coherence): "
        f"{json.dumps(prior_titles, ensure_ascii=False)}\n\n"
        f"ACCEPTANCE CRITERIA THIS SECTION MUST SATISFY:\n"
        f"{json.dumps(_acs_for_section(plan, sid), ensure_ascii=False)}\n\n"
        f"EVIDENCE FOR THIS SECTION ONLY (cite by inline source NAME; you may "
        f"also add a numeric [n] but the sentence must stand without it):\n"
        f"{json.dumps(ev_view, ensure_ascii=False)[:42000]}\n"
        f"{capel_block}"
    )
    if feedback:
        user += f"\nREVISION FEEDBACK — fix these and integrate the cited evidence inline:\n{feedback}\n"
    # Bumped from 7000 → 14000 to accommodate the deeper H3→H4 tree the
    # depth_seeds drive. This is the LLM-call upper bound; in production with
    # `DR_CAPEL_G=on` (the default) the per-section CAPEL countdown — driven
    # by `target_tokens` ≈ length_ceiling/0.75/n_top_sections (≈2.5-3.5k tokens
    # for the typical 8-12-section plan) — is the OPERATIVE per-section cap,
    # not max_tokens. The 14k headroom matters in three cases: (a) CAPEL
    # disabled (`DR_CAPEL_G=off`); (b) degenerate TOCs with <=4 sections where
    # weight-share + `SECTION_BUDGET_CEILING=20_000` push target_tokens past
    # 7k; (c) refiner-pass output that needs room to grow. The "depth uplift"
    # PR #20 promises lands primarily via (i) the architect's deeper outline
    # (more sections × more H3 × explicit depth_seeds payload) and (ii) the
    # length_ceiling 2.2× bump that lifts the per-section CAPEL target —
    # NOT primarily via this max_tokens headroom.
    raw = llm.call("writer", user, system=sys, max_tokens=14000, note=f"writer.sec.{sid}")
    if capel_active:
        text, stats = strip_capel_markers(raw)
        return text, stats
    return raw, {"n_markers_stripped": 0, "n_violations": 0}


def assemble(opening: str, sections: list) -> str:
    return opening.strip() + "\n\n" + "\n\n".join(s.strip() for s in sections)
