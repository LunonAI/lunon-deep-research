"""WebWeaver hierarchical writer (p1-checklist items 13, 25; arXiv 2509.13312).

Writes the report PER SECTION. For each section it retrieves ONLY that
section's evidence from the WebWeaver memory bank (by citation ID) — the writer
never sees the full evidence corpus (item 25 context boundary). Opus 4.7.
Applies the differentiator writing rules (opening template, insight minimums,
cleaning-resistant attribution, length governor) via writing_rules.writer_system.

P2-Wave-1-B2 (2026-05-22): writer is now WebWeaver-style aware. When
`DR_WEBWEAVER != "off"`:
  - evidence retrieval uses `bank.for_section_pruned(sid, mode=DR_WEBWEAVER)`
    so non-primary cross-cutting evidence becomes a `see_elsewhere` placeholder
    that the writer cites by source name only;
  - the writer prompt receives a PRIOR SECTIONS WRITTEN block (passed by the
    orchestrator's serial-write loop), letting later sections build on earlier
    sections' framing by reference instead of restating their analysis.
The legacy parallel path (DR_WEBWEAVER=off, default) is byte-identical to
pre-Wave-1 behavior — the new code paths only fire when the env flag is set.
"""

import json
import os

from .. import llm
from .. import writing_rules as wr


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


def write_opening(plan, prompt, language, archetype, domain, digest):
    """Position-1 opening / executive frame (item 17). Uses the compressed
    digest (a synthesis input, not a full per-section evidence dump)."""
    sys = wr.writer_system(archetype, domain, language, [s.get("title") for s in plan.get("report_toc", [])])
    user = (
        f"PROMPT ({language}):\n{prompt}\n\nREPORT TITLE: "
        f"{plan.get('report_title', '')}\n\nEVIDENCE DIGEST (synthesis "
        f"input):\n{digest[:18000]}\n\nWrite ONLY the report title (as "
        f"'# Title') followed by the OPENING per the position-1 rule "
        f"(~200 tokens, hard max ~300). Then STOP — sections follow "
        f"separately."
    )
    return llm.call("writer", user, system=sys, max_tokens=1400, note="writer.open")


def _build_ev_view(evidence: list[dict]) -> list[dict]:
    """Render evidence (possibly including placeholders) into the writer-prompt
    JSON view. Placeholder entries carry `see_elsewhere: true` and no text/url —
    the writer is instructed to cite them by source name only."""
    view = []
    for e in evidence:
        if e.get("placeholder"):
            view.append(
                {
                    "eid": e["eid"],
                    "source_name": e.get("source_name", ""),
                    "see_elsewhere": True,
                    "primary_section_id": e.get("primary_section_id"),
                }
            )
        else:
            view.append(
                {
                    "eid": e["eid"],
                    "source_name": e.get("source_name", ""),
                    "url": e.get("url", ""),
                    "text": e.get("text", ""),
                }
            )
    return view


_B3_DIRECTIVE = (
    "WAVE-1-B3 CROSS-SECTION DIRECTIVE — ENFORCED:\n"
    "You have access to PRIOR SECTIONS WRITTEN (above, if any) and to "
    "evidence entries marked `see_elsewhere: true` (in the evidence list).\n"
    "  1. PRIOR SECTIONS: build on their framing and central claims BY "
    "REFERENCE — cite their conclusions briefly to set up your own "
    "contribution, but do NOT restate their underlying analysis or "
    "re-derive their results. Redundancy across sections is the #1 "
    "reader-fatigue complaint. Your section must ADVANCE the report.\n"
    "  2. `see_elsewhere` EVIDENCE: those entries belong to another "
    "section's primary scope. You may cite them by source NAME (e.g. "
    "'as McKinsey 2025 establishes...') to acknowledge prior coverage, "
    "but do NOT restate the underlying claim, number, or methodology — "
    "those are owned by the other section."
)


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
    prior_sections=None,
):
    """Write one section using ONLY this section's memory-bank evidence.

    P2-Wave-1-B2: when ``DR_WEBWEAVER != "off"``, evidence retrieval becomes
    mode-aware (non-primary cross-cutting eids become `see_elsewhere`
    placeholders) and an optional ``prior_sections`` list contributes a
    PRIOR SECTIONS WRITTEN context block + the B3 cross-section directive.
    Legacy path (``DR_WEBWEAVER=off``, default) preserves the exact
    pre-Wave-1 prompt shape.
    """
    sid = unit["id"]
    mode = os.environ.get("DR_WEBWEAVER", "off")
    if mode == "off":
        evidence = bank.for_section(sid)
    else:
        evidence = bank.for_section_pruned(sid, mode=mode)
    ev_view = _build_ev_view(evidence)
    sys = wr.writer_system(archetype, domain, language, [s.get("title") for s in plan.get("report_toc", [])])

    prior_block = ""
    if mode != "off" and prior_sections:
        # Each prior section: {sid, title, summary} — summary is the first
        # ~200 words of the prior section's written draft. Keeps the
        # accumulated context bounded across N sections.
        lines = ["\nPRIOR SECTIONS WRITTEN (build on these by reference; do NOT restate):\n"]
        for ps in prior_sections:
            lines.append(f"\n§{ps.get('sid', '?')} — {ps.get('title', '')}")
            lines.append(f"Central frame: {ps.get('summary', '')}\n")
        prior_block = "".join(lines)

    user = (
        f"PROMPT ({language}):\n{prompt}\n\n"
        f"You are writing ONLY this section of the report (other sections are "
        f"written separately — do not write them, do not repeat the opening).\n"
        f"SECTION {sid}: {unit['title']}\n"
        f"SUBSECTIONS: {json.dumps(unit['subs'], ensure_ascii=False)}\n"
        f"DEPTH TARGET: {unit['depth']}\n"
        f"REPORT OUTLINE (titles only, for coherence): "
        f"{json.dumps(prior_titles, ensure_ascii=False)}\n\n"
        f"{prior_block}"
        f"ACCEPTANCE CRITERIA THIS SECTION MUST SATISFY:\n"
        f"{json.dumps(_acs_for_section(plan, sid), ensure_ascii=False)}\n\n"
        f"EVIDENCE FOR THIS SECTION ONLY (cite by inline source NAME; you may "
        f"also add a numeric [n] but the sentence must stand without it):\n"
        f"{json.dumps(ev_view, ensure_ascii=False)[:42000]}\n"
    )
    if mode != "off":
        user += f"\n{_B3_DIRECTIVE}\n"
    if feedback:
        user += f"\nREVISION FEEDBACK — fix these and integrate the cited evidence inline:\n{feedback}\n"
    return llm.call("writer", user, system=sys, max_tokens=7000, note=f"writer.sec.{sid}")


def assemble(opening: str, sections: list) -> str:
    return opening.strip() + "\n\n" + "\n\n".join(s.strip() for s in sections)
