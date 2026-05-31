"""WebWeaver hierarchical writer (p1-checklist items 13, 25; arXiv 2509.13312).

Writes the report PER SECTION. For each section it retrieves ONLY that
section's evidence from the WebWeaver memory bank (by citation ID) — the writer
never sees the full evidence corpus (item 25 context boundary). Opus 4.7.
Applies the differentiator writing rules (opening template, insight minimums,
cleaning-resistant attribution, length governor) via writing_rules.writer_system.

P2-Wave-2-A wires CAPEL inline countdown markers (writing_rules.capel_directive)
into each section prompt, then strips them via `_capel_strip.strip_capel_markers`
before returning. P2-Wave-2-G propagates `task_id` to `writer_system` so the
W9-readability fragile-density heuristic can omit `_DEDUP_RULE` when appropriate.
Both default on post-sanity-4 hardcode; set `DR_CAPEL_G=off` to disable
(kill-switch for debug / fall-back).
"""

import json
import os
import re
import sys

from .. import llm
from .. import writing_rules as wr
from ..text_metrics import approx_tokens
from ._capel_strip import strip_capel_markers

# Wave 2 §1.2 follow-up (2026-05-26 PR #30 self-review): writer.py reads
# the per-archetype outline bounds from architect and threads them into
# `writer_system()` so the system-prompt STRUCTURAL CAPS block matches
# the user-prompt OUTLINE SHAPE block (no system/user contradiction).
# Lazy import inside the call to avoid module-load circular-import
# concerns (architect doesn't currently import writer, but defending
# against future changes).


def _capel_g_on() -> bool:
    # P2-Wave-2 hardcoded post-sanity-4 (2026-05-23: paired ΔO +0.0034 vs B0
    # on n=3, 0 marker leaks, ΔReadability +0.0213 firing as designed across
    # both EN+ZH). `DR_CAPEL_G=off` retained as a kill-switch only — set to
    # disable CAPEL countdown markers + G's W9-readability dedup-rule
    # suppression in one go (debug / fall-back path).
    return os.environ.get("DR_CAPEL_G", "on") != "off"


def outline_units(plan):
    """Flatten the Architect TOC into ordered section units.

    Each subsection includes its `depth_seeds` (post-P2-Option-A-#1): 2-4
    short claim/entity/data-point phrases that the writer should populate
    as H4 sub-sub-sections under the H3 subsection. Pre-#1 plans had no
    depth_seeds field — architect._normalize backfills an empty list, which
    the writer treats as "no architect guidance, populate as you see fit".
    """
    units = []
    for s in plan.get("report_toc", []):
        subs = []
        for sub in s.get("subsections", []) or []:
            subs.append(
                {
                    "id": sub.get("id"),
                    "title": sub.get("title", ""),
                    "depth_seeds": sub.get("depth_seeds", []) or [],
                }
            )
        units.append(
            {
                "id": s.get("id"),
                "title": s.get("title", ""),
                "level": 1,
                "subs": subs,
                "depth": s.get("depth_target", "broad"),
            }
        )
    return units


def _acs_for_section(plan, sid):
    out = []
    for a in plan.get("acceptance_criteria", []):
        ts = a.get("target_sections", [])
        if sid in ts or sid.split(".")[0] in ts or not ts:
            out.append({"id": a.get("id"), "text": a.get("text"), "verification": a.get("verification", "")})
    return out[:14]


# A hard cap on the opening's VISIBLE length, kept as defense-in-depth.
# round 4 (2026-05-31) reverted write_opening to max_tokens=1400 (no think) —
# the proven pre-#86 prose-only call — so max_tokens again physically bounds the
# opening. This backstop is now redundant with that ceiling but harmless: the
# position-1 rule targets ~200 tokens (hard max ~300), so 1400 (~4.6× the hard
# max) never trips on a well-formed opening; the backstop only fires on a
# catastrophic overshoot that would otherwise pass every downstream stage
# untouched (no validator checks the opening's length).
_OPENING_TOKEN_BACKSTOP = 1400

# Sentence/paragraph boundaries used to truncate an overshooting opening at a
# clean break: a sentence terminator (Latin or CJK) followed by space/newline/
# end, or a blank-line paragraph break.
_OPENING_BOUNDARY_RE = re.compile(r"[.!?。！？](?=\s|$)|\n\n+")


def _cap_opening_length(text: str) -> str:
    """Backstop the visible opening at `_OPENING_TOKEN_BACKSTOP` (CJK-aware).

    No-op for any well-formed opening (the common case). On overshoot, slices
    the ORIGINAL string at the latest sentence/paragraph boundary whose prefix
    stays within the cap — slicing in place (not split-and-rejoin) preserves the
    `# Title\n\n…` structure so the opening-template check still sees a valid
    head — and logs the truncation to stderr (the visible-length signal the
    raised max_tokens otherwise removed).
    """
    if approx_tokens(text) <= _OPENING_TOKEN_BACKSTOP:
        return text
    cut = 0
    for m in _OPENING_BOUNDARY_RE.finditer(text):
        end = m.end()
        if approx_tokens(text[:end]) > _OPENING_TOKEN_BACKSTOP:
            break
        cut = end
    # Pathological single run with no boundary under the cap: hard-cut by an
    # approximate character budget (non-CJK rate; intentionally generous).
    if cut == 0:
        cut = _OPENING_TOKEN_BACKSTOP * 4
    capped = text[:cut].rstrip()
    print(
        f"[writer.open] visible opening {approx_tokens(text)} tok exceeded the "
        f"{_OPENING_TOKEN_BACKSTOP}-token backstop — truncated to {approx_tokens(capped)} tok",
        file=sys.stderr,
        flush=True,
    )
    return capped


def write_opening(plan, prompt, language, archetype, domain, digest, *, task_id=None):
    """Position-1 opening / executive frame (item 17). Uses the compressed
    digest (a synthesis input, not a full per-section evidence dump).

    Opening NEVER gets CAPEL markers — the position-1 template is already
    tightly length-controlled (~200 tokens) and CAPEL counter-overhead is
    not worth it for such a small target. `task_id` propagates for parity
    with `write_section` but the opening's `_DEDUP_RULE` decision matches
    section behavior (G suppresses there too for consistency).
    """
    # Wave 2 §1.2 follow-up: pass per-archetype outline bounds for
    # system-prompt-vs-user-prompt consistency (see write_section).
    from .architect import _bounds_for_archetype

    outline_shape = _bounds_for_archetype(archetype)
    # Greptile PR #46 round-1 issue #2 (2026-05-27): thread the
    # `has_stakeholder_chapter` flag so the system prompt only carries
    # the ~850-char stakeholder rule when the plan actually has the
    # chapter. The architect emits stakeholder_chapter as None for
    # single-audience prompts; bool() correctly yields False on None
    # and on empty dicts.
    #
    # Greptile PR #45 round-6 issue #2 (2026-05-27): same pattern for
    # `has_limitations_chapter` — trend / recommend archetypes never
    # carry the chapter, so the ~1300-char rule is omitted there.
    #
    # Greptile PR #47 round-5 preempt: same gating for the ~700-char
    # `_TIER_RANKING_RULE` — only compare/predict tasks with ≥5
    # entities AND ≥4 rubric dimensions get tier_ranking, so the
    # rule is pure prompt noise on the majority of tasks.
    sys = wr.writer_system(
        archetype,
        domain,
        language,
        [s.get("title") for s in plan.get("report_toc", [])],
        task_id=task_id,
        outline_shape=outline_shape,
        has_stakeholder_chapter=bool(plan.get("stakeholder_chapter")),
        has_limitations_chapter=bool(plan.get("limitations_chapter")),
        has_tier_ranking=bool(plan.get("tier_ranking")),
    )
    user = (
        f"PROMPT ({language}):\n{prompt}\n\nREPORT TITLE: "
        f"{plan.get('report_title', '')}\n\nEVIDENCE DIGEST (synthesis "
        f"input):\n{digest[:18000]}\n\nWrite ONLY the report title (as "
        f"'# Title') followed by the OPENING per the position-1 rule "
        f"(~200 tokens, hard max ~300). Then STOP — sections follow "
        f"separately."
    )
    raw = llm.call("writer", user, system=sys, max_tokens=1400, note="writer.open")
    return _cap_opening_length(raw)


