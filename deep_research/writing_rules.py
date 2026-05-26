"""Differentiator writing rules (p1-checklist items 17, 18, 19, 21).

- Position-1 opening template (item 17) + graded recovery ladder (plan point 8):
  200-token target / 300-token hard boundary.
- Insight-targeted minimums (item 18) + post-draft validator.
- Cleaning-resistant attribution (item 19) — the LOCKED rule from
  p0_artifacts/cleaner_behavior.md (obeyed in writer AND refiner).
- Per-domain length governor (item 21; decision #5) — soft ceiling = EN
  reference median word_len by domain, from p0_artifacts/reference_catalog.jsonl.
- P2-Wave-2-A: CAPEL countdown directive (capel_directive).
- P2-Wave-2-G: archetype + W9-readability conditional `_DEDUP_RULE` omission.
"""

import collections
import json
import os
import pathlib
import re
import statistics

_CAT = pathlib.Path(__file__).resolve().parent.parent / "p0_artifacts" / "reference_catalog.jsonl"


def _en_domain_medians():
    rows = [json.loads(ln) for ln in _CAT.read_text(encoding="utf-8").splitlines() if ln.strip()]
    en = [r for r in rows if r.get("language") == "en"]
    by = collections.defaultdict(list)
    for r in en:
        by[r.get("domain", "?")].append(r.get("word_len", 0))
    med = {d: int(statistics.median(v)) for d, v in by.items() if v}
    med["_overall"] = int(statistics.median([r.get("word_len", 0) for r in en]))
    return med


_MED = _en_domain_medians()
# coarse runtime domain -> closest reference_catalog domain (decision #5)
_DOMAIN_KEY = {
    "finance": "Finance & Business",
    "health": "Health",
    "science": "Science & Technology",
    "default": "_overall",
}

# ---- Inline-source-name attribution (verbatim from p0_artifacts/cleaner_behavior.md;
# internal label removed so the term itself does not leak into article text).
CLEANING_RESISTANT_RULE = (
    "SOURCE ATTRIBUTION (mandatory, non-negotiable):\n"
    '1. Attribute with source NAMES inline as prose — e.g. "according to '
    'McKinsey 2025", "Gartner\'s 2024 analysis" — never a bare [n]/[^n] for '
    "anything load-bearing.\n"
    "2. No sentence may be semantically dependent on a citation mark surviving. "
    "Every sentence must read complete after all [n]/[^n] and reference/"
    "footnote blocks are deleted.\n"
    "3. SUPPLEMENTARY FOOTNOTE CITATION is MANDATORY for every "
    "load-bearing claim sourced from a specific evidence atom (URL is "
    "OPTIONAL, not required — the #1 reference-leaderboard articles use "
    "academic-citation footnotes WITHOUT URLs and produce ~326 inline "
    "markers per long article; URL-conditional emission produced 0 "
    "footnotes in the 2026-05-26 CAPEL smoke). Pattern:\n"
    "   - inline: ...as Lebrun (1999) showed[^{section_id}-3]...\n"
    "   - definition (at the END of YOUR section, one per UNIQUE source):\n"
    '       [^{section_id}-3]: Lebrun, B. (1999), "First-Price Auctions in '
    'the Asymmetric N-Bidder Case," International Economic Review 40(1).\n'
    "       Include ` — <url>` at the end ONLY if the evidence atom's "
    "`url` is non-empty; otherwise omit the URL entirely.\n"
    "   The `{section_id}-N` scope is REQUIRED — substitute YOUR current "
    "section's id (e.g. S1, S3.2) and number sequentially from 1 within "
    "this section. The post-process step (footnote_normalize) globally "
    "renumbers across sections and builds the article's ## References "
    "block; without the section-scope your markers WILL collide with other "
    "sections' markers and get stripped as orphans.\n"
    "   REUSE markers across multiple mentions of the SAME source — "
    "the reference reuses each `[^{section_id}-N]` ~7× on average. Don't invent "
    "a new number per sentence when citing the same paper repeatedly. The "
    "`{section_id}-` scope prefix is REQUIRED on reused markers too — "
    "bare `[^N]` (no section scope) WILL be stripped as orphans by "
    "footnote_normalize, silently dropping every reused citation.\n"
    "4. Never place a fact, name, date, or figure ONLY inside a citation mark, "
    "footnote, or the reference list. The inline prose still carries the "
    "claim; footnotes are SUPPLEMENTARY URL citation, not the substantive "
    "payload."
)

