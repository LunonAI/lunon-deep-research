"""validation node (p1-checklist item 35; LINK-Researcher pipeline node 9).

Runs after refiner, before adapter output. Structural gate that checks:
- All Architect-required sections present (verbatim section/subsection titles).
- All Insight minimums (writing_rules.check_insight_minimums).
- Total length within domain governor median (writing_rules.length_ceiling).
- Citation format compliant with the LOCKED cleaning-resistant rule
  (writing_rules.citation_strip_audit).
- Position-1 opening template applied (writing_rules.check_opening).
- No empty/stub sections (each ≥ 0.7 × expected_length_tokens per Scaffold).

Failure → structured feedback (list of {check, severity, detail}) routed back
to refiner for one corrective pass. Cap **2 corrective refiner passes** total;
on cap-exhaustion, log to `p1_artifacts/validation_failures.jsonl` and proceed
with the best draft (NEVER block the adapter — DRB needs an article per task).

Checks derived from `p0_artifacts/judge_preferences.md`, NOT LINK defaults.
"""

import json
import pathlib
import re
from dataclasses import dataclass

from .. import writing_rules as wr
from ..node_wrap import node
from ..state import DesignGuide, Scaffold
from ..text_metrics import approx_tokens, approx_words

_FAIL_LOG = pathlib.Path(__file__).resolve().parent.parent.parent / "p1_artifacts" / "validation_failures.jsonl"
_FAIL_LOG.parent.mkdir(parents=True, exist_ok=True)

# Greptile PR #42 round-8 issue #1: extracted as module-level constant so
# the value is visible + tuneable. Body extraction in
# `_validate_stakeholder_overlap` falls back to this cap when no
# subsequent heading is found (e.g., for the trailing stakeholder of a
# closing chapter at end-of-article). For long stakeholder blocks —
# routine in deep-research articles where individual blocks can run
# 6-12k chars — only the first N chars enter the Jaccard computation.
# Truncation in opposite directions across two sections can produce
# either inflated similarity (shared boilerplate within cap, divergence
# past it) or missed overlap (sections share content only in second
# halves). When the cap fires, the stakeholder's id is recorded in
# `truncated_bodies` so the audit trail is honest about which bodies
# were truncated (parallel to the `short_pairs` fallback signal).
_STAKEHOLDER_BODY_MAX_CHARS = 5000

# P3-W5.b (2026-05-27): max chars scanned in a limitations sub-section
# body when looking for a "specific anchor" (year / proper noun / R-N
# rubric id). Mirrors `_STAKEHOLDER_BODY_MAX_CHARS` for the case where
# a sub-section is the article-trailing block and has no subsequent
# heading. 3000 is intentionally smaller than the stakeholder cap
# because limitations sub-sections are bounded at 150-300 words by the
# directive — 3000 chars is ~6× the upper bound, generous slack for
# malformed-heading cases.
_LIMITATIONS_BODY_MAX_CHARS = 3000

# P3-W5.b (2026-05-27): regex that detects a "specific anchor" inside a
# limitations sub-section body. A sub-section passes the anti-generic
# bar when its body contains ≥1 of:
#   - 4-digit year in the 1900-2099 range.
#   - Acronym (3+ all-caps letters): "IBM", "NIST", "PQC", "CMA".
#     Greptile PR #45 round-6 issue #1 (2026-05-27): tightened from
#     `{2,}` to `{3,}` because 2-letter all-caps tokens like "AI",
#     "IT", "OR", "IS", "OF" appear ubiquitously in generic
#     research-prose phrasing ("AI capabilities are limited", "IT data
#     is unavailable") — pre-fix these silently passed the anti-generic
#     bar. "EU" is admitted as a specific 2-letter entity carve-out
#     since it is a legitimate organization reference frequently named
#     in scope/jurisdiction boundary discussion; other 2-letter entity
#     references would need an explicit carve-out (none observed in
#     the Qianfan corpus to date).
#   - Mid-sentence proper noun (capitalized 3+ letters preceded by a
#     lowercase letter + a literal space or tab — excludes sentence-
#     initial words like "The", "Per", "Beyond" which are common leaders,
#     not entity names. The lookbehind deliberately uses `[ \t]` rather
#     than `\s` so a newline (e.g., "limited data\nBeyond 2028") does NOT
#     count as the intra-sentence boundary; a newline is treated as a
#     line break that may begin a new sentence.
#   - Rubric identifier `R-\d+` (links to §1 framing-chapter items —
#     verbatim by Qianfan corpus pattern).
#   - Greptile PR #45 round-5 issue #2 (2026-05-27): CJK run of 4+
#     consecutive characters from any of the common CJK blocks (Unified,
#     Ext A, Ext B, Compat, Kangxi Radicals) — captures Chinese entity /
#     organization / location names like "宝武钢铁集团" (Baowu Steel),
#     "国家发改委" (NDRC), "粤港澳大湾区" (Greater Bay Area). Pre-fix the
#     regex had no CJK alternation, so every Chinese-only sub-section
#     body was systematically flagged generic regardless of how
#     concretely it named entities — misleading drift telemetry on the
#     predominantly-ZH Qianfan corpus. The 4+ length bar requires
#     specificity beyond common 2-3 char phrases ("数据", "需要", "可持续")
#     while admitting realistic entity names (entity-name medians in the
#     Qianfan corpus run 4-6 chars). Two char-classes are alternated
#     because Python regex does not combine BMP + supplementary ranges
#     in a single class — mirrors `_CJK_TEXT_RE` at line 100.
# The body is pre-stripped of citation markers (`[^...]`) and `§N.M` refs
# in `_validate_limitations_chapter` before this regex runs, so a body
# whose only "year" is `[^S5-2024]` or whose only "noun" is `§Section`
# correctly fails the anchor check.
_LIMITATIONS_SPECIFIC_ANCHOR_RE = re.compile(
    r"\b(?:19|20)\d{2}\b"  # 4-digit year
    r"|\bEU\b"  # EU (2-letter entity carve-out)
    r"|\b[A-Z]{3,}\b"  # acronym 3+ letters
    r"|(?<=[a-z][ \t])[A-Z][a-zA-Z]{2,}"  # mid-sentence proper noun
    r"|\bR-\d+\b"  # rubric id
    r"|[㐀-䶿一-鿿豈-﫿⼀-⿟]{4,}"  # CJK BMP entity / org / location run
    r"|[\U00020000-\U0002a6df]{4,}"  # CJK Ext B entity run
)

# Citation markers + § refs are pre-stripped so their internal digits
# (e.g., `[^S5-2024]`) don't false-positive the year sub-pattern, and
# so `§3.2` doesn't false-positive any of the alternations. The strip
# is conservative — anything inside a `[^...]` or any `§N(.N)*` is
# removed; the surrounding prose remains scannable for real anchors.
_LIMITATIONS_CITATION_STRIP_RE = re.compile(r"\[\^[^\]]*\]|§\d+(?:\.\d+)*")

# Greptile PR #42 round-8 issue #2: extended CJK character ranges. The
# prior `"一" <= c <= "鿿"` heuristic covered ONLY CJK Unified Ideographs
# (U+4E00-U+9FFF) and missed CJK Extension A (U+3400-U+4DBF), CJK
# Compatibility Ideographs (U+F900-U+FAFF), Kangxi Radicals
# (U+2F00-U+2FDF), and CJK Extension B (U+20000+). Additionally the
# prior scan window `text[:200]` would miss CJK detection when a heading
# opened with a non-CJK prefix (`"1. 投资者建议"`, `"§ 投资者"`), silently
# triggering word-tokenized n-grams on ZH bodies and yielding an empty
# overlap set. Centralized as a module-level regex so a future range
# adjustment touches a single source of truth.
_CJK_TEXT_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿⼀-⿟]|[\U00020000-\U0002a6df]")


def _is_cjk_text(text: str) -> bool:
    """True when `text` contains at least one character in any of the
    common CJK blocks (Unified, Ext A, Ext B, Compat, Kangxi Radicals).

    Used by `_validate_framing_chapter` and `_validate_stakeholder_overlap`
    to decide between CJK-character n-gram tokenization and EN word
    tokenization. Scans the entire string (not a 200-char prefix) so a
    heading like `"1. 投资者建议"` is correctly classified — the prior
    prefix-only scan silently produced false-negatives on numbered ZH
    headings.
    """
    if not text:
        return False
    return _CJK_TEXT_RE.search(text) is not None


@dataclass
class ValidationInput:
    article: str
    plan: dict
    scaffold: Scaffold
    design_guide: DesignGuide
    language: str
    domain: str
    task_id: str = ""
    # Greptile PR #76 (2026-05-29): the deliverable archetype drives the
    # opening verdict check in `check_opening`. Defaults to "" for back-compat
    # with any caller/test that doesn't thread it — "" is non-deliverable, so
    # the verdict element is treated as present and the check is unchanged.
    archetype: str = ""


@dataclass
class ValidationOutput:
    ok: bool
    failures: list  # list[{check, severity, detail}]
    feedback_text: str  # routed to refiner if not ok
    counts: dict


def _section_present(text: str, title: str) -> bool:
    """Verbatim title match (case-insensitive, normalized whitespace)."""
    if not title:
        return True

    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip().lower()

    return norm(title) in norm(text)