def write_section(
    unit,
    plan,
    bank,
    *,
    prompt,
    language,
    archetype,
    domain,
    prior_titles,
    feedback="",
    task_id=None,
    target_tokens=None,
):
    """Write one section using ONLY this section's memory-bank evidence.

    Returns (text, stats) where stats = {n_markers_stripped, n_violations}
    when CAPEL is active, else stats has all zeros. Callers may discard
    stats with `text, _ = write_section(...)` when telemetry is not needed.
    """
    sid = unit["id"]
    evidence = bank.for_section(sid)
    # Wave 2 §2.1c (2026-05-26): pre-assign each evidence atom its
    # `[^{sid}-N]` marker number so the writer can't pick a wrong number.
    # The post-process safety net (`_synthesize_missing_defs` below) relies
    # on this mapping: marker N corresponds to `evidence[N-1]`. Pre-Wave-2
    # the marker numbering was writer's choice — verified failure mode on
    # the post-Wave-1 id=91 smoke (writer emitted 183 clean inline markers
    # but zero `[^X]: source` def lines → all 183 stripped as orphans →
    # no References block → distance score regressed to 1.966).
    ev_view = []
    for i, e in enumerate(evidence):
        atom = {
            "marker": f"[^{sid}-{i + 1}]",
            "eid": e["eid"],
            "source_name": e["source_name"],
            "url": e["url"],
            "text": e["text"],
        }
        # P3-W0b (2026-05-27): surface specialist-extracted causal chain
        # to the writer when the finding is multi-step (2+ links).
        # Single-link "chains" are degenerate (= statement again) and
        # add no information, so they're suppressed at render time. The
        # writer is instructed (CITATION CONTRACT block below) to emit
        # the chain prose as "X → Y → Z" when present rather than
        # synthesizing chains from the flat `text` field — preserves
        # source-grounded reasoning vs hallucinated chain construction.
        chain = e.get("chain") or []
        if len(chain) >= 2:
            atom["causal_chain"] = list(chain)
        ev_view.append(atom)
    # Wave 2 §1.2 follow-up (PR #30 self-review): thread per-archetype
    # outline bounds into writer_system so the system-prompt STRUCTURAL
    # CAPS block matches the user-prompt OUTLINE SHAPE block (no
    # system/user contradiction). Without this, list-all sections would
    # get system="3-6 subsections + 4 levels" while user="0-2 subs +
    # no H4" — the LLM would have to pick one to follow.
    from .architect import _bounds_for_archetype

    outline_shape = _bounds_for_archetype(archetype)
    # Greptile PR #46 round-1 issue #2 (2026-05-27): mirror the
    # `has_stakeholder_chapter` flag from `write_opening`. The per-
    # section call assembles the same system prompt; the architect's
    # decision lives on the plan, not the unit.
    # Greptile PR #45 round-6 issue #2 (2026-05-27): same for
    # `has_limitations_chapter` — must match `write_opening` to keep
    # both call sites symmetric (plan-driven, not unit-driven).
    # PR #47 round-5 preempt: same threading for `has_tier_ranking`.
    sys = wr.writer_system(
        archetype,
        domain,
        language,
        [s.get("title") for s in plan.get("report_toc", [])],
        task_id=task_id,
        outline_shape=outline_shape,
        has_stakeholder_chapter=bool(plan.get("stakeholder_chapter")),
        has_limitations_chapter=bool(plan.get("limitations_chapter")),
        has_tier_ranking=bool(plan.get("tier_ranking")),
    )

    capel_block = ""
    capel_active = _capel_g_on() and target_tokens and target_tokens > 0
    if capel_active:
        capel_block = "\n\n" + wr.capel_directive(int(target_tokens))

    # SUBSECTIONS payload (P2-Option-A-#1): each subsection carries its
    # depth_seeds list. The writer renders each subsection as an H3 and
    # populates each depth_seed as an H4 sub-sub-section. Old plans without
    # depth_seeds present an empty list, in which case the writer is told
    # to choose its own H4 leaves (back-compat).
    has_any_seeds = any(sub.get("depth_seeds") for sub in unit["subs"])
    depth_block = (
        "DEPTH POPULATION — REQUIRED:\n"
        "For each H3 subsection above, render ALSO each of its depth_seeds "
        "as an H4 sub-sub-section (####). Each H4 leaf = a focused 400-800 "
        "word treatment of one depth_seed (named entity, claim, data point, "
        "or comparison). If a subsection has no depth_seeds, pick 2-4 H4 "
        "leaves yourself based on the prompt + evidence — do not skip the "
        "depth tier.\n"
        if has_any_seeds
        else "DEPTH POPULATION: pick 2-4 H4 sub-sub-sections per H3 subsection "
        "(architect did not pre-seed them). Each H4 leaf = a focused 400-800 "
        "word treatment of a specific entity, claim, or comparison.\n"
    )

    # P2-Option-A-#7: surface the entity_matrix (when present) to the writer
    # for list-all/compare archetypes. The matrix is the article's structural
    # spine; S1 (and ONLY S1) renders it as a markdown table at the top of
    # its body, while every section gets the equal-depth-per-entity reminder
    # so each one independently maintains the contract. Other archetypes
    # don't see the matrix at all.
    #
    # Greptile PR #25 follow-up (2026-05-25), 2 issues:
    #   Issue 1 (duplicate-table risk): the prior block sent the
    #     "render this as a markdown table" directive to every write_section
    #     call. Each section LLM is independent, so a capable writer could
    #     emit the table at the top of S2, S4, ..., producing up to 12
    #     duplicate tables in the assembled article. The render directive
    #     is now gated on `sid == "S1"`; the equal-depth reminder still
    #     broadcasts to all sections (that's the contract every section
    #     must satisfy on its own slice of the matrix).
    #   Issue 2 (ambiguous canonical placement): "near the article start"
    #     was misleading — write_opening generates the literal article start
    #     (title + ~200-token executive frame) and intentionally does NOT
    #     receive the matrix (bloating the opening frame would burn the
    #     200-token budget). The clarified S1 wording now pins the matrix
    #     to S1's body "immediately under the §1 heading" so neither the
    #     LLM nor a future reviewer can mistake the executive frame as
    #     the right place.
    #
    # Greptile PR #25 follow-up round 3 (2026-05-25): the suppression guard
    # now also requires `em.get("dimensions")` — symmetric with the data
    # contract. A matrix with entities but an empty/missing dimensions list
    # (a state _normalize flags as `entity_matrix.dimensions=0<4` but does
    # not reject) would otherwise still fire the S1 "render this as a
    # markdown table" directive with no column headers, forcing the LLM to
    # hallucinate dimensions or emit a degenerate single-column table.
    # P3-W1 (2026-05-27): writer directive dispatches on entity_matrix
    # `instantiation_mode` field. Two modes:
    #   - "prose_subheaders" (default, P3-W1): writer instantiates each
    #     entity as a sub-section whose body begins with the canonical
    #     bolded sub-headers (one per dimension, in `render_order` with
    #     EXACT lexical match) followed by 1-3 sentences of content
    #     matching that dimension's `content_template`. This is the
    #     Qianfan corpus-wide pattern verified across 11 of 11 articles.
    #   - "table_columns_only" (legacy): pre-W1 behaviour — S1 renders
    #     the matrix as a markdown table; other sections get equal-depth
    #     reminder only.
    #
    # Optional-archetype matrices (predict/explain-mechanism/trend/recommend)
    # are surfaced in the SAME way as required ones when the architect chose
    # to populate them (auto-promote happens in architect._normalize).
    entity_matrix_block = ""
    em = plan.get("entity_matrix")
    em_present = isinstance(em, dict) and em.get("entities") and em.get("dimensions")
    # Required archetypes (list-all/compare) always emit the matrix
    # directive, regardless of instantiation_mode. Optional archetypes
    # (predict/explain-mechanism/trend/recommend) only emit it when
    # instantiation_mode is `prose_subheaders` — the per-entity
    # micro-template path.
    #
    # INTENTIONAL silent-skip (Greptile PR #37 round-5): an optional
    # archetype with `instantiation_mode = "table_columns_only"` falls
    # through this gate and produces no matrix block. There is no
    # legacy table-only writer directive for optional archetypes — the
    # legacy directive was list-all/compare-specific. The audit field
    # `entity_matrix_instantiation_mode = "table_columns_only"` records
    # the state for telemetry, so the skip is observable post-hoc; the
    # writer output alone shows no sign the matrix existed. If an
    # optional-archetype caller wants matrix output, they should set
    # `prose_subheaders` (the normalize default for any falsy value).
    em_active = em_present and (
        archetype in {"list-all", "compare"} or em.get("instantiation_mode") == "prose_subheaders"
    )
    if em_active:
        mode = em.get("instantiation_mode") or "prose_subheaders"
        # Dimensions are normalized to object form by
        # architect._normalize_dimensions. Sort by render_order so every
        # entity covers the themes in the same order — uniform treatment is
        # the contract (the per-entity prose paragraphs follow this theme order).
        raw_dims = em.get("dimensions") or []
        dims_sorted = sorted(
            (d for d in raw_dims if isinstance(d, dict) and d.get("axis_name")),
            key=lambda d: d.get("render_order", 999),
        )
        # Defensive `or 3`: covers the case where the plan reaches the
        # writer without passing through architect._normalize (e.g. unit
        # tests, future caller). `dict.get(key, default)` returns the
        # stored None when the key is present-with-null, and int(None)
        # raises TypeError. Greptile PR #37 round-3 finding.
        min_axes = min(int(em.get("min_axes_per_entity") or 3), len(dims_sorted))
        if mode == "prose_subheaders" and dims_sorted:
            # G5 (2026-05-28): RESTORE the byte-identical bolded-axis-label
            # micro-template (reverts P3b-opt2/#53, which retired it on a MISREAD
            # — the FRESH q91 DOES use a fixed-label template: `**Signature
            # techniques.**` ×23, `**Key arc appearances.**` ×25, `**Final
            # outcome.**` ×20, each canonical string dominating its axis ~88%).
            # dev4 id=91 fragmented to 34/30/28 label variants per axis (top form
            # only 21-34%), so the template never read as a template — directly
            # costing InstFollow ("implementation of the specified organizational
            # structure", id=91 weight 0.32). We KEEP the complementary
            # one-idea-per-paragraph / equal-depth / flat rules from #53; the two
            # are orthogonal (label = first ~3 words; paragraph body unchanged).
            axis_labels = [str(d["axis_name"]).strip() for d in dims_sorted]
            label_menu = "\n".join(f"  **{name}.** …{{one dense paragraph}}" for name in axis_labels)
            template_block = (
                f"PER-ENTITY TREATMENT — Qianfan-verified micro-template. Render EACH "
                f"entity this section addresses as a SINGLE FLAT section (one `##` "
                f"heading; NO `###`/`####` sub-headings inside an entity). The body is "
                f"{min_axes}-{len(dims_sorted)} DENSE paragraphs, ONE analytical theme "
                f"per paragraph, each OPENED BY THE EXACT BOLD AXIS LABEL below — "
                f"BYTE-IDENTICAL across every entity (q91 repeats `**Signature "
                f"techniques.**` verbatim 23×; do NOT paraphrase, translate, "
                f"abbreviate, or vary the label per entity):\n"
                f"{label_menu}\n"
                f"RULES:\n"
                f"  • Use these {len(axis_labels)} labels EXACTLY as written, in this "
                f"order, for EVERY entity. A reader must see the SAME bold labels "
                f"repeat per entity — that consistent structure is precisely what the "
                f"judge rewards as 'implementation of the specified organizational "
                f"structure'. A different phrasing per entity is the failure mode.\n"
                f"  • Each paragraph ~110-200 words developing ONE theme fully. Do "
                f"NOT stack multiple modes (source-criticism + power-scaling + "
                f"mythology + speculation) into one paragraph — the judge penalizes "
                f"that as 'internally unstable'. Choppy <80-word paragraphs also "
                f"hurt; Qianfan's median is ~110+ words.\n"
                f"  • EQUAL-DEPTH across entities: same labels, similar length. "
                f"No entity dropped; none expanded into a multi-heading essay while "
                f"siblings get a stub.\n"
                f"  • Flat ONLY: the bold labels ARE the sub-structure — do NOT "
                f"introduce `###`/`####` headings within an entity.\n"
            )
        else:
            template_block = ""
        # Name the "PER-ENTITY TREATMENT" block in the wrapper only when the
        # directive itself is fired. Legacy mode (template_block is empty)
        # keeps the wrapper text generic so the substring doesn't leak into
        # prompts where the directive doesn't actually appear.
        if template_block:
            s1_wrapper = (
                "\nENTITY MATRIX (article spine for this archetype) — "
                "render this as a markdown table at the top of THIS section "
                "(immediately under the §1 heading; the executive opening "
                "frame is written separately and must not duplicate the "
                "table). Then apply the PER-ENTITY TREATMENT below to "
                "every entity this section addresses:\n"
                f"{json.dumps(em, ensure_ascii=False)}\n"
                f"{template_block}"
            )
            non_s1_wrapper = (
                "\nENTITY MATRIX REMINDER — section §1 renders the canonical "
                "table; THIS section must give EACH entity equal-depth "
                "treatment using the PER-ENTITY TREATMENT below, and "
                "MUST NOT re-render the matrix table:\n"
                f"{json.dumps(em, ensure_ascii=False)}\n"
                f"{template_block}"
            )
        else:
            # Legacy table_columns_only mode: wrapper text references the
            # table only — no mention of the micro-template directive.
            s1_wrapper = (
                "\nENTITY MATRIX (article spine for this archetype) — "
                "render this as a markdown table at the top of THIS section "
                "(immediately under the §1 heading; the executive opening "
                "frame is written separately and must not duplicate the "
                "table) AND give EACH entity equal-depth treatment in the "
                "downstream sections (no entity dropped, no entity "
                "over-weighted vs siblings):\n"
                f"{json.dumps(em, ensure_ascii=False)}\n"
            )
            non_s1_wrapper = (
                "\nENTITY MATRIX REMINDER — section §1 renders the canonical "
                "table for this list-all/compare article; THIS section must "
                "give EACH entity equal-depth treatment (no entity dropped, "
                "no entity over-weighted vs siblings) and MUST NOT re-render "
                "the matrix table:\n"
                f"{json.dumps(em, ensure_ascii=False)}\n"
            )
        entity_matrix_block = s1_wrapper if sid == "S1" else non_s1_wrapper

    # P3-W2 (2026-05-27): framing-chapter dispatch.
    #   §1 (sid=="S1"): receives the FRAMING CONTRACT directive instructing
    #     the writer to emit the 4 sub-sections (scope / rubric / roadmap
    #     / vocabulary) — the §1 chapter is the article's contract with
    #     the reader.
    #   Other sections: receive the NAMED TERM BANK (published_vocabulary
    #     + published_rubric_items) and are instructed to reuse them
    #     unmodified — Qianfan's verified corpus-wide pattern (10/11).
    framing_block = ""
    fc = plan.get("framing_chapter")
    if isinstance(fc, dict):
        if sid == "S1":
            sub_sections = fc.get("sub_sections") or []
            vocab = [str(t) for t in (fc.get("published_vocabulary") or []) if t]
            rubric = [r for r in (fc.get("published_rubric_items") or []) if isinstance(r, dict) and r.get("id")]
            if sub_sections or vocab or rubric:
                parts = [
                    "\nFRAMING CHAPTER CONTRACT (§1 — this section IS the framing chapter; "
                    "write it as the article's contract with the reader):"
                ]
                if sub_sections:
                    parts.append(f"  4 REQUIRED sub-sections: {json.dumps(sub_sections, ensure_ascii=False)}")
                    parts.append(
                        "  Each sub-section: 200-400 words. Use the type field to drive content "
                        '("scope" defines what is in / out of the report; "rubric" lists the '
                        'weighted evaluation dimensions used downstream; "roadmap" names what '
                        'each downstream chapter §2-§N will address; "vocabulary" introduces '
                        "the 5-10 named terms below as the article's analytical lexicon)."
                    )
                if vocab:
                    parts.append(f"  Vocabulary to introduce: {json.dumps(vocab, ensure_ascii=False)}")
                    parts.append(
                        "  Each vocabulary term: define it once in §1.4 vocabulary sub-section; "
                        "downstream chapters will reuse the term UNMODIFIED."
                    )
                if rubric:
                    rubric_summary = "; ".join(f"{r['id']}: {r.get('label', '')}" for r in rubric)
                    parts.append(f"  Rubric to publish: {rubric_summary}")
                    parts.append(
                        "  Render the rubric as a markdown table in §1.2 (columns: id, label, weight). "
                        "In PROSE (here and in every downstream chapter) refer to each item by its "
                        "human-readable LABEL — the `R-N` id belongs ONLY in the §1.2 table's id column, "
                        "never in reader-facing sentences."
                    )
                framing_block = "\n".join(parts) + "\n"
        else:
            vocab = [str(t) for t in (fc.get("published_vocabulary") or []) if t]
            rubric = [r for r in (fc.get("published_rubric_items") or []) if isinstance(r, dict) and r.get("id")]
            if vocab or rubric:
                parts = ["\nNAMED TERM BANK (from §1 framing chapter — use these terms UNMODIFIED when relevant):"]
                if vocab:
                    parts.append(f"  Vocabulary: {json.dumps(vocab, ensure_ascii=False)}")
                    parts.append(
                        "  Reuse each term in its declared form (preserve case, language, "
                        "punctuation); do NOT synonymize or translate. Each vocabulary "
                        "term should appear ≥1 time when contextually relevant — "
                        "Qianfan's verified pattern is ~2-5 reuses per term across the article."
                    )
                if rubric:
                    # PR-B (2026-05-29): expose only the LABELS here (not the `R-N`
                    # ids) — the dev6 list-all (id91) leaked 129 bare R-N despite the
                    # "use labels, not R-N" instruction below, because the ids were
                    # still shown to the writer in this very line. Removing them at the
                    # source removes the temptation; the id is needed only for the §1.2
                    # table (S1 path above), never in entity-verdict prose.
                    rubric_summary = "; ".join(str(r.get("label") or r["id"]) for r in rubric)
                    parts.append(f"  Rubric criteria (name each by this label in prose): {rubric_summary}")
                    parts.append(
                        "  When a section evaluates an entity against a rubric item, render a "
                        "COMPARATIVE VERDICT (a pass/fail/degree judgment per axis), not "
                        "descriptive narration — this is the Qianfan-verified Insight move. "
                        "Write the verdict in YOUR OWN WORDS, referring to each criterion by "
                        "its human-readable LABEL. Do NOT surface the internal 'R-N' ids, do "
                        "NOT use the scaffolding phrase 'per the rubric'/'rubric', and do NOT "
                        "walk each axis descriptively. Keep the verdict as its OWN sentence — "
                        "never appended onto an entity's descriptive paragraph (one analytical "
                        "idea per paragraph). At least one such verdict per chapter that "
                        "evaluates a rubric item is the minimum compliance bar."
                    )
                framing_block = "\n".join(parts) + "\n"

    # P3-W7.b (2026-05-27): TIER RANKING + SENSITIVITY CHECK CONTRACT injection.
    #
    # The architect populates `plan["tier_ranking"]` (architect.py schema
    # lines 153-179) for compare / predict archetypes when entity_matrix
    # has ≥5 entities AND ≥4 dimensions. It carries a `scoring_formula`,
    # `weights` dict (mirroring §1 framing-chapter rubric items),
    # `tiers` list with thresholds, and `sensitivity_check` with the
    # default ±10pp perturbation. The post-merge audit on `main` found
    # that while the architect plans this chapter, the writer LLM had
    # no in-prompt directive to render it — so the scoring table and
    # sensitivity sub-section weren't produced. Qianfan corpus-verified
    # pattern: 3-5/11 articles, distinctive in q14 §7.3-§7.6 (10 teams,
    # S_base/RBM/S_final with 2-decimal scores) and q3 §8.1 (11 sectors,
    # 6-dimension weighted scoring + ±10pp sensitivity).
    #
    # The directive emphasises: (a) 2-decimal precision on all scores,
    # (b) the sensitivity check must be COMPUTATIONAL (actual recomputed
    # S_final values), not narrative — the Lunon writer has historically
    # hallucinated the sensitivity table without grounding.
    tier_ranking_block = ""
    tr = plan.get("tier_ranking")
    if isinstance(tr, dict) and unit.get("title") and unit["title"] == tr.get("title"):
        weights_raw = tr.get("weights") if isinstance(tr.get("weights"), dict) else {}
        # Greptile pre-scan (W7 PR #43 round-3): bool is a subclass of int,
        # so a naive `isinstance(v, (int, float))` would silently admit
        # `True`/`False` as weight values. Filter explicitly.
        weights = {k: v for k, v in weights_raw.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        # PR-B (2026-05-29): map each weight's internal `R-N` id → its §1
        # human-readable label so the chapter opening names criteria in PROSE
        # without leaking the scaffolding ids (the live GPT-5.5 judge dings bare
        # `R-N` hard under Readability/Language-Fluency; dev6 still leaked 206).
        # The id stays available for the scoring-table id column only.
        _rubric_labels = {
            r["id"]: str(r.get("label") or r["id"])
            for r in ((fc or {}).get("published_rubric_items") or [])
            if isinstance(r, dict) and r.get("id")
        }
        weights_labeled = {_rubric_labels.get(k, k): v for k, v in weights.items()}
        tiers = [t for t in (tr.get("tiers") or []) if isinstance(t, dict) and t.get("name")]
        sensitivity = tr.get("sensitivity_check") if isinstance(tr.get("sensitivity_check"), dict) else {}
        # Greptile PR #47 round-2: bool-subclass guard on perturbation_pp,
        # and also coerce float (e.g. `10.0` from a JSON deserializer
        # that doesn't distinguish int from int-valued float) to int so
        # the directive interpolates a clean `±10pp` rather than
        # `±10.0pp`. Prior `isinstance(raw_pp, int)` silently rejected
        # floats and fell back to the default 10 with no signal —
        # callers who legitimately emitted `10.0` (e.g., from a JSON
        # source) saw their value silently discarded.
        #
        # Greptile PR #47 round-6: `sensitivity` is guaranteed to be a
        # dict by the line above (either the actual sensitivity_check
        # dict or `{}`), so the prior `isinstance(sensitivity, dict)`
        # ternary was a dead branch — `else None` was unreachable.
        # Direct `.get()` makes the data flow obvious.
        raw_pp = sensitivity.get("perturbation_pp")
        if isinstance(raw_pp, bool) or not isinstance(raw_pp, (int, float)):
            perturbation_pp = 10
        else:
            perturbation_pp = int(raw_pp)
        scoring_formula = tr.get("scoring_formula") or "S_final = Σ(weight_i × dim_i)"
        if weights and tiers:
            parts = [
                "\nTIER RANKING + SENSITIVITY CHECK CONTRACT (P3-W7; this "
                "section IS the tier-ranking chapter — Qianfan corpus-verified "
                "pattern in 3-5/11 articles, most distinctive in q14 §7.3-§7.6 "
                "(10 teams, S_base/RBM/S_final with 2-decimal scores) and "
                "q3 §8.1 (11 sectors, 6-dimension weighted scoring with "
                "±10pp sensitivity)):"
            ]
            parts.append(
                f"  Scoring formula (use VERBATIM in the chapter opening "
                f"so readers can trace the math): {scoring_formula}"
            )
            parts.append(
                f"  Weights by §1 rubric LABEL — name each criterion by its LABEL in prose; "
                f"the `R-N` id is internal (table id column only), NEVER write it in sentences: "
                f"{json.dumps(weights_labeled, ensure_ascii=False)}"
            )
            parts.append(f"  Tiers and thresholds: {json.dumps(tiers, ensure_ascii=False)}")
            # P3b-OPT3 (2026-05-27): when the architect pre-computed per-entity
            # scores (tier_ranking_score.score_entities), render them verbatim
            # instead of asking the writer to invent them. Pre-computation is
            # LLM judgment (dimension scores) + Python arithmetic (S_final +
            # tier) — consistent, and the 2-decimal validator passes by
            # construction because we format every value as "X.XX" here.
            entities_scored = tr.get("entities_scored")
            display = []
            if isinstance(entities_scored, list):
                for e in entities_scored:
                    # Require a usable name AND a numeric S_final. An entry with
                    # a non-numeric S_final (e.g. a plan whose entities_scored
                    # came from a non-scorer path) would otherwise render as the
                    # literal `null`, which the verbatim-render directive tells
                    # the writer to copy — failing the 2-decimal validator. Skip
                    # it; if that empties `display`, the if-display gate below
                    # falls through to the compute directive. (Greptile #51 r2.)
                    sf = e.get("S_final") if isinstance(e, dict) else None
                    if (
                        not isinstance(e, dict)
                        or not e.get("name")
                        or not (isinstance(sf, (int, float)) and not isinstance(sf, bool))
                    ):
                        continue
                    # Remap dimension-score keys R-N → §1 label (same mapping as
                    # weights_labeled) so the verbatim-render table headers and the
                    # label-keyed norm_weights below share one key schema and no
                    # bare `R-N` id reaches the writer. (Greptile PR #72 round-2.)
                    dims = {
                        _rubric_labels.get(k, k): f"{v:.2f}"
                        for k, v in (e.get("dimension_scores") or {}).items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)
                    }
                    display.append(
                        {
                            "name": e["name"],
                            "dimension_scores": dims,
                            "S_final": f"{sf:.2f}",
                            "tier": e.get("tier"),
                        }
                    )
            # Gate on the FILTERED list: if every entry was malformed (e.g. a
            # corrupt deserialized plan), display is empty and we fall through
            # to the compute directive rather than emit "PRE-COMPUTED SCORES []"
            # with a verbatim-render instruction. (Greptile PR #51 P2.)
            if display:
                # The pre-computed S_final values were derived from weights
                # renormalized to sum to 1.0 (tier_ranking_score._clean_weights).
                # The sensitivity directive MUST hand the writer those same
                # normalized weights — using the raw architect weights (which may
                # not sum to 1.0, e.g. {R-1:5, R-2:3, R-3:2}) would give a
                # sensitivity baseline inconsistent with the main table, the very
                # inconsistency this PR removes. (Greptile PR #51 round-2.)
                _w_total = sum(weights_labeled.values()) or 1.0
                norm_weights = {k: round(v / _w_total, 6) for k, v in weights_labeled.items()}
                parts.append(
                    "  PRE-COMPUTED SCORES — the scoring math is already done "
                    "for you. Render these EXACT values VERBATIM; do NOT "
                    "recompute, round differently, or alter any number:\n"
                    f"    {json.dumps(display, ensure_ascii=False)}"
                )
                parts.append(
                    "  REQUIRED chapter structure:\n"
                    "    1. Opening (~2 paragraphs): state the scoring formula "
                    "explicitly + refer to each §1 rubric item by its human-readable "
                    "LABEL so the weights trace back to the published rubric — do "
                    "NOT write the internal `R-N` id in prose.\n"
                    "    2. SCORING TABLE — render the PRE-COMPUTED SCORES above "
                    "as a markdown table: rows = entities, columns = entity name "
                    "+ each dimension score + S_final + tier. Copy every number "
                    "EXACTLY as given (they are already 2-decimal).\n"
                    "    3. TIER ASSIGNMENT: 1-2 sentence rationale per entity "
                    "naming the DOMINANT dimension(s) (highest dimension scores) "
                    "that drove its placement — this is YOUR analysis prose.\n"
                    f"    4. SENSITIVITY CHECK (sub-section heading must contain "
                    f"'sensitivity' / '敏感性' / '±{perturbation_pp}pp'): using the "
                    f"pre-computed dimension scores and these NORMALIZED weights "
                    f"(they sum to 1.0 and match the pre-computed S_final baseline "
                    f"— use THESE, not the raw weights above): "
                    f"{json.dumps(norm_weights, ensure_ascii=False)}, "
                    f"recompute S_final under ±{perturbation_pp}pp perturbation of "
                    "each weight (the arithmetic is deterministic from the data "
                    "above — do it precisely). Report:\n"
                    "       - Number of entities that change tier under each "
                    "perturbation.\n"
                    "       - The most-sensitive weight (highest tier-shift "
                    "count).\n"
                    "       - A RANK-STABILITY TABLE: rows = scenarios (base / "
                    "each weight ±pp), columns = entities, cells = tier.\n"
                    "    Interpretation: stability across ±perturbation = robust; "
                    "≥3 tier shifts in any scenario = sensitive ranking, "
                    "acknowledge that conclusions depend on weight choice. "
                    "Produce ACTUAL recomputed 2-decimal S_final values, not "
                    "prose describing what would happen."
                )
            else:
                # Fallback (scorer returned None / not yet run): the writer
                # computes the table itself, as before this PR.
                parts.append(
                    "  REQUIRED chapter structure:\n"
                    "    1. Opening (~2 paragraphs): state the scoring formula "
                    "explicitly + refer to each §1 rubric item by its human-readable "
                    "LABEL so the weights trace back to the published rubric — do "
                    "NOT write the internal `R-N` id in prose.\n"
                    "    2. SCORING TABLE — markdown table:\n"
                    "       - Rows = entities (from §1 entity_matrix).\n"
                    "       - Columns = entity name + each rubric dimension score "
                    "+ S_final + tier.\n"
                    "       - ALL scores reported to 2 DECIMAL PLACES (e.g., "
                    "7.45, 6.32, 8.81 — NEVER 7.5 or 7, NEVER 7.452). Pin "
                    "precision to 2; the validator checks for ≥1 cell matching "
                    "`\\b\\d+\\.\\d{2}\\b` AND zero cells with 3+ decimals.\n"
                    "    3. TIER ASSIGNMENT: each entity placed in a tier per "
                    "the thresholds; 1-2 sentence rationale per entity naming "
                    "the DOMINANT dimension(s) driving the placement.\n"
                    f"    4. SENSITIVITY CHECK (sub-section heading must "
                    f"contain 'sensitivity' / '敏感性' / '±{perturbation_pp}pp'): "
                    f"re-rank under ±{perturbation_pp}pp perturbation of each "
                    "weight. For each perturbed weight, recompute S_final for "
                    "ALL entities and report:\n"
                    "       - Number of entities that change tier under the "
                    "perturbation.\n"
                    "       - The most-sensitive weight (whose perturbation "
                    "causes the highest tier-shift count).\n"
                    "       - A RANK-STABILITY TABLE: rows = scenarios (base / "
                    "each weight ±pp), columns = entities, cells = tier "
                    "assignment.\n"
                    "    Interpretation directive: rank stability across "
                    "±perturbation = robust findings; ≥3 tier shifts in any "
                    "perturbed scenario = sensitive ranking, acknowledge "
                    "explicitly that conclusions depend on weight choice.\n"
                    "  Sensitivity perturbation MUST be COMPUTATIONAL not "
                    "narrative — produce the ACTUAL recomputed S_final values "
                    "(2 decimals each), not a paragraph describing what would "
                    "happen if weights were perturbed. The Lunon writer has "
                    "historically hallucinated this sub-section as prose; the "
                    "validator checks for the table structure (2-decimal cells "
                    "+ sensitivity sub-heading)."
                )
            tier_ranking_block = "\n".join(parts) + "\n"

    # P3-W5.b (2026-05-27): LIMITATIONS CHAPTER CONTRACT injection.
    #
    # The architect populates `plan["limitations_chapter"]` (architect.py
    # schema lines 180-210) for predict / compare / explain-mechanism /
    # list-all archetypes with 5 sub-section types (data_granularity,
    # scope_cap, time_validity, sampling, falsifiers). The post-merge
    # audit on `main` found that while the architect plans this chapter,
    # the writer had no in-prompt directive instructing it to render the
    # 5 sub-sections — the chapter showed up in the TOC but the writer
    # produced generic prose. This block matches `framing_block`'s
    # pattern (title-gated extraction + JSON serialisation + prose
    # contract) so the writer LLM sees explicit instructions ONLY when
    # the section currently being written IS the limitations chapter.
    # Qianfan corpus-verified pattern: 6/11 articles. Engineering-grade
    # falsification — each sub-section must name a concrete entity,
    # year, or rubric item (avoid "this report has limitations" boiler-
    # plate). For predict archetype with `scenario_stress_test` populated,
    # an extra sub-section recomputes the tier_ranking (from P3-W7
    # framing-rubric weights) under 3 scenarios (base / optimistic /
    # pessimistic) with a rank-stability table.
    limitations_block = ""
    lc = plan.get("limitations_chapter")
    if isinstance(lc, dict) and unit.get("title") and unit["title"] == lc.get("title"):
        sub_sections = [s for s in (lc.get("sub_sections") or []) if isinstance(s, dict)]
        # Greptile PR #45 round-5 issue #1 (2026-05-27): assign
        # `scenario_stress_test` once instead of calling `lc.get(...)`
        # twice (one inside `isinstance(...)`, one as the value). The
        # double-call was fragile to future renames or property wraps —
        # a single lookup is canonical.
        _sst_raw = lc.get("scenario_stress_test")
        sst = _sst_raw if isinstance(_sst_raw, dict) else None
        if sub_sections:
            parts = [
                "\nLIMITATIONS CHAPTER CONTRACT (P3-W5; this section IS the "
                "limitations chapter — engineering-grade falsification, Qianfan "
                "corpus-verified pattern in 6/11 articles):"
            ]
            parts.append(f"  5 REQUIRED sub-sections: {json.dumps(sub_sections, ensure_ascii=False)}")
            parts.append(
                "  Each sub-section type drives content (each MUST name a "
                "concrete entity, year, or rubric item — generic 'this report "
                "has limitations' boilerplate is forbidden):\n"
                "    - data_granularity: name a SPECIFIC observable the article's "
                "sources could not resolve (2+ sentences naming the gap).\n"
                "    - scope_cap: cite the §1 framing-chapter scope boundary "
                "verbatim; name what the article does NOT cover (population, "
                "region, technology, time-window).\n"
                "    - time_validity: name a SPECIFIC year/phase boundary after "
                "which the article's conclusions may stop holding (e.g., 'beyond "
                "2028 the regulatory regime is expected to change, invalidating "
                "the §3.2 cost projections').\n"
                "    - sampling: name an under-represented entity class or "
                "population whose perspective is not in the source base, with "
                "one sentence on the bias direction.\n"
                "    - falsifiers: name 2-3 SPECIFIC empirical observations that "
                "would refute the article's main claims (drawing on §1.2 rubric "
                "items for falsification axes — name each axis by its human-readable "
                "LABEL, not the internal R-N id).\n"
                "  Each sub-section: 150-300 words. Avoid the lazy form 'data "
                "is limited / scope is constrained' — every sentence must point "
                "to a concrete, checkable gap."
            )
            if sst is not None:
                scenarios = sst.get("scenarios") or ["base", "optimistic", "pessimistic"]
                recompute_target = sst.get("recompute_target") or "tier_ranking"
                parts.append(
                    "  SCENARIO STRESS TEST (predict archetype with tier_ranking — "
                    "append as the FINAL sub-section after the 5 above):\n"
                    f"    Scenarios: {json.dumps(scenarios, ensure_ascii=False)}\n"
                    f"    Recompute the {recompute_target} from the prior chapter "
                    "under each scenario. Render a markdown table with columns: "
                    "Scenario | Top-Ranked Entity | Number of entities that "
                    "moved tier vs base.\n"
                    "    Interpretation directive: <3 tier shifts across scenarios "
                    "= conclusions are robust; ≥3 shifts = conclusions are "
                    "sensitive to scenario assumptions (acknowledge this "
                    "explicitly in the closing sentence of the sub-section)."
                )
            limitations_block = "\n".join(parts) + "\n"

    # P3-W6.b (2026-05-27): STAKEHOLDER-SEGMENTED CLOSING CONTRACT injection.
    #
    # The architect populates `plan["stakeholder_chapter"]` (architect.py
    # schema lines 211-222) with 3-5 stakeholder addressee blocks when
    # the user prompt signals a plural audience (investors AND policy-
    # makers; researchers AND industry; etc.). The post-write validator
    # `_validate_stakeholder_overlap` at validation.py:517-716 has been
    # ACTIVE since PR #42 (P3-W6) catching Jaccard 4-gram overlap >0.20
    # between pairs — but the writer LLM had no in-prompt directive
    # instructing it to render the chapter that way. The validator was
    # auditing blind output. This block matches `framing_block`'s pattern
    # (title-gated extraction + JSON serialisation + prose contract) so
    # the writer LLM sees explicit non-overlap discipline ONLY when the
    # section currently being written IS the stakeholder chapter.
    # Qianfan corpus-verified pattern: 6/11 articles, typically 4 stake-
    # holders for predict / 7 for compare-contest (q23). The 3-5 emit-
    # bound mirrors architect.py — wider acceptance would create a dead
    # branch when the architect produces a 6+ stakeholder chapter.
    stakeholder_block = ""
    sc = plan.get("stakeholder_chapter")
    if isinstance(sc, dict) and unit.get("title") and unit["title"] == sc.get("title"):
        stakeholders = [s for s in (sc.get("stakeholders") or []) if isinstance(s, dict) and s.get("label")]
        if 3 <= len(stakeholders) <= 5:
            parts = [
                "\nSTAKEHOLDER-SEGMENTED CLOSING CONTRACT (P3-W6; this section "
                "IS the stakeholder chapter — Qianfan corpus-verified pattern in "
                "6/11 articles, typically 4 stakeholders for predict / 7 for "
                "compare-contest tasks):"
            ]
            payload = [{"label": s["label"], "directive": s.get("content_directive", "")} for s in stakeholders]
            parts.append(
                f"  {len(stakeholders)} REQUIRED stakeholder sub-sections: {json.dumps(payload, ensure_ascii=False)}"
            )
            parts.append(
                "  Per stakeholder sub-section:\n"
                "    - Heading explicitly names the addressee. EN forms: "
                "'For Policymakers' / 'Recommendations for Investors' / "
                "'From the {Stakeholder} Perspective'. ZH forms: "
                "'对政策制定者的建议' / '对投资者的建议' / '面向{stakeholder}的建议'.\n"
                "    - 200-500 words of advice SPECIFIC to that stakeholder's "
                "decision context (their budget / time horizon / decision "
                "authority / information access).\n"
                "    - Opening phrase modelled on the Qianfan corpus: "
                "'For {stakeholder}, the priority is…' / "
                "'{Stakeholder} should focus on…' / "
                "'The key consideration for {stakeholder} is…' / "
                "'From the {stakeholder} perspective, three steps emerge…'.\n"
                "    - Reference 1-2 specific entities from prior chapters "
                "where relevant.\n"
                # Greptile PR #46 round-2 issue #1 (2026-05-27): user-
                # prompt directive must source the threshold from
                # `wr._STAKEHOLDER_JACCARD_MAX` so a future tightening
                # (e.g., to 0.15) propagates to ALL three surfaces:
                # validator literal, system-prompt rule, AND user-prompt
                # directive. Pre-fix the user-prompt block still had a
                # hardcoded `0.20` literal — the writer LLM would have
                # been steered toward a stale target after a threshold
                # change.
                "  NON-OVERLAP DISCIPLINE (CRITICAL — the post-write validator "
                "`_validate_stakeholder_overlap` enforces pairwise Jaccard "
                f"4-gram overlap < {wr._STAKEHOLDER_JACCARD_MAX:.2f} between "
                "every pair of sub-sections):\n"
                "    - Each block's recommendations MUST address content "
                "DISJOINT from the other blocks.\n"
                "    - Do NOT re-state advice that applies to multiple "
                "stakeholders — choose the PRIMARY stakeholder and place the "
                "recommendation under THAT block only.\n"
                "    - Forbidden: generic recommendations applicable to "
                "'all stakeholders'; boilerplate advice that doesn't name "
                "the stakeholder's specific constraints (budget, time "
                "horizon, decision authority, information access)."
            )
            stakeholder_block = "\n".join(parts) + "\n"

    user = (
        f"PROMPT ({language}):\n{prompt}\n\n"
        f"You are writing ONLY this section of the report (other sections are "
        f"written separately — do not write them, do not repeat the opening).\n"
        f"SECTION {sid}: {unit['title']}\n"
        f"SUBSECTIONS (with depth_seeds for H4 leaves): "
        f"{json.dumps(unit['subs'], ensure_ascii=False)}\n"
        f"DEPTH TARGET: {unit['depth']}\n"
        f"{depth_block}"
        f"{entity_matrix_block}"
        f"{framing_block}"
        f"{tier_ranking_block}"
        f"{limitations_block}"
        f"{stakeholder_block}"
        f"REPORT OUTLINE (titles only, for coherence): "
        f"{json.dumps(prior_titles, ensure_ascii=False)}\n\n"
        f"ACCEPTANCE CRITERIA THIS SECTION MUST SATISFY:\n"
        f"{json.dumps(_acs_for_section(plan, sid), ensure_ascii=False)}\n\n"
        f"EVIDENCE FOR THIS SECTION ONLY — each atom is PRE-ASSIGNED its "
        f"citation marker. Cite atom #N as `[^{sid}-N]`. See CITATION "
        f"CONTRACT below:\n"
        f"{json.dumps(ev_view, ensure_ascii=False)[:42000]}\n\n"
        f"CITATION CONTRACT — MANDATORY (post-2026-05-26 Wave-1 smoke "
        f"surfaced 0 def-lines emitted → 183 markers stripped as orphans "
        f"→ no References block → distance score regressed to 1.966; this "
        f"contract is the structural fix):\n"
        f"• Each evidence atom above carries its PRE-ASSIGNED `marker` "
        f"field (`[^{sid}-1]`, `[^{sid}-2]`, ...). Use the atom's marker "
        f"as-is when citing it — do NOT pick your own numbers. The "
        f"post-process safety net synthesizes def lines using this exact "
        f"mapping (marker N ↔ atom N), so picking a wrong number means "
        f"your citation points to the WRONG source in the rendered "
        f"References block.\n"
        f"• Every load-bearing claim that came from a specific evidence "
        f"atom MUST carry an inline `[^{sid}-N]` marker right after the "
        f"sentence's citation context (e.g. `...as Lebrun (1999) showed[^{sid}-3]` "
        f"means atom #3). REUSE the same marker every time you cite that "
        f"atom — Qianfan reuses each marker ~7× on average. Don't invent "
        f"a new number per sentence; that produces an unreadable "
        f"citation salad.\n"
        f"• DEFINITION LINES — MANDATORY AT SECTION END (this is the bit "
        f"the pre-Wave-2 writer kept skipping; the Wave-1 smoke showed 0 "
        f"def lines on 183 inline markers, dropping every citation). "
        f"At the END of your section, on their own lines, emit ONE def "
        f"line per UNIQUE marker you used:\n"
        f'    `[^{sid}-1]: Author/Source (year), "Title," Publisher/Journal volume, pages.`\n'
        f"  URL is OPTIONAL — if the evidence atom's `url` is non-empty "
        f"include it as ` — <url>` at the end, otherwise omit. Academic "
        f"citation metadata (author, year, title, venue) is the "
        f"substantive payload; URL is supplementary.\n"
        f"• FORBIDDEN: emitting inline `[^{sid}-N]` markers in body prose "
        f"WITHOUT trailing `[^{sid}-N]: source` def lines at section end. "
        f"`footnote_normalize` strips every inline marker that has no "
        f"matching def line as an orphan — your entire section's "
        f"citation surface disappears silently. The CAPEL countdown "
        f"counter does NOT count def lines as 'content tokens' — emit "
        f"def lines AFTER your section's body content, AFTER reaching "
        f"the CAPEL `<0>` marker if applicable.\n"
        f"• FORBIDDEN: picking your own marker numbers instead of using "
        f"the atom's pre-assigned `marker` field. If atom #5 in the "
        f"evidence list is pre-assigned `[^{sid}-5]`, cite it as "
        f"`[^{sid}-5]` — NOT as `[^{sid}-1]` or `[^{sid}-3]` or any "
        f"other number. The post-process safety net maps marker `N` to "
        f"atom `N-1` (1-indexed); if you renumber, your synthesized def "
        f"line will point to the WRONG source. The renaming feels like "
        f"polish but breaks the citation surface — DO NOT do it.\n"
        f"• Section-scope `{sid}-N` is REQUIRED so markers from different "
        f"sections don't collide; the post-process step renumbers "
        f"globally. A bare `[^N]` without the section-scope WILL be "
        f"stripped as orphan.\n"
        f"• Inline NAME citations stay too: every sentence must still "
        f"read complete if all `[^X]` markers are deleted. Footnotes "
        f"are SUPPLEMENTARY identifiers, not the substantive claim.\n"
        f"• Numeric `[n]` markers (without the `^`) are NOT used in this "
        f"pipeline — only `[^{sid}-N]` form.\n"
        # P3-W0b (2026-05-27): when an evidence atom carries a
        # `causal_chain` field (populated by the mechanism_explorer
        # specialist for multi-step findings), prefer rendering the
        # chain explicitly rather than synthesizing one from the flat
        # statement. RACE Insight criterion 2 (causal reasoning) scores
        # higher when chains are source-grounded vs writer-invented.
        f"• CAUSAL CHAIN RENDER (when evidence atom has `causal_chain` field): "
        f"some atoms carry a `causal_chain` array of 2-6 ordered clauses "
        f"naming the intervening causal links (populated by the "
        f"mechanism_explorer specialist). When you cite such an atom, "
        f"prefer rendering the chain EXPLICITLY in prose — '<link1>, "
        f"which leads to <link2>, in turn enabling <link3>[^{sid}-N]' — "
        f"rather than collapsing to the flat `text` summary. This makes "
        f"the causal mechanism visible and source-grounded; do NOT "
        f"invent additional links beyond what the chain provides.\n\n"
        # Wave 2 §3.2 (2026-05-26): mirror the system-prompt `_INSIGHT_MIN`
        # distribution targets here in the user prompt with per-archetype
        # interpolation so the writer sees the explicit percentages for
        # this archetype upfront (where attention lands), not just buried
        # in the system prompt's PR #21 wording.
        f"{_insight_distribution_block(archetype)}"
        f"{capel_block}"
    )
    # P3b-opt2: keep the per-retry feedback OUT of `user` so the heavy stable
    # prompt (evidence + citation contract) stays byte-identical across a
    # section's retries and can be cached (cache_user). The feedback rides as
    # user_suffix — a separate trailing UNCACHED block — so retries read the
    # stable prefix at 0.1× while the small varying feedback is fresh.
    feedback_block = (
        f"\nREVISION FEEDBACK — fix these and integrate the cited evidence inline:\n{feedback}\n" if feedback else ""
    )
    # 2026-05-31 (round 4): revert 96000 -> 21000, drop think/effort. dev8 proved
    # effort=high/max made the writer over-generate — sections ran to 56-96k tokens
    # (vs ~8.5k baseline) and hit the ceiling, for NO leaderboard-score gain. This is
    # the proven pre-#86 prose-only call. The 21000 ceiling == the 0.7x validator
    # pass-line for the SECTION_BUDGET_CEILING=30000 CAPEL cap, so a full-length
    # section still fits. Total-article length parity with Qianfan (~80k EN words /
    # ~110k ZH chars) comes from BREADTH — more chapters (architect TOC) + the
    # per-language CAPEL target — NOT from inflating this single call (which would
    # re-introduce the streaming-timeout/truncation risk).
    raw = llm.call("writer", user, system=sys, max_tokens=21000, note=f"writer.sec.{sid}", user_suffix=feedback_block)
    if capel_active:
        text, stats = strip_capel_markers(raw)
    else:
        text = raw
        stats = {"n_markers_stripped": 0, "n_violations": 0}
    # Wave 2 §2.1c (2026-05-26): synthesize missing def lines from the
    # pre-assigned-marker evidence pack. Safety net for the post-Wave-1
    # smoke failure mode where the writer emitted clean inline markers
    # but 0 trailing def lines, causing footnote_normalize to strip every
    # marker as orphan. Synthesis runs AFTER capel strip so it sees the
    # final marker forms.
    text, n_synth = _synthesize_missing_defs(text, sid, evidence)
    stats["n_synthesized_defs"] = n_synth
    return text, stats


