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
    "OPTIONAL, not required — Qianfan #1-leaderboard articles use "
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
    "Qianfan reuses each `[^{section_id}-N]` ~7× on average. Don't invent "
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
# Post-merge full-archetype fresh-corpus measurement on 14 Qianfan #1
# tasks (5 gate-verify-5 + 9 missing-archetype tasks across compare /
# predict / trend / recommend) recorded in
# `transfer/p2_artifacts/wave3_insight_bundle_spec.md` §PR-1:
#   Pattern: "Chapter N" / "第N章" anywhere in opening sentence(s)
#   Qianfan rate per task: 75% (id 8) / 57% (id 20) / 86% (id 23) /
#                          89% (id 56) / 75% (id 91) and similar on
#                          predict/trend/recommend samples.
#   Overall: 75-89% of Qianfan chapters reference an earlier chapter in
#   the opening sentence — this is an IDIOMATIC rhetorical move in the
#   high-scoring corpus, NOT a v2-style antipattern.
# Verified Qianfan opening idioms (across multiple ids):
#   - "The framework constructed in Chapter 1 — [substantive recap of
#     what Ch1 established] — finds its first and most consequential
#     application in [topic of this chapter]." (id 91 chapter 2)
#   - "第1章已论证：[recap of Ch1's substantive claim]。本章承接全链条
#     技术框架中的数据环节，系统梳理[substantive new claim]。" (id 8 ch 2)
#   - "The N preceding chapters have populated [topic]. [Substantive
#     new claim]." (id 91 chapter 9)
# These are SUBSTANTIVE recaps anchored to a named prior result, not
# the bare "Building on §X established in §Y" template v3 correctly
# banned (which IS still antipattern at Qianfan's 0% rate).
#
# v4 amendment:
#   - KEEPS all v3 antipatterns EXCEPT the §N-in-openings blanket ban:
#     - Building-on / Applied-to / Under-the-rubric / Using-the-taxonomy
#       templates STAY forbidden (Qianfan 0%).
#     - "This section/chapter/report" as opening subject STAYS forbidden
#       (Qianfan 0%).
#     - Prose-before-table STAYS required.
#     - Disconnected exposition STAYS forbidden.
#   - RE-ALLOWS Chapter-N / 第N章 references in opening sentences when
#     PAIRED with a substantive recap of what that earlier chapter
#     established — matches Qianfan's 75-89% idiom rate.
#   - DROPS the "OPENING-SENTENCE FORBIDDEN-§N RULE OVERRIDES THIS
#     NARROWING" addendum — body-narrowing's named-artefact allowance
#     now applies uniformly to body AND openings.
#   - ADDS a new "Acceptable chapter-reference idioms" block with the
#     three Qianfan-verified opening patterns.
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
    "SECTION-OPENING PROSE LEAD (P2-Wave-3-§12.A.v4 — Qianfan-parity "
    "amendment to v3):\n"
    "EVERY section, including those whose primary content is a markdown "
    "table or list, MUST open with at least one substantive prose sentence "
    "INTRODUCING THE TOPIC OF THIS SECTION. The prose lead names the actual "
    "subject matter directly. References to earlier chapters ARE allowed "
    "when paired with a substantive recap of what that chapter established "
    "(this is the Qianfan idiom — see Acceptable patterns below); what is "
    "FORBIDDEN is the formulaic '[Building on / Applied to / Under the "
    "rubric of] §X' template that reads as compliance theatre.\n\n"
    "Critical: each section reads like the opening of a book CHAPTER — "
    "diving into the topic — not like a meeting summary that lists what "
    "earlier sections discussed. When the section's primary content is a "
    "table or list, the prose lead comes BEFORE that block; the data block "
    "does NOT replace the prose lead. Pattern: prose-paragraph-then-data. "
    "NEVER data-block-first-no-prose.\n\n"
    "FORBIDDEN opening patterns (verified against the Qianfan #1 corpus — "
    "these antipatterns fire ~0% in Qianfan and ~80% in pre-v3 Lunon, and "
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
    "  the opening sentence. Qianfan never opens a chapter with a meta-"
    "  subject; the opening subject is the substantive topic noun (the "
    "  thing being discussed), not a referent to the document itself.\n"
    "- Opening with a markdown table (`|...|...|`) or list (`-` / `*`) "
    "  without a prose sentence first. The section MUST have a prose "
    "  paragraph BEFORE any data block.\n"
    "- Stating only the section topic with no substantive claim about it "
    "  (disconnected exposition — judge penalises). The opening must "
    "  carry a claim, definition, anchor, or quantitative fact about the "
    "  topic, not just name it.\n\n"
    "Acceptable opening patterns (EN — modeled on verified Qianfan #1 "
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
    "Acceptable chapter-reference idioms (v4-added; Qianfan fires this "
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
    "Acceptable opening patterns (ZH — modeled on Qianfan ZH samples):\n"
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
    "contradicted Qianfan's verified 75-89% rate.\n\n"
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


