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

import os
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
# round 8 (2026-06-02): 30_000 → 12_000. The P3b-v5 raise to 30000 chased ZH
# length parity by making each chapter FATTER, but the id-44 profiling exposed
# the failure mode: total_tokens (the domain governor's length target, ~96k ZH)
# was divided across only ~8 chapters, so each chapter's share/leaf-floor hit the
# 30k ceiling, the writer ran to its 32k cap, got CUT mid-section, and the cut
# tripped the truncation + quality re-rolls (30 writer calls for 8 sections,
# 3.75×, 63 min, 697k tokens) — AND we STILL came out UNDER-length (0.56× of
# Qianfan) because the cut/re-rolled content was lost. The fix takes the SAME
# total_tokens to Qianfan's actual shape — ~11-16 chapters each ~one Qianfan
# chapter (~6-8k tokens) that COMPLETE in one pass. So the ceiling drops to
# 12_000 (no section exceeds ~a Qianfan chapter + headroom, well under the writer
# cap → single-pass, no cut, no re-roll) and the architect chapter bands rise in
# LOCKSTEP (architect.py) so the unchanged total_tokens spreads across more,
# shorter chapters — length from BREADTH, not per-chapter inflation. The total is
# a distribution of the fixed total_tokens (sum of shares == total_tokens), so
# total_target is preserved; test_init_format_budget pins this.
# EN list-all (id91) is already LONGER than Qianfan and is gated out below.
SECTION_BUDGET_CEILING = 12_000

# target tokens per planned H3/H4 LEAF. The per-section budget floors at
# leaf_count × this, so length scales with the architect's planned leaf count
# rather than the H2 share split thin. round 8 (2026-06-02): 900 → 650 in
# lockstep with the 30k→12k ceiling. At 900/leaf an 8-12-leaf chapter floored to
# 7.2-10.8k and a leaf-heavy one pinned straight to the 30k ceiling; 650/leaf
# keeps a Qianfan-sized chapter (~8 leaves ≈ 5.2k) without the floor becoming the
# binding constraint that re-inflates per-chapter size — so length comes from
# more chapters (breadth), not deeper ones. Env-overridable so a dev4 sanity can
# dial it; a malformed override falls back to the default rather than crashing.
_DR_PER_LEAF_ENV = os.environ.get("DR_PER_LEAF_TOKENS")
try:
    _PER_LEAF_TOKENS = int(_DR_PER_LEAF_ENV) if _DR_PER_LEAF_ENV else 650
except ValueError:
    _PER_LEAF_TOKENS = 650
_MIN_LEAVES_PER_SECTION = 3  # back-compat floor for an under-seeded section


def _leaf_count(s: dict) -> int:
    """Number of renderable leaves the architect planned for a section: each
    depth_seed is one H4 leaf, each H3 subsection floors at 1 leaf, and a
    section with no subsections floors at _MIN_LEAVES_PER_SECTION."""
    subs = s.get("subsections") or []
    n = sum(max(1, len(ss.get("depth_seeds") or [])) for ss in subs)
    return n or _MIN_LEAVES_PER_SECTION


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

    # Domain length governor → median word_len from reference_catalog.jsonl,
    # scaled by the per-language multiplier (round 4: ZH targets Qianfan's longer
    # profile than EN). language threads through so ZH gets its higher target.
    median_words = wr.length_ceiling(inp.domain, inp.language)
    total_tokens = int(median_words / _WORDS_PER_TOKEN)

    # P3b-v5 leaf-aware allocation. id91 / EN list-all is already longer than
    # Qianfan and must NOT grow — gate it to the original depth-only behaviour.
    archetype = (inp.plan.get("_outline_audit") or {}).get("archetype", "")
    _is_en_list_all = (inp.language or "").lower().startswith("en") and archetype == "list-all"
    leaves = [_leaf_count(s) for s in toc]

    # Allocation weights. For EN list-all: original depth-only weights (id91
    # regression lock). Else: scale the depth weight by the section's planned
    # leaf count so a 12-leaf chapter gets proportionally more than a 3-leaf one
    # (today both get the same share — the root cause of starved deep chapters).
    if _is_en_list_all:
        weights = [1.5 if s.get("depth_target") == "deep" else 1.0 for s in toc]
    else:
        weights = [lv * (1.5 if s.get("depth_target") == "deep" else 1.0) for s, lv in zip(toc, leaves, strict=True)]
    weight_sum = sum(weights) or len(toc)

    sections = []
    for i, s in enumerate(toc):
        sid = s.get("id", f"S{i + 1}")
        share = total_tokens * weights[i] / weight_sum
        # P3b-v5: floor each section at leaf_count × _PER_LEAF_TOKENS so every
        # planned leaf carries its own grounded-depth target even when the domain
        # governor's total_tokens is the binding constraint — this converts the
        # length budget into per-leaf depth instead of a thin H2 split. EN
        # list-all skips the floor (no-grow gate). Greptile PR #17 ceiling clamp
        # still bounds a degenerate TOC; 800 stays the empty-section floor.
        leaf_floor = leaves[i] * _PER_LEAF_TOKENS
        target = int(share) if _is_en_list_all else max(int(share), leaf_floor)
        expected = max(800, min(target, SECTION_BUDGET_CEILING))
        sections.append(
            ScaffoldSection(
                section_id=sid,
                title=s.get("title", f"Section {i + 1}"),
                subsections=[ss.get("title", "") for ss in s.get("subsections", [])],
                expected_length_tokens=expected,
                assigned_specialists=_section_specialists(sid, inp.plan),
            )
        )

    # total_target_tokens must reflect the EXPECTED total output length, not the
    # domain governor ceiling: once leaf floors bind, the aggregate of per-section
    # expected_length_tokens can exceed total_tokens, so report the real sum.
    total_target = sum(s.expected_length_tokens for s in sections)
    return InitFormatOutput(scaffold=Scaffold(sections=sections, total_target_tokens=total_target))