# Wave 2 §2.1c: pattern for inline markers in section body (NOT def lines).
# Mirrors footnote_normalize._INLINE_RE — negative lookahead for `:` keeps
# this from matching the `[^X]:` def-line form.
_INLINE_MARKER_RE = re.compile(r"\[\^([A-Za-z0-9._-]+)\](?!:)")
# Def line pattern — anchored to line start (MULTILINE) like footnote_normalize.
_DEF_LINE_RE = re.compile(r"^[ \t]*\[\^([A-Za-z0-9._-]+)\]:[ \t]*", re.MULTILINE)


def _insight_band(lo: int) -> str:
    """Floor→band (P3b-opt2): `lo` is the calibrated Qianfan-corpus floor —
    NEVER lowered, so the Insight coverage that beats the reference (+1.08)
    is preserved. `hi` adds an upper cap (≈1.5× lo, min spread 5pp, capped at
    100) that forecloses the measured ~5-6× over-production the RACE judge
    reads as 'internally unstable' stacking."""
    hi = min(100, max(lo + 5, round(lo * 1.5)))
    return f"{lo}–{hi}"


def _insight_distribution_block(archetype: str | None) -> str:
    """Wave 2 §3.2 (2026-05-26): user-prompt mirror of the system-prompt
    `_INSIGHT_MIN` distribution targets with per-archetype interpolation.

    Pre-Wave-2 the rule lived only in the system prompt as "pick ONE of
    (a)-(d)"; the 2026-05-26 id=91 smoke showed it wasn't landing
    (forward-looking 7× short of Qianfan density, contrarian 1.77×
    over). Mirroring to the user prompt with explicit per-archetype
    percentages gives the writer a self-check target."""
    d = wr.insight_distribution(archetype)
    return (
        "INSIGHT DISTRIBUTION FOR THIS SECTION — DISTRIBUTIONAL COVERAGE "
        f"(archetype `{archetype}`, Wave 3 PR 2 — extended from 4 to 6 "
        f"elements to cover RACE Insight criteria 2 + 3):\n"
        f"Across all leaves in YOUR section, target this distribution of "
        f"the six `_INSIGHT_MIN` elements (these are BANDS, not floors):\n"
        f"  • (a) FORWARD-LOOKING IMPLICATION:   aim {_insight_band(d['forward_looking_min'])}% of leaves\n"
        f"  • (b) NAMED CONTRARIAN FRAMING:      aim {_insight_band(d['contrarian_min'])}% of leaves\n"
        f"  • (c) QUANTIFIED PROJECTION:         aim {_insight_band(d['quant_min'])}% of leaves\n"
        f"  • (d) NAMED-ALTERNATIVE COMPARISON:  aim {_insight_band(d['alternative_min'])}% of leaves\n"
        f"  • (e) CAUSAL CHAIN (multi-link):     aim {_insight_band(d['causal_chain_min'])}% of leaves\n"
        f"  • (f) PROBLEM-TRADEOFF:              aim {_insight_band(d['problem_tradeoff_min'])}% of leaves\n"
        f"P3b-opt2 (2026-05-28): the lower bound is the Qianfan-corpus-"
        f"calibrated rate that ALREADY beats the reference on Insight "
        f"(+1.08) — landing there is fully acceptable. Do NOT exceed the "
        f"upper bound: over-firing the EASY elements (the measured ~5-6× "
        f"quant/contrarian overshoot vs the Qianfan corpus) is what the "
        f"RACE judge reads as 'internally unstable' multi-mode stacking. "
        f"Give each element its OWN dense paragraph (one analytical theme "
        f"per paragraph) — never stack two modes to hit a number.\n"
        f"(f) PROBLEM-TRADEOFF needs an explicit RESOLUTION clause: name the "
        f"expected outcome, the actual resolution, and the cause — IN YOUR OWN "
        f"WORDS, with varied natural phrasing (do NOT reuse a fixed template "
        f"sentence). A bare unresolved tension does not count; this is our "
        f"weakest Insight sub-criterion.\n"
        f"Each element's full definition is in the system-prompt "
        f"`_INSIGHT_MIN` block. (e) and (f) are NEW in Wave 3 PR 2 and "
        f"target the two RACE Insight criteria (Causal Reasoning + "
        f"Problem-Solution) that Lunon's pre-Wave-3 four elements "
        f"structurally uncovered. The post-process compliance scorer "
        f"(`scripts/p2_writer_compliance.py`) measures actual landing "
        f"rates per element per section, so sustained imbalance shows "
        f"up in drift telemetry.\n\n"
    )