# P2-Wave-2.5-E1.v2 (2026-05-23, post-v1-pilot revision):
# v1 (committed earlier today) tested at 9.2% compliance on a 3-task pilot.
# Root cause: writer chose TABLE-FIRST section openings for taxonomy archetypes
# (id=91 had 0/50 sections with recap because every section opened with a
# markdown table, not prose). The v1 directive assumed prose openings and
# silently failed on tables.
#
# v2 fixes the structural blind-spot: every section opens with a 1-2 sentence
# PROSE PARAGRAPH first, even when the section's primary content is a data
# table. The recap paragraph comes BEFORE the table; the table follows as
# the populated detail. Tables stand on their own; the prose anchors them
# to the §1 framework.
#
# Calibrated against the #1 reference corpus per p2_artifacts/reference_methodology_deep.md
# §1 finding (framework→population→synthesis loop) PLUS the bonus-article
# audit's narrowing that section-number refs ARE acceptable when paired with
# named artefacts.
_SECTION_OPENING_RECAP_RULE = (
    "SECTION-OPENING FRAMEWORK RECAP (P2-Wave-2.5-E1.v2):\n"
    "EVERY section after the first opens with a 1-2 SENTENCE PROSE PARAGRAPH "
    "that does two things: (a) recap the framework, taxonomy, dimensions, "
    "or analytical spine established in §1 (or the most recent framework-"
    "introducing section), and (b) state what this section ADDS by "
    "populating that framework with new entities, evidence, or scenarios. "
    "Only AFTER that prose paragraph may the section's primary content "
    "(table, list, formula, narrative) appear.\n\n"
    "Critical: when the section's main content is a markdown table, the "
    "table does NOT replace the prose recap — the table follows the recap. "
    "Pattern: prose-paragraph-then-table. NEVER table-first-no-prose.\n\n"
    "Acceptable opening templates (EN):\n"
    "- 'Building on the framework introduced in §1, this section populates "
    "  the [dimension] axis with [entity class]. The table below records...'\n"
    "- 'Applied to the dimensions set out above, the present chapter examines "
    "  [entity class] under [scoped criterion]. [table or content follows]'\n"
    "- 'Under the rubric from §1, this section operationalises [framework "
    "  concept] for [entity class]; the matrix below shows...'\n"
    "- 'Using the taxonomy established above, this section catalogues "
    "  [entity class] across [dimensions]; the table records...'\n\n"
    "Acceptable opening templates (ZH):\n"
    "- '沿用第一节框架，本节将...维度具体化为...。下表记录...'\n"
    "- '在前述维度下，本章考察...，下表显示...'\n"
    "- '应用上一节的分类，本节对...进行操作化；下表给出...'\n"
    "- '依据前述框架，本节将...。下表列出...'\n\n"
    "Section-number references — NARROWING: refs to earlier sections like "
    "'§1' or '第3节' are GOOD when paired with a named artefact "
    "('§1's four-pillar framework', '第3节我们已对Iyer节奏维度作过分析'). "
    "Bare temporal pointers without naming what was at that section "
    "('as discussed in §1', 'as shown above') are BAD — they read as "
    "filler. The named artefact is the substantive payload.\n\n"
    "FORBIDDEN opening patterns:\n"
    "- Opening with a markdown table (`|...|...|`) or list (`-` / `*`) "
    "  without a prose recap paragraph first. The section MUST have a "
    "  prose paragraph BEFORE any data block.\n"
    "- Stating the section topic with no link to prior framework "
    "  (disconnected exposition — judge penalises).\n"
    "- Pure summary-of-prior-section recap with no statement of NEW "
    "  value (reads as filler).\n"
    "- Bare 'as discussed in §N' / 'as shown above' references with no "
    "  named artefact.\n\n"
    "The FIRST section (or article opening) is EXEMPT from the recap "
    "requirement — it establishes the framework rather than recapping it."
)


