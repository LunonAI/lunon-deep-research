"""Per-experiment compliance check: did the prompt change actually produce
the intended STRUCTURAL change in writer output?

This is the FREE signal that runs before any LLM-judge call. Use it to
catch prompt-isn't-being-followed cases (where the writer ignored the
new directive) without spending $50+ on full evaluation.

Each experiment registers a `compliance_check(article) -> dict` function.
The CLI runs it across all articles in a jsonl and reports per-task
compliance + aggregate fire rate.

Usage:
  python3 scripts/p2_e_compliance.py \\
    --experiment e1_section_opening_recap \\
    --jsonl p2_artifacts/e1_articles.jsonl \\
    --out p2_artifacts/e1_compliance.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable
from pathlib import Path

# ---- E1.v4: section-opening prose-lead (reference-parity, antipattern gate) -
#
# v1 (committed 2026-05-23) tested at 9.2% compliance because the writer
# chose table-first openings on taxonomy archetypes (id=91 had 0/50 sections
# with prose-recap because every section opened with a markdown table
# directly under the heading). v2 split compliance into a STRUCTURAL gate
# (first content block must be prose, NOT a table/list) and a SEMANTIC gate
# that REWARDED "Building on §N..." / "this section examines..." vocab.
#
# v3 (2026-05-26, gap-map §12.A) flipped the semantic gate's meaning: the
# fresh-corpus A/B retro showed the #1 reference fires the "Building on" /
# "this section" phrases at ~0% and Lunon at ~77%, and the RACE judge
# flagged them as "repeated setup language" + "forward references to
# missing sections". The writer-prompt rule
# (`_SECTION_OPENING_PROSE_LEAD_RULE` in deep_research/writing_rules.py)
# now BANS those phrases as antipatterns and this script's regex matches
# the same set as forbidden tokens — the gate PASSES when the opener
# contains none of them.
#
# v4 (2026-05-26, post-PR-32-merge full-archetype retro): v3's blanket ban
# on ANY §N / 第N章 reference in openings was OVERCORRECTION. Fresh-corpus
# measurement on 14 reference tasks across all 6 archetypes shows 75-89% of
# chapters reference an earlier chapter ("Chapter N" / "第N章") in the
# opening sentence — paired with a substantive recap of what that prior
# chapter established. v4 drops the §N / 第N章 / "section N's framework"
# patterns from the forbidden regex. The writer-prompt rule body still
# distinguishes ACCEPTABLE recap-then-pivot openings (paired with named
# artefact, the reference idiom) from the FORBIDDEN bare-pointer openings ('as
# discussed in §3, ...'), but this regex enforces only the coarse
# building-on / meta-subject ban; nuanced bare-pointer-vs-named-artefact
# detection is harder to regex reliably and is left to the writer's
# system-prompt directive + post-merge smoke validation.
#
# The structural gate (prose-before-data) survived v3 and v4 unchanged; it
# remains the part of v2 that worked.


# First-line-of-section-body test: does the section open with a markdown
# table row (`|...|`), a bulleted list (`- ` / `* ` / `+ `), or a bare
# heading (`#`)? If yes, the structural gate FAILS — there's no prose
# lead paragraph before the data block.
_TABLE_OR_LIST_LEAD_RE = re.compile(r"^\s*(?:\|[^\n]*\||[-*+]\s+\S|#{1,4}\s+\S)")

# v4 FORBIDDEN opening tokens — phrases the writer-prompt rule explicitly
# bans in the opening sentence(s) of each section (P2-Wave-3-§12.A.v4).
# Verified against the #1 reference corpus: ~0% landing in the reference, ~77%
# pre-v3 in Lunon. These were the exact templates the v2 semantic gate
# REWARDED; v3 inverted the gate to mark them as failures, and v4 keeps
# the v3 set MINUS the §N / 第N章 / "section N's framework" patterns
# (the v3 ban on those overcorrected — the reference uses Chapter-N refs in
# 75-89% of chapter openings, paired with substantive recap; see v4
# docstring above for the full retro).
_V4_FORBIDDEN_OPENING_TOKENS = re.compile(
    r"(?:building on|extends? the (?:framework|rubric|taxonomy|matrix)|"
    r"using the (?:dimension|rubric|matrix|taxonomy|framework|classification)|"
    r"applied to the (?:framework|rubric|dimensions|matrix|taxonomy)|"
    r"under the (?:framework|rubric|taxonomy)|"
    r"per the (?:framework|rubric|dimensions|taxonomy)|"
    r"with this (?:framework|rubric|taxonomy) in (?:place|hand)|"
    r"within the framework (?:set out|established|introduced)|"
    r"(?:returns? to|revisits?) the (?:framework|rubric|dimensions)|"
    # Meta-subject openers ("This section adds...", "The present chapter...")
    # — v3/v4 explicitly forbid 'This section' / 'This chapter' / 'This
    # report' as the SUBJECT of an opening sentence, REGARDLESS of the verb
    # that follows. The verb slot is `\w+` (any word) rather than an
    # enumerated list — earlier rounds used a closed list that missed
    # common synonyms (explores / focuses / provides / offers / highlights
    # / investigates / summarises / explains). The `\s+\w+` requirement
    # keeps possessives like "This section's four-pillar framework" from
    # matching (no space between `section` and `'s`).
    r"this (?:chapter|section|report)\s+\w+|"
    r"the present (?:section|chapter|report)|"
    # v4 REMOVED: §N / 'section N's framework' patterns. v3 banned these in
    # openings even when paired with a named artefact; v4 fresh-corpus data
    # shows the reference uses Chapter-N refs in openings at 75-89% rate (paired
    # with substantive recap — the named-artefact pattern). The v4 rule
    # body distinguishes acceptable recap-then-pivot from forbidden bare-
    # pointer, but this regex enforces only the coarser bans; nuanced
    # bare-vs-paired §N detection is left to the writer's system-prompt
    # directive + post-merge smoke validation.
    # ZH equivalents — recap-template and meta-subject phrasings.
    r"沿用|延续上述|应用上一节|遵循前述|依据前述|按前文|"
    r"在(?:上述|前述)(?:框架|维度|分类)下?|在前述基础上|"
    r"基于(?:上文|前述)|"
    r"本(?:节|章|报告)(?:补充|拓展|添加|建立|应用|延伸|具体化|"
    r"考察|分析|讨论|研究|记录|测量|介绍|阐述|论述|涉及|探讨|"
    r"关注|涵盖|着重|聚焦|侧重|阐释|描述|呈现|展示|总结|概述|"
    r"说明|审视|旨在|意在|尝试|致力))",
    re.IGNORECASE,
)


# Window used for the opening-sentence semantic check. The v3 rule applies
# specifically to the OPENING SENTENCE(S), not the full section body — body
# text may legitimately contain §N refs paired with named artefacts. We
# scope to (first paragraph) ∩ (first 280 chars). The paragraph bound is
# the load-bearing one: it prevents the window from reaching into body
# paragraphs where the rule no longer applies. The char cap is a backstop
# for the pathological case of a single-paragraph section whose only break
# is a sub-heading hundreds of chars in.
_OPENING_WINDOW_CHARS = 280


def e1_section_opening_recap(article: str) -> dict:
    """E1.v4 compliance: structural + antipattern two-gate check.

    A section is COMPLIANT iff:
      (structural) first non-heading content line is PROSE — not a markdown
                   table row, not a bulleted list, not another heading.
      (semantic)   the OPENING SENTENCE(S) (first ~280 chars) contain NONE
                   of the v4-forbidden opener tokens
                   (`_V4_FORBIDDEN_OPENING_TOKENS`).

    Note on diagnostic bucket naming: v3 flipped the semantic gate's pass
    condition (v2 rewarded the tokens; v3 penalises them); v4 kept that
    inversion and narrowed the token set (Chapter-N refs in openings
    moved from forbidden to allowed — the reference uses them at 75-89%). The
    BUCKET semantics still describe orthogonal failure modes:
      - structural_ok + semantic_ok = compliant (prose lead, clean opener)
      - structural_ok only          = prose lead BUT opener uses a
                                      v4-forbidden recap/meta-subject phrase
      - semantic_ok only            = opener vocab clean BUT section opens
                                      with a table/list/sub-heading
      - neither                     = data-block lead AND forbidden phrase

    §1 grading (v3, preserved in v4): every section is graded, including
    sections[0]. The narrowed §1 exemption frees the article opener from
    the introduce-a-sub-topic requirement ONLY; the FORBIDDEN antipatterns
    (meta-subject openers, building-on templates, table-first leads,
    topic-only stubs) still apply to it. The earlier sections[1:] skip
    was v2-era logic where §1 had a wholesale exemption — under v3/v4
    that would silently mark a "This report examines..." article opener
    as compliant by default, overstating the post-merge smoke compliance
    rate.
    """
    sections = re.split(r"(?=^#{1,3}\s+\S)", article, flags=re.MULTILINE)
    sections = [s for s in sections if s.strip()]
    if not sections:
        return {"n_sections": 0, "n_compliant": 0, "rate": 0.0, "applicable": False}
    candidates = sections
    n_compliant = 0
    n_only_structural = 0  # prose lead but uses v4-forbidden opener vocab
    n_only_semantic = 0  # opener vocab clean but data-block-first
    n_neither = 0
    per_section = []
    for s in candidates:
        body = s.split("\n", 1)[1] if "\n" in s else ""
        body_stripped = body.lstrip("\n").lstrip()
        # LEVEL 1 structural: first content line must be prose (not table /
        # list / nested heading).
        first_line = body_stripped.split("\n", 1)[0] if body_stripped else ""
        is_data_block_lead = bool(_TABLE_OR_LIST_LEAD_RE.match(first_line))
        structural_ok = not is_data_block_lead and bool(first_line)
        # LEVEL 2 semantic (v4): opening sentence(s) must NOT contain any
        # v4-forbidden opener token. Windowed to the FIRST PARAGRAPH (with
        # a char-cap backstop) because the rule's body-text narrowing
        # allows §N refs in body paragraphs (paired with named artefacts).
        first_paragraph = body_stripped.split("\n\n", 1)[0]
        opener = first_paragraph[:_OPENING_WINDOW_CHARS]
        semantic_ok = not bool(_V4_FORBIDDEN_OPENING_TOKENS.search(opener))
        compliant = structural_ok and semantic_ok
        if compliant:
            n_compliant += 1
        elif structural_ok:
            n_only_structural += 1
        elif semantic_ok:
            n_only_semantic += 1
        else:
            n_neither += 1
        per_section.append(
            {
                "header": (s.split("\n", 1)[0] or "")[:80],
                "structural_ok": structural_ok,
                "semantic_ok": semantic_ok,
                "compliant": compliant,
            }
        )
    n = len(candidates)
    return {
        "n_sections": n,
        "n_compliant": n_compliant,
        "n_only_structural_ok": n_only_structural,
        "n_only_semantic_ok": n_only_semantic,
        "n_neither": n_neither,
        "rate": round(n_compliant / max(1, n), 3),
        "structural_rate": round((n_compliant + n_only_structural) / max(1, n), 3),
        "semantic_rate": round((n_compliant + n_only_semantic) / max(1, n), 3),
        "applicable": True,
        "per_section": per_section,
    }


# ---- registry -------------------------------------------------------------


_REGISTRY: dict[str, Callable[[str], dict]] = {
    "e1_section_opening_recap": e1_section_opening_recap,
}


# ---- CLI ------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--experiment",
        required=True,
        choices=sorted(_REGISTRY.keys()),
        help="which experiment's compliance pattern to apply",
    )
    ap.add_argument("--jsonl", required=True, help="adapter output jsonl to audit")
    ap.add_argument("--out", required=True, help="output JSON path with per-task compliance")
    args = ap.parse_args()

    check = _REGISTRY[args.experiment]
    rows = []
    rates = []
    for line in Path(args.jsonl).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        article = d.get("article", "")
        result = check(article)
        result["task_id"] = d.get("id")
        rows.append(result)
        if result.get("applicable"):
            rates.append(result.get("rate", 0))

    aggregate = {
        "experiment": args.experiment,
        "n_articles": len(rows),
        "mean_rate": round(sum(rates) / max(1, len(rates)), 3),
        "per_article": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(aggregate, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[compliance] {args.experiment}: mean compliance rate = {aggregate['mean_rate']}")
    for r in rows:
        if not r.get("applicable"):
            continue
        # v3 surfaces structural + semantic separately so we can diagnose
        # failure mode (table-first vs forbidden-opener-vocab).
        if "structural_rate" in r:
            print(
                f"  id={r['task_id']:>3}  compliant={r['rate']:>5.2f}  "
                f"struct={r['structural_rate']:>5.2f}  "
                f"sem={r['semantic_rate']:>5.2f}  "
                f"({r['n_compliant']}/{r['n_sections']}; "
                f"struct-only={r['n_only_structural_ok']}, "
                f"sem-only={r['n_only_semantic_ok']}, "
                f"neither={r['n_neither']})"
            )
        else:
            print(f"  id={r['task_id']:>3}  rate={r['rate']:>5.2f}")


if __name__ == "__main__":
    main()