def _synthesize_missing_defs(text: str, sid: str, evidence: list) -> tuple[str, int]:
    """Synthesize `[^{sid}-N]: source` def lines for cited markers the
    writer skipped.

    The pre-Wave-2 contract relied on the writer to emit both inline
    markers AND trailing def lines per the CITATION CONTRACT. Verified
    failure mode on the 2026-05-26 post-Wave-1 smoke: 183 clean inline
    markers were emitted on id=91 with 0 def lines, so
    `footnote_normalize` stripped every marker as orphan and the
    rendered article had no References block (distance score regressed
    to 1.966 from 1.456 baseline).

    Structural fix: each evidence atom is now pre-assigned its marker
    number in `write_section` above (atom N gets `[^{sid}-N]`). This
    safety net parses the writer's output, finds inline markers in the
    `{sid}-N` namespace that lack matching def lines, looks up the
    corresponding atom, and appends synthesized def lines at section
    end. The append preserves the contract's section-scope semantics
    so `footnote_normalize` then renumbers globally as if the writer
    had emitted the defs itself.

    Wave 2 PR #30 self-review robustness fix: the lookup uses a TWO-TIER
    fallback to handle writers that ignore the pre-assigned numbering:

      Tier 1 (name-based): scan the body ±200 chars around each missing
        marker's citation context for any atom's `source_name`. If a
        match is found, use THAT atom's metadata for the synthesized
        def — guarantees correct source attribution even when the
        writer used arbitrary marker numbers (e.g. cited atom #5 as
        `[^S1-2]` because it consulted them out of order).

      Tier 2 (index-based fallback): use atom at index N-1 (1-indexed
        contract). Original Wave 2 behaviour, kept as fallback for
        markers whose citation context doesn't mention any atom's
        source name (the writer cited "as the analysis shows[^S1-3]"
        without naming the analysis).

      Tier 3 (out-of-bounds placeholder): if neither tier produces a
        mapping (marker number > evidence count AND no name match),
        emit a placeholder def so the marker isn't stripped as orphan.
        Operator can inspect via drift log.

    Synthesis is GATED ON THIS SECTION'S `{sid}-N` namespace — markers
    from other sections (which a writer wouldn't legitimately emit but
    might if the writer copied from a prior section's output) are not
    synthesized for this section's pack.

    Returns (text_with_defs, n_synthesized).
    """
    if not evidence:
        return text, 0
    # Collect cited marker numbers in this section's namespace, with
    # their citation-context byte spans (for name-based lookup below).
    namespace_prefix = f"{sid}-"
    cited_spans: dict[int, tuple[int, int]] = {}  # {marker_n: (span_start, span_end)}
    for m in _INLINE_MARKER_RE.finditer(text):
        token = m.group(1)
        if not token.startswith(namespace_prefix):
            continue
        try:
            n = int(token[len(namespace_prefix) :])
        except ValueError:
            continue
        # First-occurrence span only — reused markers all share the
        # same atom mapping, so one window is enough.
        if n not in cited_spans:
            cited_spans[n] = (m.start(), m.end())
    if not cited_spans:
        return text, 0
    # Collect existing def-line numbers in this section's namespace.
    defined_numbers: set[int] = set()
    for m in _DEF_LINE_RE.finditer(text):
        token = m.group(1)
        if not token.startswith(namespace_prefix):
            continue
        try:
            n = int(token[len(namespace_prefix) :])
        except ValueError:
            continue
        defined_numbers.add(n)
    # Synthesize defs for cited-but-undefined markers, in numeric order.
    missing = sorted(n for n in cited_spans if n not in defined_numbers)
    if not missing:
        return text, 0
    synth_lines: list[str] = []
    for n in missing:
        atom = _resolve_atom_for_marker(text, sid, n, cited_spans[n], evidence)
        if atom is None:
            line = f"[^{sid}-{n}]: Evidence atom (writer-emitted marker out of bounds for this section's pack)"
        else:
            source = (atom.get("source_name") or "").strip() or "Evidence atom"
            url = (atom.get("url") or "").strip()
            line = f"[^{sid}-{n}]: {source} — {url}" if url else f"[^{sid}-{n}]: {source}"
        synth_lines.append(line)
    # Append def block at section end (with a blank-line separator so it
    # doesn't run into the writer's final paragraph).
    text = text.rstrip() + "\n\n" + "\n".join(synth_lines) + "\n"
    return text, len(missing)


