"""Wave 2 §6.1: per-rule writer-compliance landing-rate scorer.

Regex-based, no LLM — cheap iteration feedback signal for every smoke
output. Measures whether the writer's actual output complies with the
rules the prompts ask for. Without this, every prompt-tuning change has
to be measured via expensive RACE evals; with this, we get a feedback
loop in seconds.

Rules measured (each per article):

  1. Footnote density (§2.1b): inline `[^X-N]` markers per 1000 words.
     Qianfan target: ~6/1000. Pre-Wave-2 verified: 2.3/1000 on id=91.

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

# Import the per-archetype shape accessor + insight distribution so
# this scorer measures against the SAME thresholds the writer was
# prompted with — single source of truth for both contract and audit.
#
# Greptile PR #30 round-4 follow-up (2026-05-26): import the canonical
# `_bounds_for_archetype()` ACCESSOR instead of the raw
# `_ARCHETYPE_OUTLINE_SHAPE` dict. Going through the accessor matters
# because (a) it returns a defensive copy (mirrors the
# `insight_distribution` mutation-safety contract), and (b) if the
# accessor ever grows normalization / clamping logic the scorer
# automatically tracks the writer's view rather than measuring against
# raw unclamped values.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
from deep_research.pipeline.architect import _bounds_for_archetype  # noqa: E402
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
#
# Wave 2 PR #30 self-review (gap #4): regex coverage expanded after
# manual review of Qianfan corpus idioms. Forward-looking gains
# "looking ahead" / "trajectory" / "going forward" / "anticipate" /
# ZH "前景" / "展望". Quant tightened — bare "range" was too broad
# (matches "wide range of topics" etc.); replaced with scoped patterns
# like "in the range of N" + "range of N-N". Alternative gains
# "compared to" / "as opposed to" / "rather than" / ZH "对比" /
# "相比". Contrarian gains "yet" (when scoped) / "in fact" / "argue
# against" / ZH "实际上" / "事实上".
_DATE_RE = re.compile(
    r"\b(20[2-9]\d|in \d+ years|by Q[1-4]|H[12] 20\d\d|"
    r"\d{4}[-–]\d{2,4}|未来|到 ?20\d\d|20\d\d ?年)\b"
)
_FORWARD_RE = re.compile(
    r"(by 20\d\d|through 20\d\d|likely to|expected to|projected to|"
    r"will (?:likely|probably|continue|see|need|require)|"
    r"forecast|predict|anticipate|looking ahead|going forward|"
    r"in the (?:next|coming) \d+ years|over the next \d+ years|"
    r"trajectory|outlook|near-term|long-term horizon|"
    r"by H[12] 20\d\d|"
    r"未来|到 ?20\d\d|预计|展望|前景|趋势|发展方向)",
    re.IGNORECASE,
)
_CONTRARIAN_RE = re.compile(
    # Greptile PR #30 round-3 follow-up (2026-05-26): `\byet\b` removed.
    # The previous negative lookahead `(?!,? \w+ ago)` was logically
    # inverted — it checked what comes AFTER "yet", not before, so
    # "not yet" / "yet another" / "5 years ago, yet the pattern
    # continues" all still matched. The other contrarian phrases below
    # cover genuine adversative framing without the false-positive risk.
    #
    # Greptile PR #30 round-5 follow-up (2026-05-26): `\bin fact\b`
    # narrowed to require a reversal marker (reverse/opposite/contrary)
    # after. The bare phrase matches common analytical openings
    # ("In fact, performance improved 30%" / "In fact, this is
    # well-understood") that are NOT contrarian framing; over-counting
    # there inflates `per_element_rate_pct["contrarian"]` and masks
    # genuine under-performance — the opposite of what §3.2 is meant
    # to surface.
    r"(\bdespite\b|\bcontrary to\b|"
    r"challenges? the (?:view|consensus|standard|prevailing|conventional)|"
    r"against (?:the )?(?:consensus|commonly|conventional)|"
    r"counter to (?:the )?(?:consensus|conventional|standard|received)|"
    r"argue(?:s|d)? against|push(?:es|ed)? back (?:on|against)|"
    r"\bin fact[,\s]+(?:the\s+)?(?:reverse|opposite|contrary)|"
    r"contrary to popular|differs from the standard|"
    r"尽管|与.{0,8}相反|挑战.{0,8}共识|反直觉|实际上|事实上|"
    r"反观|相反地)",
    re.IGNORECASE,
)
_QUANT_RE = re.compile(
    r"(±|\+/-|"
    r"in the range of \d+|"  # tighter than bare "range"
    r"\d+\s*[-–]\s*\d+\s*(?:%|×|x|percent)|"  # "60-75%" or "2-5x"
    r"range of \d+[-–]\d+|"
    r"\d+%\s*[-–]\s*\d+%|"
    r"\d+-\d+%|"
    r"confidence interval|"
    r"credible interval|"
    r"\d+\s*(?:to|-)\s*\d+\s*(?:hour|day|week|month|year)|"
    r"approximately \d+|roughly \d+|"
    r"on the order of \d+|"
    r"区间|置信|大约 ?\d+)",
    re.IGNORECASE,
)
_ALTERNATIVE_RE = re.compile(
    r"(\balternative(?:ly|s)?\b|"
    r"\bwhereas\b|\bhowever\b|\bon the other hand\b|"
    r"\bby contrast\b|\bin contrast\b|\bconversely\b|"
    r"\binstead of\b|\brather than\b|"
    r"\bcompared (?:to|with)\b|\bas opposed to\b|"
    r"\btrade-?off\b|"
    r"\bversus\b|\bvs\.?\s|"
    r"另一种|另一方面|然而|相比之下|相较|相比|对比|"
    r"相对而言|与之相对|替代方案|相反|不同于|反观|权衡|"
    r"取舍|不如|优于|劣于|胜过)",
    re.IGNORECASE,
)


def _split_into_leaves(article: str, archetype: str) -> list[str]:
    """Split article into per-leaf chunks for element-distribution scoring.

    Leaf detection is ADAPTIVE per article: the leaf tier is the
    DEEPEST observed semantic heading depth in the article (capped at
    the archetype's expected leaf depth — flat archetypes use H2 as
    the cap; deep archetypes allow up to H4). This handles the
    Qianfan-vs-Lunon convention mismatch:
      - Qianfan id=56 (explain-mech) tops out at H3 — leaves are H3
      - Our Lunon explain-mech may use H4 — leaves are H4
      - Qianfan id=91 (list-all) tops out at H2 — leaves are H2
      - Our Lunon list-all may use H4 (pre-Wave-2) or H2 (post-Wave-2)

    Wave 2 PR #30 self-review (gap #3 corpus calibration): without the
    adaptive depth, Qianfan corpus articles measured zero leaves
    (because we were looking for H4 but they only have H3), making
    per-archetype distribution-target calibration impossible.

    Returns the body text of each leaf, in document order. Excludes
    the article opening (pre-§1 frame) and the References block.
    """
    deep_archetypes = {"explain-mechanism", "predict", "trend", "recommend"}
    is_deep = archetype in deep_archetypes
    cap_depth = 4 if is_deep else 2
    # First pass: find the deepest semantic depth in the article (capped).
    observed_max = 0
    for line in article.splitlines():
        if re.match(r"^[ \t]*#+[ \t]+\d*\.?[ \t]*References?\b", line, re.IGNORECASE):
            break
        if re.match(r"^[ \t]*\d+(?:\.\d+){0,4}\.?[ \t]+References?\b", line, re.IGNORECASE):
            break
        d = _line_semantic_depth(line)
        if d:
            observed_max = max(observed_max, d)
    # Leaf depth = min(observed_max, cap). If observed_max < 2 (article
    # had no real headings), fall back to depth 2 so the splitter
    # doesn't degenerately treat the entire article as one leaf.
    leaf_depth = min(observed_max, cap_depth) if observed_max >= 2 else 2

    leaves: list[str] = []
    current_lines: list[str] = []
    in_leaf = False
    for line in article.splitlines():
        if re.match(r"^[ \t]*#+[ \t]+\d*\.?[ \t]*References?\b", line, re.IGNORECASE):
            break
        if re.match(r"^[ \t]*\d+(?:\.\d+){0,4}\.?[ \t]+References?\b", line, re.IGNORECASE):
            break
        depth = _line_semantic_depth(line)
        if depth == leaf_depth:
            # New leaf heading boundary — flush prior leaf, start new.
            if in_leaf and current_lines:
                leaves.append("\n".join(current_lines))
            current_lines = []
            in_leaf = True
            continue
        # Greptile PR #30 follow-up (2026-05-26): when we're inside a
        # leaf and we hit a SHALLOWER heading (H2/H3 boundary for a
        # H4 leaf, H1 boundary for a H2 leaf), flush + exit leaf mode.
        # Without this, the next H2/H3 section's heading text leaks
        # into the preceding leaf's body — heading strings like
        # "By 2030 trends in X" would fire false element detections
        # against the wrong leaf, skewing per_element_rate_pct.
        if 0 < depth < leaf_depth and in_leaf:
            if current_lines:
                leaves.append("\n".join(current_lines))
            current_lines = []
            in_leaf = False
            continue
        if in_leaf:
            current_lines.append(line)
    if in_leaf and current_lines:
        leaves.append("\n".join(current_lines))
    return leaves


def _line_semantic_depth(line: str) -> int:
    """Derive semantic heading depth for a line, handling both markdown
    (`## Foo`) and bare-numbered (`1.1 Foo`) conventions.

    Returns 0 for non-heading lines, else depth in [1, 4+].
    Bare-numbered headings use `dot_count + 1` (Qianfan convention).
    Hybrid `## 1.1.1 Foo` returns `max(hash_depth, dot_count + 1)`.
    """
    md_match = re.match(r"^[ \t]*(#{1,6})[ \t]+(.*)$", line)
    md_depth = len(md_match.group(1)) if md_match else 0
    rest = md_match.group(2) if md_match else line.lstrip()
    num_match = re.match(r"^(\d+(?:\.\d+){0,4})\.?[ \t]+\S", rest)
    num_depth = (num_match.group(1).count(".") + 1) if num_match else 0
    if md_depth == 0 and num_depth == 0:
        return 0
    if md_depth == 0:
        return num_depth
    return max(md_depth, num_depth)


def _classify_leaf_elements(leaf_body: str) -> dict[str, bool]:
    """For a single leaf, return which `_INSIGHT_MIN` elements fire.

    Greptile PR #30 round-3 follow-up (2026-05-26): `_DATE_RE` removed
    from the forward-looking detector. `_DATE_RE` captures any year in
    `20[2-9]\\d` (2020-2099), so a retrospective sentence like "In 2023,
    the recession hit market valuations" was scoring as forward-looking
    — inflating the count and masking genuine under-performance on the
    element §3.2 was meant to surface. Only `_FORWARD_RE` (which uses
    explicit forward markers like "by 20XX", "through 20XX", "expected
    to", "looking ahead", "trajectory") drives the classification now.
    `_DATE_RE` is retained at module level for callers that explicitly
    need date detection (none currently).
    """
    return {
        "forward_looking": bool(_FORWARD_RE.search(leaf_body)),
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
        # Qianfan target for context. ≥4 per 1000 words is a soft floor;
        # 6+ is the documented ~Qianfan-id-56 density.
        "qianfan_target_per_1k": 6,
        "below_qianfan_target": density_per_1k < 4.0,
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
    """Outline-bound compliance (§1.2) — H2/H3/H4 counts vs per-archetype preset.

    Greptile PR #30 round-4 follow-up: routes through the canonical
    `_bounds_for_archetype()` accessor instead of bypassing it with a
    direct dict lookup. Guarantees the scorer measures against the
    same bounds the writer was prompted with — single source of truth.
    """
    bounds = _bounds_for_archetype(archetype)
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
        # Greptile PR #30 follow-up (2026-05-26): `#` added to the
        # non-prose prefix list. Sections whose first non-blank content
        # line is a subheading (`### 1.1 Foo` or `#### 1.1.1 Bar`) were
        # previously counted as prose-recap-compliant, inflating the
        # rate and hiding the real failure mode the recap rule is meant
        # to catch (table-first / list-first / heading-first openings).
        if first_line and not first_line.startswith(("|", "- ", "* ", "1.", "2.", "3.", "#")):
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
        f"  footnotes: {f['n_inline_markers']} inline ({f['density_per_1k_words']}/1k words, target ≥{f['qianfan_target_per_1k']}), "
        f"def-coverage {f['def_coverage_rate'] * 100:.1f}% ({f['n_defined_unique_markers']}/{f['n_unique_markers']} uniques)"
    )
    if f["below_qianfan_target"]:
        lines.append("    ↳ BELOW Qianfan footnote-density floor (≥4/1000)")
    ins = scores["insight_distribution"]
    lines.append(f"  insight distribution ({ins['n_leaves']} leaves):")
    for elem in ("forward_looking", "contrarian", "quant", "alternative"):
        rate = ins["per_element_rate_pct"][elem]
        target = ins["per_element_target_pct"][elem]
        gap = ins["per_element_gap_pct"][elem]
        # Greptile PR #30 round-5 follow-up (2026-05-26): pad the
        # non-compliant `↓` to 2-char display width so the element-name
        # column aligns whether the row passed (`  `) or failed (`↓ `).
        # Pre-fix, failing rows shifted left by one column making the
        # table hard to scan when multiple elements failed.
        marker = "  " if gap >= 0 else "↓ "
        lines.append(f"    {marker}{elem:<16s}: {rate:>5.1f}% (target ≥{target}%, gap {gap:+.1f}%)")
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