def _section_length_ok(text: str, title: str, expected_tok: int) -> tuple:
    """Locate the section body and check len >= 0.7 × expected_length_tokens.

    A section's body spans from its heading to the next heading of the SAME or
    SHALLOWER level, so a parent chapter rendered with nested sub-headings
    (a ``##`` with ``###``/``####`` children) counts its whole subtree — not
    just the intro before its first child. Measuring to the next heading of
    *any* level miscounted hierarchically-rendered parents as "short" and
    triggered wasteful corrective refiner passes on articles that were actually
    complete (validation runs before the final numbering_fix flatten, so it
    sees the nested H2/H3 shape).
    """
    if not title:
        return True, 0
    level = None
    m = re.search(rf"^(#+)\s*[\d\.\sA-Z]*\s*{re.escape(title)}\s*$", text, re.IGNORECASE | re.MULTILINE)
    if m:
        level = len(m.group(1))
    else:
        # title not on a heading line — fall back to a loose match; level unknown.
        m = re.search(re.escape(title), text, re.IGNORECASE)
        if not m:
            return False, 0
    rest = text[m.end() :]
    # Next heading at the same or shallower depth ends this section's body;
    # deeper children (more #s) stay inside it. Loose match → any heading.
    if level is not None:
        nxt = re.search(rf"\n#{{1,{level}}}\s", rest)
    else:
        nxt = re.search(r"\n#+\s", rest)
    body = rest[: nxt.start()] if nxt else rest
    # E2: use the shared CJK-aware estimator so this gate and orchestrate's
    # chapter-completion gate agree. For non-CJK bodies this equals the prior
    # len(body) // 4; ZH bodies are no longer under-counted ~2.5×.
    body_tok = approx_tokens(body)
    return body_tok >= int(0.7 * expected_tok), body_tok