# Wave 2 PR #30 self-review: name-based mapping window.
#
# The window is BOUNDED BY PARAGRAPH BOUNDARIES so adjacent markers'
# def lines (which live on their own lines, typically separated by `\n`)
# don't bleed into each other's citation contexts. Without the
# paragraph bound, the writer-emitted def line `[^S1-1]: McKinsey (2025)`
# would name-match for S1-2's window (when the two markers are close
# in the body) and wrongly attribute S1-2 to McKinsey.
#
# Within the paragraph, we cap at ±_NAME_MATCH_WINDOW chars so very
# long paragraphs (rare in practice) don't pull source names from
# unrelated sentences.
_NAME_MATCH_WINDOW = 200


def _resolve_atom_for_marker(text: str, sid: str, n: int, span: tuple[int, int], evidence: list) -> dict | None:
    """Three-tier atom lookup for `_synthesize_missing_defs`.

    Returns the resolved atom dict, or None for the out-of-bounds case
    (caller emits placeholder def). See `_synthesize_missing_defs`
    docstring for tier semantics.
    """
    # Tier 1: name-based. Window bounded by paragraph (≥2 consecutive
    # newlines on each side) AND ±_NAME_MATCH_WINDOW chars within the
    # paragraph. First match wins in atom-list order.
    span_start, span_end = span
    # Find paragraph start (previous \n\n or start of text).
    para_start_match = list(re.finditer(r"\n\n", text[:span_start]))
    para_start = para_start_match[-1].end() if para_start_match else 0
    # Find paragraph end (next \n\n or end of text).
    after_match = re.search(r"\n\n", text[span_end:])
    para_end = span_end + after_match.start() if after_match else len(text)
    # Cap to ±_NAME_MATCH_WINDOW within the paragraph.
    window_start = max(para_start, span_start - _NAME_MATCH_WINDOW)
    window_end = min(para_end, span_end + _NAME_MATCH_WINDOW)
    window = text[window_start:window_end]
    for atom in evidence:
        source_name = (atom.get("source_name") or "").strip()
        if not source_name:
            continue
        # Substring match. Source names are typically short distinctive
        # strings like "McKinsey 2025" or "Lebrun (1999)" — case-sensitive
        # match avoids false hits on common words.
        if source_name in window:
            return atom
    # Tier 2: index-based fallback. Marker N → atom index N-1.
    idx = n - 1
    if 0 <= idx < len(evidence):
        return evidence[idx]
    # Tier 3: out-of-bounds. Caller emits placeholder.
    return None


def assemble(opening: str, sections: list) -> str:
    return opening.strip() + "\n\n" + "\n\n".join(s.strip() for s in sections)
