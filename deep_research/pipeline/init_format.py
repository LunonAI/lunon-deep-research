"""init_format node (p1-checklist item 34; LINK-Researcher pipeline node 8).

Runs after design_guide, before writer. Produces a typed Scaffold dataclass
listing every section with section_id, title, subsections, expected_length
tokens, assigned specialists (which researchers' evidence feeds this section).

Distinct from the Architect plan: Architect plans what to RESEARCH; init_format
plans what the REPORT looks like structurally. The writer fills this scaffold;
the validator checks against it (every section >= 0.7 of expected length).

P2-Wave-2.5-D1: length budgeting uses `writing_rules.length_target()` with
the architect-emitted `report_depth_tier` (compact/standard/deep/comprehensive),
falling back to archetype-default when the plan doesn't specify. Total target
tokens are now archetype × depth_tier scaled — see
p2_artifacts/reference_findings.md §F1 for the calibration.
"""

from dataclasses import dataclass

from .. import writing_rules as wr
from ..node_wrap import node
from ..state import Scaffold, ScaffoldSection

# rough token-per-word factor for English-style writers
_WORDS_PER_TOKEN = 0.75


@dataclass
class InitFormatInput:
    plan: dict  # from architect
    language: str
    domain: str
    archetype: str = ""


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

    # P2-Wave-2.5-D1 article-level target. The architect MAY emit
    # `report_depth_tier`; if not, archetype-default applies. ZH adjusts
    # the unit from words to CJK-char-equivalents inside length_target().
    plan_tier = inp.plan.get("report_depth_tier")
    target_units = wr.length_target(
        inp.domain,
        archetype=inp.archetype,
        depth_tier=plan_tier,
        language=inp.language,
    )
    # Convert article-level units back to tokens for the per-section budget.
    # For EN: units == words. For ZH: units == CJK chars ≈ 2 words.
    # Tokens ≈ words / _WORDS_PER_TOKEN ≈ 1.33 × words.
    if inp.language == "zh":
        equiv_words = target_units / 2
    else:
        equiv_words = target_units
    total_tokens = int(equiv_words / _WORDS_PER_TOKEN)

    # Depth-weighted per-section allocation: architect's per-section
    # `depth_target` ("deep" vs "broad") still scales individual section share.
    weights = [1.5 if s.get("depth_target") == "deep" else 1.0 for s in toc]
    weight_sum = sum(weights) or len(toc)

    sections = []
    for i, s in enumerate(toc):
        sid = s.get("id", f"S{i + 1}")
        share = total_tokens * weights[i] / weight_sum
        expected = max(800, int(share))
        sections.append(
            ScaffoldSection(
                section_id=sid,
                title=s.get("title", f"Section {i + 1}"),
                subsections=[ss.get("title", "") for ss in s.get("subsections", [])],
                expected_length_tokens=expected,
                assigned_specialists=_section_specialists(sid, inp.plan),
            )
        )

    return InitFormatOutput(scaffold=Scaffold(sections=sections, total_target_tokens=total_tokens))