@node("validation")
def run(inp: ValidationInput) -> ValidationOutput:
    failures = []
    counts = {"sections_total": len(inp.scaffold.sections)}

    # 1. all Architect-required sections present
    missing = []
    short = []
    for s in inp.scaffold.sections:
        if not _section_present(inp.article, s.title):
            missing.append(s.section_id + ":" + s.title)
            continue
        # Greptile PR #69 round-2: read through ScaffoldSection.effective_length_tokens
        # (the single-source-of-truth None/0→1200 fallback) so this length walk can
        # never crash at `int(0.7 * …)` on an unset target — matching orchestrate's
        # _expected_tok_for path.
        ok, body_tok = _section_length_ok(inp.article, s.title, s.effective_length_tokens)
        if not ok:
            short.append(
                {
                    "section": s.section_id,
                    "title": s.title,
                    "got_tok": body_tok,
                    "min_tok": int(0.7 * s.effective_length_tokens),
                }
            )
    counts["sections_missing"] = len(missing)
    counts["sections_short"] = len(short)
    if missing:
        failures.append({"check": "sections_present", "severity": "high", "detail": f"missing: {missing}"})
    if short:
        failures.append({"check": "section_min_length", "severity": "medium", "detail": short})

    # 2. Insight elements — DOWNGRADED to advisory (W9 diagnostic 2026-05-21):
    # We win Insight by +1.21 mean gap; forcing insertion of speculative
    # projections/caveats was inflating Readability losses (81% loss rate on
    # that dim). Track counts but don't hard-fail.
    ins = wr.check_insight_minimums(inp.article)
    counts["insight"] = ins["counts"]
    # No failure entry — Insight is advisory now.

    # 3. Total length within domain governor — TIGHTENED. The W9 judge cited
    # "excessive length" / "overlong" in 7 of 10 worst Readability losses.
    ceil_words = wr.length_ceiling(inp.domain, inp.language)
    words = len(inp.article.split())
    counts["words"] = words
    counts["domain_ceiling_words"] = ceil_words
    # TIGHTENED: 1.30× → 1.15× ceiling. The W9 judge penalized "excessive
    # length" in 7 of 10 worst Readability losses. Trigger corrective refiner
    # pass at 1.15× to actually rein in length, not just 1.30×.
    if words > int(ceil_words * 1.15):
        failures.append(
            {
                "check": "length_governor",
                "severity": "high",
                "detail": f"{words} words > {int(ceil_words * 1.15)} (1.15× ceiling — judge penalizes excessive length)",
            }
        )

    # 4. Citation format compliant (LOCKED cleaning-resistant rule)
    cit = wr.citation_strip_audit(inp.article)
    counts["citation"] = {"retention": cit["retention"], "has_inline_source_names": cit["has_inline_source_names"]}
    if not cit["ok"]:
        failures.append(
            {
                "check": "citation_format",
                "severity": "high",
                "detail": {"retention": cit["retention"], "inline_names": cit["has_inline_source_names"]},
            }
        )

    # 5. Position-1 opening template (writing_rules; per item 17). Pass the
    # archetype so the deliverable-archetype committed-verdict element (5) is
    # validated, not silently accepted (Greptile PR #76).
    opn = wr.check_opening(inp.article, inp.archetype)
    counts["opening"] = opn
    if not opn["within_300"]:
        failures.append({"check": "opening_template", "severity": "high", "detail": {"missing": opn["missing"]}})

    # 6. NUMBERING CONSISTENCY — telemetry only. Numbering is handled
    # deterministically by `pipeline/numbering_fix.renumber_headings`, which
    # runs at the end of `orchestrate.from_plan`. Triggering a corrective
    # refiner pass here was paying an LLM call for an issue that the post-
    # edit step would have resolved for free. Counts kept for drift logging.
    headings = re.findall(r"^(#{2,4})\s*([0-9.]+)?\s", inp.article, re.MULTILINE)
    nums = [n for _, n in headings if n]
    counts["headings_with_numbers"] = len(nums)
    counts["unique_numbers"] = len(set(nums))
    # No failure appended — numbering_fix is the single source of truth.

    # 7. CROSS-SECTION REDUNDANCY (W9 diagnostic — 40%+ Readability losses
    # cited "repeats concepts across sections"). Crude detection: count
    # repeated 5-grams across section bodies.
    sec_bodies = re.split(r"\n#{2,3}\s", inp.article)[1:]
    if len(sec_bodies) >= 3:
        five_grams_per_section = []
        for body in sec_bodies:
            words = body.split()
            grams = set(" ".join(words[i : i + 5]).lower() for i in range(len(words) - 4))
            five_grams_per_section.append(grams)
        # Count 5-grams that appear in >=3 sections
        from collections import Counter

        all_grams = Counter()
        for g in five_grams_per_section:
            for ng in g:
                all_grams[ng] += 1
        cross_repeats = sum(1 for ng, c in all_grams.items() if c >= 3)
        counts["cross_section_5gram_repeats"] = cross_repeats
        if cross_repeats > 25:  # heuristic threshold
            failures.append(
                {
                    "check": "cross_section_redundancy",
                    "severity": "medium",
                    "detail": f"{cross_repeats} 5-grams appear in 3+ sections (judge penalizes 'repeats concepts across sections')",
                }
            )

    # 8. P3b-opt2 (2026-05-28): PROSE-FORM readability telemetry (advisory,
    # like INSIGHT), replacing the retired micro-template compliance check.
    # The prose form (#53) targets dense paragraphs (EN corpus median ~81
    # words) and flat structure (corpus h4=0); we log those so the re-grade
    # has quantitative readability signal. No hard-fail (the writer directive
    # + deterministic flatten/clamp do the work; this is observation only).
    pf = _validate_prose_form(inp.article)
    counts["prose_form_para_median_words"] = pf["para_median_words"]
    counts["prose_form_choppy_frac"] = pf["choppy_frac"]
    counts["prose_form_h3_count"] = pf["h3_count"]
    counts["prose_form_h4_count"] = pf["h4_count"]
    # P3b-D1: labeled-reasoning adoption telemetry (advisory) so the re-grade
    # can attribute Insight movement to whether the directives landed.
    pr = _validate_prose_reasoning(inp.article)
    counts["prose_reasoning_synthesis_per_chapter"] = pr["synthesis_per_chapter"]
    counts["prose_reasoning_synthesis_headings"] = pr["synthesis_headings"]
    counts["prose_reasoning_article_synthesis"] = pr["article_synthesis"]
    counts["prose_reasoning_h2_chapters"] = pr["h2_chapters"]
    counts["prose_reasoning_tension_paras"] = pr["tension_paras"]
    counts["prose_reasoning_tension_resolved"] = pr["tension_resolved"]
    counts["prose_reasoning_tension_resolution_rate"] = pr["tension_resolution_rate"]

    # 9. P3-W2 (2026-05-27): framing-chapter downstream-reuse — telemetry
    # only. Measures whether §2+ chapters re-engage with §1's published
    # vocabulary + rubric items (Qianfan corpus-wide pattern of
    # analytical continuity). No fail/pass — surfaced in counts for drift
    # logging; the corrective-feedback loop is via the post-write
    # compliance scorer, not the validation gate. Returns None (skipped)
    # when the plan has no framing_chapter or it is empty.
    fc_reuse = _validate_framing_chapter(inp.article, inp.plan.get("framing_chapter"))
    if fc_reuse is not None:
        counts["framing_chapter_reuse"] = fc_reuse

    # 9b. TIER RANKING STRUCTURE + PRECISION (P3-W7.b). When the architect
    # populated `plan["tier_ranking"]` (compare / predict archetypes with
    # ≥5 entities and ≥4 dimensions), the chapter MUST carry a markdown
    # scoring table with 2-decimal cells AND a sensitivity sub-section.
    # Cross-PR consistency: weights keys should mirror framing_chapter
    # rubric ids — divergence is flagged in `rubric_mismatch_keys`.
    # Returns None when no chapter is in the plan; advisory severity.
    tr_audit = _validate_tier_ranking(inp.article, inp.plan)
    if tr_audit is not None:
        counts["tier_ranking"] = tr_audit
        # G3 (2026-05-28): promote an UNCOMMITTED ranking to a HARD failure so
        # the regen loop fixes it (the predict core payload). Both conditions are
        # guarded by `entities_scored_present` so they fire ONLY when the architect
        # actually computed scores — qualitative compare tiers and the fail-soft
        # no-scores path never loop the regenerator. (a) requires a committed
        # 2-decimal matrix; (b) fails a rendered-but-hedged ranking.
        #
        # Greptile PR #64 issue #1 (2026-05-28): (b) previously carried NO
        # entities_scored_present guard, so any article whose tier-ranking chapter
        # contained >2 deferral/placeholder tokens — including qualitative compare
        # articles that discuss uncertainty inline — would hard-fail and loop the
        # regenerator. Guarding (b) symmetrically with (a) matches the PR's stated
        # loop-protection intent: the deferral gate is only meaningful when there
        # ARE computed scores that the writer is hedging away from committing.
        if tr_audit["entities_scored_present"] and (
            not tr_audit["scoring_table_present"] or tr_audit["two_decimal_cells"] == 0
        ):
            failures.append(
                {
                    "check": "tier_ranking_uncommitted",
                    "severity": "high",
                    "detail": (
                        "tier_ranking has computed scores (entities_scored populated) but the "
                        f"chapter renders no committed numeric matrix (table_present="
                        f"{tr_audit['scoring_table_present']}, two_decimal_cells="
                        f"{tr_audit['two_decimal_cells']}). Render the per-entity S_final scores "
                        "as a 2-decimal markdown table — do not defer to other sections."
                    ),
                }
            )
        if tr_audit["entities_scored_present"] and tr_audit["deferral_hits"] > _TIER_RANKING_DEFERRAL_MAX:
            failures.append(
                {
                    "check": "tier_ranking_deferred",
                    "severity": "high",
                    "detail": (
                        f"tier_ranking chapter contains {tr_audit['deferral_hits']} deferral/"
                        "placeholder tokens (待…核实 / 未核实 / 证据缺口 / 占位); commit the "
                        "ranking with concrete scores instead of deferring it."
                    ),
                }
            )

    # 9. STAKEHOLDER CHAPTER OVERLAP (P3-W6; Greptile PR #42 round-2 wiring).
    # When the architect populated `plan["stakeholder_chapter"]` because the
    # prompt signaled plural audience, each stakeholder sub-section must
    # carry NON-OVERLAPPING content. Pairwise Jaccard on n-grams; pairs
    # above `wr._STAKEHOLDER_JACCARD_MAX` fail. Returns None when no
    # chapter is present (single-audience prompts), so the check is
    # silent in that case.
    sc_audit = _validate_stakeholder_overlap(inp.article, inp.plan.get("stakeholder_chapter"))
    if sc_audit is not None:
        counts["stakeholder_chapter"] = sc_audit
        if sc_audit["overlap_pairs"]:
            failures.append(
                {
                    "check": "stakeholder_overlap",
                    "severity": "medium",
                    "detail": (
                        f"{len(sc_audit['overlap_pairs'])} stakeholder pair(s) above "
                        f"{wr._STAKEHOLDER_JACCARD_MAX:.2f} Jaccard "
                        f"(max={sc_audit['max_pair_overlap']}); each block must address "
                        f"its audience with disjoint advice: {sc_audit['overlap_pairs']}"
                    ),
                }
            )

    # 10. LIMITATIONS CHAPTER STRUCTURE (P3-W5.b). When the architect
    # populated `plan["limitations_chapter"]` for predict / compare /
    # explain-mechanism / list-all archetypes, the chapter MUST carry 5
    # sub-sections (data_granularity / scope_cap / time_validity /
    # sampling / falsifiers) each with a concrete anchor (year, proper
    # noun, or rubric id) — Qianfan-grade falsification, not boilerplate.
    # Returns None when no chapter is present (e.g., trend archetype),
    # so the check is silent in that case. Advisory severity — surfaces
    # in counts for drift telemetry but does NOT trigger refiner pass;
    # the corrective signal is the (deferred) compliance scorer.
    lim_audit = _validate_limitations_chapter(inp.article, inp.plan.get("limitations_chapter"))
    if lim_audit is not None:
        counts["limitations_chapter"] = lim_audit

    # 11. MICRO-TEMPLATE LABEL CONSISTENCY (G5). When entity_matrix is in
    # prose_subheaders mode, each axis must open its per-entity paragraph with
    # ONE byte-identical bold label across all entities (q91 form). Severe
    # fragmentation (canonical label covers <50% of entities) → medium failure
    # so the regen loop re-pins the labels. Returns None for table_columns_only
    # mode or <3 entities, so the check is silent there.
    mt_audit = _validate_micro_template(inp.article, inp.plan.get("entity_matrix"))
    if mt_audit is not None:
        counts["micro_template"] = mt_audit
        if mt_audit["min_axis_coverage"] < _MICRO_TEMPLATE_MIN_COVERAGE:
            failures.append(
                {
                    "check": "micro_template_fragmented",
                    "severity": "medium",
                    "detail": (
                        f"per-entity axis labels fragmented (min canonical coverage "
                        f"{mt_audit['min_axis_coverage']:.2f} over {mt_audit['n_entities']} "
                        f"entities; target ≥{_MICRO_TEMPLATE_MIN_COVERAGE:.2f}). Open each "
                        f"entity's per-axis paragraph with the EXACT bold axis label, "
                        f"byte-identical across entities: {json.dumps(mt_audit['axis_coverage'], ensure_ascii=False)}"
                    ),
                }
            )

    # 11b. ENTITY COVERAGE (L3). Every declared entity must get its own body
    # expansion, not just a §1 matrix row. A SEVERE collapse → medium failure so
    # the regen expands the omitted entities (the Qianfan head-to-head's biggest
    # Comprehensiveness gap: id8 expanded 1 of 12 systems). Silent for
    # table_columns_only / <3 entities.
    ec_audit = _validate_entity_coverage(inp.article, inp.plan.get("entity_matrix"))
    if ec_audit is not None:
        counts["entity_coverage"] = ec_audit
        if ec_audit["coverage"] < _ENTITY_COVERAGE_MIN_RATIO:
            failures.append(
                {
                    "check": "entity_coverage_collapsed",
                    "severity": "medium",
                    "detail": (
                        f"only {ec_audit['n_expanded']}/{ec_audit['n_entities']} declared "
                        f"entities got their own body expansion (coverage {ec_audit['coverage']:.2f}, "
                        f"target ≥{_ENTITY_COVERAGE_MIN_RATIO:.2f}). A §1 matrix row is NOT a "
                        f"substitute — give EACH entity its own subsection with the full "
                        f"per-entity treatment. Missing: {json.dumps(ec_audit['missing'], ensure_ascii=False)}"
                    ),
                }
            )

    # 12. NUMERIC-SPINE CONSISTENCY (round 8, id-44). When the architect planned
    # a quantitative deliverable (`plan["numeric_spine"]`), fire a HARD failure if
    # ≥2 figures EACH self-declare THE headline total (主脊/头条) yet disagree by
    # >3× or across count-units — the dev6 id-44 "体系崩塌". The detail string IS
    # the corrective instruction the refiner receives; it leads with the action
    # because feedback_text truncates each detail to 600 chars. Returns None
    # (silent) for qualitative plans or non-CJK articles.
    ns_audit = _validate_numeric_spine_consistency(inp.article, inp.plan.get("numeric_spine"))
    if ns_audit is not None:
        counts["numeric_spine_consistency"] = ns_audit
        if ns_audit["conflict"]:
            failures.append(
                {
                    "check": "numeric_spine_conflict",
                    "severity": "high",
                    "detail": (
                        "Pick the owner chapter's ONE triangulated headline figure, restate that "
                        "EXACT value+unit VERBATIM in the abstract and EVERY chapter, and DEMOTE all "
                        "other totals to explicitly scope-tagged sub-figures (e.g. 在弓存量/纯消耗口径/"
                        "全口径轨交) so no two figures both claim to be the report's single headline "
                        f"answer. Conflict: {ns_audit['n_headline_figures']} figures self-declared as THE "
                        f"headline (主脊/头条) disagree by {ns_audit['spread_ratio']:.0f}x"
                        + (f" and mix units {ns_audit['units']}" if len(ns_audit["units"]) > 1 else "")
                        + f": {ns_audit['headline_values']}."
                    ),
                }
            )

    ok = not failures

    # Build structured feedback for the refiner (NOT free-text)
    if ok:
        fb = ""
    else:
        lines = []
        for f in failures:
            lines.append(
                f"- [{f['severity'].upper()}] {f['check']}: {json.dumps(f['detail'], ensure_ascii=False)[:600]}"
            )
        fb = "VALIDATION FAILURES — fix these in place; preserve correct content; do not shorten:\n" + "\n".join(lines)

    return ValidationOutput(ok=ok, failures=failures, feedback_text=fb, counts=counts)


