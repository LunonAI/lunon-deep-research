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

_FAIL_LOG = pathlib.Path(__file__).resolve().parent.parent.parent / "p1_artifacts" / "validation_failures.jsonl"
_FAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
_TOK = 4  # ~chars-per-token heuristic; cheap, scoring uses the harness cleaner


@dataclass
class ValidationInput:
    article: str
    plan: dict
    scaffold: Scaffold
    design_guide: DesignGuide
    language: str
    domain: str
    task_id: str = ""


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
    """Locate the section body and check len >= 0.7 × expected_length_tokens."""
    if not title:
        return True, 0
    m = re.search(rf"^#+\s*[\d\.\sA-Z]*\s*{re.escape(title)}\s*$", text, re.IGNORECASE | re.MULTILINE)
    if not m:
        # try a looser match
        m = re.search(re.escape(title), text, re.IGNORECASE)
        if not m:
            return False, 0
    nxt = re.search(r"\n#+\s", text[m.end() :])
    body = text[m.end() : m.end() + (nxt.start() if nxt else len(text))]
    body_tok = len(body) // _TOK
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
        ok, body_tok = _section_length_ok(inp.article, s.title, s.expected_length_tokens)
        if not ok:
            short.append(
                {
                    "section": s.section_id,
                    "title": s.title,
                    "got_tok": body_tok,
                    "min_tok": int(0.7 * s.expected_length_tokens),
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
    ceil_words = wr.length_ceiling(inp.domain)
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

    # 5. Position-1 opening template (writing_rules; per item 17)
    opn = wr.check_opening(inp.article)
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

    # 8. P3-W1 MICRO-TEMPLATE COMPLIANCE (advisory, like INSIGHT). When the
    # plan has a non-empty entity_matrix in prose_subheaders mode, every
    # entity-bearing chapter should instantiate the same bolded sub-headers
    # in render_order. We don't hard-fail (writer is not yet retried for
    # this specifically) but we log compliance ratios into counts for
    # drift telemetry. Implementation deliberately lightweight (no regex
    # parsing of section trees here) — full per-entity compliance lives
    # in `_validate_micro_template` below for offline analysis. The check
    # surfaces a single ratio so dev-run readers can spot regressions.
    em = (inp.plan or {}).get("entity_matrix") if inp.plan else None
    mt_result = _validate_micro_template(inp.article, em)
    if mt_result is not None:
        counts["micro_template_article_compliance"] = mt_result["article_compliance"]
        counts["micro_template_min_axes"] = mt_result["min_axes_per_entity"]
        counts["micro_template_entities_below_floor"] = len(mt_result["below_threshold_entities"])
        # Advisory only — no failure appended. Drift telemetry surfaces
        # the per-entity below-threshold list for post-hoc analysis.

    # 9. P3-W2 (2026-05-27): framing-chapter downstream-reuse — telemetry
    # only. Measures whether §2+ chapters re-engage with §1's published
    # vocabulary + rubric items (the reference corpus-wide pattern of
    # analytical continuity). No fail/pass — surfaced in counts for drift
    # logging; the corrective-feedback loop is via the post-write
    # compliance scorer, not the validation gate. Returns None (skipped)
    # when the plan has no framing_chapter or it is empty.
    fc_reuse = _validate_framing_chapter(inp.article, inp.plan.get("framing_chapter"))
    if fc_reuse is not None:
        counts["framing_chapter_reuse"] = fc_reuse

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


def _find_entity_body_anchor(article: str, ent: str) -> int:
    """Locate the first occurrence of `ent` that is on a line which is
    NOT a markdown table row, so the resulting window covers the
    entity's body section rather than its row inside the §1 matrix.

    The §1 entity matrix is rendered as a markdown table (writer.py
    §1 wrapper). Entity names therefore first appear inside that
    table — pipe-bounded rows, ~20-80 chars apart. Anchoring on the
    bare first occurrence (`article.find(ent)`) lands inside the
    table; the window extends only to the adjacent entity's row;
    the window contains no `**Axis:**` patterns; and every entity
    except the last scores 0.0 — systematically misleading telemetry
    (Greptile PR #37 round-3 finding).

    A table row's first non-whitespace char is `|`. We walk all
    case-insensitive occurrences and return the first one whose
    containing line does not start with `|`. Fall back to the bare
    first occurrence if every match is table-bound — the function
    stays total, and the (still 0.0) compliance signal for that
    entity is correct: the writer never instantiated it outside the
    table.

    Returns the byte index of the anchor, or -1 if `ent` is absent.
    """
    first_any = -1
    for m in re.finditer(re.escape(ent), article, re.IGNORECASE):
        idx = m.start()
        if first_any < 0:
            first_any = idx
        line_start = article.rfind("\n", 0, idx) + 1
        if not article[line_start:idx].lstrip().startswith("|"):
            return idx
    return first_any


def _validate_micro_template(article: str, entity_matrix) -> dict | None:
    """P3-W1 (2026-05-27): compute per-entity micro-template compliance ratio.

    Returns:
      None — when no entity_matrix is active (skip the check)
      dict {
        "article_compliance": float (0.0-1.0; mean across entities),
        "per_entity_compliance": {entity_name: float},
        "below_threshold_entities": [entity_name, ...],
        "min_axes_per_entity": int,
      }

    Compliance per entity = (axes_found_as_bolded_subheader) / (len(dimensions)).
    Below-threshold = ratio < (min_axes_per_entity / len(dimensions)).
    """
    if not isinstance(entity_matrix, dict):
        return None
    entities = entity_matrix.get("entities") or []
    dims = entity_matrix.get("dimensions") or []
    mode = entity_matrix.get("instantiation_mode", "prose_subheaders")
    if not entities or not dims or mode != "prose_subheaders":
        return None
    # Extract axis_name strings (dimensions may be objects post-normalize
    # or strings pre-normalize). Defensive coercion mirrors writer.write_section.
    axis_names: list[str] = []
    for d in dims:
        if isinstance(d, dict):
            n = str(d.get("axis_name", "")).strip()
            if n:
                axis_names.append(n)
        elif isinstance(d, str):
            n = d.strip()
            if n:
                axis_names.append(n)
    if not axis_names:
        return None
    # Defensive `or 3`: covers the case where the matrix reaches the
    # validator without passing through architect._normalize. `dict.get`
    # returns the stored None when the key is present-with-null;
    # int(None) would raise TypeError. Matches the writer's coercion.
    # Greptile PR #37 round-3 finding.
    min_axes = int(entity_matrix.get("min_axes_per_entity") or 3)
    # `axis_names` is non-empty here: the `if not axis_names: return None`
    # guard above fires first. So n_dims > 0 always — no zero-division
    # branch needed. Greptile PR #37 round-7.
    n_dims = len(axis_names)
    threshold_ratio = min(1.0, min_axes / n_dims)

    per_entity: dict[str, float] = {}
    below: list[str] = []
    # For each entity, find its body-section anchor and slice a window
    # that extends until the NEXT entity's body anchor (or a 3000-char
    # cap, whichever is shorter). Without the next-entity boundary, the
    # window would overlap with later entities' sections and inflate
    # the axis count — Greptile pre-scan caught this in the partial-
    # compliance test.
    #
    # Body-section anchor (Greptile PR #37 round-3): NOT a bare first
    # occurrence — the §1 entity matrix is rendered as a markdown table
    # where every entity name appears in compact pipe-bounded rows
    # (~20-80 chars apart). A bare first-mention anchor would land
    # inside that table, the window to the next entity would be tiny
    # and table-bound, contain no `**Axis:**` patterns, and score every
    # entity 0.0 — systematically misleading telemetry. `_find_entity_
    # body_anchor` skips table-row matches.
    entity_positions: list[tuple[str, int]] = []
    for ent_raw in entities:
        ent = str(ent_raw).strip()
        if not ent:
            continue
        idx = _find_entity_body_anchor(article, ent)
        entity_positions.append((ent, idx))
    # Sort by position; -1 (not found) sorted last but treated specially.
    found = sorted(((e, i) for e, i in entity_positions if i >= 0), key=lambda p: p[1])
    not_found = [e for e, i in entity_positions if i < 0]

    for k, (ent, start) in enumerate(found):
        # End of this entity's body slice = start of NEXT found entity,
        # capped at +3000 chars from its own start.
        next_start = found[k + 1][1] if k + 1 < len(found) else len(article)
        end = min(next_start, start + 3000, len(article))
        window = article[start:end]
        n_axes_found = 0
        for ax in axis_names:
            # The micro-template directive emits `**{axis_name}:**` (EN)
            # or `**{axis_name}：**` (ZH). Accept both colon forms — but
            # only the FULL `**...:**` shape. Earlier rounds also matched
            # the open-only `**{ax}:` shape, but those partials are a
            # superstring of the full pattern and never add a new match
            # when the writer closed the bold correctly. They DID falsely
            # match `**Axis: unclosed bold text` from a malformed writer
            # output — silently inflating compliance on cases where the
            # writer forgot to close the markers (Greptile PR #37 round-5).
            patterns = (f"**{ax}:**", f"**{ax}：**")
            if any(p in window for p in patterns):
                n_axes_found += 1
        ratio = n_axes_found / n_dims
        per_entity[ent] = round(ratio, 3)
        if ratio < threshold_ratio:
            below.append(ent)

    for ent in not_found:
        per_entity[ent] = 0.0
        below.append(ent)

    if per_entity:
        article_compliance = round(sum(per_entity.values()) / len(per_entity), 3)
    else:
        article_compliance = 0.0
    return {
        "article_compliance": article_compliance,
        "per_entity_compliance": per_entity,
        "below_threshold_entities": below,
        "min_axes_per_entity": min_axes,
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
    (the reference-verified 5-9% upper bound on §1 length, floored at 8k
    to maintain margin on short/mid-length articles). Reuse measures
    whether DOWNSTREAM chapters re-engage with §1 vocabulary + rubric
    items — the reference-verified corpus-wide pattern of analytical
    continuity.
    """
    if not isinstance(framing_chapter, dict):
        return None
    vocab = [str(t) for t in (framing_chapter.get("published_vocabulary") or []) if t]
    rubric = [r for r in (framing_chapter.get("published_rubric_items") or []) if isinstance(r, dict) and r.get("id")]
    if not vocab and not rubric:
        return None
    # Skip §1 region — heuristic upper bound on the framing chapter's
    # extent. the reference §1 is 5-9% of article length, so the proportional
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
        if any("一" <= c <= "鿿" for c in term):
            # CJK: case is meaningless; count verbatim.
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