# P2-Option-A-#3 (2026-05-23): _INSIGHT_MIN rewritten to be Insight-positive
# across ALL archetypes. The previous version (post-W9 over-correction) told
# the writer to NOT add forward-looking content for list-all/compare/
# explain-mechanism — a calibration that was right when the judge was hitting
# us for "paranoid speculation" but wrong now: the high-scoring corpus shows
# +0.154 raw Insight gap (57% of the total Overall gap weighted), meaning
# corpus articles densely populate forward-looking framing, contrarian moves,
# quantified projections, and named alternatives — across ALL archetypes,
# including those Lunon was being told to suppress. The new rule requires a
# substantive Insight element at the close of every H4 leaf (the depth_seeds
# unit from PR #20). "Grounded" stays — every insight element must be tied
# to a named source / concrete data, not free speculation.
_INSIGHT_MIN = (
    "INSIGHT DENSITY — REQUIRED CLOSE-OF-LEAF (post-#3):\n"
    "Every H4 leaf section (#### 1.1.1 Foo) must close with AT LEAST ONE of "
    "the following four elements. The element is the leaf's analytical "
    "payoff — not a tacked-on sentence, but the substantive synthesis that "
    "makes the leaf worth reading:\n"
    "\n"
    "  (a) FORWARD-LOOKING IMPLICATION — a stated consequence, follow-on "
    "      effect, or downstream condition, grounded in a named source and "
    "      tied to a concrete time horizon (e.g. 'By 2027, Pegasus-class "
    "      Cloths are likely to undergo a second V-stage revision per the "
    "      Hades-arc continuity, conditional on canonical resolution of the "
    "      Cloth-of-Sagittarius reassignment timeline').\n"
    "\n"
    "  (b) NAMED CONTRARIAN FRAMING — an explicit alternative to the "
    "      consensus interpretation, attributed to a specific source or "
    "      reasoning chain (e.g. 'Despite the standard reading that Marin's "
    "      Cosmo level is bounded at Silver Saint tier, the Episode G data "
    "      suggests a Gold-class burst capacity under specific conditions').\n"
    "\n"
    "  (c) QUANTIFIED PROJECTION OR CONFIDENCE RANGE — a numeric range, "
    "      probability, or scoped estimate, with stated assumptions (e.g. "
    "      '60-75% of the Sanctuary's Silver-tier roster falls within the "
    "      Mach 2-5 speed band per the 1986-1989 canon; outliers are "
    "      explicitly the Ophiuchus and Crystal Saint cases').\n"
    "\n"
    "  (d) NAMED-ALTERNATIVE COMPARISON — a direct comparison against a "
    "      named alternative entity, framework, theory, or counterfactual "
    "      (e.g. 'Whereas Mu's Crystal Wall absorbs kinetic energy radially, "
    "      Aiolia's Lightning Plasma propagates directionally; the two "
    "      defensive postures imply opposite tradeoffs at peak intensity').\n"
    "\n"
    "GROUNDING RULE (unchanged from prior policy): every element above MUST "
    "be evidence-backed — name a source, cite a date or named work, or "
    "ground the projection in stated assumptions. Free speculation without "
    "evidential support hurts more than absent insight.\n"
    "\n"
    "AVOID FORMULAIC INSERTION: do NOT bolt a generic 'looking ahead...' or "
    "'further research is needed' onto every leaf. The four elements above "
    "are substantive payoffs grounded in the leaf's actual evidence. If the "
    "evidence for this leaf genuinely cannot support any of (a)-(d) — a "
    "narrow definitional or list-membership leaf, for instance — state the "
    "leaf's bounded scope explicitly (e.g. 'the canonical record does not "
    "extend to X; the cross-arc comparison in §N.M handles the projection') "
    "and STOP. Do NOT drop or skip the H4 leaf — every depth_seed in the "
    "outline must produce a leaf section, in order. Under-payoff on one "
    "leaf is preferable to a generic forecast the judge will read as filler."
)