def _validate_prose_form(article: str) -> dict:
    """P3b-opt2 (2026-05-28): advisory prose-form readability telemetry.
    This measures only the Qianfan-verified prose-form readability targets:
      - paragraph density (EN corpus median ~81 words; "choppy" = < 80 words)
      - heading flatness (Qianfan corpus h4_total = 0)

    Axis-label consistency is NOT measured here. G5 (this PR) restored the
    byte-identical pinned bold axis labels (`**axis:**` per entity), and that
    coverage is audited separately by `_validate_micro_template`; this function
    deliberately stays label-agnostic so it stands on every archetype, prose or
    micro-template.

    Runs on every article; advisory only (no hard-fail). NOTE: validation
    runs BEFORE the numbering_fix flatten, so h3/h4 reflect the writer's RAW
    nesting (how much the deterministic flatten will then clean up).
    """
    # Paragraph split mirrors scripts/qianfan_style_profile.py (blank-line
    # blocks, excluding heading blocks) so the median maps to the measured
    # corpus target.
    paras = [p for p in re.split(r"\n\s*\n", article) if p.strip() and not p.strip().startswith("#")]

    # F2: shared CJK-aware word count (was a byte-identical copy here and in
    # style_clamp._words; both now call text_metrics.approx_words).
    lens = sorted(approx_words(p) for p in paras)
    if lens:
        mid = len(lens) // 2
        median_words = lens[mid] if len(lens) % 2 else (lens[mid - 1] + lens[mid]) // 2
    else:
        median_words = 0
    choppy = sum(1 for w in lens if w < 80)
    return {
        "para_count": len(paras),
        "para_median_words": median_words,
        "choppy_paras": choppy,
        "choppy_frac": round(choppy / max(len(paras), 1), 3),
        "h3_count": len(re.findall(r"^###\s", article, re.MULTILINE)),
        "h4_count": len(re.findall(r"^####\s", article, re.MULTILINE)),
    }


# P3b-D1 (2026-05-28): adoption telemetry for the labeled-reasoning directives
# (end-of-chapter synthesis subsection + tension→resolution). Advisory only —
# its purpose is to let the re-grade ATTRIBUTE any Insight movement to whether
# the directives actually landed (the LLM-compliance risk), NOT to hard-fail.
_SYNTHESIS_HEADING_RE = re.compile(r"(?im)^#{2,4}[ \t].*(?:synthesis|综合)")
# A `##`-level synthesis heading is an ARTICLE-level synthesis chapter (the
# flat-report archetype's directive: one top-level synthesis over N entity
# chapters), distinct from a per-chapter `###`/`####` synthesis subsection.
_ARTICLE_SYNTHESIS_RE = re.compile(r"(?im)^##[ \t].*(?:synthesis|综合)")
_TENSION_RE = re.compile(r"(?i)\b(tension|paradox|trade-?off|at odds|in conflict)\b|悖论|矛盾")
_RESOLUTION_RE = re.compile(r"(?i)\b(resolv\w+|reconcil\w+|where one might expect|the resolution)\b|从而化解")


def _validate_prose_reasoning(article: str) -> dict:
    """Coarse advisory signal of labeled-reasoning adoption (P3b-D1):
    per-chapter synthesis-subsection density and tension→resolution
    co-occurrence. No hard-fail; pre-flatten chapters are `##`.

    `synthesis_per_chapter` counts only per-chapter (`###`/`####`) synthesis
    subsections over CONTENT chapters, excluding any article-level (`##`)
    synthesis chapter from BOTH numerator and denominator. Otherwise a
    compliant flat-report archetype (one top-level `## Synthesis` over N
    entity chapters) would read as ~1/(N+1) and be indistinguishable from
    non-adoption. The article-level case is surfaced separately as
    `article_synthesis` so the re-grade can tell the archetypes apart."""
    n_synth = len(_SYNTHESIS_HEADING_RE.findall(article))
    n_article_synth = len(_ARTICLE_SYNTHESIS_RE.findall(article))
    n_subsection_synth = n_synth - n_article_synth
    n_h2 = len(re.findall(r"^##[ \t]", article, re.MULTILINE))
    content_chapters = n_h2 - n_article_synth
    paras = [p for p in re.split(r"\n\s*\n", article) if p.strip() and not p.strip().startswith("#")]
    tension = 0
    resolved = 0
    for p in paras:
        if _TENSION_RE.search(p):
            tension += 1
            if _RESOLUTION_RE.search(p):
                resolved += 1
    return {
        "synthesis_headings": n_synth,
        "article_synthesis": n_article_synth,
        "h2_chapters": n_h2,
        "synthesis_per_chapter": round(n_subsection_synth / max(content_chapters, 1), 3),
        "tension_paras": tension,
        "tension_resolved": resolved,
        "tension_resolution_rate": round(resolved / max(tension, 1), 3),
    }


def _validate_framing_chapter(article: str, framing_chapter) -> dict | None:
    """P3-W2 (2026-05-27): compute framing-chapter downstream-reuse compliance.

    Returns None when no framing_chapter is active (skip the check).
    Otherwise returns:
      {
        "vocabulary_terms_reused": {term: count_in_body},
        "vocabulary_reuse_rate": float (fraction of terms with >=1 body reuse),
        "rubric_items_referenced": {id: count_in_body},
        "rubric_reference_rate": float (fraction of items referenced),
      }

    "Body" = article after the first `max(8000, 0.09 * len)` chars
    (the Qianfan-verified 5-9% upper bound on §1 length, floored at 8k
    to maintain margin on short/mid-length articles). Reuse measures
    whether DOWNSTREAM chapters re-engage with §1 vocabulary + rubric
    items — the Qianfan-verified corpus-wide pattern of analytical
    continuity.
    """
    if not isinstance(framing_chapter, dict):
        return None
    vocab = [str(t) for t in (framing_chapter.get("published_vocabulary") or []) if t]
    rubric = [r for r in (framing_chapter.get("published_rubric_items") or []) if isinstance(r, dict) and r.get("id")]
    if not vocab and not rubric:
        return None
    # Skip §1 region — heuristic upper bound on the framing chapter's
    # extent. Qianfan §1 is 5-9% of article length, so the proportional
    # skip is `0.09 * len(article)`. Floor at 8000 chars to maintain
    # margin on short/mid-length articles where 9% would otherwise leave
    # too little buffer past §1's actual close (e.g. on a 50k article,
    # 9% is 4.5k while §1 routinely runs 3-4.5k). Clamp to len(article)
    # so a stub article slices to an empty body rather than past-the-end.
    # Greptile PR #38 round-1: the prior `min(8000, len//7)` capped long
    # articles at 8k (under-skipping when §1 grows to 45k on a 500k-char
    # article) AND under-skipped short articles by falling to the //7
    # branch — both directions of the bound were inverted.
    skip_chars = min(len(article), max(8000, int(0.09 * len(article))))
    body = article[skip_chars:]
    vocab_counts: dict[str, int] = {}
    for term in vocab:
        if _is_cjk_text(term):
            # CJK: case is meaningless; count verbatim. Greptile PR #42
            # round-8: routed through `_is_cjk_text` so the same extended
            # CJK ranges (Ext A/B, Compat, Kangxi) apply here as in the
            # stakeholder-overlap audit's n-gram tokenizer.
            vocab_counts[term] = body.count(term)
        else:
            # EN: case-insensitive (writers may de-capitalize mid-sentence).
            vocab_counts[term] = body.lower().count(term.lower())
    rubric_counts: dict[str, int] = {}
    for item in rubric:
        rid = str(item["id"])
        rubric_counts[rid] = body.count(rid)
    vocab_reused = sum(1 for v in vocab_counts.values() if v >= 1)
    rubric_referenced = sum(1 for v in rubric_counts.values() if v >= 1)
    return {
        "vocabulary_terms_reused": vocab_counts,
        "vocabulary_reuse_rate": round(vocab_reused / len(vocab), 3) if vocab else 0.0,
        "rubric_items_referenced": rubric_counts,
        "rubric_reference_rate": round(rubric_referenced / len(rubric), 3) if rubric else 0.0,
    }


