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

from .. import llm
from .. import writing_rules as wr
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
    sys = wr.writer_system(
        archetype,
        domain,
        language,
        [s.get("title") for s in plan.get("report_toc", [])],
        task_id=task_id,
        outline_shape=outline_shape,
        has_stakeholder_chapter=bool(plan.get("stakeholder_chapter")),
    )
    user = (
        f"PROMPT ({language}):\n{prompt}\n\nREPORT TITLE: "
        f"{plan.get('report_title', '')}\n\nEVIDENCE DIGEST (synthesis "
        f"input):\n{digest[:18000]}\n\nWrite ONLY the report title (as "
        f"'# Title') followed by the OPENING per the position-1 rule "
        f"(~200 tokens, hard max ~300). Then STOP — sections follow "
        f"separately."
    )
    return llm.call("writer", user, system=sys, max_tokens=1400, note="writer.open")


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
    sys = wr.writer_system(
        archetype,
        domain,
        language,
        [s.get("title") for s in plan.get("report_toc", [])],
        task_id=task_id,
        outline_shape=outline_shape,
        has_stakeholder_chapter=bool(plan.get("stakeholder_chapter")),
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
        zh = bool(language) and str(language).lower().startswith("zh")
        colon = "：" if zh else ":"
        # Dimensions are normalized to object form by
        # architect._normalize_dimensions. Sort by render_order so every
        # section instantiates axes in the same order — byte-stable header
        # emission across entities is the contract.
        raw_dims = em.get("dimensions") or []
        dims_sorted = sorted(
            (d for d in raw_dims if isinstance(d, dict) and d.get("axis_name")),
            key=lambda d: d.get("render_order", 999),
        )
        axis_lines = "\n".join(
            f"    **{d['axis_name']}{colon}** ({d.get('content_template', '')})" for d in dims_sorted
        )
        # Defensive `or 3`: covers the case where the plan reaches the
        # writer without passing through architect._normalize (e.g. unit
        # tests, future caller). `dict.get(key, default)` returns the
        # stored None when the key is present-with-null, and int(None)
        # raises TypeError. Greptile PR #37 round-3 finding.
        min_axes = int(em.get("min_axes_per_entity") or 3)
        if mode == "prose_subheaders" and dims_sorted:
            template_block = (
                f"PER-ENTITY MICRO-TEMPLATE — for every entity in the matrix that "
                f"this section addresses, produce a sub-section whose body BEGINS "
                f"with these bolded sub-headers (in render_order, EXACT lexical "
                f"match including the terminal `{colon}`):\n"
                f"{axis_lines}\n"
                f"RULES:\n"
                f"  • Every entity instantiates the SAME axes in the SAME order.\n"
                f"  • At least {min_axes} of the {len(dims_sorted)} axes must be "
                f"populated per entity; an axis with no content may be omitted "
                f"ONLY if you write the sub-header anyway and a one-sentence "
                f"note explaining the visibility gap with a `[^{sid}-N]` citation.\n"
                f"  • Do NOT reorder axes per entity. Do NOT introduce ad-hoc "
                f"sub-headers between axes. Do NOT collapse two axes into one bullet.\n"
                f"  • Each axis: 1-3 sentences, max 80 words.\n"
            )
        else:
            template_block = ""
        # Mention "PER-ENTITY MICRO-TEMPLATE" by name in the wrapper only
        # when the directive itself is fired. Legacy mode (template_block
        # is empty) keeps the wrapper text generic so the substring doesn't
        # leak into prompts where the directive doesn't actually appear.
        if template_block:
            s1_wrapper = (
                "\nENTITY MATRIX (article spine for this archetype) — "
                "render this as a markdown table at the top of THIS section "
                "(immediately under the §1 heading; the executive opening "
                "frame is written separately and must not duplicate the "
                "table). Then apply the PER-ENTITY MICRO-TEMPLATE below to "
                "every entity this section addresses:\n"
                f"{json.dumps(em, ensure_ascii=False)}\n"
                f"{template_block}"
            )
            non_s1_wrapper = (
                "\nENTITY MATRIX REMINDER — section §1 renders the canonical "
                "table; THIS section must give EACH entity equal-depth "
                "treatment using the PER-ENTITY MICRO-TEMPLATE below, and "
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
                        "Downstream chapters reference rubric items by `id`."
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
                    rubric_summary = "; ".join(f"{r['id']}: {r.get('label', '')}" for r in rubric)
                    parts.append(f"  Rubric items: {rubric_summary}")
                    parts.append(
                        "  When evaluating an entity against a rubric item, cite the item "
                        'by `id` form (e.g. "Per R-2 (market-size criterion), this sector '
                        'scores high…"). At least one rubric reference per chapter that '
                        "applies a rubric item is the minimum compliance bar."
                    )
                framing_block = "\n".join(parts) + "\n"

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
                "  NON-OVERLAP DISCIPLINE (CRITICAL — the post-write validator "
                "`_validate_stakeholder_overlap` enforces pairwise Jaccard "
                "4-gram overlap < 0.20 between every pair of sub-sections):\n"
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
    if feedback:
        user += f"\nREVISION FEEDBACK — fix these and integrate the cited evidence inline:\n{feedback}\n"
    # Bumped from 7000 → 14000 to accommodate the deeper H3→H4 tree the
    # depth_seeds drive. This is the LLM-call upper bound; in production with
    # `DR_CAPEL_G=on` (the default) the per-section CAPEL countdown — driven
    # by `target_tokens` ≈ length_ceiling/0.75/n_top_sections (≈2.5-3.5k tokens
    # for the typical 8-12-section plan) — is the OPERATIVE per-section cap,
    # not max_tokens. The 14k headroom matters in three cases: (a) CAPEL
    # disabled (`DR_CAPEL_G=off`); (b) degenerate TOCs with <=4 sections where
    # weight-share + `SECTION_BUDGET_CEILING=20_000` push target_tokens past
    # 7k; (c) refiner-pass output that needs room to grow. The "depth uplift"
    # PR #20 promises lands primarily via (i) the architect's deeper outline
    # (more sections × more H3 × explicit depth_seeds payload) and (ii) the
    # length_ceiling 4.0× bump that lifts the per-section CAPEL target —
    # NOT primarily via this max_tokens headroom.
    raw = llm.call("writer", user, system=sys, max_tokens=14000, note=f"writer.sec.{sid}")
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
        f"the six `_INSIGHT_MIN` elements:\n"
        f"  • (a) FORWARD-LOOKING IMPLICATION:   aim ≥{d['forward_looking_min']}% of leaves\n"
        f"  • (b) NAMED CONTRARIAN FRAMING:      aim ≥{d['contrarian_min']}% of leaves\n"
        f"  • (c) QUANTIFIED PROJECTION:         aim ≥{d['quant_min']}% of leaves\n"
        f"  • (d) NAMED-ALTERNATIVE COMPARISON:  aim ≥{d['alternative_min']}% of leaves\n"
        f"  • (e) CAUSAL CHAIN (multi-link):     aim ≥{d['causal_chain_min']}% of leaves\n"
        f"  • (f) PROBLEM-TRADEOFF:              aim ≥{d['problem_tradeoff_min']}% of leaves\n"
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