# P3-W3 (2026-05-27): mid-paragraph cross-reference directive. Qianfan's
# verified corpus-wide pattern (11/11 articles average 100-451 cross-chapter
# refs per article) attaches xrefs MID-PARAGRAPH to factual claims, NOT as
# chapter-opening templates. The Wave-3 §12.A rewrite (PR #32-#34) eliminated
# the "Building on §X established in §Y" antipattern at chapter openings
# (0% in the W3 smoke vs 80% in W2). P3-W3 installs the POSITIVE directive:
# every chapter ≥5 mid-paragraph xrefs, attached to specific claims, with
# acceptable / forbidden forms enumerated.
_MID_PARAGRAPH_XREF_RULE = (
    "MID-CHAPTER CROSS-REFERENCE DISCIPLINE (P3-W3, 2026-05-27):\n"
    "Each H2 chapter (`## N Title`) must contain AT LEAST 5 cross-references "
    "to other chapters/sections in the report, embedded MID-PARAGRAPH (not "
    "as a chapter-opening template), each attached to a specific factual "
    "or analytical claim. This is Qianfan's verified corpus-wide pattern "
    "(11/11 articles, 100-451 cross-refs each) and the structural feature "
    "that makes long articles feel coherent rather than survey-like.\n"
    "\n"
    "ACCEPTABLE forms (attached to a specific factual/analytical claim):\n"
    "  EN: '(Section N.M)' parenthetical | 'as detailed in Chapter N' | "
    "'Chapter N will return to this' | 'the {entity} introduced in §N' | "
    "'(see §N below)'\n"
    "  ZH: '（详见§N.M）' | '如第N章所述' | '第N章将进一步分析' | "
    "'承接第N章关于{topic}的论述' | '（见第N章）'\n"
    "\n"
    "FORBIDDEN forms:\n"
    "  - Chapter-opening template recapping the prior chapter "
    "    ('Building on §X established in §Y, this section…'). Already "
    "    eliminated by _SECTION_OPENING_PROSE_LEAD_RULE; this directive "
    "    reinforces. A chapter MAY open with a substantive bridge that "
    "    names the analytical role of THIS chapter relative to a sibling "
    "    (e.g. 'If §2 covers X, §3 covers Y') — see _SECTION_OPENING_PROSE_"
    "    LEAD_RULE for the prose-bridge form.\n"
    "  - Generic 'as discussed earlier' / 'we will see below' WITHOUT a "
    "    §N anchor — these are recap fillers, not callbacks.\n"
    "  - Bare `§N` reference with no analytical claim attached.\n"
    "\n"
    "QUALITY TARGETS:\n"
    "  - ≥40% of cross-refs are parenthetical `(Section N.M)` form — the "
    "    densest, lowest-narrative-overhead form Qianfan uses to attach "
    "    a fact to its prior-chapter source.\n"
    "  - Forward-defer references ('§N below will detail') allowed but "
    "    ≤30% of total — too many forward-defers signal the writer "
    "    deferred substance rather than delivered it.\n"
    "  - DO NOT use §N to reference sections that don't exist in the "
    "    article's heading set; the post-write validator strips dangling "
    "    forward-refs as drift entries (and may delete the offending "
    "    sentence). When you forward-defer, the deferred chapter MUST "
    "    appear in the report TOC."
)


# P3-W4 (2026-05-27): mermaid semantic-diagram directive. Qianfan-verified
# corpus pattern (10/11 articles, 1-19 mermaid blocks each, used semantically
# for timelines / dependencies / decision trees / process flows). Lunon's
# id=91 W2 baseline has 0 mermaid blocks. The directive opts the writer
# IN to emit diagrams when the section content fits one of the four shapes,
# with strict constraints to avoid LLM-malformation modes (parser-breaking
# bold/code-spans inside nodes; missing terminating fence; decorative
# duplication of adjacent prose).
_MERMAID_DIRECTIVE = (
    "SEMANTIC DIAGRAM DIRECTIVE (P3-W4, 2026-05-27):\n"
    "When a section introduces ONE of:\n"
    "  (a) a timeline with ≥3 dated milestones,\n"
    "  (b) a dependency relationship where entity A produces input for "
    "entity B with ≥3 such links,\n"
    "  (c) a decision tree with ≥3 branching conditions,\n"
    "  (d) a multi-stage process flow with ≥3 stages,\n"
    "emit a mermaid block to visualise it. Syntax:\n"
    "  ```mermaid\n"
    "  timeline\n"
    "    title <topic>\n"
    "    <year> : <event>\n"
    "    <year> : <event>\n"
    "  ```\n"
    "  OR:\n"
    "  ```mermaid\n"
    "  graph LR\n"
    "    A[<entity>] --> B[<entity>]\n"
    "  ```\n"
    "Per chapter: max 2-3 mermaid blocks; one per distinct purpose.\n"
    "FORBIDDEN forms (these break the renderer or add no signal):\n"
    "  - Markdown formatting INSIDE node labels: NO **bold**, *italic*, "
    "`code`, [^N] footnote refs, or `[link](url)` — the parser breaks.\n"
    "  - Mermaid blocks WITHOUT a terminating triple-backtick fence.\n"
    "  - First line not a valid diagram type "
    "(timeline | graph | flowchart | sequenceDiagram | stateDiagram | "
    "stateDiagram-v2 | classDiagram | erDiagram | journey | gantt | pie | "
    "requirementDiagram | gitGraph | C4Context | mindmap). "
    "Anything else gets stripped by the post-pass.\n"
    "  - Decorative diagrams that restate the immediately-preceding "
    "paragraph (the diagram must ADD a structural view the prose doesn't).\n"
    "Tasks where mermaid is most likely to help: predict (timeline of "
    "milestones), explain-mechanism (causal dependency graph), "
    "list-all (process flow for entity-introduction timeline)."
)


# P3-W6.b (2026-05-27): STAKEHOLDER-SEGMENTED CLOSING rule.
#
# System-prompt summary of the 3-5 addressee-block discipline + non-
# overlap quality bar. The heavy lifting (per-stakeholder label +
# content_directive payload) is in the writer.py user-prompt
# `stakeholder_block`. This rule gives the writer LLM a system-level
# anchor so the per-section directive from writer.py reinforces — not
# contradicts — the structural contract. Qianfan corpus-verified
# pattern: 6/11 articles, typically 4 stakeholders for predict (q3,
# q14) or 7 for compare-contest (q23 — though Lunon's architect caps
# emit at 5, the rule's "3-5" wording matches architect.py:213).
# Architect-side schema lives at architect.py:211-222; post-write
# validator `_validate_stakeholder_overlap` (already ACTIVE since
# PR #42, P3-W6) at validation.py:517-716 enforces pairwise Jaccard
# 4-gram overlap < 0.20 between every pair of sub-sections. The
# `_STAKEHOLDER_JACCARD_MAX` constant references the same threshold
# value the validator uses so source-of-truth stays one place.
_STAKEHOLDER_JACCARD_MAX = 0.20

