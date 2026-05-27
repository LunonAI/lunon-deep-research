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

# P2-Wave-3-§12.A.v4 (2026-05-26, post-PR-32-merge full-archetype fresh-corpus retro):
#
# v3 (just-merged PR #32) was a course-correction on v2's docx-corpus
# miscalibration. v3 banned ANY §N / 第N节 reference inside the opening
# sentences of a section (lines 147-150 of v3) AND added an
# "OPENING-SENTENCE FORBIDDEN-§N RULE OVERRIDES THIS NARROWING" addendum
# (v3 lines 187-189) that extended the ban over the body-narrowing's
# named-artefact allowance. This was OVERCORRECTION.
#
# Post-merge full-archetype fresh-corpus measurement on 14 the #1 reference
# tasks (5 gate-verify-5 + 9 missing-archetype tasks across compare /
# predict / trend / recommend) recorded in
# `transfer/p2_artifacts/wave3_insight_bundle_spec.md` §PR-1:
#   Pattern: "Chapter N" / "第N章" anywhere in opening sentence(s)
#   the reference rate per task: 75% (id 8) / 57% (id 20) / 86% (id 23) /
#                          89% (id 56) / 75% (id 91) and similar on
#                          predict/trend/recommend samples.
#   Overall: 75-89% of the reference chapters reference an earlier chapter in
#   the opening sentence — this is an IDIOMATIC rhetorical move in the
#   high-scoring corpus, NOT a v2-style antipattern.
# Verified the reference opening idioms (across multiple ids):
#   - "The framework constructed in Chapter 1 — [substantive recap of
#     what Ch1 established] — finds its first and most consequential
#     application in [topic of this chapter]." (id 91 chapter 2)
#   - "第1章已论证：[recap of Ch1's substantive claim]。本章承接全链条
#     技术框架中的数据环节，系统梳理[substantive new claim]。" (id 8 ch 2)
#   - "The N preceding chapters have populated [topic]. [Substantive
#     new claim]." (id 91 chapter 9)
# These are SUBSTANTIVE recaps anchored to a named prior result, not
# the bare "Building on §X established in §Y" template v3 correctly
# banned (which IS still antipattern at the reference's 0% rate).
#
# v4 amendment:
#   - KEEPS all v3 antipatterns EXCEPT the §N-in-openings blanket ban:
#     - Building-on / Applied-to / Under-the-rubric / Using-the-taxonomy
#       templates STAY forbidden (the reference 0%).
#     - "This section/chapter/report" as opening subject STAYS forbidden
#       (the reference 0%).
#     - Prose-before-table STAYS required.
#     - Disconnected exposition STAYS forbidden.
#   - RE-ALLOWS Chapter-N / 第N章 references in opening sentences when
#     PAIRED with a substantive recap of what that earlier chapter
#     established — matches the reference's 75-89% idiom rate.
#   - DROPS the "OPENING-SENTENCE FORBIDDEN-§N RULE OVERRIDES THIS
#     NARROWING" addendum — body-narrowing's named-artefact allowance
#     now applies uniformly to body AND openings.
#   - ADDS a new "Acceptable chapter-reference idioms" block with the
#     three reference-verified opening patterns.
#   - Article-opener exemption is now SIMPLER: the §1/opener is free
#     from the topic-restriction (since there's no prior chapter to
#     recap) and the prose-before-table requirement still applies.
#
# v4 still subsumes the v3 root-cause fix for §12.A (recap-rule
# mis-calibration). Forward-ref bugs from v2 (§54/§63/§64/§65/§70 in
# the W2 smoke) are addressed by a separate post-write validator
# (Wave 3 PR 4 candidate — gap-map §12.C); the rule body itself only
# enforces the IDIOMATIC shape of acceptable opening references.
_SECTION_OPENING_PROSE_LEAD_RULE = (
    "SECTION-OPENING PROSE LEAD (P2-Wave-3-§12.A.v4 — reference-parity "
    "amendment to v3):\n"
    "EVERY section, including those whose primary content is a markdown "
    "table or list, MUST open with at least one substantive prose sentence "
    "INTRODUCING THE TOPIC OF THIS SECTION. The prose lead names the actual "
    "subject matter directly. References to earlier chapters ARE allowed "
    "when paired with a substantive recap of what that chapter established "
    "(this is the reference idiom — see Acceptable patterns below); what is "
    "FORBIDDEN is the formulaic '[Building on / Applied to / Under the "
    "rubric of] §X' template that reads as compliance theatre.\n\n"
    "Critical: each section reads like the opening of a book CHAPTER — "
    "diving into the topic — not like a meeting summary that lists what "
    "earlier sections discussed. When the section's primary content is a "
    "table or list, the prose lead comes BEFORE that block; the data block "
    "does NOT replace the prose lead. Pattern: prose-paragraph-then-data. "
    "NEVER data-block-first-no-prose.\n\n"
    "FORBIDDEN opening patterns (verified against the #1 reference corpus — "
    "these antipatterns fire ~0% in the reference and ~80% in pre-v3 Lunon, and "
    "were the named root cause of the RACE judge's 'repeated setup "
    "language' findings on the Wave-2 smoke):\n"
    "- 'Building on [the framework/taxonomy/spine/dimensions/scaffold] "
    "  [established/set out/introduced] in §N...' — formulaic recap that "
    "  reads as compliance theatre.\n"
    "- 'Applied to the dimensions set out above...' / 'Under the rubric "
    "  from §N...' / 'Using the taxonomy established above...' — variants "
    "  of the same recap-template antipattern.\n"
    "- BARE '§N' or '第N节' pointer with no named artefact, used as the "
    "  leading move ('As discussed in §1, ...' / 'Per §3, ...' / "
    "  '如§1所述，...'). The pointer itself is fine when paired with a "
    "  substantive recap of what was at that section (see Acceptable "
    "  patterns); the antipattern is the bare-pointer-as-recap.\n"
    "- 'This section' / 'This chapter' / 'This report' as the SUBJECT of "
    "  the opening sentence. the reference never opens a chapter with a meta-"
    "  subject; the opening subject is the substantive topic noun (the "
    "  thing being discussed), not a referent to the document itself.\n"
    "- Opening with a markdown table (`|...|...|`) or list (`-` / `*`) "
    "  without a prose sentence first. The section MUST have a prose "
    "  paragraph BEFORE any data block.\n"
    "- Stating only the section topic with no substantive claim about it "
    "  (disconnected exposition — judge penalises). The opening must "
    "  carry a claim, definition, anchor, or quantitative fact about the "
    "  topic, not just name it.\n\n"
    "Acceptable opening patterns (EN — modeled on verified the #1 reference "
    "chapter openers):\n"
    "- Definition opening: '<Topic-noun> is <definition / canonical "
    "  characterisation>...' (e.g. 'The Cloth is the franchise's defining "
    "  invention, and its conceptual genesis is unusually well documented.')\n"
    "- Quantified-claim opening: '<Topic-noun> <verb> <number / "
    "  quantitative anchor>...' (e.g. 'Within Athena's army, the eighty-"
    "  eight Cloths are stratified into three principal ranks...')\n"
    "- Factual-anchor opening: '<Subject> <action> <historical / textual "
    "  evidence>...' (e.g. 'Kurumada repeatedly grounded his metaphysics "
    "  in concrete velocity claims, producing a quantitative ladder...')\n"
    "- Substantive-contextualisation opening: '<Topic-noun> originated in "
    "  <context>, and <substantive claim about it>.'\n\n"
    "Acceptable chapter-reference idioms (v4-added; the reference fires this "
    "shape 75-89% of the time across the verified corpus):\n"
    "- Recap-then-pivot: 'The framework constructed in Chapter N — "
    "  <substantive recap of what Ch N established> — finds its first "
    "  application in <topic of this chapter>.' (verified id=91 ch 2; "
    "  the recap must NAME what Ch N established, not just gesture at it)\n"
    "- ZH recap-then-pivot: '第N章已论证：<recap of Ch N's substantive "
    "  claim>。本章承接<connector>，系统梳理<substantive new claim>。' "
    "  (verified id=8 ch 2)\n"
    "- Multi-chapter recap: 'The N preceding chapters have populated "
    "  <topic>. <Substantive new claim>.' (verified id=91 ch 9)\n"
    "Critical distinction between the FORBIDDEN bare-pointer and the "
    "ACCEPTABLE recap-then-pivot: the acceptable form NAMES what the "
    "prior chapter established (the artefact, framework, finding) BEFORE "
    "pivoting to the current chapter's claim. The forbidden form is the "
    "bare pointer ('As discussed in §3...') that asks the reader to recall "
    "what was at §3 without naming it.\n\n"
    "Acceptable opening patterns (ZH — modeled on the reference ZH samples):\n"
    "- '<主题名词>是<定义>...'\n"
    "- '<具体数字>项<内容>...'\n"
    "- '<事实陈述>，<进一步说明>。'\n"
    "- '<主题名词>起源于<背景>，<关于它的实质性主张>。'\n\n"
    "Section-number references — narrowing (UNCHANGED from v2; v4 removes "
    "the v3 opening-sentence override):\n"
    "Refs to earlier sections like '§1' or '第3节' are GOOD when paired "
    "with a named artefact ('§1's four-pillar framework', '第3节我们已对"
    "Iyer节奏维度作过分析'). Bare temporal pointers without naming what "
    "was at that section ('as discussed in §1', 'as shown above') are "
    "BAD — they read as filler. The named artefact is the substantive "
    "payload. This narrowing applies uniformly to OPENING sentences AND "
    "body text in v4; the v3 'opening-sentence override' that forbade "
    "even named-artefact §N refs in openings was removed because it "
    "contradicted the reference's verified 75-89% rate.\n\n"
    "The FIRST section (or article opening) is EXEMPT from the topic-"
    "restriction — it establishes the framework rather than diving into "
    "a sub-topic. The prose-before-table requirement still applies to it. "
    "Other FORBIDDEN patterns still apply: do NOT open the article with "
    "'This report examines...' / 'This chapter introduces...' / 'This "
    "section discusses...' (the meta-subject ban), do NOT open with a "
    "bare-pointer reference (there's nothing earlier to point at anyway), "
    "do NOT open with a table or list before any prose, and do NOT state "
    "only the topic with no substantive claim. The exemption is NARROW: "
    "it only frees the opener from the requirement to introduce a sub-"
    "topic, allowing it to establish the article-wide framework instead."
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
    "INSIGHT DENSITY — DISTRIBUTIONAL COVERAGE (Wave 2 §3.2 rewrite):\n"
    "Every leaf section (H4 `#### 1.1.1 Foo` in deep-hierarchy archetypes, "
    "or H2 `## N Foo` body in flat archetypes like list-all) must close with "
    "a substantive analytical payoff drawn from the four elements below. "
    "Pre-Wave-2 the rule said 'pick AT LEAST ONE of the four' — the verified "
    "id=91 smoke (2026-05-26) showed the writer over-fires the EASY elements "
    "(contrarian 1.77× over, quant 2.44× over) and under-fires the HARD one "
    "(forward-looking 0.14× short, 7× below the reference's density). Path of "
    "least resistance defeats the rule's intent. Wave 2 now requires "
    "DISTRIBUTIONAL coverage across the section's leaves rather than "
    "per-leaf ANY-of-four:\n"
    "\n"
    "TARGET DISTRIBUTION — per-archetype, calibrated against the 10-doc "
    "the reference corpus (Wave 2 PR #30 self-review). The specific "
    "minimum percentages for THIS archetype are interpolated in the "
    "user-prompt `INSIGHT DISTRIBUTION FOR THIS SECTION` block below — "
    "DEFER TO THAT BLOCK FOR THE EXACT TARGETS. Do not assume a uniform "
    "20% floor across elements; the reference corpus shows wildly different "
    "natural distributions per archetype (e.g. list-all averages ~13% "
    "contrarian while predict averages ~2%; explain-mechanism averages "
    "~2% quant). The single source of truth for these targets is the "
    "`_INSIGHT_DISTRIBUTION_BY_ARCHETYPE` dict + the user-prompt block "
    "the writer sees on every section call. Count each leaf once for "
    "whichever element it primarily uses; totals can exceed 100% when a "
    "leaf carries two. The post-process scorer "
    "`scripts/p2_writer_compliance.py` measures each element's actual "
    "landing rate per section against the per-archetype target so a "
    "sustained imbalance shows up in drift logs.\n"
    "\n"
    "PER-ARCHETYPE BIAS LOGIC (the WHY behind the per-archetype targets, "
    "without the numbers): predict / trend / recommend archetypes are "
    "forward-looking-by-mission; their (a) share is biased UP at the "
    "expense of (b)/(d). list-all / compare archetypes are entity-"
    "enumerated; their (d) share is biased UP (most leaves are inherently "
    "comparisons across the matrix). explain-mechanism balances (a) and "
    "(d) higher than (b)/(c) — the reference corpus shows explain-mech "
    "explains via alternatives + forward-looking projection, NOT via "
    "contrarian framing or heavy quantification. The exact percentages "
    "for THIS section's archetype are in the user-prompt block.\n"
    "\n"
    "FOUR ELEMENTS (unchanged from PR #21 / Option-A-#3):\n"
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
    "and STOP. Do NOT drop or skip the leaf — every depth_seed (or body "
    "leaf in flat archetypes) in the outline must produce content. "
    "Under-payoff on one leaf is preferable to a generic forecast the "
    "judge will read as filler."
)