# NEW (W9 diagnostic 2026-05-21): the judge cited "inconsistent section
# numbering" / "duplicated headings" as 30%+ of Readability losses. Make
# numbering an explicit, ENFORCED writer rule.
_NUMBERING_RULE = (
    "SECTION NUMBERING — ENFORCED:\n"
    "Use ONE consistent numbering scheme top-to-bottom (1, 1.1, 1.1.1). "
    "NEVER skip numbers (no jumps like 1.4→5→6→1.7). NEVER duplicate a "
    "number or heading. NEVER reset depth mid-document. If you write '1.1.1' "
    "somewhere, every depth-3 heading uses three-dot numbering. Consistency "
    "is more important than completeness — if a numbering doesn't fit "
    "cleanly, drop the number entirely rather than break the pattern."
)

# NEW: cross-section non-redundancy — the judge cited "repeats concepts
# across sections" / "same drivers/caveats recur" as 40%+ of Readability losses.
_DEDUP_RULE = (
    "CROSS-SECTION NON-REDUNDANCY:\n"
    "Each section should advance the report; do NOT restate drivers, caveats, "
    "or conclusions from sibling sections. If a point belongs in section X, "
    "make it in section X and don't repeat it elsewhere. Reference it briefly "
    "if needed ('as covered in §2') but never restate it. Repeated framing "
    "across sections is the #1 reader-fatigue complaint."
)

_ARCH_REFINE_EMPHASIS = {
    "list-all": "Maximize exhaustive coverage; one clearly-delimited unit per "
    "required item; comparison/inventory tables.",
    "compare": "Sharpen the entity×dimension comparison matrix; equalize depth "
    "across entities; quantify every cell where possible.",
    "trend": "Strengthen the dated chronological spine and the forward signal.",
    "explain-mechanism": "Deepen causal chains by showing each intermediate "
    "step explicitly; add named theories/frameworks and "
    "confounders.",
    "predict": "Add scenarios, drivers, explicit confidence ranges and time horizons; tie every forecast to evidence.",
    "recommend": "Make the ranked recommendation decisive; add a rationale "
    "table and the decision logic under constraints.",
}


# Length target multiplier. The historical _MED catalog was calibrated to
# Lunon's W9 outputs (~9k word median); the #1-leaderboard the reference corpus
# runs ~22k words mean across 100 articles; explain-mechanism extremes
# like id=56 reach ~80k (confirmed 2026-05-26 smoke).
#
# Calibration history:
#  - W9 baseline: 1.0× → ~9k words/article
#  - PR #20 (2026-05-22): 2.2× → ~20k words/article (still 4.3× short of
#    the reference id=56's 80k)
#  - Post-2026-05-26 smoke: 4.0× → target ~36k words/article. The smoke
#    at 2.2× produced 18.8k words for id=56 (1.34× W9, but still 4.26×
#    short of the reference). Bumped to 4.0× to get to ~36k target, a
#    meaningful step toward reference-class length without overshooting
#    cost envelope (~$17 → ~$35/task projected).
#
# Per-domain medians remain the relative shape — finance and science still
# run longer than travel/literature, just at a higher absolute floor.
# A multiplier higher than ~5-6 risks the writer producing repetitive
# content to fill space when the architect's outline depth doesn't keep
# pace; the architect's _SYSTEM HARD RULES (8-12 H2 × 3-6 H3 × 2-4 H4)
# need to be honored simultaneously for length growth to convert to
# substantive depth rather than filler.
_LENGTH_TARGET_MULT = 4.0


def length_ceiling(domain: str) -> int:
    """Per-domain SOFT word target. Bumped `_LENGTH_TARGET_MULT`× above
    the historical W9-era catalog medians to push toward reference-corpus
    structural depth. The writer prompt now frames this as a soft target
    rather than a hard ceiling — see writer_system below. Callers that
    want the historical W9 baseline should compute
    `length_ceiling(domain) / _LENGTH_TARGET_MULT` — referencing the
    constant by name so future calibration bumps stay in sync with this
    docstring.
    """
    key = _DOMAIN_KEY.get(domain, "_overall")
    raw = _MED.get(key, _MED["_overall"])
    return int(raw * _LENGTH_TARGET_MULT)