def _validate_stakeholder_overlap(article: str, stakeholder_chapter) -> dict | None:
    """P3-W6 (2026-05-27): pairwise content-overlap audit on stakeholder chapter.

    Returns None when no stakeholder_chapter is active. Otherwise:
      {
        "n_stakeholders_declared": int,
        "n_stakeholders_audited": int,
        "max_pair_overlap": float,
        "overlap_pairs": [(stakeholder_id_a, stakeholder_id_b, jaccard)],
        "short_pairs": [(stakeholder_id_a, stakeholder_id_b, n_used)],
        "missing_labels": [stakeholder_id, ...],
      }

    For each pair of stakeholder sub-sections, compute Jaccard similarity
    on 4-gram tokens (word 4-grams for EN; char 4-grams for ZH). Pairs
    with similarity > `wr._STAKEHOLDER_JACCARD_MAX` (currently 0.20)
    are flagged in `overlap_pairs`. Qianfan's stakeholder sub-sections
    in q23/q3/q14 are nearly content-disjoint.

    Greptile PR #42 round-2: short bodies (EN <4 words or ZH <4 chars)
    previously produced empty 4-gram sets and were silently skipped,
    creating false-negatives. Now the function falls back to 3-grams
    then 2-grams when 4-grams are empty for either side of the pair —
    the `n_used` value in `short_pairs` records when fallback fired so
    short stakeholder bodies remain observable in the audit output.

    Greptile PR #42 round-3 — body extraction now anchors to a markdown
    heading line containing the label (`r"#{2,4}\\s+...label..."`) instead
    of `str.find(label)`. The old approach matched the first occurrence
    of the label string ANYWHERE in the article, so a cross-reference
    like "...see the For Investors section below..." would land before
    the actual heading and the extracted body would span the wrong
    section — silent false-negatives on the overlap audit. The heading-
    anchored regex matches only at line-start `#{2,4} ... label`, which
    is the canonical section heading form.

    Greptile PR #42 round-3 — `n_stakeholders` previously counted every
    DECLARED stakeholder (including those whose label was not found in
    the article and so contributed an empty body). A reader of the audit
    output seeing `n_stakeholders=5` would assume all five were compared,
    but if 2 labels weren't present only 3 non-empty bodies entered the
    pairwise comparison. Now the audit reports both
    `n_stakeholders_declared` (total entries in the plan) and
    `n_stakeholders_audited` (non-empty bodies that actually entered
    the comparison) and lists `missing_labels` for visibility.
    """
    if not isinstance(stakeholder_chapter, dict):
        return None
    stakeholders = stakeholder_chapter.get("stakeholders") or []
    if len(stakeholders) < 2:
        return None
    bodies: dict[str, str] = {}
    missing_labels: list[str] = []
    # Greptile PR #42 round-8 issue #1: sids whose body extraction hit
    # the `_STAKEHOLDER_BODY_MAX_CHARS` cap (no subsequent heading found
    # within N chars). Recorded as a diagnostic so downstream readers can
    # correlate audit results with truncation risk.
    truncated_bodies: list[str] = []
    n_declared = 0
    for s in stakeholders:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id", "")).strip()
        label = str(s.get("label", "")).strip()
        if not sid or not label:
            continue
        n_declared += 1
        # Greptile PR #42 round-3: anchor to a markdown heading line
        # (`## label`, `### label`, `#### label`) instead of any
        # occurrence of the label string. Headings may carry leading
        # numbering (`### 8.3 For Investors`) so we allow optional
        # `\d+(?:\.\d+)*\s+` between the hashes and the label.
        #
        # Greptile PR #42 round-4: case-insensitive. The writer LLM may
        # de-capitalize headings (e.g. plan label `"For Investors"` →
        # rendered `### for investors`), and the canonical English-only
        # `re.IGNORECASE` flag matches the same casing tolerance already
        # used by `_validate_framing_chapter` for vocabulary lookup
        # (`body.lower().count(term.lower())`). Without this, a single
        # casing drift dropped the stakeholder into `missing_labels` and
        # silently excluded it from the pairwise audit.
        #
        # Greptile PR #42 round-7: anchor the label end. Pre-fix the
        # pattern had no terminator, so a plan label `"For Industry"`
        # silently matched a heading `### For Industry Practitioners` —
        # the extracted body belonged to the wrong section, but the
        # stakeholder was NOT added to `missing_labels` and
        # `n_stakeholders_audited` counted it as found (audit looks
        # complete while comparing the wrong content). Naive `(?!\w)`
        # would NOT fix this because after "Industry" comes a SPACE
        # (non-word) — the lookahead would pass and still match the
        # longer heading. The correct anchor requires the label to be
        # followed by optional whitespace then either end-of-line OR a
        # terminator punctuation (`:`, `-`, `—`, `–`) that ends the
        # heading label cleanly. This rejects `### For Industry
        # Practitioners` while still accepting `### For Investors`,
        # `### For Investors: Capital Allocation`, `### For Investors
        # — Capital Allocation`, etc.
        m = re.search(
            r"(?m)^#{2,4}\s+(?:\d+(?:\.\d+)*\s+)?" + re.escape(label) + r"(?=\s*(?:$|[:\-—–]))",
            article,
            re.IGNORECASE,
        )
        if m is None:
            bodies[sid] = ""
            missing_labels.append(sid)
            continue
        # `m.end()` is just past the label; advance to the next line
        # start so the body begins with section content, not the
        # remainder of the heading line.
        nl = article.find("\n", m.end())
        start = nl + 1 if nl >= 0 else m.end()
        # Greptile PR #42 round-5 fix: broadened `#{2,4}` → `#{1,4}` so
        # level-1 chapter breaks (`# Appendix`, `# References`) are
        # recognized as section boundaries. Pre-fix, a stakeholder block
        # immediately followed by `# Appendix` would not see that boundary
        # and the body would run to the 5000-char cap, pulling in
        # unrelated content and inflating/deflating the Jaccard score.
        # `#{1,4}` still excludes `#####` deep headers which the Qianfan
        # corpus doesn't use.
        next_heading = re.search(r"\n#{1,4}\s+", article[start:])
        # Greptile PR #42 round-8 issue #1: use the module-level
        # `_STAKEHOLDER_BODY_MAX_CHARS` constant + record truncation in
        # `truncated_bodies` so the audit trail surfaces when the cap
        # was binding. For long stakeholder blocks the cap can hide
        # second-half divergence or convergence; this signal lets a
        # downstream reader correlate audit results with truncation.
        if next_heading is not None:
            end = start + next_heading.start()
        else:
            end = start + _STAKEHOLDER_BODY_MAX_CHARS
            if end < len(article):
                truncated_bodies.append(sid)
        bodies[sid] = article[start : min(end, len(article))]

    def _ngrams(text: str, n: int) -> set:
        text = text.strip()
        if not text or n < 1:
            return set()
        # Greptile PR #42 round-8 issue #2: route through `_is_cjk_text`
        # which scans the FULL text (not a 200-char prefix) and covers
        # CJK Ext A / Ext B / Compat / Kangxi Radicals in addition to
        # Unified Ideographs. Pre-fix a heading body opening with
        # `"1. 投资者..."` (numeric prefix) would fall through to the
        # EN word path because the first 200 chars contained no CJK
        # match — yielding an empty EN word set on a ZH body and a
        # silent skip in the pairwise comparison.
        if _is_cjk_text(text):
            if len(text) < n:
                return set()
            return {text[i : i + n] for i in range(len(text) - n + 1)}
        words = [w.lower() for w in re.findall(r"[a-zA-Z0-9]+", text)]
        if len(words) < n:
            return set()
        return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}

    overlap_pairs: list[tuple] = []
    short_pairs: list[tuple] = []
    max_overlap = 0.0
    # Greptile PR #42 round-3: only audit bodies that were actually
    # found in the article. Empty bodies (missing labels) are EXCLUDED
    # from the pairwise comparison set so n_stakeholders_audited
    # honestly reports the number that entered the comparison.
    auditable_ids = [sid for sid, body in bodies.items() if body]
    for i, a in enumerate(auditable_ids):
        for b in auditable_ids[i + 1 :]:
            # Progressive n-gram fallback: try 4-grams first (the canonical
            # threshold-calibrated bound), then 3-grams, then 2-grams. The
            # first n where BOTH bodies produce a non-empty set wins; if
            # all three are empty for either side, skip with no false
            # signal. Smaller n inflates accidental overlap, so we track
            # the n used in `short_pairs` for diagnostic visibility.
            sa: set = set()
            sb: set = set()
            n_used = 0
            for n in (4, 3, 2):
                sa = _ngrams(bodies[a], n)
                sb = _ngrams(bodies[b], n)
                if sa and sb:
                    n_used = n
                    break
            if not sa or not sb:
                continue
            inter = len(sa & sb)
            union = len(sa | sb)
            jaccard = inter / union if union else 0.0
            max_overlap = max(max_overlap, jaccard)
            # Greptile PR #46 round-1 issue #1 (2026-05-27): the
            # threshold MUST be sourced from
            # `wr._STAKEHOLDER_JACCARD_MAX` (the same constant the
            # writer system-prompt directive references) so a future
            # tightening (e.g., to 0.15) flows automatically into both
            # the validator literal AND the prompt-displayed value.
            # Pre-fix the threshold was duplicated as a `0.20` literal
            # here AND embedded as `_STAKEHOLDER_JACCARD_MAX = 0.20`
            # in writing_rules with no import link — silent drift risk.
            if jaccard > wr._STAKEHOLDER_JACCARD_MAX:
                overlap_pairs.append((a, b, round(jaccard, 3)))
            if n_used < 4:
                short_pairs.append((a, b, n_used))

    return {
        "n_stakeholders_declared": n_declared,
        "n_stakeholders_audited": len(auditable_ids),
        "max_pair_overlap": round(max_overlap, 3),
        "overlap_pairs": overlap_pairs,
        "short_pairs": short_pairs,
        "missing_labels": missing_labels,
        "truncated_bodies": truncated_bodies,
    }


# P3-W7.b (2026-05-27): regexes for tier_ranking validator.
#
# `_TIER_RANKING_2DEC_RE` matches a 2-decimal score literal in the body,
# scoped by `\b` boundaries so `7.45` matches but `7.452` (3 decimals)
# and `1.234` and `7` and `7.5` do not.
#
# `_TIER_RANKING_3PLUS_DEC_RE` matches the disallowed 3+-decimal form,
# used to reject articles that emit `7.452` style precision instead of
# the Qianfan corpus's 2-decimal convention.
#
# Both regexes are pre-stripped of footnote markers + `§N.M` refs so
# their internal digits don't cause false positives (mirrors the
# limitations validator's pre-strip pattern from P3-W5.b).
_TIER_RANKING_2DEC_RE = re.compile(r"(?<!\d)\b\d+\.\d{2}\b(?!\d)")
_TIER_RANKING_3PLUS_DEC_RE = re.compile(r"(?<!\d)\b\d+\.\d{3,}\b(?!\d)")

