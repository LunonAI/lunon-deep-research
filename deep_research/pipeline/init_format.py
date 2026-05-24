"""init_format node (p1-checklist item 34; LINK-Researcher pipeline node 8).

Runs after design_guide, before writer. Produces a typed Scaffold dataclass
listing every section with section_id, title, subsections, expected_length
tokens, assigned specialists (which researchers' evidence feeds this section).

Distinct from the Architect plan: Architect plans what to RESEARCH; init_format
plans what the REPORT looks like structurally. The writer fills this scaffold;
the validator checks against it (every section >= 0.7 of expected length).

Length budgeting respects the per-domain governor (writing_rules.length_ceiling).

P2-Wave-2.5 Greptile PR #17 follow-up: SECTION_BUDGET_CEILING clamps per-
section `expected_length_tokens` so the validator's 0.7× pass-line stays
reachable inside the writer's single LLM call. Without the clamp, a TOC
with very few sections (esp. one deep-weighted section) lands the full
total_tokens budget on one section — exceeding the writer's max_tokens
hardcoded ceiling and locking that task into the validator/refiner loop.
This guard originally landed in PR #12 (D1) and is re-applied here so the
revert doesn't reintroduce the degenerate-TOC failure case.
"""

from dataclasses import dataclass

from .. import writing_rules as wr
from ..node_wrap import node
from ..state import Scaffold, ScaffoldSection

# rough token-per-word factor for English-style writers
_WORDS_PER_TOKEN = 0.75

# Per-section budget ceiling: keeps expected_length_tokens inside what
# `writer.write_section` can produce in one llm.call. Validator passes at
# >= 0.7× expected, so ceiling × 0.7 must be <= writer_max_tokens.
#
# P2-Option-A-#1 (2026-05-23): writer.max_tokens bumped 7000 → 14000 to
# accommodate the depth_seeds H4-leaf payload. Matching ceiling = 14000 / 0.7
# = 20000. Without this re-calibration the per-section CAPEL countdown would
# still terminate the writer at the pre-#1 token budget (~2500-3900 tokens
# per section), capping output at ~1500-2200 words/section and structurally
# preventing the depth_seeds from being populated as H4 leaves regardless of
# the 14k max_tokens headroom (Greptile PR #20 issue 2).
SECTION_BUDGET_CEILING = 20_000


@dataclass
class InitFormatInput:
    plan: dict  # from architect
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
        sid = s.get("id", f"S{i + 1}")
        share = total_tokens * weights[i] / weight_sum
        # Greptile PR #17 follow-up: clamp upper bound so a degenerate TOC
        # (few sections, esp. one deep-weighted) can't request more tokens
        # than the writer can produce in a single call. Floor is the pre-
        # existing 800-token minimum for empty-section detection.
        expected = max(800, min(int(share), SECTION_BUDGET_CEILING))
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