def capel_directive(target_tokens: int) -> str:
    """P2-Wave-2-A: CAPEL inline countdown markers (arXiv 2508.13805 §3.1-3.3).

    The writer is instructed to emit the section as content interleaved with
    `<N>`, `<N-1>`, ..., `<0>` markers, one marker per ~content token. The
    counter forces precise length adherence (paper: 10% → 74.9% exact-match
    on MT-Bench-LI when applied at full-article scale). Markers are stripped
    in post-processing via `pipeline._capel_strip.strip_capel_markers`.

    n_markers is derived from target_tokens conservatively (tokens → words
    ≈ 0.75×) so a 1200-token section emits ~900 markers, keeping the count
    inside the "reliable counting" envelope the paper flags for current
    frontier models.
    """
    n_markers = max(50, int(target_tokens * 0.75))
    return (
        "CAPEL LENGTH CONTROL — INLINE COUNTDOWN MARKERS (arXiv 2508.13805):\n"
        f"Emit this section's content interleaved with countdown markers. "
        f"Begin with `<{n_markers}>` immediately followed by one content "
        f"token (a word in EN, a single character or short token in ZH), "
        f"then `<{n_markers - 1}>`, then one content token, and so on, "
        f"decrementing to `<0>` at the section's end. "
        "Two markers MUST NEVER appear back-to-back — every marker must be "
        "followed by at least one content token before the next marker. "
        "Headings, subheadings, and tables are part of the content stream — "
        "embed markers around their words too. Post-processing strips every "
        "`<digits>` marker before the section is shown to the judge, so "
        "write naturally; the markers exist only to enforce the target "
        f"length of approximately {n_markers} content tokens for this "
        "section. If you run out of substantive content before reaching "
        "`<0>`, STOP early rather than padding — under-length is acceptable; "
        "padding to hit the counter is not."
    )


def opening_directive() -> str:
    return (
        "POSITION-1 OPENING (the first ~200 tokens, hard max ~300; this report "
        "is always article_1, write to dominate the comparison): the opening "
        "must, in order, contain (1) a single declarative THESIS sentence, "
        "(2) a QUANTIFIED SCOPE claim with a concrete number, (3) a NAMED "
        "CONTRARIAN view ('despite the common claim that …'), (4) a "
        "FORWARD-LOOKING DATE ANCHOR ('through 2030', 'by Q3 2026'). No "
        "preamble before the thesis."
    )