# Sensitivity sub-section heading detection. The W7.b directive teaches
# the writer to use 'sensitivity' / '敏感性' / '±Npp' / '±N个百分点' as
# heading-anchor tokens; the regex covers all 4 forms so EN / ZH /
# symbolic-shorthand variants of the heading are all detected.
#
# Greptile pre-scan: `\b` word-boundary doesn't behave the same for CJK
# characters. `\b敏感性\b` would FAIL on `敏感性分析` because `敏感性`
# and `分析` are both word-character runs (no boundary between them in
# Python regex). We therefore drop the `\b` and rely on substring
# match within the heading line — false positives ("Insensitivity of X"
# at heading level) are vanishingly rare in DRB-genre prose.
#
# Greptile PR #47 round-3: a 5th alternation `stress\s+test` was here
# but undocumented in the comment, writer.py directive, and
# `_TIER_RANKING_RULE`. Silent contract drift: a chapter with a
# `### Stress Test Analysis` heading but no actual ±pp re-ranking
# section would have `sensitivity_subsection_present=True` logged
# even though the required computational content is absent. Also
# conflicts terminology with P3-W5 `limitations_chapter.scenario_
# stress_test` (a different architectural concept). Removed —
# validator now matches the documented contract.
_TIER_RANKING_SENSITIVITY_HEADING_RE = re.compile(
    r"(?im)^#{2,4}\s+(?:\d+(?:\.\d+)*\s+)?.*(?:sensitivity|敏感性|±\s*\d+\s*(?:pp|个百分点|percentage\s+points))",
)

# Citation marker + § ref strip — re-used from limitations validator
# pattern. Suppresses footnote-internal digits and chapter-ref digits
# so `[^S7-2.45]` and `§7.45` don't false-positive the 2-decimal regex.
_TIER_RANKING_NOISE_STRIP_RE = re.compile(r"\[\^[^\]]*\]|§\d+(?:\.\d+)*")

# G3 (2026-05-28): deferral / placeholder tokens that signal an UNCOMMITTED
# ranking. q14 §7.6 commits 30 teams with numeric S_final and ZERO deferral
# vocab; dev4 id=14 rendered its multi-team tables with every score cell tagged
# 待§2核实 / 未核实 / 占位 / 证据缺口 — a table-shaped chapter with no actual
# predictions. These tokens are ~0 in the fresh #1 corpus and in Lunon's
# non-predict dev4 articles (id8=1, id37=1, id91=0), so a low in-chapter ceiling
# is regression-safe. `待…(核实|完成|验证|补充)` covers `待核实`, `待§2核实`, and
# `待§2–§7完成`; the rest are literal placeholder markers.
#
# Greptile PR #64 issue #3 (2026-05-28): the trailing `占位` alternation carries a
# negative lookahead `(?![置费])` so the placeholder sense (`占位`, `占位符`,
# `占位说明`) is still counted while the unrelated compounds `占位置` ("occupy a
# position") and `占位费` ("site/booth fee") are NOT — those two chars appearing as
# a substring of a different word are false positives. Recall on the placeholder
# sense and on the other tokens (`待…核实`, `未核实`, `证据缺口`) is unchanged.
#
# Greptile PR #64 round-2 (2026-05-29): the leading `待` alternation carries a
# symmetric negative lookbehind `(?<![期对招款])` so hopeful compounds ending in
# `待` — `期待` (look forward), `对待` (treat), `招待`/`款待` (entertain/host) —
# do NOT contribute false-positive deferral hits (e.g. `期待完成` via `待完成`).
# Genuine deferrals (`待核实`, `等待核实` — `等` is not in the exclusion set) still
# match.
_TIER_RANKING_DEFERRAL_RE = re.compile(
    r"(?<![期对招款])待[^，。；、\n]{0,10}(?:核实|完成|验证|补充)|未核实|证据缺口|占位(?![置费])"
)
_TIER_RANKING_DEFERRAL_MAX = 2

# G5 (2026-05-28): minimum per-axis canonical-label coverage for the
# prose_subheaders micro-template. Below this, a canonical axis label appears
# for fewer than half the entities → the writer fragmented into per-entity
# variant phrasings (dev4 id=91: top form only 21-34% per axis) instead of the
# pinned byte-identical label. 0.5 is deliberately lenient (severe fragmentation
# only) to avoid firing when an article profiles some entities in groups.
_MICRO_TEMPLATE_MIN_COVERAGE = 0.5

# L3 (2026-05-29): minimum fraction of entity_matrix entities that must get
# their OWN body expansion (a heading), not just a §1 matrix row. The Qianfan
# head-to-head showed Lunon collapses coverage — id8 expanded 1 of 12 systems
# (0.08), id14 ~4 of 15 teams (0.27) — a large Comprehensiveness loss. 0.5 fires
# only on a SEVERE collapse, lenient enough that imperfect heading-name matching
# on a near-complete article doesn't false-fire.
_ENTITY_COVERAGE_MIN_RATIO = 0.5