# Wave 2 §3.2 (2026-05-26): per-archetype distribution targets for the
# four `_INSIGHT_MIN` elements. Surfaced via `insight_distribution(archetype)`
# so the user-prompt mirror block in writer.write_section can interpolate
# the right percentages for the archetype being written. Pre-Wave-2 the
# rule lived ONLY in the system prompt as "pick ONE of (a)-(d)"; the
# 2026-05-26 id=91 smoke showed that wasn't landing (forward-looking
# 7× short, contrarian 1.77× over). Wave 2 mirrors to the user prompt
# with explicit per-archetype targets the writer can self-check against.
#
# Wave 2 PR #30 self-review (gap #3 calibration, 2026-05-26): targets
# CALIBRATED against the 10-doc reference corpus via
# `scripts/p2_writer_compliance.py` weighted-mean profile. Pre-fix
# targets were reasoning-derived ("pick 30/20/20/20"); the reference
# corpus revealed several pre-fix targets were way off:
#   - list-all: pre-fix said 30% forward-looking; the reference does 69%
#   - explain-mech: pre-fix said 20% contrarian; the reference does 10%
#   - trend: pre-fix said 15% contrarian; the reference does 2%
# Wave 2 PR #30 targets are set to ≈80% of the observed the reference
# weighted mean per element per archetype, so they're MEASURABLE
# floors (writer can clear them with some variance) without
# overspecifying. The compliance scorer (`p2_writer_compliance.py`)
# uses these targets to compute per-element gap percentages on every
# smoke output.
_INSIGHT_DISTRIBUTION_DEFAULT = {
    "forward_looking_min": 30,
    "contrarian_min": 8,
    "quant_min": 5,
    "alternative_min": 30,
}
_INSIGHT_DISTRIBUTION_BY_ARCHETYPE: dict[str, dict[str, int]] = {
    # Forward-looking-by-mission archetypes. the reference trend (id=38)
    # observed: fwd 58% / contr 2% / quant 3% / alt 7%. Predict and
    # recommend extrapolated (no direct the reference corpus data) with
    # slightly higher alt/contr for analytical depth.
    "predict": {"forward_looking_min": 45, "contrarian_min": 5, "quant_min": 5, "alternative_min": 10},
    "trend": {"forward_looking_min": 45, "contrarian_min": 1, "quant_min": 2, "alternative_min": 5},
    "recommend": {"forward_looking_min": 40, "contrarian_min": 5, "quant_min": 5, "alternative_min": 15},
    # Entity-enumerated archetypes. the reference list-all (id=8, 14, 44, 91)
    # weighted mean: fwd 69% / contr 13% / quant 21% / alt 59%. The
    # forward-looking rate is SURPRISINGLY HIGH for an enumeration
    # archetype — the reference entity profiles consistently project trends
    # ("by 2027 this lineage will...") rather than purely cataloguing.
    "list-all": {"forward_looking_min": 55, "contrarian_min": 10, "quant_min": 17, "alternative_min": 47},
    # compare: no direct the reference corpus data; use list-all calibration
    # as the closest neighbor (both are entity-table archetypes).
    "compare": {"forward_looking_min": 50, "contrarian_min": 10, "quant_min": 17, "alternative_min": 47},
    # Deep analytical archetype. the reference explain-mech (id=20, 37, 56,
    # 89) weighted mean: fwd 35% / contr 10% / quant 2% / alt 53%.
    # Notably LOW on quant/contrarian (the reference explains with
    # alternatives + forward-looking, not contrarian framing).
    "explain-mechanism": {"forward_looking_min": 28, "contrarian_min": 8, "quant_min": 1, "alternative_min": 42},
}