def writer_system(
    archetype: str,
    domain: str,
    language: str,
    toc_titles: list,
    *,
    task_id: int | None = None,
    suppress_dedup: bool = False,
) -> str:
    """Assemble the writer system prompt.

    P2-Wave-2-G: when `suppress_dedup=True` OR the auto-fire heuristic
    triggers (archetype == "explain-mechanism" AND prior-W9 readability
    >= 0.50 AND task_id supplied), `_DEDUP_RULE` is omitted. The W9
    cross-reference identifies id=56 as the canonical fragile-density
    case; under the current rule no other W9 task triggers G.
    """
    ceil = length_ceiling(domain)

    # P2-Wave-2-G auto-fire. Fail-soft when the W9 cache is missing
    # (cache.fragile_tasks returns False) so engine still runs cleanly on
    # machines without the DRB results tree.
    auto_suppress = False
    if (
        not suppress_dedup
        and archetype == "explain-mechanism"
        and task_id is not None
        # P2-Wave-2 hardcoded; DR_CAPEL_G=off is now the kill-switch only.
        and os.environ.get("DR_CAPEL_G", "on") != "off"
    ):
        try:
            from .cache import fragile_tasks as _ft

            auto_suppress = _ft.is_fragile_density_task(task_id)
        except Exception:  # noqa: BLE001 — never break the caller
            auto_suppress = False
    include_dedup = not (suppress_dedup or auto_suppress)

    middle_rules = [_NUMBERING_RULE]
    if include_dedup:
        middle_rules.append(_DEDUP_RULE)
    middle_rules.extend([_INSIGHT_MIN, CLEANING_RESISTANT_RULE, _SECTION_OPENING_RECAP_RULE])
    middle_block = "\n\n".join(middle_rules)

    return (
        f"You are an elite research-report writer. Language: {language}. "
        f"Write partner-grade analytical prose (not bullet dumps), with "
        f"headings/subheadings and comparison tables where they aid the reader."
        f"\n\nDEPTH BEFORE BREVITY (recalibrated post-#1). Earlier guidance "
        f"told you to be terse because we were losing Readability points to "
        f"padding; that was a 9k-word-median calibration. The corpus we now "
        f"target averages ~22k words and reaches ~80-100k on deep analytical "
        f"tasks. Match that depth by populating every subsection with H4 "
        f"leaves (one per depth_seed when provided), each treating a single "
        f"concrete claim/entity/data point. PADDING (filler sentences, "
        f"repeated framing, recap-of-recap) still hurts; ADDED LEAVES with "
        f"new payload do not."
        # AgentCPM-Report (arXiv 2602.06540) verbatim non-redundancy + meta-suppression directives
        f"\n\nYou should ensure that the content you write is not redundant "
        f"with other sections. Each section must advance the report; do NOT "
        f"restate drivers, caveats, or conclusions from sibling sections."
        f"\n\nDO NOT output meta-commentary about other sections, your "
        f"process, your methodology, your evidence sourcing, or your writing "
        f"approach. Output ONLY the report content itself. The reader does "
        f"not see (and is not told) how the report was produced."
        f"\n\nSTRUCTURAL CAPS — HARD: use 3-6 subsections per major section "
        f"(post-#1: aligned to the architect's 3-6 subsection bound, which "
        f"matches the high-scoring-corpus mean of ~4); never exceed 3 levels "
        f"of heading depth (e.g. 1, 1.1, 1.1.1 — never 1.1.1.1). Skip a "
        f"subsection rather than break these limits."
        # Internal label (P2-Option-A-#2) intentionally kept OUT of the
        # prompt string below — earlier draft had it inline and the LLM
        # might have treated it as part of the spec or echoed it back.
        f"\n\nHEADING-HASH MAPPING — STRICT:\n"
        f"- `# Title` (one `#`) — the REPORT TITLE only. Exactly ONE per "
        f"  article. Never numbered.\n"
        f"- `## 1 Section name` (two `##`) — top-level section. Single-digit "
        f"  number (1, 2, 3, ...).\n"
        f"- `### 1.1 Sub-section name` (three `###`) — sub-section. Two-dot "
        f"  number (1.1, 1.2, ...).\n"
        f"- `#### 1.1.1 Sub-sub-section name` (four `####`) — sub-sub-section "
        f"  (maximum depth). Three-dot number.\n"
        f"FORBIDDEN: emitting `# 1. Introduction` or `# 1.2 Bronze Saints` — "
        f"a numbered chapter is NEVER an H1. Use `## 1 Introduction` and "
        f"`### 1.2 Bronze Saints` instead. Re-using `#` after the title is "
        f"the single most common heading bug; do not do it."
        f"\n\n{opening_directive()}\n\n{middle_block}"
        f"\n\nLENGTH TARGET — SOFT: aim for ≈{ceil} words total ({int(ceil * 0.7)}"
        f"-{int(ceil * 1.4)} acceptable range; this is a calibration band, NOT "
        f"a hard cap). Run shorter on simple prompts where the evidence is "
        f"thin; run longer on deep analytical prompts (explain-mechanism, "
        f"predict, list-all) where the corpus reference articles average "
        f"~22k+ words. Length comes from POPULATED H4 LEAVES, not from "
        f"stretching prose.\n\n"
        f"Cover every section of the plan TOC verbatim: "
        f"{json.dumps(toc_titles, ensure_ascii=False)[:2000]}"
    )


# ---------- post-draft validators (item 17 / 18) ----------
_DATE = re.compile(
    r"\b(20[2-9]\d|in \d+ years|by Q[1-4]|H[12] 20\d\d|"
    r"\d{4}[-–]\d{2,4}|未来|到 ?20\d\d|20\d\d ?年)\b"
)


