"""design_guide node (p1-checklist item 33; LINK-Researcher init_design_guide).

Runs after architect.py, before init_format. Produces a typed DesignGuide
encoding stylistic + structural conventions for this specific report.

CRITICAL (directive): content is derived from `p0_artifacts/judge_preferences.md`
— the actual GPT-5.5 judge target — NOT from LINK-Researcher's stylistic
defaults. We adopt LINK's pipeline SHAPE; our P0 catalog provides the CONTENT.

Output (DesignGuide) is consumed by writer.py, refiner.py, zh_writer_pass.py,
and validation.py — every downstream call sees the SAME guide.
"""
import json
from dataclasses import dataclass

from .. import llm
from .. import writing_rules as wr
from ..node_wrap import node
from ..state import DesignGuide


@dataclass
class DesignGuideInput:
    query: str
    language: str
    archetype: str
    domain: str
    persona: str          # from role_play
    plan: dict            # from architect


@dataclass
class DesignGuideOutput:
    guide: DesignGuide


# ---- Content derived from p0_artifacts/judge_preferences.md ----
# Rewards/penalties + cleaning-resistant rule are P0 catalog → judge target.
# (See p0_artifacts/judge_preferences.md §§ rewards/penalties; cleaner_behavior.md)
_REWARDS = [
    "Make every prompt-required item a visible section, subsection, or table column.",
    "Provide requested metrics explicitly (CAGR, market size, MAE/RMSE, "
    "projections) — never substitute 'trends'/'growth' for the number.",
    "Explain causal mechanisms as step-by-step chains showing each intermediate "
    "link; reject single-step assertions that skip the intervening mechanism.",
    "Build entity×dimension comparison MATRICES whenever multiple entities are "
    "compared — judge rewards matrices over scattered prose.",
    "Lead each major section with scope, definitions, data sources, methodology "
    "before detail.",
    "Include quantitative evidence and scenario modelling, not assertions.",
    "Provide source rigor: named publications/institutions/years, inline.",
    "End with a synthesis section that directly answers the prompt's final ask.",
]
_PENALTIES = [
    "Vague mentions ('several factors matter') without specifics, numbers, or "
    "named cases (judge calls this '笼统提及').",
    "Lists of factors without mechanisms/pathways/relative importance.",
    "Scope drift into adjacent background that crowds out the requested ask.",
    "Hedging at equal content (judge penalty ~25.6%) — assert what the evidence "
    "in the text supports.",
    "Generic 'value-investing platitudes' or other domain-cliché filler.",
    "Truncation markers, placeholder text, broken numbering, malformed tables.",
    "Same drivers/caveats repeated across multiple sections.",
    "Bare [n] markers carrying load-bearing facts — they get stripped pre-scoring.",
]

_SYSTEM = """You produce a STRICT JSON DesignGuide for ONE research report. \
Output ONLY this JSON object:

{
 "section_numbering": "1.1.1" | "I.A.1" | "none",
 "header_depth_max": 3 | 4,
 "transitions_register": "analytical"|"technical"|"predictive"|"comparative"|"causal",
 "tone_register": str,
 "table_use": "comparison-when-multi-entity"|"liberal"|"sparing",
 "terminology": { "<ambiguous term>": "<preferred term for this report>", ... },
 "zh_register_markers": [ "一方面/另一方面", "据...显示", "进而", "从而", ... ]
   (ONLY when language=='zh'; otherwise [])
}

Rules:
- For predict/trend archetypes: tone_register='predictive', transitions='predictive'.
- For explain-mechanism: tone='causal', transitions='causal'.
- For compare/recommend: tone='analytical', transitions='comparative', table_use='liberal'.
- For technical/science deep tasks (depth_target='deep' on many sections): header_depth_max=4.
- For ZH tasks: include 4-7 native analytical Mandarin register markers (parallelism,
  attribution patterns, causal connectors) that the writer must use natively, not translate.
- terminology: ONLY include entries that would actually disambiguate (e.g., for a Finance
  task: {"return": "total shareholder return (TSR)", "dividend": "actual cash dividend per share"}).
"""


@node("design_guide")
def run(inp: DesignGuideInput) -> DesignGuideOutput:
    deep_count = sum(1 for s in inp.plan.get("report_toc", [])
                     if s.get("depth_target") == "deep")
    user = (
        f"PROMPT ({inp.language}):\n{inp.query}\n\n"
        f"DOMAIN: {inp.domain}\nARCHETYPE: {inp.archetype}\n"
        f"PERSONA (use to calibrate voice/register): {inp.persona}\n\n"
        f"PLAN TOC: {json.dumps([s.get('title') for s in inp.plan.get('report_toc',[])], ensure_ascii=False)}\n"
        f"Deep-depth section count: {deep_count}\n\n"
        "Emit the DesignGuide JSON now."
    )
    try:
        obj = llm.call_json("architect", user, system=_SYSTEM, max_tokens=2400,
                            effort="low", note="design_guide")
    except Exception:  # noqa: BLE001
        obj = {}
    if not isinstance(obj, dict):  # B-13 defensive
        obj = obj[0] if isinstance(obj, list) and obj and isinstance(obj[0], dict) else {}

    g = DesignGuide(
        section_numbering=str(obj.get("section_numbering", "1.1.1")),
        header_depth_max=int(obj.get("header_depth_max", 3)),
        transitions_register=str(obj.get("transitions_register", "analytical")),
        tone_register=str(obj.get("tone_register", "analytical")),
        table_use=str(obj.get("table_use", "comparison-when-multi-entity")),
        terminology={str(k): str(v) for k, v in
                     (obj.get("terminology") or {}).items()},
        zh_register_markers=[str(x) for x in
                              (obj.get("zh_register_markers") or [])][:8]
                              if inp.language == "zh" else [],
        # citation rule is LOCKED (cleaner_behavior.md) — never model-derived
        citation_format="inline-source-name",
        citation_instruction=wr.CLEANING_RESISTANT_RULE,
        rewards_directives=_REWARDS,
        penalties_directives=_PENALTIES,
    )
    return DesignGuideOutput(guide=g)