def insight_distribution(archetype: str | None) -> dict[str, int]:
    """Return the per-archetype `_INSIGHT_MIN` distribution targets dict
    (Wave 2 §3.2). Falls back to the balanced default for unknown
    archetypes.

    Greptile PR #30 follow-up (2026-05-26): wraps the `.get()` result
    in `dict(...)` so the return is ALWAYS a fresh copy regardless of
    whether the archetype was known. Pre-fix the known-archetype path
    returned the actual module-level dict object — a caller mutating
    the returned dict would have silently corrupted the
    `_INSIGHT_DISTRIBUTION_BY_ARCHETYPE` constant.
    """
    return dict(_INSIGHT_DISTRIBUTION_BY_ARCHETYPE.get(archetype or "", _INSIGHT_DISTRIBUTION_DEFAULT))


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

    Wave 0 §11 (2026-05-26): the directive was previously ambiguous on what
    "one content token" means. The writer interpreted it at the BPE-subword
    level, splitting `Sagittarius` as `<N> Sag <N-1> itt <N-2> arius` (3
    markers, 3 fragments). After post-strip, the fragments persisted in the
    article body as `Sag itt arius` and dotted heading numbers landed as
    `## 4 . 1 . 1`. The strengthened directive below makes "ONE COMPLETE
    WORD per marker" explicit, gives a worked FORBIDDEN example, and
    enumerates the dotted-number and short-acronym cases that count as
    single tokens.
    """
    n_markers = max(50, int(target_tokens * 0.75))
    return (
        "CAPEL LENGTH CONTROL — INLINE COUNTDOWN MARKERS (arXiv 2508.13805):\n"
        f"Emit this section's content interleaved with countdown markers. "
        f"Begin with `<{n_markers}>` immediately followed by one content "
        f"token, then `<{n_markers - 1}>`, then one content token, and so "
        f"on, decrementing to `<0>` at the section's end.\n\n"
        "ONE COMPLETE WORD PER MARKER (CRITICAL — read this twice):\n"
        "A 'content token' here means ONE COMPLETE ENGLISH WORD (e.g. "
        "`Sagittarius`, `astrophysics`, `recalibration`) OR ONE CJK "
        "CHARACTER in ZH, not a BPE subword piece. NEVER split a multi-"
        "syllable word across multiple markers. Examples:\n"
        "  CORRECT:    `<N> Sagittarius <N-1> emerged <N-2> from <N-3>`\n"
        "  FORBIDDEN:  `<N> Sag <N-1> itt <N-2> arius <N-3> emerged`\n"
        "  FORBIDDEN:  `<N> Sagitt <N-1> arius <N-2> emerged`\n"
        "Splitting a word across markers leaves visible fragmentation in "
        "the article after post-processing strips the markers — the reader "
        "sees `Sag itt arius` instead of `Sagittarius`. This destroys "
        "Readability scores and signals broken English to the judge.\n\n"
        "DOTTED NUMBERS AND ACRONYMS COUNT AS ONE TOKEN:\n"
        "  - `4.1.1` is ONE token: `<N> 4.1.1 <N-1>`, NOT "
        "`<N> 4 <N-1> . <N-2> 1 <N-3> . <N-4> 1 <N-5>`.\n"
        "  - `H4` is ONE token. `arXiv` is ONE token. `2026-05-26` is "
        "ONE token. `[^S1-3]` is ONE token (footnote markers are single "
        "atomic units — never split them).\n"
        "  - URLs, code identifiers, equations are ONE token even if long.\n"
        "If a single word or atom is too long to fit comfortably in your "
        "remaining marker budget, REPHRASE to use shorter words OR STOP "
        "the section early — DO NOT subword-split to make the counter "
        "land precisely.\n\n"
        "Two markers MUST NEVER appear back-to-back — every marker must be "
        "followed by at least one content token before the next marker. "
        "Headings, subheadings, and tables are part of the content stream "
        "— embed markers around their words too (but treat `## 4.1.1 "
        "Section name` as `## | 4.1.1 | Section | name` — four tokens, not "
        "eleven). Post-processing strips every `<digits>` marker before the "
        "section is shown to the judge, so write naturally; the markers "
        f"exist only to enforce the target length of approximately "
        f"{n_markers} content tokens for this section. If you run out of "
        "substantive content before reaching `<0>`, STOP early rather than "
        "padding — under-length is acceptable; padding to hit the counter "
        "is not; subword-splitting to hit the counter is FORBIDDEN."
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
    outline_shape: dict | None = None,
) -> str:
    """Assemble the writer system prompt.

    P2-Wave-2-G: when `suppress_dedup=True` OR the auto-fire heuristic
    triggers (archetype == "explain-mechanism" AND prior-W9 readability
    >= 0.50 AND task_id supplied), `_DEDUP_RULE` is omitted. The W9
    cross-reference identifies id=56 as the canonical fragile-density
    case; under the current rule no other W9 task triggers G.

    Wave 2 §1.2 follow-up (2026-05-26 PR #30 self-review): `outline_shape`
    accepts the per-archetype outline bounds dict from
    `pipeline.architect._bounds_for_archetype(archetype)`. When provided
    the STRUCTURAL CAPS block + HEADING-HASH MAPPING block interpolate
    the per-archetype `sub_min-sub_max` and the H4-allowed status,
    eliminating the system-prompt-vs-user-prompt contradiction the
    Wave 2 PR otherwise carried (system said "3-6 subsections" while
    user prompt said "0-2" for list-all). Falls back to the historical
    3-6 / 4-level defaults when `outline_shape=None` for back-compat
    with any caller that doesn't yet thread the bounds through.
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
    middle_rules.extend([_INSIGHT_MIN, CLEANING_RESISTANT_RULE, _SECTION_OPENING_PROSE_LEAD_RULE])
    middle_block = "\n\n".join(middle_rules)

    # Wave 2 §1.2 follow-up: interpolate per-archetype outline bounds into
    # STRUCTURAL CAPS + HEADING-HASH MAPPING. Falls back to the historical
    # 3-6 / 4-level defaults when `outline_shape=None`.
    sub_min = (outline_shape or {}).get("sub_min", 3)
    sub_max = (outline_shape or {}).get("sub_max", 6)
    seed_max = (outline_shape or {}).get("seed_max", 4)
    if seed_max == 0:
        # Flat archetypes (list-all / compare): NO H4 leaves, NO `####`
        # heading depth — outline collapses to article title + flat H2
        # body sections with optional H3 cross-cutting subsections.
        structural_caps_block = (
            f"STRUCTURAL CAPS — HARD (per-archetype, archetype=`{archetype}`): "
            f"this is a FLAT outline. Use {sub_min}-{sub_max} subsections per "
            f"major section (most flat archetypes use 0 — every body section "
            f"stands on its own). NEVER emit H4 (`####`) headings — this "
            f"archetype's outline preset disallows H4 leaves per the "
            f"Wave-2 reference-corpus-calibrated shape (the reference id=91 / id=14 "
            f"/ id=8 use 0 H4). Maximum heading depth = 3 (e.g. `# Title`, "
            f"`## N`, `### N.N`). Skip the H3 tier rather than break these "
            f"limits."
        )
        heading_hash_block = (
            "HEADING-HASH MAPPING — STRICT (per-archetype, flat):\n"
            "- `# Title` (one `#`) — the REPORT TITLE only. Exactly ONE per "
            "  article. Never numbered.\n"
            "- `## 1 Section name` (two `##`) — top-level section. "
            "  Single-digit number (1, 2, 3, ...).\n"
            "- `### 1.1 Sub-section name` (three `###`) — sub-section "
            "  (use sparingly for flat archetypes; most sections do NOT "
            "  need H3 subdivision).\n"
            "- `#### ...` (four `####`) — FORBIDDEN for this archetype. "
            "  Do NOT emit H4 leaves.\n"
            "FORBIDDEN: emitting `# 1. Introduction` or `# 1.2 Bronze Saints` "
            "— a numbered chapter is NEVER an H1. Use `## 1 Introduction` "
            "and `### 1.2 Bronze Saints` instead. Re-using `#` after the "
            "title is the single most common heading bug; do not do it. "
            "Also FORBIDDEN: any `####` heading on this archetype."
        )
    else:
        # Deep archetypes (explain-mechanism / predict / trend / recommend):
        # H4 leaves are the leaf tier, one per depth_seed.
        structural_caps_block = (
            f"STRUCTURAL CAPS — HARD (per-archetype, archetype=`{archetype}`): "
            f"use {sub_min}-{sub_max} subsections per major section "
            f"(aligned to the per-archetype outline preset, calibrated "
            f"against the reference corpus). Never exceed 4 levels of heading "
            f"depth (`# Title`, `## N`, `### N.N`, `#### N.N.N` — never "
            f"`##### N.N.N.N`). Skip a subsection rather than break these "
            f"limits."
        )
        heading_hash_block = (
            "HEADING-HASH MAPPING — STRICT (per-archetype, hierarchical):\n"
            "- `# Title` (one `#`) — the REPORT TITLE only. Exactly ONE per "
            "  article. Never numbered.\n"
            "- `## 1 Section name` (two `##`) — top-level section. "
            "  Single-digit number (1, 2, 3, ...).\n"
            "- `### 1.1 Sub-section name` (three `###`) — sub-section. "
            "  Two-dot number (1.1, 1.2, ...).\n"
            "- `#### 1.1.1 Sub-sub-section name` (four `####`) — H4 leaf "
            "  (maximum depth). Three-dot number. One per depth_seed.\n"
            "FORBIDDEN: emitting `# 1. Introduction` or `# 1.2 Bronze Saints` "
            "— a numbered chapter is NEVER an H1. Use `## 1 Introduction` "
            "and `### 1.2 Bronze Saints` instead. Re-using `#` after the "
            "title is the single most common heading bug; do not do it."
        )

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
        f"\n\n{structural_caps_block}"
        # Internal label (P2-Option-A-#2) intentionally kept OUT of the
        # prompt string below — earlier draft had it inline and the LLM
        # might have treated it as part of the spec or echoed it back.
        f"\n\n{heading_hash_block}"
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