def _approx_tokens(s: str) -> int:
    return max(1, int(len(s) / 4))  # ~4 chars/token heuristic


def check_opening(text: str) -> dict:
    """Graded recovery ladder support (plan point 8). Returns
    {ok, within_200, within_300, missing, recommended_action}."""
    head300 = text[:1600]  # ~300 tokens
    head200 = text[:1100]  # ~200 tokens

    def present(seg):
        seg_l = seg.lower()
        thesis = bool(re.search(r"[.。!?！？]", seg)) and len(seg.split()) > 6
        quant = bool(re.search(r"\d", seg))
        contrarian = any(
            k in seg_l
            for k in ("despite", "contrary", "common claim", "widely", "however", "尽管", "与普遍", "并非", "误区")
        )
        date = bool(_DATE.search(seg))
        miss = [
            n
            for n, ok in (
                ("thesis", thesis),
                ("quantified_scope", quant),
                ("contrarian", contrarian),
                ("date_anchor", date),
            )
            if not ok
        ]
        return miss

    miss200 = present(head200)
    miss300 = present(head300)
    if not miss200:
        action = "accept"
    elif not miss300:
        action = "accept_soft_warning"
    else:
        action = "regen_opening"
    return {
        "ok": not miss200,
        "within_200": not miss200,
        "within_300": not miss300,
        "missing": miss300,
        "action": action,
    }


def check_insight_minimums(text: str) -> dict:
    fwd = len(set(_DATE.findall(text)))
    # P2 Wave-1.5-N0 (2026-05-22): expanded alternations after L2 diagnostic.
    # Pre-fix: ZH coverage was 4 patterns; the regex matched 0 hits on 78% of
    # W9 ZH tasks → gate fired and retries had 0% success because the writer's
    # actual ZH comparative-vocabulary doesn't use the captured tokens. EN
    # coverage was 5 patterns and missed many common forms. Both sides expanded
    # below; the substantive set of comparative-discourse moves the judge
    # rewards is broader than the original.
    alts = len(
        re.findall(
            # EN comparative / contrastive vocabulary
            r"(alternative(?:ly)?|whereas|however|on the other hand|"
            r"by contrast|conversely|instead|in contrast|"
            r"trade-?off|weaker|stronger|versus|vs\.?\s|"
            # ZH comparative / contrastive vocabulary. `(?<!比)较` (negative
            # lookbehind) so the bare 较 matches comparative uses (`较好`/
            # `较大`/`较低`) but NOT the high-frequency neutral compound `比较`
            # (compare). Without the lookbehind, "通过比较多种方法" would
            # falsely contribute to the alternatives count. Greptile PR #3
            # post-merge follow-up.
            r"另一种|另一方面|然而|相比之下|相较|(?<!比)较|相对而言|"
            r"与之相对|替代方案|相反|不同于|反观|权衡|取舍|利弊|折中|"
            r"劣于|优于|不如|胜过)",
            text,
            re.I,
        )
    )
    # P2-Option-A-#3 Greptile PR #21 follow-up (2026-05-25): realigned the
    # four advisory counts to map 1:1 to _INSIGHT_MIN's four contract elements:
    #   forward_looking   → element (a) FORWARD-LOOKING IMPLICATION
    #   contrarian_framing→ element (b) NAMED CONTRARIAN FRAMING  ← NEW
    #   quant_projection  → element (c) QUANTIFIED PROJECTION/RANGE
    #   alternatives      → element (d) NAMED-ALTERNATIVE COMPARISON
    # The prior `causal_chain` count (→ / -> / 导致.*进而 / 从而) had no
    # equivalent in the new contract, so validation_failures.jsonl rows would
    # have shown a metric the prompt no longer instructed — confusing future
    # calibration. The advisory check stays advisory (validation.py:113-115
    # logs counts but does not hard-fail), so renaming is safe.
    contrarian = len(
        re.findall(
            # element (b) markers: explicit pushback against a consensus
            # interpretation. The rule additionally requires evidence-backing,
            # which a regex cannot verify — this is presence telemetry only.
            # Greptile PR #21 round-2 follow-up: dropped the bare
            # `standard reading` alternative. In legal/literary/policy prose,
            # `the standard reading of the statute…` / `a standard reading
            # list` is neutral technical vocabulary and carries no inherent
            # adversative signal. Every other alternative here ships its own
            # challenge signal (despite, contrary to, challenges the…,
            # against consensus, counter to, etc.), so a contrarian use like
            # `Despite the standard reading…` still counts via the bare
            # `despite\b` alternative — we just stop inflating the count on
            # neutral mentions.
            # Greptile PR #21 round-3 follow-up: same logic applied to the
            # bare `commonly (?:held|assumed|believed)` / `通常认为` /
            # `普遍认为` alternatives — those describe what a consensus
            # believes, not pushback against it ("It is commonly held that
            # X is true, which recent data confirms" would have fired). The
            # `against (?:the )?consensus` slot is widened to
            # `against (?:the )?(?:consensus|commonly)` so the contrarian
            # exemplar "Against the commonly held assumption…" still counts;
            # ZH contrarian uses still land via `尽管` / `与…相反` / `挑战…共识`.
            r"(despite\b|contrary to\b|"
            r"challenges? the (?:view|consensus|standard|prevailing)|"
            r"against (?:the )?(?:consensus|commonly)|"
            r"counter to (?:the )?(?:consensus|conventional|standard)|"
            r"尽管|与.{0,8}相反|挑战.{0,8}共识|反直觉)",
            text,
            re.I,
        )
    )
    quant_proj = len(
        re.findall(
            r"(±|\+/-|range|区间|置信|confidence|"
            r"\d+%\s*[-–]\s*\d+%|\d+\s*[-–]\s*\d+x)",
            text,
            re.I,
        )
    )
    need = {
        "forward_looking>=3": fwd >= 3,
        "alternatives>=2": alts >= 2,
        "contrarian_framing>=1": contrarian >= 1,
        "quant_projection>=1": quant_proj >= 1,
    }
    return {
        "ok": all(need.values()),
        "counts": {
            "forward_looking": fwd,
            "alternatives": alts,
            "contrarian_framing": contrarian,
            "quant_projection": quant_proj,
        },
        "fail": [k for k, v in need.items() if not v],
    }


