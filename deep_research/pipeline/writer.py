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
    sys = wr.writer_system(
        archetype,
        domain,
        language,
        [s.get("title") for s in plan.get("report_toc", [])],
        task_id=task_id,
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
    ev_view = [
        {
            "marker": f"[^{sid}-{i + 1}]",
            "eid": e["eid"],
            "source_name": e["source_name"],
            "url": e["url"],
            "text": e["text"],
        }
        for i, e in enumerate(evidence)
    ]
    sys = wr.writer_system(
        archetype,
        domain,
        language,
        [s.get("title") for s in plan.get("report_toc", [])],
        task_id=task_id,
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
    entity_matrix_block = ""
    em = plan.get("entity_matrix")
    if archetype in {"list-all", "compare"} and isinstance(em, dict) and em.get("entities") and em.get("dimensions"):
        if sid == "S1":
            entity_matrix_block = (
                f"\nENTITY MATRIX (article spine for this archetype) — "
                f"render this as a markdown table at the top of THIS section "
                f"(immediately under the §1 heading; the executive opening "
                f"frame is written separately and must not duplicate the "
                f"table) AND give EACH entity equal-depth treatment in the "
                f"downstream sections (no entity dropped, no entity "
                f"over-weighted vs siblings):\n"
                f"{json.dumps(em, ensure_ascii=False)}\n"
            )
        else:
            # Non-S1 sections: no render directive (S1 owns the canonical
            # table). Just the equal-depth reminder so this section knows
            # the entity roster it must treat fairly.
            entity_matrix_block = (
                f"\nENTITY MATRIX REMINDER — section §1 renders the "
                f"canonical table for this list-all/compare article; THIS "
                f"section must give EACH entity equal-depth treatment "
                f"(no entity dropped, no entity over-weighted vs siblings) "
                f"and MUST NOT re-render the matrix table:\n"
                f"{json.dumps(em, ensure_ascii=False)}\n"
            )

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
        f"• Section-scope `{sid}-N` is REQUIRED so markers from different "
        f"sections don't collide; the post-process step renumbers "
        f"globally. A bare `[^N]` without the section-scope WILL be "
        f"stripped as orphan.\n"
        f"• Inline NAME citations stay too: every sentence must still "
        f"read complete if all `[^X]` markers are deleted. Footnotes "
        f"are SUPPLEMENTARY identifiers, not the substantive claim.\n"
        f"• Numeric `[n]` markers (without the `^`) are NOT used in this "
        f"pipeline — only `[^{sid}-N]` form.\n\n"
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
        f"(archetype `{archetype}`, Wave 2 §3.2):\n"
        f"Across all leaves in YOUR section, target this distribution of "
        f"the four `_INSIGHT_MIN` elements:\n"
        f"  • (a) FORWARD-LOOKING IMPLICATION: aim ≥{d['forward_looking_min']}% of leaves\n"
        f"  • (b) NAMED CONTRARIAN FRAMING:    aim ≥{d['contrarian_min']}% of leaves\n"
        f"  • (c) QUANTIFIED PROJECTION:       aim ≥{d['quant_min']}% of leaves\n"
        f"  • (d) NAMED-ALTERNATIVE COMPARISON: aim ≥{d['alternative_min']}% of leaves\n"
        f"Each element's full definition is in the system-prompt "
        f"`_INSIGHT_MIN` block. The post-process compliance scorer "
        f"(`scripts/p2_writer_compliance.py`) measures actual landing "
        f"rates per element per section, so sustained imbalance "
        f"(e.g. 90% contrarian / 5% forward-looking, the verified "
        f"id=91 failure mode) shows up in drift telemetry.\n\n"
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
    corresponding atom by index, and appends synthesized def lines at
    section end. The append preserves the contract's section-scope
    semantics so `footnote_normalize` then renumbers globally as if the
    writer had emitted the defs itself.

    Synthesis is GATED ON THIS SECTION'S `{sid}-N` namespace — markers
    from other sections (which a writer wouldn't legitimately emit but
    might if the writer copied from a prior section's output) are not
    synthesized for this section's pack.

    Returns (text_with_defs, n_synthesized).
    """
    if not evidence:
        return text, 0
    # Collect cited marker numbers in this section's namespace.
    cited_numbers: set[int] = set()
    namespace_prefix = f"{sid}-"
    for m in _INLINE_MARKER_RE.finditer(text):
        token = m.group(1)
        if not token.startswith(namespace_prefix):
            continue
        try:
            n = int(token[len(namespace_prefix) :])
        except ValueError:
            continue
        cited_numbers.add(n)
    if not cited_numbers:
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
    missing = sorted(n for n in cited_numbers if n not in defined_numbers)
    if not missing:
        return text, 0
    synth_lines: list[str] = []
    for n in missing:
        # Marker N maps to evidence atom index N-1 (1-indexed contract).
        # Out-of-range markers (writer picked a number with no
        # corresponding atom) get a generic "synthesized; source mapping
        # lost" def so the marker isn't stripped as orphan — preserves
        # the citation surface even when the writer-side numbering was
        # off. Operator can inspect via drift log if needed.
        idx = n - 1
        if 0 <= idx < len(evidence):
            atom = evidence[idx]
            source = (atom.get("source_name") or "").strip() or "Evidence atom"
            url = (atom.get("url") or "").strip()
            if url:
                line = f"[^{sid}-{n}]: {source} — {url}"
            else:
                line = f"[^{sid}-{n}]: {source}"
        else:
            line = f"[^{sid}-{n}]: Evidence atom (writer-emitted marker out of bounds for this section's pack)"
        synth_lines.append(line)
    # Append def block at section end (with a blank-line separator so it
    # doesn't run into the writer's final paragraph).
    text = text.rstrip() + "\n\n" + "\n".join(synth_lines) + "\n"
    return text, len(missing)


def assemble(opening: str, sections: list) -> str:
    return opening.strip() + "\n\n" + "\n\n".join(s.strip() for s in sections)
