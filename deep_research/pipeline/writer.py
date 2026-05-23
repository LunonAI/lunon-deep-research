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


# P2-Wave-2.5-D1 Greptile follow-up (PR #12): hard cap for a single writer
# LLM call. Opus 4.7's per-call output budget is comfortably > 16k tokens with
# the extended-output beta; 16000 leaves headroom for system prompt overhead
# and matches the SECTION_BUDGET_CEILING in init_format.py (9500 × 1.4 ≈ 13300,
# well within this cap). Anthropic anthropic_client.py already accepts up to
# 32000, so this is a conservative middle ground that pairs with the scaffold
# clamp to guarantee validator-reachable sections.
WRITER_CALL_TOKEN_CAP = 16_000


def outline_units(plan):
    """Flatten the Architect TOC into ordered section units."""
    units = []
    for s in plan.get("report_toc", []):
        units.append(
            {
                "id": s.get("id"),
                "title": s.get("title", ""),
                "level": 1,
                "subs": s.get("subsections", []),
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

    P2-Wave-2.5-D1: `report_depth_tier` flows from architect plan → writer_system
    so the LENGTH SERVES SUBSTANCE directive emits the correct target.
    """
    depth_tier = plan.get("report_depth_tier")
    sys = wr.writer_system(
        archetype,
        domain,
        language,
        [s.get("title") for s in plan.get("report_toc", [])],
        task_id=task_id,
        depth_tier=depth_tier,
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
        depth_tier=plan.get("report_depth_tier"),
    )

    capel_block = ""
    capel_active = _capel_g_on() and target_tokens and target_tokens > 0
    if capel_active:
        capel_block = "\n\n" + wr.capel_directive(int(target_tokens))

    user = (
        f"PROMPT ({language}):\n{prompt}\n\n"
        f"You are writing ONLY this section of the report (other sections are "
        f"written separately — do not write them, do not repeat the opening).\n"
        f"SECTION {sid}: {unit['title']}\n"
        f"SUBSECTIONS: {json.dumps(unit['subs'], ensure_ascii=False)}\n"
        f"DEPTH TARGET: {unit['depth']}\n"
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
    # P2-Wave-2.5-D1 Greptile follow-up (PR #12, second round): wire the
    # WRITER_CALL_TOKEN_CAP constant into the actual llm.call so the cap
    # documented in init_format / tests / module-level comments matches
    # production behavior. Pre-fix the constant existed but the call still
    # used the legacy literal 7000 — for a section budgeted at
    # SECTION_BUDGET_CEILING=9500, the validator's 0.7× pass-line is 6650,
    # within the literal 7000 by only 350 tokens. Any future bump to the
    # ceiling (e.g. 10001) would push the pass-line above 7000 and
    # systematically fail validation. Scaling max_tokens with target_tokens
    # restores the documented relationship.
    if target_tokens and target_tokens > 0:
        section_max_tokens = min(WRITER_CALL_TOKEN_CAP, max(7_000, int(target_tokens * 1.4)))
    else:
        section_max_tokens = 7_000
    raw = llm.call("writer", user, system=sys, max_tokens=section_max_tokens, note=f"writer.sec.{sid}")
    if capel_active:
        text, stats = strip_capel_markers(raw)
        return text, stats
    return raw, {"n_markers_stripped": 0, "n_violations": 0}


def assemble(opening: str, sections: list) -> str:
    return opening.strip() + "\n\n" + "\n\n".join(s.strip() for s in sections)