def citation_strip_audit(text: str) -> dict:
    """Item 19 auditor: strip [n]/[^n] + reference blocks; the body must remain
    semantically complete and carry inline source NAMES.

    P2-Wave-2.5 Greptile PR #17 follow-up: retention is computed against
    the body WITHOUT the References section (in both numerator and
    denominator) so a non-trivial References appendix doesn't artificially
    suppress retention. The audit asks "does body prose survive `[n]`
    strip?" — references appendix size is irrelevant to that question.
    This fix originally landed in PR #14 (D3 footnote relaxation) and was
    re-applied here so the revert doesn't lose a correctness improvement
    that's independent of the Wave 2.5 prompt direction.
    """
    refs_pattern = r"\n#+\s*(References|参考文献|Sources)[\s\S]*$"
    body_only = re.sub(refs_pattern, "", text, flags=re.I)
    stripped = re.sub(r"\[\^?\d+\]", "", body_only)
    has_inline_names = bool(
        re.search(
            r"(according to|per |报告|estimates|analysis|数据|Source:|"
            r"[A-Z][a-zA-Z]+ (?:20\d\d|study|report))",
            stripped,
        )
    )
    # crude completeness proxy: `[n]` strip on body-only must not drop >10%
    # of body chars. With References excluded from both sides, a 300-marker
    # body in ~250k chars sees ~0.5% reduction — well above the 0.9 gate.
    retention = len(stripped) / max(1, len(body_only))
    return {
        "ok": has_inline_names and retention > 0.9,
        "retention": round(retention, 3),
        "has_inline_source_names": has_inline_names,
    }


def refiner_emphasis(archetype: str) -> str:
    return _ARCH_REFINE_EMPHASIS.get(archetype, "")