def _validate_tier_ranking(article: str, plan: dict) -> dict | None:
    """P3-W7.b (2026-05-27): structural + precision + sensitivity audit
    on the tier_ranking chapter.

    Returns None when no `tier_ranking` is active in the plan.
    Otherwise:
      {
        "n_weights": int,             # weight entries the architect emitted
        "n_tiers": int,
        "scoring_table_present": bool,  # markdown table found in chapter region
        "two_decimal_cells": int,      # number of `\\b\\d+\\.\\d{2}\\b` matches
                                        # in chapter body (after noise strip)
        "three_plus_decimal_cells": int,  # cells violating the 2-decimal rule
        "decimal_precision_ok": bool,  # ≥1 two-dec cell AND 0 three-plus
        "sensitivity_subsection_present": bool,
        "rubric_mismatch_keys": [str],  # tier_ranking.weights keys NOT in
                                        # framing_chapter.published_rubric_items
                                        # (cross-PR consistency check)
        "entities_scored_present": bool,  # G3: architect computed numeric scores
        "deferral_hits": int,           # G3: deferral/placeholder tokens in chapter
      }

    The structural/precision fields are advisory drift telemetry. G3
    (2026-05-28): the CALLER promotes two conditions to HARD failures —
    (a) entities_scored_present but no committed numeric matrix, and
    (b) deferral_hits over `_TIER_RANKING_DEFERRAL_MAX` — so the regen loop
    fixes an uncommitted/deferred ranking (the predict archetype's core
    analytic payload).
    """
    tr = plan.get("tier_ranking")
    if not isinstance(tr, dict):
        return None
    weights = tr.get("weights")
    tiers = tr.get("tiers")
    if not isinstance(weights, dict) or not isinstance(tiers, list):
        return None
    # Filter weights to numeric only (mirror writer.py filter — bool
    # subclass of int trap from W7 PR #43 round-3).
    numeric_weights = {k: v for k, v in weights.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    valid_tiers = [t for t in tiers if isinstance(t, dict) and t.get("name")]
    if not numeric_weights or not valid_tiers:
        return None

    # Locate the chapter region by title match (mirrors framing /
    # limitations / stakeholder pattern). If the title isn't found,
    # the chapter wasn't rendered — return an all-zero audit for
    # drift visibility rather than None (None means "skip", but here
    # the architect DID plan the chapter — non-render is a defect).
    title = str(tr.get("title", "")).strip()
    chapter_start = -1
    chapter_end = len(article)
    if title:
        # Allow h1 OR h2 OR h3 for the chapter heading (`# Tier Ranking`,
        # `## 7 Tier Ranking`, `### 7.1 Tier Ranking` all match). Capture
        # the hash run as group 1 so the chapter-end boundary can be
        # built at the SAME level — see below.
        #
        # End-anchor `(?=\s*(?:$|[:\-—–]))` prevents the prefix-collision
        # class fixed in `_validate_stakeholder_overlap` (PR #42 round-7
        # commit `4d420a9`) from recurring here: without the anchor,
        # title `"Tier Ranking"` would silently match a heading like
        # `## 7 Tier Ranking Considerations`, extracting the wrong
        # chapter's body. Accepts the title followed by end-of-line OR a
        # known heading terminator (colon, dash, em-dash, en-dash).
        m = re.search(
            r"(?m)^(#{1,3})\s+(?:\d+(?:\.\d+)*\s+)?" + re.escape(title) + r"(?=\s*(?:$|[:\-—–]))",
            article,
            re.IGNORECASE,
        )
        if m is not None:
            chapter_start = m.end()
            # Greptile PR #47 round-2: end the chapter scan at the next
            # SIBLING-or-higher heading. The chapter's own sub-sections
            # (e.g. the sensitivity sub-heading) sit ONE level deeper
            # than the chapter heading itself, so ending at the chapter
            # level keeps them inside the scanned region while preventing
            # bleed into sibling chapters at the same level. The prior
            # fixed `#{1,2}` boundary worked for h2 chapters but caused
            # an h3 chapter (`### 7.3 Tier Ranking`) to absorb its h3
            # siblings (`### 7.4 …`) — those siblings' tables and
            # sensitivity headings then registered as passing for the
            # actual (potentially empty) tier-ranking chapter, yielding
            # false-positive drift telemetry.
            chapter_hash_count = len(m.group(1))
            next_h = re.search(
                rf"\n#{{1,{chapter_hash_count}}}\s+",
                article[chapter_start:],
            )
            chapter_end = chapter_start + next_h.start() if next_h else len(article)
    chapter_body = article[chapter_start:chapter_end] if chapter_start >= 0 else ""

    # Pre-strip footnote markers + § refs so their internal digits don't
    # false-positive the 2-dec / 3+-dec regex.
    scannable_body = _TIER_RANKING_NOISE_STRIP_RE.sub("", chapter_body)

    # Scoring table presence: detect a markdown table pipe pattern
    # within the chapter region (heuristic — 2+ consecutive lines with
    # ≥3 pipe chars each indicates a markdown table).
    scoring_table_present = False
    pipe_lines = 0
    for line in chapter_body.splitlines():
        if line.count("|") >= 3:
            pipe_lines += 1
            if pipe_lines >= 2:
                scoring_table_present = True
                break
        else:
            pipe_lines = 0

    two_dec_cells = len(_TIER_RANKING_2DEC_RE.findall(scannable_body))
    three_plus_dec_cells = len(_TIER_RANKING_3PLUS_DEC_RE.findall(scannable_body))
    decimal_precision_ok = two_dec_cells >= 1 and three_plus_dec_cells == 0

    sensitivity_subsection_present = bool(_TIER_RANKING_SENSITIVITY_HEADING_RE.search(chapter_body))

    # G3 (2026-05-28): did the architect actually compute numeric scores? When
    # `entities_scored` is populated, the chapter MUST render them as a committed
    # 2-decimal matrix; when it's absent (qualitative compare tiers, or the
    # fail-soft None path when tier_ranking_score.score_entities times out) we do
    # NOT require a numeric matrix — gating on this keeps the commitment failure
    # off compare and off the no-scores path so it can't loop the regen.
    entities_scored = tr.get("entities_scored")
    entities_scored_present = isinstance(entities_scored, (list, dict)) and len(entities_scored) > 0
    # Deferral / placeholder density INSIDE the ranking chapter (a rendered but
    # hedged ranking). Chapter-scoped so legitimate uncertainty prose elsewhere
    # (e.g. the limitations chapter) is not penalised.
    deferral_hits = len(_TIER_RANKING_DEFERRAL_RE.findall(chapter_body))

    # Cross-PR consistency: tier_ranking.weights keys SHOULD mirror the
    # framing_chapter.published_rubric_items ids. When both are present
    # in the plan, any tier_ranking weight key NOT in the rubric is
    # flagged. Audit-only (advisory) — the architect MAY produce a
    # weight key that doesn't appear in the rubric (e.g., a composite
    # weight added downstream), but a divergence is worth surfacing.
    rubric_mismatch_keys: list[str] = []
    fc = plan.get("framing_chapter")
    if isinstance(fc, dict):
        rubric_items = fc.get("published_rubric_items") or []
        rubric_ids = {str(r.get("id")) for r in rubric_items if isinstance(r, dict) and r.get("id")}
        if rubric_ids:
            for k in numeric_weights:
                if k not in rubric_ids:
                    rubric_mismatch_keys.append(k)

    return {
        "n_weights": len(numeric_weights),
        "n_tiers": len(valid_tiers),
        "scoring_table_present": scoring_table_present,
        "two_decimal_cells": two_dec_cells,
        "three_plus_decimal_cells": three_plus_dec_cells,
        "decimal_precision_ok": decimal_precision_ok,
        "sensitivity_subsection_present": sensitivity_subsection_present,
        "rubric_mismatch_keys": rubric_mismatch_keys,
        "entities_scored_present": entities_scored_present,
        "deferral_hits": deferral_hits,
    }


def _validate_micro_template(article: str, entity_matrix) -> dict | None:
    """G5 (2026-05-28): per-axis canonical-label coverage for the
    prose_subheaders micro-template.

    Returns None unless `entity_matrix` is in prose_subheaders mode with ≥3
    entities and ≥1 named axis. Otherwise, for each axis_name, count the
    paragraphs it OPENS as a canonical bold lead-in (`**axis.**` / `**axis:**` /
    `**axis**`, optional terminal `. : 。 ：`, at a line start) and divide by the
    entity count
    (capped at 1.0). The match is intentionally case-insensitive: casing-only
    drift (e.g. `**Signature Techniques**`) is treated as a canonical hit to
    avoid false-positive fragmentation alerts, even though the writer is asked
    for byte-identical labels. Coverage ~1.0 means the writer used ONE
    canonical label per axis for every entity (the q91 form); low coverage
    means the labels fragmented into per-entity variants (the dev4 id=91
    failure — top form only 21-34% per axis).

    Returns {axis_coverage: {axis: float}, min_axis_coverage: float,
    n_entities: int, n_axes: int}. Advisory; the caller promotes a severe
    shortfall (< _MICRO_TEMPLATE_MIN_COVERAGE) to a medium failure.
    """
    if not isinstance(entity_matrix, dict):
        return None
    if entity_matrix.get("instantiation_mode") != "prose_subheaders":
        return None
    entities = entity_matrix.get("entities")
    dims = entity_matrix.get("dimensions") or []
    axis_names = [str(d.get("axis_name")).strip() for d in dims if isinstance(d, dict) and d.get("axis_name")]
    n_entities = len(entities) if isinstance(entities, list) else 0
    if n_entities < 3 or not axis_names:
        return None
    axis_coverage: dict[str, float] = {}
    for name in axis_names:
        # Canonical bold lead-in: `**name**` with an optional terminal
        # period/colon (EN or ZH) inside or just before the closing `**`.
        # Case-insensitive: we treat wrong capitalisation as canonical to
        # avoid false-positive fragmentation alerts on casing-only drift.
        #
        # Greptile PR #64 round-3 (2026-05-29): anchor to a paragraph LEAD-IN
        # (`(?m)^[ \t]*`) so only labels that OPEN a line count. entity_matrix
        # carries no chapter title to slice on, so a framing/rubric sentence
        # that names the axes inline (e.g. "...evaluates **Signature techniques.**
        # and **Key arc appearances.**") would otherwise add out-of-section hits
        # that inflate coverage and mask a fragmented entity section. The
        # lead-in anchor errs toward firing the failure, never suppressing it.
        pat = re.compile(r"(?m)^[ \t]*\*\*\s*" + re.escape(name) + r"\s*[.:。：]?\s*\*\*", re.IGNORECASE)
        uses = len(pat.findall(article))
        axis_coverage[name] = round(min(uses / n_entities, 1.0), 3)
    min_cov = min(axis_coverage.values()) if axis_coverage else 0.0
    return {
        "axis_coverage": axis_coverage,
        "min_axis_coverage": round(min_cov, 3),
        "n_entities": n_entities,
        "n_axes": len(axis_names),
    }


def _validate_entity_coverage(article: str, entity_matrix) -> dict | None:
    """L3 (2026-05-29): every entity_matrix entity must get its OWN body
    expansion (a heading), not just a §1 matrix row.

    Returns None unless entity_matrix is prose_subheaders with ≥3 entities.
    Otherwise an entity is 'expanded' if its name appears in a markdown heading
    anywhere in the body (a per-entity section). Returns {n_entities, n_expanded,
    coverage, missing}. The caller promotes a SEVERE collapse
    (coverage < _ENTITY_COVERAGE_MIN_RATIO) to a medium failure — the Qianfan
    head-to-head's biggest Comprehensiveness gap (id8 expanded 1/12 systems).
    """
    if not isinstance(entity_matrix, dict):
        return None
    if entity_matrix.get("instantiation_mode") != "prose_subheaders":
        return None
    entities = entity_matrix.get("entities")
    if not isinstance(entities, list) or len(entities) < 3:
        return None
    # All heading TEXT (H1-H6, so a deep per-entity section heading still counts;
    # greptile regex-heading-coverage: cap at 6, not 4), so a per-entity section
    # heading counts but a matrix table row (a `| ... |` line) does not.
    heading_text = "\n".join(re.findall(r"(?m)^#{1,6}\s+(.+)$", article))
    # Match each entity in the heading text, anchored on ASCII-alphanumeric word
    # boundaries and case-insensitively. `missing` keeps original casing for
    # readable telemetry.
    #   - Greptile PR #69 round-1: re.IGNORECASE so a casing-only rewrite
    #     ("IBM Quantum" -> heading "## IBM quantum") still counts — a cluster of
    #     EN entities must not be pushed below _ENTITY_COVERAGE_MIN_RATIO and force
    #     a needless regen. Mirrors the IGNORECASE axis-label match in _validate_micro_template.
    #   - Greptile PR #69 round-3: the guards `(?<![A-Za-z0-9])…(?![A-Za-z0-9])`
    #     stop a SHORT EN entity ("AI", "OS", "ML") from false-positive matching
    #     INSIDE a larger word ("AI" in "SAIL", "OS" in "POSIX"), which would
    #     silently mask a real coverage gap below the 0.5 threshold. The guards key
    #     on [A-Za-z0-9] ONLY, so a CJK entity inside a longer CJK heading
    #     ("量子计算" in "量子计算的发展") still matches — CJK is not ASCII-word-
    #     delimited and a naive \b would wrongly miss it — and multi-word proper
    #     nouns ("IBM Quantum") match verbatim. Same boundary technique as
    #     cjk_despace._CJK_SCAFFOLD_RE.
    n_expanded = 0
    missing: list[str] = []
    for ent in entities:
        e = str(ent).strip()
        if not e:
            continue
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(e) + r"(?![A-Za-z0-9])", re.IGNORECASE)
        if pat.search(heading_text):
            n_expanded += 1
        else:
            missing.append(e)
    total = n_expanded + len(missing)
    coverage = round(n_expanded / total, 3) if total else 1.0
    return {"n_entities": total, "n_expanded": n_expanded, "coverage": coverage, "missing": missing[:20]}


