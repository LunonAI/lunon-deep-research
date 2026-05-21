"""init_format node (p1-checklist item 34; LINK-Researcher pipeline node 8).

Runs after design_guide, before writer. Produces a typed Scaffold dataclass
listing every section with section_id, title, subsections, expected_length
tokens, assigned specialists (which researchers' evidence feeds this section).

Distinct from the Architect plan: Architect plans what to RESEARCH; init_format
plans what the REPORT looks like structurally. The writer fills this scaffold;
the validator checks against it (every section >= 0.7 of expected length).

Length budgeting respects the per-domain governor (writing_rules.length_ceiling).
"""
from dataclasses import dataclass

from .. import writing_rules as wr
from ..node_wrap import node
from ..state import Scaffold, ScaffoldSection

# rough token-per-word factor for English-style writers
_WORDS_PER_TOKEN = 0.75


@dataclass
class InitFormatInput:
    plan: dict           # from architect
    language: str
    domain: str


@dataclass
class InitFormatOutput:
    scaffold: Scaffold


def _section_specialists(section_id: str, plan: dict) -> list:
    """Which specialists' queries target this section?"""
    out = set()
    for q in plan.get("queries", []):
        if section_id in (q.get("target_sections") or []):
            r = q.get("specialist_role")
            if r:
                out.add(r)
    return sorted(out)


@node("init_format")
def run(inp: InitFormatInput) -> InitFormatOutput:
    toc = inp.plan.get("report_toc", []) or []
    if not toc:
        return InitFormatOutput(scaffold=Scaffold(sections=[], total_target_tokens=0))

    # Domain length governor → median word_len from reference_catalog.jsonl.
    median_words = wr.length_ceiling(inp.domain)
    total_tokens = int(median_words / _WORDS_PER_TOKEN)

    # Depth-weighted allocation: 'deep' sections get 1.5x, 'broad' 1.0x.
    weights = [1.5 if s.get("depth_target") == "deep" else 1.0 for s in toc]
    weight_sum = sum(weights) or len(toc)

    sections = []
    for i, s in enumerate(toc):
        sid = s.get("id", f"S{i+1}")
        share = total_tokens * weights[i] / weight_sum
        expected = max(800, int(share))
        sections.append(ScaffoldSection(
            section_id=sid,
            title=s.get("title", f"Section {i+1}"),
            subsections=[ss.get("title", "") for ss in s.get("subsections", [])],
            expected_length_tokens=expected,
            assigned_specialists=_section_specialists(sid, inp.plan),
        ))

    return InitFormatOutput(scaffold=Scaffold(
        sections=sections, total_target_tokens=total_tokens))
