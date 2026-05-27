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


def _validate_stakeholder_overlap(article: str, stakeholder_chapter) -> dict | None:
    """P3-W6 (2026-05-27): pairwise content-overlap audit on stakeholder chapter.

    Returns None when no stakeholder_chapter is active. Otherwise:
      {
        "n_stakeholders": int,
        "max_pair_overlap": float,
        "overlap_pairs": [(stakeholder_id_a, stakeholder_id_b, jaccard_4gram)],
      }

    For each pair of stakeholder sub-sections, compute Jaccard similarity
    on 4-gram tokens (word 4-grams for EN; char 4-grams for ZH). Pairs
    with overlap > 0.20 are flagged. the reference's stakeholder sub-sections
    in q23/q3/q14 are nearly content-disjoint (each addresses a distinct
    role with non-overlapping advice).
    """
    if not isinstance(stakeholder_chapter, dict):
        return None
    stakeholders = stakeholder_chapter.get("stakeholders") or []
    if len(stakeholders) < 2:
        return None
    bodies: dict[str, str] = {}
    for s in stakeholders:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id", "")).strip()
        label = str(s.get("label", "")).strip()
        if not sid or not label:
            continue
        idx = article.find(label)
        if idx < 0:
            bodies[sid] = ""
            continue
        nl = article.find("\n", idx)
        start = nl + 1 if nl >= 0 else idx + len(label)
        next_heading = re.search(r"\n#{2,4}\s+", article[start:])
        end = start + (next_heading.start() if next_heading else 5000)
        bodies[sid] = article[start : min(end, len(article))]

    def _ngrams(text: str) -> set:
        text = text.strip()
        if not text:
            return set()
        if any("一" <= c <= "鿿" for c in text[:200]):
            return {text[i : i + 4] for i in range(len(text) - 3)}
        words = [w.lower() for w in re.findall(r"[a-zA-Z0-9]+", text)]
        return {" ".join(words[i : i + 4]) for i in range(len(words) - 3)}

    ngrams_by_id = {sid: _ngrams(body) for sid, body in bodies.items()}
    overlap_pairs: list[tuple] = []
    max_overlap = 0.0
    ids = list(ngrams_by_id.keys())
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            sa, sb = ngrams_by_id[a], ngrams_by_id[b]
            if not sa or not sb:
                continue
            inter = len(sa & sb)
            union = len(sa | sb)
            jaccard = inter / union if union else 0.0
            max_overlap = max(max_overlap, jaccard)
            if jaccard > 0.20:
                overlap_pairs.append((a, b, round(jaccard, 3)))

    return {
        "n_stakeholders": len(ngrams_by_id),
        "max_pair_overlap": round(max_overlap, 3),
        "overlap_pairs": overlap_pairs,
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