# ---------------------------------------------------------------------------
# NUMERIC-SPINE CONSISTENCY (round 8, id-44). The dev6/round-7b id-44 collapse
# (0.476 / 0.5365) was 3+ figures EACH self-declared as THE headline total
# (数字主脊 / 头条数字) at conflicting values — 120万 vs 4.5万 vs 40万 条/年, a ~28x
# spread; the judge called it "体系崩塌" and it dragged Readability (0.43),
# Insight-rigor and Comprehensiveness even though we BEAT the reference on every
# other criterion. Fix C's soft "restate VERBATIM" prompt could not enforce it:
# each section is an isolated llm.call that never sees the owner chapter's number,
# so every chapter re-derived its own total. This DETERMINISTIC gate fires when
# ≥2 figures that BOTH self-declare headline status conflict by >ratio or across
# count-units, routing a targeted reconcile instruction to the EXISTING refiner
# (which has whole-article view and runs on id-44's ~78k chars).
#
# The discriminator is HEADLINE SELF-DECLARATION, not raw magnitude divergence —
# this is what makes it safe where the earlier flag-any-two gate was not. A
# correct triangulation (Qianfan-style) tags its divergent figures as
# scope/scenario/method COMPONENTS (中枢/区间/情景/自上而下) with only ONE figure
# declared THE headline, so the headline-declared set collapses to size 1 and the
# gate stays silent. The cues below are the STRONG self-declaration tokens our
# spine writer emits next to the single headline total — deliberately NOT 中枢/
# 基准/区间, which consistent reports also attach to legitimate components.
_SPINE_HEADLINE_CUES = ("主脊", "头条")
# A count figure in the spine's domain: [约] <digits>[.<digits>] [万|亿] <条|片|根|件>.
# Currency (元/亿元) and percentages carry no count-unit so they are ignored.
_SPINE_FIGURE_RE = re.compile(r"(?:约|近|逾|超|达)?\s*([0-9]+(?:\.[0-9]+)?)\s*([万亿])?\s*([条片根件])")
_SPINE_MULT = {"万": 1e4, "亿": 1e8, None: 1.0}
_SPINE_RATIO_MAX = 3.0


def _validate_numeric_spine_consistency(article: str, numeric_spine) -> dict | None:
    """Flag ≥2 mutually-contradictory figures that each self-declare THE headline.

    Returns None (silent) unless the architect planned a quantitative deliverable
    (``numeric_spine`` is a non-null dict) AND the article is CJK (the cue lexicon
    and 万/亿 magnitude parsing are Chinese-specific; gated on actual text, not the
    possibly-mislabeled ``language``). Conflict = the set of
    headline-declared count figures spans a >``_SPINE_RATIO_MAX`` magnitude ratio
    OR mixes count-units (条 vs 片 — the口径/unit-switch failure mode).
    """
    if not (isinstance(numeric_spine, dict) and numeric_spine.get("quantity")):
        return None
    if not _is_cjk_text(article):
        return None
    figures: list[tuple] = []  # (magnitude_in_base_units, unit_char)
    for sent in re.split(r"[。！？\n]", article):
        if not any(cue in sent for cue in _SPINE_HEADLINE_CUES):
            continue
        for m in _SPINE_FIGURE_RE.finditer(sent):
            mag = float(m.group(1)) * _SPINE_MULT[m.group(2)]
            # Floor: a headline ANNUAL TOTAL is 万-scale. Exclude per-unit/per-line
            # coefficients (每弓2条, 单条, 80根/线) that can also sit near a cue token
            # — they are not totals and would inflate the spread spuriously.
            if mag >= 1000:
                figures.append((mag, m.group(3)))
    if len(figures) < 2:
        return {"conflict": False, "n_headline_figures": len(figures), "headline_values": []}
    mags = [f[0] for f in figures]
    units = sorted({f[1] for f in figures})
    spread = max(mags) / min(mags) if min(mags) > 0 else 0.0
    conflict = spread > _SPINE_RATIO_MAX or len(units) > 1
    # de-dup for the report: distinct values rendered in 万 (central+range
    # restatements of the SAME value collapse to one entry).
    distinct = sorted({round(v, -3) for v in mags})
    return {
        "conflict": conflict,
        "n_headline_figures": len(figures),
        "spread_ratio": round(spread, 1),
        "units": units,
        "headline_values": [f"{v / 1e4:.2f}万" for v in distinct][:8],
    }


def _validate_limitations_chapter(article: str, limitations_chapter) -> dict | None:
    """P3-W5.b (2026-05-27): structural + anti-generic audit on the
    limitations chapter.

    Returns None when no `limitations_chapter` is active in the plan.
    Otherwise:
      {
        "n_subsections_declared": int,    # entries the architect emitted
        "n_subsections_present": int,     # heading found in article
        "present_subsections": [type, ...],
        "missing_subsections": [type, ...],
        "generic_subsections": [type, ...],  # heading present but body
                                              # had no specific anchor
                                              # (year / proper noun /
                                              # rubric id) — fails the
                                              # anti-generic bar
        "scenario_stress_test_present": bool,  # for predict archetype
        "truncated_bodies": [type, ...],  # sub-sections whose body
                                          # extraction hit the
                                          # _LIMITATIONS_BODY_MAX_CHARS
                                          # cap (no subsequent heading
                                          # within range)
      }

    For each of the 5 declared sub-sections (data_granularity, scope_cap,
    time_validity, sampling, falsifiers), this checks:
      (a) Heading present in article — sub-section title text appears
          on a markdown heading line `#{2,4}\\s+...title...`.
      (b) Body carries ≥1 "specific anchor" matching
          `_LIMITATIONS_SPECIFIC_ANCHOR_RE` (a year, proper noun, or
          rubric id) — distinguishes Qianfan-grade falsification
          (concrete, checkable) from Lunon's prior boilerplate
          ("this report has limitations").

    Advisory severity — surfaced in `counts["limitations_chapter"]` for
    drift telemetry; does NOT block the validation gate. The
    corrective-feedback signal is the compliance scorer (out of scope
    for this PR; deferred per the plan).
    """
    if not isinstance(limitations_chapter, dict):
        return None
    sub_sections = limitations_chapter.get("sub_sections") or []
    if not sub_sections:
        return None
    declared_types = [(idx, s) for idx, s in enumerate(sub_sections) if isinstance(s, dict) and s.get("type")]
    if not declared_types:
        return None

    present_subsections: list[str] = []
    missing_subsections: list[str] = []
    generic_subsections: list[str] = []
    truncated_bodies: list[str] = []

    for _idx, sub in declared_types:
        sub_type = str(sub.get("type", "")).strip()
        sub_title = str(sub.get("title", "")).strip()
        # Locate the heading. Prefer title match (rich heading text), fall
        # back to type-name keyword search (e.g., "data granularity" /
        # "数据" + "粒度" — but the type-name fallback is too noisy for ZH
        # so we only fall back when title is empty). The heading regex
        # anchors to a word boundary (`\b`) after the label rather than
        # requiring end-of-line / punctuation immediately after, so
        # elaborated LLM headings like `### 5.3 Time Validity Horizon`
        # still match for `anchor_text="Time Validity"`. `\b` still
        # blocks mid-word false-positives (`Validityx`).
        anchor_text = sub_title if sub_title else sub_type.replace("_", " ")
        if not anchor_text:
            missing_subsections.append(sub_type)
            continue
        m = re.search(
            r"(?m)^#{2,4}\s+(?:\d+(?:\.\d+)*\s+)?" + re.escape(anchor_text) + r"\b",
            article,
            re.IGNORECASE,
        )
        if m is None:
            missing_subsections.append(sub_type)
            continue
        present_subsections.append(sub_type)
        # Extract body for the anti-generic check.
        nl = article.find("\n", m.end())
        start = nl + 1 if nl >= 0 else m.end()
        next_heading = re.search(r"\n#{1,4}\s+", article[start:])
        if next_heading is not None:
            end = start + next_heading.start()
        else:
            end = start + _LIMITATIONS_BODY_MAX_CHARS
            if end < len(article):
                truncated_bodies.append(sub_type)
        body = article[start : min(end, len(article))]
        # Pre-strip citation markers + § refs so their internal digits
        # don't false-positive the year sub-pattern. See
        # `_LIMITATIONS_CITATION_STRIP_RE` docstring.
        scannable_body = _LIMITATIONS_CITATION_STRIP_RE.sub("", body)
        if not _LIMITATIONS_SPECIFIC_ANCHOR_RE.search(scannable_body):
            generic_subsections.append(sub_type)

    # Scenario stress-test sub-section detection: only relevant when the
    # plan's `scenario_stress_test` is a dict (predict archetype with
    # tier_ranking present). Search the chapter region for an anchor like
    # "scenario stress test" / "情景压力测试" / "stress test" on a heading
    # line. We don't require a specific anchor format — the directive's
    # required output is a markdown table, but a Lunon-degenerate render
    # might emit just a heading; presence is a yes/no signal for drift.
    sst = limitations_chapter.get("scenario_stress_test")
    scenario_stress_test_present = False
    if isinstance(sst, dict):
        # Search the article for a stress-test heading anywhere (could
        # be inside the chapter or, in a writer regression, elsewhere).
        if re.search(
            r"(?m)^#{2,4}\s+(?:\d+(?:\.\d+)*\s+)?(?:scenario\s+stress|stress\s+test|情景压力|情景敏感性|stress\s+scenario)",
            article,
            re.IGNORECASE,
        ):
            scenario_stress_test_present = True

    return {
        "n_subsections_declared": len(declared_types),
        "n_subsections_present": len(present_subsections),
        "present_subsections": present_subsections,
        "missing_subsections": missing_subsections,
        "generic_subsections": generic_subsections,
        "scenario_stress_test_present": scenario_stress_test_present,
        "truncated_bodies": truncated_bodies,
    }


def log_failures(task_id: str, vout: ValidationOutput) -> None:
    """Persist a final-cap failure to validation_failures.jsonl."""
    try:
        _FAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _FAIL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps({"task_id": task_id, "counts": vout.counts, "failures": vout.failures}, ensure_ascii=False)
                + "\n"
            )
    except Exception:  # noqa: BLE001
        pass
