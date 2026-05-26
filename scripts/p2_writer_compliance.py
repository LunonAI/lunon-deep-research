"""Wave 2 §6.1: per-rule writer-compliance landing-rate scorer.

Regex-based, no LLM — cheap iteration feedback signal for every smoke
output. Measures whether the writer's actual output complies with the
rules the prompts ask for. Without this, every prompt-tuning change has
to be measured via expensive RACE evals; with this, we get a feedback
loop in seconds.

Rules measured (each per article):

  1. Footnote density (§2.1b): inline `[^X-N]` markers per 1000 words.
     the reference target: ~6/1000. Pre-Wave-2 verified: 2.3/1000 on id=91.

  2. Definition coverage (§2.1c): % of unique inline markers that have
     a matching `[^X-N]: source` def line in body. Wave 2 added post-
     process synthesis so this should approach 100%; if below, the
     synthesis is missing cases worth diagnosing.

  3. `_INSIGHT_MIN` element distribution (§3.2): % of leaves (H4 in
     deep-hierarchy archetypes, H2 body in flat archetypes) that fire
     each of the four elements (forward-looking / contrarian / quant /
     named-alternative). Wave 2 §3.2 target: balanced 30/20/20/20
     default, with per-archetype bias (predict/trend ≥50% forward-
     looking; list-all/compare ≥30% alternative). Verified id=91
     pre-Wave-2 failure mode: forward-looking 0.14× short, contrarian
     1.77× over, quant 2.44× over.

  4. Section-opening recap (§E1 / `_SECTION_OPENING_RECAP_RULE`): % of
     sections (excluding §1) that open with a 1-2 sentence prose recap
     paragraph before the section's primary content. Verified id=91
     ~90% landing pre-Wave-2.

  5. Outline-bound compliance (§1.2): H2/H3/H4 counts vs the
     per-archetype shape preset from `pipeline/architect._ARCHETYPE_
     OUTLINE_SHAPE`. Reports whether the architect's emission matched
     the preset bounds AND whether the writer rendered it faithfully.

  6. Heading-numbering consistency: % of headings with valid dotted
     numbering (`## 4.1.1` form). Wave 0 fix targets `## 4 . 1 . 1`
     corruption; should be ~100% post-Wave-0.

Usage:
    .venv/bin/python scripts/p2_writer_compliance.py \\
        --lunon-jsonl p2_artifacts/parity_smoke_id91_wave1.jsonl \\
        --ids 91 \\
        --archetype list-all

    # JSON output for downstream tooling:
    .venv/bin/python scripts/p2_writer_compliance.py \\
        --lunon-jsonl p2_artifacts/option_a_dev4.jsonl \\
        --ids 8,14,56,91 \\
        --json-out p2_artifacts/dev4_compliance.json

Exit codes:
    0 = ran successfully (regardless of how compliant)
    2 = no Lunon entry found for any requested id
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Import the per-archetype shape preset + insight distribution so this
# scorer measures against the SAME thresholds the writer was prompted
# with — single source of truth for both contract and audit.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
from deep_research.pipeline.architect import _ARCHETYPE_OUTLINE_SHAPE, _DEFAULT_OUTLINE_SHAPE  # noqa: E402
from deep_research.writing_rules import insight_distribution  # noqa: E402


# Footnote inline marker pattern — same shape as
# `deep_research.pipeline.footnote_normalize._INLINE_RE` (negative
# lookahead for `:` so def lines aren't counted as inline markers).
_INLINE_MARKER_RE = re.compile(r"\[\^([A-Za-z0-9._-]+)\](?!:)")
_DEF_LINE_RE = re.compile(r"^[ \t]*\[\^([A-Za-z0-9._-]+)\]:[ \t]*", re.MULTILINE)

# Heading patterns — match `## N`, `### N.N`, `#### N.N.N`. Used for both
# outline-shape compliance + heading-numbering consistency. Captures the
# full numbering token so dot-count can derive semantic depth.
_HEADING_RE = re.compile(r"^(?P<hashes>#+)[ \t]+(?P<num>\d+(?:\.\d+){0,5})?\.?[ \t]+\S", re.MULTILINE)
# Corrupted heading numbering (pre-Wave-0 fix pattern) — `## 4 . 1 . 1`
# with spaces around dots. Should match 0 lines post-Wave-0.
_CORRUPT_HEADING_RE = re.compile(r"^#+[ \t]+\d+[ \t]+\.[ \t]+\d+", re.MULTILINE)


# `_INSIGHT_MIN` element detectors — regex heuristics derived from the
# rule's exemplar phrases + the existing
# `deep_research.writing_rules.check_insight_minimums` regexes. Each
# detector returns True if the leaf contains at least one phrase matching
# its element. False positives are bounded by the heuristic nature —
# this scorer is iteration feedback, not a judge.
_DATE_RE = re.compile(
    r"\b(20[2-9]\d|in \d+ years|by Q[1-4]|H[12] 20\d\d|"
    r"\d{4}[-–]\d{2,4}|未来|到 ?20\d\d|20\d\d ?年)\b"
)
_FORWARD_RE = re.compile(
    r"(by 20\d\d|through 20\d\d|likely to|expected to|projected to|"
    r"will (?:likely|probably)?|forecast|predict|未来|到20\d\d|预计|"
    r"by H[12] 20\d\d|in the next \d+ years)",
    re.IGNORECASE,
)
_CONTRARIAN_RE = re.compile(
    r"(despite|contrary to|challenges? the (?:view|consensus|standard|prevailing)|"
    r"against (?:the )?(?:consensus|commonly)|counter to (?:the )?(?:consensus|conventional|standard)|"
    r"尽管|与.{0,8}相反|挑战.{0,8}共识|反直觉)",
    re.IGNORECASE,
)
_QUANT_RE = re.compile(
    r"(±|\+/-|range|区间|置信|confidence|\d+%\s*[-–]\s*\d+%|\d+\s*[-–]\s*\d+x|\d+-\d+%)",
    re.IGNORECASE,
)
_ALTERNATIVE_RE = re.compile(
    r"(alternative(?:ly)?|whereas|however|on the other hand|by contrast|conversely|"
    r"instead|in contrast|trade-?off|versus|vs\.?\s|另一种|另一方面|然而|相比之下|相较|"
    r"相对而言|与之相对|替代方案|相反|不同于|反观|权衡)",
    re.IGNORECASE,
)


def _split_into_leaves(article: str, archetype: str) -> list[str]:
    """Split article into per-leaf chunks for element-distribution scoring.

    Deep-hierarchy archetypes (explain-mech / predict / trend / recommend):
    leaves are H4 sections (`#### ...`).
    Flat archetypes (list-all / compare): leaves are H2 body sections
    (`## N Title`) since Wave 2 §1.2 dropped H4 for these archetypes.

    Returns the body text of each leaf, in document order. Excludes
    the article opening (pre-§1 frame) and the References block.
    """
    deep_archetypes = {"explain-mechanism", "predict", "trend", "recommend"}
    is_deep = archetype in deep_archetypes
    leaf_prefix = "####" if is_deep else "##"
    leaves: list[str] = []
    current_lines: list[str] = []
    in_leaf = False
    for line in article.splitlines():
        # Stop at References block — leaves don't extend past it.
        # Pattern allows optional dotted numbering between `#+` and
        # `References` (e.g. `## 3 References` or `## 29 References`)
        # mirroring `footnote_normalize._WRITER_REFS_SECTION_RE`.
        if re.match(r"^[ \t]*#+[ \t]+\d*\.?[ \t]*References?\b", line, re.IGNORECASE):
            break
        stripped = line.lstrip()
        if stripped.startswith(leaf_prefix + " ") and not stripped.startswith(leaf_prefix + "#"):
            # New leaf heading boundary — flush prior leaf, start new.
            if in_leaf and current_lines:
                leaves.append("\n".join(current_lines))
            current_lines = []
            in_leaf = True
            continue
        if in_leaf:
            current_lines.append(line)
    if in_leaf and current_lines:
        leaves.append("\n".join(current_lines))
    return leaves


def _classify_leaf_elements(leaf_body: str) -> dict[str, bool]:
    """For a single leaf, return which `_INSIGHT_MIN` elements fire."""
    return {
        "forward_looking": bool(_FORWARD_RE.search(leaf_body) or _DATE_RE.search(leaf_body)),
        "contrarian": bool(_CONTRARIAN_RE.search(leaf_body)),
        "quant": bool(_QUANT_RE.search(leaf_body)),
        "alternative": bool(_ALTERNATIVE_RE.search(leaf_body)),
    }


def _score_footnotes(article: str) -> dict:
    """Footnote density + def-coverage rule (§2.1b + §2.1c)."""
    n_words = len(article.split())
    markers = _INLINE_MARKER_RE.findall(article)
    unique_markers = set(markers)
    defs = set(_DEF_LINE_RE.findall(article))
    defined_count = len(unique_markers & defs)
    density_per_1k = (len(markers) / n_words * 1000) if n_words else 0.0
    coverage = (defined_count / len(unique_markers)) if unique_markers else 1.0
    return {
        "n_words": n_words,
        "n_inline_markers": len(markers),
        "n_unique_markers": len(unique_markers),
        "n_def_lines": len(defs),
        "n_defined_unique_markers": defined_count,
        "density_per_1k_words": round(density_per_1k, 3),
        "def_coverage_rate": round(coverage, 3),
        # the reference target for context. ≥4 per 1000 words is a soft floor;
        # 6+ is the documented ~reference-id-56 density.
        "reference_target_per_1k": 6,
        "below_reference_target": density_per_1k < 4.0,
    }


def _score_insight_distribution(article: str, archetype: str) -> dict:
    """`_INSIGHT_MIN` element distribution (§3.2) per archetype."""
    leaves = _split_into_leaves(article, archetype)
    n_leaves = len(leaves)
    counts = {"forward_looking": 0, "contrarian": 0, "quant": 0, "alternative": 0}
    for leaf in leaves:
        elems = _classify_leaf_elements(leaf)
        for k, v in elems.items():
            if v:
                counts[k] += 1
    if n_leaves == 0:
        rates = {k: 0.0 for k in counts}
    else:
        rates = {k: round(c / n_leaves * 100, 1) for k, c in counts.items()}
    targets = insight_distribution(archetype)
    # Per-element gap: rate vs target. Negative gap = below target.
    gaps = {
        "forward_looking": round(rates["forward_looking"] - targets["forward_looking_min"], 1),
        "contrarian": round(rates["contrarian"] - targets["contrarian_min"], 1),
        "quant": round(rates["quant"] - targets["quant_min"], 1),
        "alternative": round(rates["alternative"] - targets["alternative_min"], 1),
    }
    return {
        "archetype": archetype,
        "n_leaves": n_leaves,
        "per_element_count": counts,
        "per_element_rate_pct": rates,
        "per_element_target_pct": {
            "forward_looking": targets["forward_looking_min"],
            "contrarian": targets["contrarian_min"],
            "quant": targets["quant_min"],
            "alternative": targets["alternative_min"],
        },
        "per_element_gap_pct": gaps,
        "elements_below_target": [k for k, g in gaps.items() if g < 0],
    }


def _score_outline_shape(article: str, archetype: str) -> dict:
    """Outline-bound compliance (§1.2) — H2/H3/H4 counts vs per-archetype preset."""
    bounds = _ARCHETYPE_OUTLINE_SHAPE.get(archetype, _DEFAULT_OUTLINE_SHAPE)
    counts = {2: 0, 3: 0, 4: 0}
    for m in _HEADING_RE.finditer(article):
        md_depth = len(m.group("hashes"))
        num = m.group("num")
        num_depth = (num.count(".") + 1) if num else 0
        depth = max(md_depth, num_depth)
        bucket = min(depth, 4)
        if bucket >= 2:
            counts[bucket] = counts.get(bucket, 0) + 1
    return {
        "archetype": archetype,
        "bounds": dict(bounds),
        "rendered_h2": counts.get(2, 0),
        "rendered_h3": counts.get(3, 0),
        "rendered_h4plus": counts.get(4, 0),
        "h2_in_bounds": bounds["top_min"] <= counts.get(2, 0) <= bounds["top_max"],
        # H3 is per-top, but we measure article-total — informational only.
        # H4 expected-zero for flat archetypes (seed_max == 0).
        "h4_violates_flat_constraint": (bounds.get("seed_max", 0) == 0 and counts.get(4, 0) > 0),
    }


def _score_heading_numbering(article: str) -> dict:
    """Heading-numbering consistency — post-Wave-0 the `## 4 . 1 . 1`
    corruption should never appear. Reports the count + sample."""
    corrupt_lines = _CORRUPT_HEADING_RE.findall(article)
    return {
        "n_corrupt_heading_numbering": len(corrupt_lines),
        "sample_corrupt": corrupt_lines[:3],
    }


def _score_section_opening_recap(article: str) -> dict:
    """% of `## N ` sections (excluding §1) that open with a prose
    recap paragraph (not a table/list) before the section's primary
    content. Heuristic: the first non-blank line after the heading is
    not a markdown table (`|`) or list (`-`/`*`) bullet."""
    h2_pattern = re.compile(r"^##[ \t]+\d+[ \t]+\S.*$", re.MULTILINE)
    sections = [(m.start(), m.group(0)) for m in h2_pattern.finditer(article)]
    if len(sections) <= 1:
        return {"n_h2_sections": len(sections), "recap_compliance_rate": None}
    # Process sections AFTER the first.
    n_total = 0
    n_recap = 0
    for i, (start, heading) in enumerate(sections[1:], start=1):
        n_total += 1
        # Body window = from this heading to the next H2 (or EOF).
        end = sections[i + 1][0] if i + 1 < len(sections) else len(article)
        body = article[start + len(heading) : end].lstrip("\n")
        # First non-blank, non-table, non-list line.
        first_line = ""
        for line in body.splitlines():
            stripped = line.strip()
            if stripped:
                first_line = stripped
                break
        if first_line and not first_line.startswith(("|", "- ", "* ", "1.", "2.", "3.")):
            n_recap += 1
    rate = (n_recap / n_total) if n_total else 0.0
    return {
        "n_h2_sections": len(sections),
        "n_non_first_sections": n_total,
        "n_with_recap": n_recap,
        "recap_compliance_rate": round(rate, 3),
    }


def compute_compliance(article: str, archetype: str) -> dict:
    """Compute all compliance metrics for one article. Returns a dict
    of per-rule scores."""
    return {
        "footnotes": _score_footnotes(article),
        "insight_distribution": _score_insight_distribution(article, archetype),
        "outline_shape": _score_outline_shape(article, archetype),
        "heading_numbering": _score_heading_numbering(article),
        "section_opening_recap": _score_section_opening_recap(article),
    }


def _render_human(task_id: str, archetype: str, scores: dict) -> str:
    lines = [f"\n### Task {task_id} — archetype `{archetype}`"]
    f = scores["footnotes"]
    lines.append(
        f"  footnotes: {f['n_inline_markers']} inline ({f['density_per_1k_words']}/1k words, target ≥{f['reference_target_per_1k']}), "
        f"def-coverage {f['def_coverage_rate'] * 100:.1f}% ({f['n_defined_unique_markers']}/{f['n_unique_markers']} uniques)"
    )
    if f["below_reference_target"]:
        lines.append("    ↳ BELOW the reference footnote-density floor (≥4/1000)")
    ins = scores["insight_distribution"]
    lines.append(f"  insight distribution ({ins['n_leaves']} leaves):")
    for elem in ("forward_looking", "contrarian", "quant", "alternative"):
        rate = ins["per_element_rate_pct"][elem]
        target = ins["per_element_target_pct"][elem]
        gap = ins["per_element_gap_pct"][elem]
        marker = "  " if gap >= 0 else "↓"
        lines.append(f"    {marker} {elem:<16s}: {rate:>5.1f}% (target ≥{target}%, gap {gap:+.1f}%)")
    if ins["elements_below_target"]:
        lines.append(f"    BELOW target: {', '.join(ins['elements_below_target'])}")
    os_ = scores["outline_shape"]
    lines.append(
        f"  outline: rendered {os_['rendered_h2']} H2 / {os_['rendered_h3']} H3 / "
        f"{os_['rendered_h4plus']} H4+ (bounds: top {os_['bounds']['top_min']}-{os_['bounds']['top_max']}, "
        f"seed_max {os_['bounds']['seed_max']})"
    )
    if not os_["h2_in_bounds"]:
        lines.append("    ↳ H2 OUT OF BOUNDS for this archetype")
    if os_["h4_violates_flat_constraint"]:
        lines.append("    ↳ H4 PRESENT but archetype is FLAT (no H4 allowed)")
    hn = scores["heading_numbering"]
    if hn["n_corrupt_heading_numbering"]:
        lines.append(f"  ⚠️ heading-numbering corruption: {hn['n_corrupt_heading_numbering']} lines")
    else:
        lines.append("  heading-numbering: clean")
    recap = scores["section_opening_recap"]
    if recap["recap_compliance_rate"] is not None:
        lines.append(
            f"  section-opening recap: {recap['n_with_recap']}/{recap['n_non_first_sections']} "
            f"({recap['recap_compliance_rate'] * 100:.1f}%)"
        )
    return "\n".join(lines)


def _load_lunon_by_id(jsonl_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        tid = row.get("id")
        article = row.get("article")
        if tid is None or not article:
            continue
        out[str(tid)] = article
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lunon-jsonl", required=True, type=Path)
    ap.add_argument("--ids", required=True, help="Comma-separated task ids.")
    ap.add_argument(
        "--archetype",
        default="explain-mechanism",
        help="Archetype for all scored tasks (default: explain-mechanism). "
        "For mixed-archetype batches, run separately per archetype.",
    )
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    requested_ids = [s.strip() for s in args.ids.split(",") if s.strip()]
    lunon_by_id = _load_lunon_by_id(args.lunon_jsonl)
    if not any(tid in lunon_by_id for tid in requested_ids):
        print(
            f"error: none of {requested_ids} found in {args.lunon_jsonl}",
            file=sys.stderr,
        )
        sys.exit(2)

    per_task = {}
    for tid in requested_ids:
        article = lunon_by_id.get(tid)
        if not article:
            print(f"\n### Task {tid} — SKIPPED (not in {args.lunon_jsonl.name})", file=sys.stderr)
            continue
        scores = compute_compliance(article, args.archetype)
        per_task[tid] = scores
        print(_render_human(tid, args.archetype, scores))

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps({"tasks": per_task}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[wrote] {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
