"""WebWeaver hierarchical writer (p1-checklist items 13, 25; arXiv 2509.13312).

Writes the report PER SECTION. For each section it retrieves ONLY that
section's evidence from the WebWeaver memory bank (by citation ID) — the writer
never sees the full evidence corpus (item 25 context boundary). Opus 4.7.
Applies the differentiator writing rules (opening template, insight minimums,
cleaning-resistant attribution, length governor) via writing_rules.writer_system.
"""
import json

from .. import llm
from .. import writing_rules as wr


def outline_units(plan):
    """Flatten the Architect TOC into ordered section units."""
    units = []
    for s in plan.get("report_toc", []):
        units.append({"id": s.get("id"), "title": s.get("title", ""),
                       "level": 1, "subs": s.get("subsections", []),
                       "depth": s.get("depth_target", "broad")})
    return units


def _acs_for_section(plan, sid):
    out = []
    for a in plan.get("acceptance_criteria", []):
        ts = a.get("target_sections", [])
        if sid in ts or sid.split(".")[0] in ts or not ts:
            out.append({"id": a.get("id"), "text": a.get("text"),
                        "verification": a.get("verification", "")})
    return out[:14]


def write_opening(plan, prompt, language, archetype, domain, digest):
    """Position-1 opening / executive frame (item 17). Uses the compressed
    digest (a synthesis input, not a full per-section evidence dump)."""
    sys = wr.writer_system(archetype, domain, language,
                           [s.get("title") for s in plan.get("report_toc", [])])
    user = (f"PROMPT ({language}):\n{prompt}\n\nREPORT TITLE: "
            f"{plan.get('report_title','')}\n\nEVIDENCE DIGEST (synthesis "
            f"input):\n{digest[:18000]}\n\nWrite ONLY the report title (as "
            f"'# Title') followed by the OPENING per the position-1 rule "
            f"(~200 tokens, hard max ~300). Then STOP — sections follow "
            f"separately.")
    return llm.call("writer", user, system=sys, max_tokens=1400, note="writer.open")


def write_section(unit, plan, bank, *, prompt, language, archetype, domain,
                   prior_titles, feedback=""):
    """Write one section using ONLY this section's memory-bank evidence."""
    sid = unit["id"]
    evidence = bank.for_section(sid)
    src_table = bank.source_table()
    ev_view = [{"eid": e["eid"], "source_name": e["source_name"],
                "url": e["url"], "text": e["text"]} for e in evidence]
    sys = wr.writer_system(archetype, domain, language,
                           [s.get("title") for s in plan.get("report_toc", [])])
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
    )
    if feedback:
        user += (f"\nREVISION FEEDBACK — fix these and integrate the cited "
                 f"evidence inline:\n{feedback}\n")
    return llm.call("writer", user, system=sys,
                    max_tokens=7000, note=f"writer.sec.{sid}")


def assemble(opening: str, sections: list) -> str:
    return opening.strip() + "\n\n" + "\n\n".join(s.strip() for s in sections)