_STAKEHOLDER_RULE = (
    "STAKEHOLDER-SEGMENTED CLOSING (P3-W6; applies when "
    "`stakeholder_chapter` is in the plan and the section currently "
    "being written IS the stakeholder chapter):\n"
    "When the architect signals a plural audience, the closing chapter "
    "splits recommendations into 3-5 stakeholder addressee blocks.\n"
    "Per sub-section requirements:\n"
    "  - Heading names the addressee verbatim (EN: 'For Policymakers' / "
    "'Recommendations for Investors'; ZH: '对政策制定者的建议' / "
    "'对投资者的建议').\n"
    "  - 200-500 words of advice SPECIFIC to that stakeholder's decision "
    "context (budget / time horizon / decision authority / information "
    "access).\n"
    "  - Opening phrase modelled on Qianfan corpus: 'For {stakeholder}, "
    "the priority is…' / '{Stakeholder} should focus on…' / "
    "'From the {stakeholder} perspective, three steps emerge…'.\n"
    "Non-overlap discipline:\n"
    f"  - The post-write validator enforces pairwise Jaccard 4-gram "
    f"overlap < {_STAKEHOLDER_JACCARD_MAX:.2f} between every pair of "
    "sub-sections.\n"
    "  - Each block's recommendations must be DISJOINT from sibling "
    "blocks; advice applicable to multiple stakeholders goes under the "
    "PRIMARY stakeholder only.\n"
    "  - Forbidden: 'recommendations for all stakeholders'-style "
    "boilerplate; advice that doesn't name the stakeholder's specific "
    "constraints."
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
    "INSIGHT DENSITY — DISTRIBUTIONAL COVERAGE (Wave 3 PR 2 extension of "
    "Wave 2 §3.2):\n"
    "Every leaf section (H4 `#### 1.1.1 Foo` in deep-hierarchy archetypes, "
    "or H2 `## N Foo` body in flat archetypes like list-all) must close with "
    "a substantive analytical payoff drawn from the SIX elements below. "
    "Pre-Wave-2 the rule said 'pick AT LEAST ONE of the four' — the verified "
    "id=91 smoke (2026-05-26) showed the writer over-fires the EASY elements "
    "(contrarian 1.77× over, quant 2.44× over) and under-fires the HARD one "
    "(forward-looking 0.14× short, 7× below Qianfan's density). Path of "
    "least resistance defeats the rule's intent. Wave 2 now requires "
    "DISTRIBUTIONAL coverage across the section's leaves rather than "
    "per-leaf ANY-of-four:\n"
    "\n"
    "TARGET DISTRIBUTION — per-archetype, calibrated against the 10-doc "
    "Qianfan reference corpus (Wave 2 PR #30 self-review). The specific "
    "minimum percentages for THIS archetype are interpolated in the "
    "user-prompt `INSIGHT DISTRIBUTION FOR THIS SECTION` block below — "
    "DEFER TO THAT BLOCK FOR THE EXACT TARGETS. Do not assume a uniform "
    "20% floor across elements; the Qianfan corpus shows wildly different "
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
    "(d) higher than (b)/(c) — the Qianfan corpus shows explain-mech "
    "explains via alternatives + forward-looking projection, NOT via "
    "contrarian framing or heavy quantification. The exact percentages "
    "for THIS section's archetype are in the user-prompt block.\n"
    "\n"
    "SIX ELEMENTS (Wave 3 PR 2: extended from 4 to 6 to cover RACE Insight "
    "criteria 2 + 3 that were structurally uncovered by the original 4):\n"
    "\n"
    "  (a) FORWARD-LOOKING IMPLICATION → targets RACE 4 (Forward-Looking and "
    "      Inspirational Thinking). A stated consequence, follow-on effect, "
    "      or downstream condition, grounded in a named source and tied to "
    "      a concrete time horizon (e.g. 'By 2027, Pegasus-class Cloths are "
    "      likely to undergo a second V-stage revision per the Hades-arc "
    "      continuity, conditional on canonical resolution of the Cloth-of-"
    "      Sagittarius reassignment timeline').\n"
    "\n"
    "  (b) NAMED CONTRARIAN FRAMING → targets RACE 1 (Analysis Depth and "
    "      Originality). An explicit alternative to the consensus "
    "      interpretation, attributed to a specific source or reasoning "
    "      chain (e.g. 'Despite the standard reading that Marin's Cosmo "
    "      level is bounded at Silver Saint tier, the Episode G data "
    "      suggests a Gold-class burst capacity under specific conditions').\n"
    "\n"
    "  (c) QUANTIFIED PROJECTION OR CONFIDENCE RANGE → targets RACE 1 "
    "      (Analysis Depth — quantified rigour). A numeric range, "
    "      probability, or scoped estimate, with stated assumptions (e.g. "
    "      '60-75% of the Sanctuary's Silver-tier roster falls within the "
    "      Mach 2-5 speed band per the 1986-1989 canon; outliers are "
    "      explicitly the Ophiuchus and Crystal Saint cases').\n"
    "\n"
    "  (d) NAMED-ALTERNATIVE COMPARISON → targets RACE 1 (Analysis Depth — "
    "      original synthesis via comparison). A direct comparison against "
    "      a named alternative entity, framework, theory, or counterfactual "
    "      (e.g. 'Whereas Mu's Crystal Wall absorbs kinetic energy radially, "
    "      Aiolia's Lightning Plasma propagates directionally; the two "
    "      defensive postures imply opposite tradeoffs at peak intensity').\n"
    "\n"
    "  (e) CAUSAL CHAIN → targets RACE 2 (Logical Reasoning and Causal "
    "      Relationships). A MULTI-STEP causal explanation with TWO OR "
    "      MORE links. A single causal step ('A produces B', 'X due to "
    "      Y', 'C enables D') is NOT a chain — single-step causation is "
    "      under-payoff for this element. The chain shows the intervening "
    "      mechanism with 2+ links: X leads to Y, which in turn produces "
    "      Z because of evidence W. (e.g. 'Saori Kido's emergence as "
    "      Athena-incarnate is causally chained: her grandfather's "
    "      Foundation Aries-Gold-Cloth deal in the Battle of the Twelve "
    "      Houses arc preserves the Cosmo-channeling capacity through her "
    "      bloodline; this latent Cosmo activates upon witnessing Seiya's "
    "      first Pegasus Meteor Fist, which in turn awakens the Seventh "
    "      Sense she needs to wield the Athena Cloth in the Sanctuary "
    "      finale'). Chain-marker phrases (compliance detector counts "
    "      these and requires ≥2 in the same leaf): 'leads to / led to / "
    "      leading to / results in / resulted in / gives rise to / gave "
    "      rise to / giving rise to / in turn / which produces|enables|"
    "      drives|leads|causes|results in / 导致 / 引发 / 进而 / 从而'. "
    "      Bare 'enables' / 'produces' / 'due to' / 'subsequently' DO "
    "      NOT count toward the chain count — they're single-step verbs "
    "      that the detector intentionally ignores to avoid false-positive "
    "      compliance credit. NEW IN WAVE 3 PR 2 — this element was the "
    "      largest structural gap vs Qianfan (Lunon at 0.02 per 1k words "
    "      vs Qianfan 0.31 — 20× behind on multi-link causal density).\n"
    "\n"
    "  (f) PROBLEM-TRADEOFF → targets RACE 3 (Problem Insight and "
    "      Solutions). An explicit identification of a tension, paradox, "
    "      challenge, or tradeoff, with substantive insight into how it "
    "      resolves OR what the resolution constraint is (e.g. 'The "
    "      apparent paradox — Bronze Saints repeatedly defeating Gold "
    "      opponents despite the rank's stated power hierarchy — resolves "
    "      via the Seventh-Sense doctrine: Cosmo depth, not Cloth tier, "
    "      determines the outcome ceiling. The tradeoff is narrative "
    "      versus mechanical consistency: Kurumada accepts the tier "
    "      paradox to enable protagonist progression'). Marker phrases: "
    "      'the (apparent) paradox / the tension / the challenge of / the "
    "      central issue / to address this / the resolution lies / "
    "      reconciles / 悖论 / 矛盾 / 挑战在于 / 关键问题'. NEW IN WAVE 3 "
    "      PR 2 — Lunon was structurally uncovered on RACE 3.\n"
    "\n"
    "GROUNDING RULE (unchanged from prior policy): every element above MUST "
    "be evidence-backed — name a source, cite a date or named work, or "
    "ground the projection in stated assumptions. Free speculation without "
    "evidential support hurts more than absent insight.\n"
    "\n"
    "DISTRIBUTIONAL COVERAGE — clarification (Wave 3 PR 2): the per-archetype "
    "targets are about the SECTION-WIDE coverage rate, NOT per-leaf "
    "requirements. A single leaf needs to carry AT LEAST ONE of (a)-(f); "
    "across all leaves in the section, the proportions track the per-"
    "archetype distribution targets in `_INSIGHT_DISTRIBUTION_BY_ARCHETYPE` "
    "(some leaves carry causal_chain, others carry forward_looking, etc.). "
    "Multiple elements can apply to ONE leaf — that's fine.\n"
    "\n"
    "AVOID FORMULAIC INSERTION: do NOT bolt a generic 'looking ahead...' or "
    "'further research is needed' onto every leaf. The six elements above "
    "are substantive payoffs grounded in the leaf's actual evidence. If the "
    "evidence for this leaf genuinely cannot support any of (a)-(f) — a "
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
# CALIBRATED against the 10-doc Qianfan reference corpus via
# `scripts/p2_writer_compliance.py` weighted-mean profile. Pre-fix
# targets were reasoning-derived ("pick 30/20/20/20"); the Qianfan
# corpus revealed several pre-fix targets were way off:
#   - list-all: pre-fix said 30% forward-looking; Qianfan does 69%
#   - explain-mech: pre-fix said 20% contrarian; Qianfan does 10%
#   - trend: pre-fix said 15% contrarian; Qianfan does 2%
# Wave 2 PR #30 targets are set to ≈80% of the observed Qianfan
# weighted mean per element per archetype, so they're MEASURABLE
# floors (writer can clear them with some variance) without
# overspecifying. The compliance scorer (`p2_writer_compliance.py`)
# uses these targets to compute per-element gap percentages on every
# smoke output.
# Wave 3 PR-0 (2026-05-26) full-archetype fresh-corpus recalibration:
# 14 Qianfan tasks fetched via PR #31 (8/14/20/23/56/91 gate-verify-5
# + 2/12/3/4/38/44/62/73 missing-archetype top-up) gave the first true
# cross-archetype baseline. The Wave 2 PR #30 calibration used the
# .docx vendor corpus which was lossy (gap-map §12.4) and missed
# compare/predict/trend/recommend tasks entirely.
#
# Wave 3 PR 2 (2026-05-26) extension: added two NEW elements that map
# directly to RACE Insight criteria 2 (Logical Reasoning and Causal
# Relationships) and 3 (Problem Insight and Solutions) — both of which
# Lunon's original 4 elements did NOT cover. Lunon was over-covering
# RACE 1 (Originality) with 3 of 4 elements (contrarian + quant + alt)
# while leaving RACE 2 and RACE 3 structurally uncovered:
#   (e) CAUSAL CHAIN     → RACE 2 (Logical Reasoning and Causal Relationships)
#   (f) PROBLEM-TRADEOFF → RACE 3 (Problem Insight and Solutions)
# Per-archetype targets are derived from Qianfan corpus observed rates
# minus 5-15% headroom so a Lunon writer at the observed rate lands
# comfortably in-band.
#
# Wave 2 PR #30 → Wave 3 PR 2 calibration deltas (per-archetype targets
# 5-15% below observed Qianfan rates):
#   - list-all (n=1, id=91, Qianfan: fwd 62/contr 3/quant 0/alt 76/causal 42/problem 5):
#     fwd 55→50, contr 10→1 (was 3× too high), quant 17→0 (was way too high),
#     alt 47→60 (was too low), +causal 30, +problem 3
#   - compare (n=2, ids 2,12, Qianfan: fwd 47/contr 6/quant 27/alt 22/causal 30/problem 3):
#     fwd 50→40, contr 10→3 (was too high), quant 17→20 (small bump),
#     alt 47→15 (was way too high), +causal 20, +problem 3
#   - explain-mechanism (n=4, ids 8/20/23/56, Q: fwd 19/contr 4/quant 6/alt 32/causal 31/problem 5):
#     fwd 28→15, contr 8→3 (was too high), quant 1→3, alt 42→25 (was too high),
#     +causal 25 (RACE 2 central to this archetype), +problem 4
#   - predict (n=1 reliable, id=3, Q: fwd 76/contr 8/quant 33/alt 42/causal 57/problem 8):
#     fwd 45→70 (was way too low — predict is forward-by-mission),
#     quant 5→25 (was way too low), alt 10→35 (was way too low),
#     +causal 45 (RACE 2 central — predict needs causal grounding),
#     +problem 6
#   - trend (n=2, ids 38,44, Q: fwd 40/contr 2/quant 14/alt 4/causal 12/problem 2):
#     fwd 45→35 (close), quant 2→10 (was too low), +causal 10, +problem 1
#   - recommend (n=2, ids 62,73, Q: fwd 30/contr 2/quant 7/alt 48/causal 20/problem 1):
#     fwd 40→25 (was too high), contr 5→1, alt 15→40 (was way too low —
#     recommend compares options densely), +causal 15, +problem 1
_INSIGHT_DISTRIBUTION_DEFAULT = {
    "forward_looking_min": 20,
    "contrarian_min": 3,
    "quant_min": 3,
    "alternative_min": 30,
    # Wave 3 PR 2: NEW elements targeting RACE 2 + 3.
    # Greptile PR #34 round-1 follow-up: causal_chain target lowered after
    # tightening the detector to require 2+ chain markers per leaf (the
    # original broad detector fired on single-step "enables" / "produces" /
    # "due to" / "subsequently"). Under the strict detector Qianfan
    # observed rates are 0-5% per archetype (mean ~2.5%), so the default
    # floor is set to 2 — a writer producing any genuine multi-link chains
    # comfortably clears it.
    "causal_chain_min": 2,
    "problem_tradeoff_min": 3,
}
_INSIGHT_DISTRIBUTION_BY_ARCHETYPE: dict[str, dict[str, int]] = {
    # Wave 3 PR-0 fresh-corpus recalibration (2026-05-26). All targets set
    # 5-15% below the observed Qianfan mean per archetype so a Lunon writer
    # at the observed rate lands comfortably in-band. See block comment
    # above this dict for per-archetype observed rates + delta rationale.
    "predict": {
        "forward_looking_min": 70,  # was 45; Q observed 76 — predict is forward-by-mission
        "contrarian_min": 5,
        "quant_min": 25,  # was 5; Q observed 33 — predict densely quantifies
        "alternative_min": 35,  # was 10; Q observed 42 — predict compares scenarios
        # NEW elements (Wave 3 PR 2). Greptile PR #34 round-1 follow-up:
        # causal_chain target lowered from 45 → 2 after tightening detector
        # (strict 2-link requirement gave Q strict-rate of 3% on id=3;
        # the prior 45 target was based on the broad detector that fired
        # on single-step "enables/produces/due to" non-chains).
        "causal_chain_min": 2,
        "problem_tradeoff_min": 5,  # Q observed 8 — kept near the broader-detector reading since prob detector tightening only dropped 2 markers
    },
    "trend": {
        "forward_looking_min": 35,  # was 45; Q observed 40 (close)
        "contrarian_min": 1,
        "quant_min": 10,  # was 2; Q observed 14 — trend articles quantify more
        "alternative_min": 3,  # was 5; Q observed 4 (close)
        "causal_chain_min": 1,  # Greptile PR #34 follow-up: was 10; Q strict-rate 1%
        "problem_tradeoff_min": 1,  # Q observed 2 — trend is descriptive
    },
    "recommend": {
        "forward_looking_min": 25,  # was 40; Q observed 30 — was over-targeting
        "contrarian_min": 1,
        "quant_min": 5,
        "alternative_min": 40,  # was 15; Q observed 48 — recommend compares options
        "causal_chain_min": 1,  # Greptile PR #34 follow-up: was 15; Q strict-rate 1%
        "problem_tradeoff_min": 1,  # Q observed 1 — recommend is decisive
    },
    "list-all": {
        "forward_looking_min": 50,  # was 55; Q observed 62 (close)
        "contrarian_min": 1,  # was 10; Q observed 3 — was 3× too high
        "quant_min": 0,  # was 17; Q observed 0 — was way too high
        "alternative_min": 60,  # was 47; Q observed 76 — was too low
        # Greptile PR #34 follow-up: causal_chain was 30; Q strict-rate
        # 0% on id=91. list-all is enumeration-shaped (entity profiles)
        # and rarely uses multi-link chains — keeping the floor at 0
        # surfaces no false deficit but lets a writer voluntarily land
        # chains in synthesis sections.
        "causal_chain_min": 0,
        "problem_tradeoff_min": 3,  # Q observed 5
    },
    "compare": {
        "forward_looking_min": 40,  # was 50; Q observed 47 (close)
        "contrarian_min": 3,  # was 10; Q observed 6 — was too high
        "quant_min": 20,  # was 17; Q observed 27
        "alternative_min": 15,  # was 47; Q observed 22 — was way too high
        "causal_chain_min": 3,  # Greptile PR #34 follow-up: was 20; Q strict-rate 5%
        "problem_tradeoff_min": 3,  # Q observed 3
    },
    "explain-mechanism": {
        "forward_looking_min": 15,  # was 28; Q observed 19
        "contrarian_min": 3,  # was 8; Q observed 4 — was too high
        "quant_min": 3,  # was 1; Q observed 6
        "alternative_min": 25,  # was 42; Q observed 32 — was too high
        # Greptile PR #34 follow-up: causal_chain was 25; Q strict-rate
        # 4% mean on ids 8/20/23/56. RACE 2 (Causal Reasoning) is the
        # archetype's mission but the multi-link chain density even in
        # Qianfan is modest under the strict detector — most explain-mech
        # causation is single-step "X because Y" which doesn't count.
        "causal_chain_min": 3,
        "problem_tradeoff_min": 4,  # Q observed 5
    },
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
# Lunon's W9 outputs (~9k word median); the #1-leaderboard Qianfan corpus
# runs ~22k words mean across 100 articles; explain-mechanism extremes
# like id=56 reach ~80k (confirmed 2026-05-26 smoke).
#
# Calibration history:
#  - W9 baseline: 1.0× → ~9k words/article
#  - PR #20 (2026-05-22): 2.2× → ~20k words/article (still 4.3× short of
#    Qianfan id=56's 80k)
#  - Post-2026-05-26 smoke: 4.0× → target ~36k words/article. The smoke
#    at 2.2× produced 18.8k words for id=56 (1.34× W9, but still 4.26×
#    short of Qianfan). Bumped to 4.0× to get to ~36k target, a
#    meaningful step toward Qianfan-class length without overshooting
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
    the historical W9-era catalog medians to push toward Qianfan-corpus
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
    middle_rules.extend(
        [
            _INSIGHT_MIN,
            CLEANING_RESISTANT_RULE,
            _SECTION_OPENING_PROSE_LEAD_RULE,
            _MID_PARAGRAPH_XREF_RULE,
            _MERMAID_DIRECTIVE,
            _STAKEHOLDER_RULE,
        ]
    )
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
            f"Wave-2 Qianfan-corpus-calibrated shape (Qianfan id=91 / id=14 "
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
            f"against the Qianfan corpus). Never exceed 4 levels of heading "
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


def check_xref_quality(text: str) -> dict:
    """P3-W3 (2026-05-27): post-write cross-reference quality audit.

    Measures the contract `_MID_PARAGRAPH_XREF_RULE` imposes:
      - per-chapter xref count (target ≥5 mid-paragraph references)
      - opening-template antipattern count (target 0 — already enforced
        by Wave-3 §12.A; this is a regression detector)
      - dangling forward-refs (§N where N is not in the heading set)
      - parenthetical-form ratio (target ≥40%)
      - forward-defer ratio (target ≤30%)

    Returns:
      {
        "ok": bool,
        "n_chapters": int,
        "per_chapter_xref_counts": {chapter_id: count},
        "opening_template_violations": int,
        "dangling_forward_refs": [str],
        "n_parenthetical": int,
        "n_total_xrefs": int,
        "parenthetical_ratio": float,
        "forward_defer_ratio": float,
        "fail": [reason, ...],
      }

    The "ok" flag is advisory — same downgrade-to-telemetry pattern as
    check_insight_minimums (post-W9 2026-05-21).
    """
    # Heading set: collect every "§N", "§N.M" target the article can
    # legitimately cross-reference to. We accept the `## N Title` or
    # `## N.M Title` numeric prefix in markdown headings as the legitimate
    # set of §-targets — same convention `numbering_fix.renumber_headings`
    # uses.
    # Greptile PR #39 round-7 issue #2: collect heading_ids and mask
    # heading lines uniformly across H2-H6. The prior `#{2,4}` bound
    # left H5/H6 lines unmasked: a sub-sub-heading like
    # `##### 5.1 Section 99 Subtopic` would have "Section 99" picked up
    # by `generic_pattern` and "99" flagged as a dangling ref, even
    # though it's title text. Widening to `#{2,6}` aligns the masked-
    # text replacement, in-body mask in `_count_refs_in`, and this
    # heading-id collection.
    heading_ids: set[str] = set()
    for m in re.finditer(r"(?m)^#{2,6}\s+([\d\.]+)\b", text):
        hid = m.group(1).rstrip(".")
        heading_ids.add(hid)

    # All xref candidates in body. Classify into (paren, bare) WITHOUT
    # double-counting: parenthetical refs are captured first, then bare
    # refs are filtered to exclude any whose span is inside a paren
    # match (avoids counting `(Section 2)` as both paren AND bare).
    paren_pattern = re.compile(r"\((?:Section|§|Chapter|Sec\.)\s*([\d\.]+)\)", re.I)
    generic_pattern = re.compile(r"(?:§\s*|(?:Section|Chapter|Sec\.)\s+)([\d\.]+)", re.I)
    zh_pattern = re.compile(r"第\s*([一二三四五六七八九十0-9\.]+)\s*[节章]")

    # Greptile PR #39 round-5: mask heading lines so the patterns don't
    # pick up `Chapter N` / `Section N` / `第N章` in TITLE text. The
    # `generic_pattern`'s `(?:Section|Chapter|Sec\.)\s+([\d\.]+)` alt
    # matches title words like "Chapter 47" in `## 5 Chapter 47 Overview`,
    # and "47" then lands in `dangling_forward_refs` even though it's
    # naming the chapter, not navigating to it. This is the same class
    # of bug `xref_repair._rewrite_body_only` addressed in round-4 — the
    # auditor needed the same filter. The mask replaces heading lines
    # with same-length space runs so character offsets in the masked
    # text match offsets in the original `text` exactly (the
    # forward-defer proximity windows below still index into `text`).
    masked_text = re.sub(
        r"(?m)^#{2,6}[^\n]*",
        lambda m: " " * len(m.group(0)),
        text,
    )

    paren_matches = list(paren_pattern.finditer(masked_text))
    paren_refs = [m.group(1) for m in paren_matches]
    paren_spans = [(m.start(), m.end()) for m in paren_matches]

    def _in_paren(pos: int) -> bool:
        return any(s <= pos < e for s, e in paren_spans)

    raw_refs: list[str] = []
    raw_ref_spans: list[tuple[int, int]] = []
    for m in generic_pattern.finditer(masked_text):
        if _in_paren(m.start()):
            continue
        raw_refs.append(m.group(1))
        raw_ref_spans.append((m.start(), m.end()))
    zh_ref_matches = list(zh_pattern.finditer(masked_text))
    zh_refs = [m.group(1) for m in zh_ref_matches]
    zh_ref_spans = [(m.start(), m.end()) for m in zh_ref_matches]
    all_refs = list(paren_refs) + raw_refs + zh_refs

    # Forward-defer detection: count XREFS that appear in a forward-defer
    # CONTEXT, not raw phrase occurrences. The intent from
    # `_MID_PARAGRAPH_XREF_RULE` is "≤30% of *xrefs* are forward-defer
    # style"; Greptile PR #39 round-2 noted that the prior implementation
    # divided raw phrase count (which fires on any "below" / "will return"
    # in the document, including non-xref contexts) by xref count —
    # numerator and denominator had incompatible units, and a document
    # using "below" 6 times around 5 xrefs would score `forward_ratio =
    # 1.2 > 0.30` and spuriously fail.
    #
    # New implementation: for each xref span, check whether a forward-
    # defer phrase appears within an ±80-char window around it (a
    # sentence-level proximity bound — captures "will return below
    # (Section 5)" but rejects "below" 200 chars away from any xref).
    forward_defer_pattern = re.compile(
        r"(?:will\s+(?:return|cover|detail|address|examine)|below|下文|下面|后续|"
        r"第\s*\d+\s*[节章]\s*将|see\s+(?:Section|§|Chapter)\s+\d[\d\.]*\s*(?:below|later))",
        re.I,
    )
    all_xref_spans = list(paren_spans) + raw_ref_spans + zh_ref_spans
    _XREF_DEFER_WINDOW = 80  # chars on each side — ~1 sentence of context
    n_forward_defer = 0
    for xstart, xend in all_xref_spans:
        wstart = max(0, xstart - _XREF_DEFER_WINDOW)
        wend = min(len(text), xend + _XREF_DEFER_WINDOW)
        # Clamp at paragraph / heading boundaries. A "below" or "will
        # return" in a prior paragraph (or chapter) is not semantically
        # tied to this xref — readers parse sentences within paragraphs,
        # not across them. Without this clamp, an isolated "below" 50
        # chars away in the prior chapter would falsely fire.
        #
        # Greptile PR #39 round-2: `pre` is sliced from `text[wstart:xstart]`
        # exactly once, so every `rfind` returns an index relative to the
        # ORIGINAL wstart. Capture `pre_start = wstart` before the loop
        # and use it as the base for absolute-position arithmetic — the
        # prior `wstart + idx + len(sep)` used the in-place-mutated
        # `wstart` as the base, inflating the offset by the previous
        # iteration's clamp. Concrete failure: original wstart=100,
        # `"\n\n"` at pre-idx 5 → wstart=107; then `"\n## "` at pre-idx 8
        # produced 107+8+4=119, but the correct absolute position is
        # 100+8+4=112 — a 7-char over-narrowing of the window that
        # silently dropped forward-defer phrases past the inflated
        # boundary.
        pre = text[wstart:xstart]
        pre_start = wstart
        for sep in ("\n\n", "\n## ", "\n### ", "\n#### "):
            idx = pre.rfind(sep)
            if idx >= 0:
                wstart = max(wstart, pre_start + idx + len(sep))
        post = text[xend:wend]
        for sep in ("\n\n", "\n## ", "\n### ", "\n#### "):
            idx = post.find(sep)
            if idx >= 0:
                wend = min(wend, xend + idx)
        # Greptile PR #39 round-6: search `masked_text`, not `text`. The
        # pre-window clamp can land `wstart` past a `\n## ` boundary at
        # the heading content itself (e.g. `"5 Section will return to §3
        # below"`). If we searched the unmasked `text`, a heading title
        # containing "will return" / "below" / another forward-defer
        # phrase within 80 chars of an xref would inflate
        # `n_forward_defer` — same heading-bleed class of bug round-5
        # fixed for ref counting. `masked_text` preserves character
        # offsets (same-length space substitution), so the clamped
        # wstart/wend positions remain valid and no arithmetic changes.
        if forward_defer_pattern.search(masked_text, wstart, wend):
            n_forward_defer += 1

    # Opening-template antipattern (P3-W3 regression detector for §12.A.v4).
    opening_template_pattern = re.compile(r"(?m)^#{2}\s+[\d\.]*\s*\S.*\n+\s*Building on\b", re.I)
    n_opening_templates = sum(1 for _ in opening_template_pattern.finditer(text))

    # Dangling forward-refs: numeric §N that isn't in the heading set.
    # Only check numeric forms — Chinese 第X章 numbers are looser semantics
    # (chapter ordinals, not heading-id matches).
    #
    # A ref `N.M` is NOT dangling when its top-level chapter `N` exists
    # in the heading set, even if `### N.M` isn't explicitly rendered:
    # the writer may legitimately reference a sub-section of an existing
    # chapter, and over-flagging here would force-rewrite legitimate
    # navigational refs.
    # Greptile PR #39 round-7 issue #1: dedupe by unique ref-id.
    # The prior list accumulated one entry per OCCURRENCE of a dangling
    # ref, so a doc that cited `(Section 47)` five times would produce
    # `dangling_forward_refs=["47","47","47","47","47"]` and the fail
    # entry would read `dangling_forward_refs=5` — a caller reading the
    # audit output would reasonably interpret that as five distinct
    # missing sections when there's only one. Order-preserving dedup
    # via a `seen` set keeps the first-occurrence ordering stable for
    # any downstream consumer that snapshots the list.
    dangling_seen: set[str] = set()
    dangling: list[str] = []
    for ref in paren_refs + raw_refs:
        ref_clean = (ref or "").rstrip(".")
        if not ref_clean:
            continue
        if ref_clean in heading_ids:
            continue
        if any(h.startswith(f"{ref_clean}.") for h in heading_ids):
            continue
        # If `N.M` is the ref and `N` is in the heading set, accept it
        # as a legitimate sub-section reference.
        top = ref_clean.split(".", 1)[0]
        if top in heading_ids:
            continue
        if ref_clean in dangling_seen:
            continue
        dangling_seen.add(ref_clean)
        dangling.append(ref_clean)

    # Per-chapter xref count. Split body on `## N` headings; count xrefs
    # within each chapter window (paren + non-paren-generic + ZH).
    #
    # Greptile PR #39 round-5: the chapter-split removes `## N Title`
    # lines as separators, but H3/H4 sub-headings (`### N.M`, `#### N.M.P`)
    # remain in the body. A sub-heading like `### 5.1 Section 99 Subtopic`
    # would contribute "99" via generic_pattern, inflating the chapter's
    # xref count. Mask all heading lines before scanning, same logic as
    # the article-level mask above.
    def _count_refs_in(body: str) -> int:
        masked_body = re.sub(
            r"(?m)^#{2,6}[^\n]*",
            lambda m: " " * len(m.group(0)),
            body,
        )
        body_paren = list(paren_pattern.finditer(masked_body))
        body_paren_spans = [(m.start(), m.end()) for m in body_paren]

        def _bp(pos: int) -> bool:
            return any(s <= pos < e for s, e in body_paren_spans)

        bare = sum(1 for m in generic_pattern.finditer(masked_body) if not _bp(m.start()))
        return len(body_paren) + bare + len(zh_pattern.findall(masked_body))

    chapter_split = re.split(r"(?m)^(#{2}\s+[^\n]+)", text)
    per_chapter: dict[str, int] = {}
    cur_id = "preamble"
    cur_body: list[str] = []
    for piece in chapter_split:
        if piece.startswith("## "):
            # Save previous, start new chapter
            if cur_body:
                per_chapter[cur_id] = _count_refs_in("".join(cur_body))
            m = re.match(r"##\s+([\d\.]+)?", piece)
            cur_id = m.group(1).rstrip(".") if m and m.group(1) else piece[:30].strip()
            cur_body = []
        else:
            cur_body.append(piece)
    if cur_body:
        per_chapter[cur_id] = _count_refs_in("".join(cur_body))
    # Drop the preamble entry — it's not a real chapter
    per_chapter.pop("preamble", None)

    n_total = len(all_refs)
    n_paren = len(paren_refs)
    paren_ratio = round(n_paren / n_total, 3) if n_total else 0.0
    forward_ratio = round(n_forward_defer / n_total, 3) if n_total else 0.0

    fail: list[str] = []
    chapters_below_floor = sum(1 for c in per_chapter.values() if c < 5)
    # Tolerate up to ~20% of chapters under the ≥5 floor (e.g. very
    # short chapters) but flag broader miss.
    #
    # Greptile PR #39 round-5: the prior `max(1, len(per_chapter) // 5)`
    # formula computed `max(1, 0) = 1` for a single-chapter article,
    # which meant `chapters_below_floor > 1` required ≥2 chapters to
    # miss the floor — impossible with only 1 chapter. So a 1-chapter
    # article with zero cross-references silently passed the audit.
    # The 20% tolerance is intended for multi-chapter docs (allowing
    # one or two short chapters to fall short); for a 1-chapter doc the
    # tolerance must collapse to 0 — that single chapter IS the whole
    # article and there's no peer chapter to dilute the miss against.
    if len(per_chapter) <= 1:
        # 0-chapter doc: chapters_below_floor is also 0 → never fires.
        # 1-chapter doc: any below-floor chapter fires the fail entry.
        tolerance = 0
    else:
        tolerance = max(1, len(per_chapter) // 5)
    if chapters_below_floor > tolerance:
        fail.append(f"chapters_below_5_xref_floor={chapters_below_floor}/{len(per_chapter)}")
    if n_opening_templates > 0:
        fail.append(f"opening_template_violations={n_opening_templates}")
    if dangling:
        fail.append(f"dangling_forward_refs={len(dangling)}")
    if n_total >= 10 and paren_ratio < 0.40:
        fail.append(f"parenthetical_ratio={paren_ratio:.2f}<0.40")
    if n_total >= 10 and forward_ratio > 0.30:
        fail.append(f"forward_defer_ratio={forward_ratio:.2f}>0.30")

    return {
        "ok": not fail,
        "n_chapters": len(per_chapter),
        "per_chapter_xref_counts": per_chapter,
        "opening_template_violations": n_opening_templates,
        "dangling_forward_refs": dangling,
        "n_parenthetical": n_paren,
        "n_total_xrefs": n_total,
        "parenthetical_ratio": paren_ratio,
        "forward_defer_ratio": forward_ratio,
        "fail": fail,
    }


def refiner_emphasis(archetype: str) -> str:
    return _ARCH_REFINE_EMPHASIS.get(archetype, "")
