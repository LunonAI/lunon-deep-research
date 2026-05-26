"""Per-task Qianfan-distance scorer.

For each requested task id, computes structural metrics on the Lunon article
+ the Qianfan reference article, surfaces the gap on every metric, and rolls
up a single "Qianfan distance" score that measures how far our output sits
from the #1-leaderboard target.

Purpose: cheap iteration feedback BETWEEN runs of the expensive RACE
scorer. Adjust a prompt → smoke one task → run this → see if the change
moved us toward Qianfan WITHOUT spending $25-30 on the GPT-5.5 judge.

Reuses `compute_metrics` from `scripts/p2_qianfan_profile` so the metric
shapes here are bit-for-bit identical to the corpus-profile analysis the
handoff doc + indistinguishability_findings.md were built on. Do NOT
re-implement metric logic here — extend that module instead so the corpus
profile and the per-task distance always agree.

Usage:
    # Single task, Lunon side is one .jsonl entry, Qianfan side is
    # auto-resolved from transfer/qianfan-dr-questions/<id>*.docx (textutil
    # → /tmp/q<id>.txt) or transfer/qianfan-dr-questions/<id>*.txt directly.
    python3 scripts/p2_qianfan_distance.py \\
        --lunon-jsonl p2_artifacts/parity_smoke_id91.jsonl \\
        --ids 91

    # Multiple ids, JSON output:
    python3 scripts/p2_qianfan_distance.py \\
        --lunon-jsonl p2_artifacts/option_a_dev4.jsonl \\
        --ids 8,14,56,91 \\
        --json-out p2_artifacts/dev4_qianfan_distance.json

Exit codes:
    0 = ran successfully (regardless of how close to Qianfan we are)
    2 = no Lunon entry found for any requested id
    3 = no Qianfan reference found for any requested id

Anti-hardcode discipline: NO target word counts, dim weights, or "good
enough" thresholds are baked in. The script only reports raw ratios +
the |log| distance. Pass/fail decisions belong in p2_paired_delta.py
(RACE-grounded) or in human inspection — not in this read-only diagnostic.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Reuse the corpus-profile metric extraction so per-task distance and
# corpus rollup always agree on what each metric MEANS.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from p2_qianfan_profile import compute_metrics  # noqa: E402

_REPO_ROOT = _HERE.parent
# The qianfan reference corpus lives under transfer/ (gitignored on this
# Mac, available via the cross-machine handoff bundle). Fall back to the
# repo root in case a future layout puts the .txt corpus there.
_QIANFAN_DIRS = [
    _REPO_ROOT / "transfer" / "qianfan-dr-questions",
    _REPO_ROOT / "qianfan-dr-questions",
]

# Metric importance weighting for the rollup distance score. Weights here
# are calibrated to the gaps that the qianfan_corpus_profile.md identified
# as RACE-relevant; see `_compute_distance` for the math. Adjusting these
# only changes the ROLLUP score — every individual metric ratio is still
# reported unweighted so the operator can inspect any axis directly.
_DISTANCE_WEIGHTS = {
    # Length + depth are the dominant Qianfan signal (handoff doc: 4.6×
    # corpus-mean gap on length; ~57% of weighted RACE gap is Insight
    # which scales with depth).
    "n_length": 3.0,
    # Heading totals (md_* + num_*) — Qianfan uses NUMBERED headings
    # (`1.1.1`) while Lunon uses MARKDOWN (`### Title`), so neither raw
    # field alone tells the real story. _augment_with_totals (below)
    # adds these virtual fields keyed by `h2_total`, `h3_total`,
    # `h4plus_total` to each metric dict before this lookup runs.
    "h2_total": 2.0,
    "h3_total": 2.5,  # the binding depth dim per id=56 smoke (1.4 H3/H2 vs 6.9)
    "h4plus_total": 1.5,
    "n_paragraphs": 1.0,
    # Citation density is the second-largest gap per id=56 smoke (0 vs 326).
    "n_footnotes": 2.5,
    "n_named_sources": 1.0,
    # Stylistic markers — secondary but informative.
    "em_dashes": 1.0,
    "contrarian_count": 1.0,
    "quant_range_count": 1.0,
    "n_table_blocks": 0.5,  # paste-fragile per handoff doc §7.2
}


# Wave 1 §7.4 (2026-05-26): semantic-depth heading scan.
#
# Pre-Wave-1 derivation summed `md_h{N} + num_h{N}` to produce the
# `h{N}_total` virtual fields. That misses the most common Lunon /
# Qianfan heading shape: `## 4.1.1 Section name` — markdown hash-depth 2
# but semantically depth 3 (three-dot numbering). `_HEADING_MD` matches
# it as md_h2; `_HEADING_NUM` (which requires the line to START with a
# digit) doesn't match because of the `##` prefix. Result: a flat-
# numbered article with 83 `## N.N` semantic-H3 headings (Qianfan id=91)
# gets reported as 83 H2. The distance comparison vs Lunon's hierarchical
# output then shows wildly wrong ratios for h2_total / h3_total.
#
# Fix: re-scan the article INDEPENDENTLY of compute_metrics's md / num
# splits, and derive each heading's SEMANTIC depth as
# `max(hash_depth, dot_count + 1)`. Apples-to-apples on both sides.
_SEMANTIC_HEADING_RE = re.compile(
    r"^(?P<hashes>#{1,6})?\s*(?P<num>\d+(?:\.\d+){0,4})?\.?\s+\S",
    re.MULTILINE,
)


def _semantic_depth_counts(article: str) -> dict[int, int]:
    r"""Walk every heading-shaped line and bucket by semantic depth.

    A heading-shaped line is either:
      - markdown form `#+\s+\S`           (semantic depth = number of `#`)
      - numbered form `N(\.N)*\s+\S`      (semantic depth = dot_count + 1)
      - hybrid   form `#+\s+N(\.N)*\s+\S` (semantic depth = max of the two)

    Returns {depth: count} where depth is in [1, 5+]. Depths >= 4 are
    bucketed under `4` for parity with compute_metrics's `h4plus`
    convention (no separate H5/H6 tracking — the corpus has none).
    """
    counts: dict[int, int] = {}
    for line in article.splitlines():
        # Markdown prefix (optional, up to 6 hashes).
        md_match = re.match(r"^(#{1,6})\s+(.*)$", line)
        md_depth = 0
        rest = line
        if md_match:
            md_depth = len(md_match.group(1))
            rest = md_match.group(2)
        # Numbered prefix on what remains (after stripping `## `). Tolerate
        # optional trailing dot (`## 4.1.1.`) per corpus convention.
        num_match = re.match(r"^(\d+(?:\.\d+){0,4})\.?\s+\S", rest)
        num_depth = 0
        if num_match:
            num_depth = num_match.group(1).count(".") + 1
        # A line is a heading if EITHER a markdown prefix OR a leading
        # numbered token was matched on a non-empty body. Bare numbered
        # headings (`4.1.1 Section`) get caught via num_depth > 0.
        if md_depth == 0 and num_depth == 0:
            continue
        # md_depth==0 + num_depth>0 is "bare numbered" — counts at num_depth.
        # Otherwise semantic = max(md_depth, num_depth).
        depth = max(md_depth, num_depth) if md_depth else num_depth
        bucket = min(depth, 4)  # H4 / H5 / H6 all bucket to 4
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def _augment_with_totals(m: dict, article: str | None = None) -> dict:
    """Add `h{N}_total` virtual fields giving SEMANTIC heading depth.

    When `article` is provided (Wave 1 §7.4 path), the totals come from a
    fresh semantic-depth scan that correctly classifies `## 4.1.1`-style
    headings as semantic H3 (not H2 as the hash-prefix-only derivation
    would). When `article` is omitted, falls back to the pre-Wave-1
    md+num sum for backward compatibility with any caller that already
    has metrics but not the source text.
    """
    if article is not None:
        counts = _semantic_depth_counts(article)
        m["h2_total"] = counts.get(2, 0)
        m["h3_total"] = counts.get(3, 0)
        m["h4plus_total"] = counts.get(4, 0)
    else:
        m["h2_total"] = m.get("md_h2", 0) + m.get("num_h2", 0)
        m["h3_total"] = m.get("md_h3", 0) + m.get("num_h3", 0)
        m["h4plus_total"] = m.get("md_h4plus", 0) + m.get("num_h4plus", 0)
    return m


def _load_lunon_by_id(jsonl_path: Path) -> dict[str, str]:
    """Read a Lunon adapter-output jsonl and return {id: article_body}."""
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


def _resolve_qianfan_path(task_id: str) -> Path | None:
    """Find the Qianfan reference file for a task id. Tries .txt first
    (faster, no shell-out), falls back to .docx (textutil → /tmp scratch)."""
    for base in _QIANFAN_DIRS:
        if not base.exists():
            continue
        # Pattern: filenames begin with the task id then a separator
        # (`.`, `-`, ` `) and the topic. Examples:
        #   "8. 能否给我提供一份详尽的报告..."
        #   "56 - Is there a general method..."
        #   "91 - I would like a detailed analysis..."
        candidates = []
        for ext in (".txt", ".docx"):
            candidates.extend(sorted(base.glob(f"{task_id} *{ext}")))
            candidates.extend(sorted(base.glob(f"{task_id}. *{ext}")))
            candidates.extend(sorted(base.glob(f"{task_id}-*{ext}")))
        # Prefer .txt over .docx (no conversion needed).
        for c in candidates:
            if c.suffix == ".txt":
                return c
        for c in candidates:
            if c.suffix == ".docx":
                return c
    return None


def _read_qianfan_body(path: Path) -> str:
    """Return the article body, converting .docx → .txt via textutil
    if needed. Pure-`.txt` path is a simple read."""
    if path.suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    if path.suffix != ".docx":
        raise ValueError(f"unsupported qianfan reference format: {path.suffix}")
    if not shutil.which("textutil"):
        raise RuntimeError(
            "textutil not found on $PATH — required to convert .docx Qianfan "
            "references. On macOS textutil ships with the OS; on Linux you'd "
            "need to pre-convert the .docx files to .txt."
        )
    # Write to a per-run tempfile so we don't litter /tmp on long sessions.
    with tempfile.NamedTemporaryFile(mode="r", suffix=".txt", delete=False) as fh:
        out_path = fh.name
    try:
        subprocess.run(
            ["textutil", "-convert", "txt", "-output", out_path, str(path)],
            check=True,
            capture_output=True,
        )
        return Path(out_path).read_text(encoding="utf-8", errors="replace")
    finally:
        try:
            Path(out_path).unlink()
        except FileNotFoundError:
            pass


def _ratio(lunon: float, qianfan: float) -> float:
    """Return lunon/qianfan ratio. Guards against div-by-zero (returns
    `inf` when Lunon is positive but Qianfan is zero, `0.0` when both are
    zero — those edge cases are reported separately from numeric ratios)."""
    if qianfan == 0 and lunon == 0:
        return 0.0
    if qianfan == 0:
        return math.inf
    return lunon / qianfan


def _verdict(ratio: float) -> str:
    """Human-readable verdict on a single-metric ratio. Bands chosen so
    "≈ Qianfan" is the 0.7-1.5× envelope (within ~50% either way);
    anything outside is a gap worth investigating."""
    if ratio == 0.0:
        return "EMPTY"  # both sides have 0 of this metric
    if ratio == math.inf:
        return "OVER (Q=0)"
    if ratio < 0.25:
        return "SHORT 4×+"
    if ratio < 0.7:
        return "short"
    if ratio <= 1.5:
        return "≈ Qianfan"
    if ratio <= 4.0:
        return "over"
    return "OVER 4×+"


def _compute_distance(lunon_m: dict, qianfan_m: dict) -> float:
    """Single roll-up: weighted mean of |log(lunon/qianfan)| over the
    metrics that matter for RACE-grounded Qianfan parity. 0.0 = identical
    on every weighted metric; higher = farther from Qianfan.

    Using log-ratio (vs raw ratio difference) gives symmetric treatment:
    a 4×-short metric and a 4×-over metric contribute equally. This
    matches the diagnostic intent — both directions are equally "not
    Qianfan-shaped". The score is unbounded above but typically lands in
    [0.0, ~3.0] for our corpus."""
    total_weight = 0.0
    total_score = 0.0
    for key, weight in _DISTANCE_WEIGHTS.items():
        lunon_v = float(lunon_m.get(key, 0))
        qianfan_v = float(qianfan_m.get(key, 0))
        # Skip metrics where both are zero (no signal either way).
        if lunon_v == 0 and qianfan_v == 0:
            continue
        # For one-sided zero, use a sentinel large distance instead of
        # log(inf) — bounded so a single empty metric doesn't dominate.
        if lunon_v == 0 or qianfan_v == 0:
            total_score += weight * 3.0
            total_weight += weight
            continue
        total_score += weight * abs(math.log(lunon_v / qianfan_v))
        total_weight += weight
    return total_score / total_weight if total_weight else 0.0


def _render_human(task_id: str, lunon_m: dict, qianfan_m: dict, distance: float) -> str:
    """Render a per-task table for stdout — metric | lunon | qianfan | ratio | verdict."""
    lines = []
    lines.append(f"\n### Task {task_id} — Qianfan distance: {distance:.3f}")
    lines.append("(0.0 = identical on weighted metrics; ~1.0 ≈ one e-fold off on avg)")
    lines.append("")
    header = f"{'metric':<22} {'lunon':>10} {'qianfan':>10} {'ratio':>8}  verdict"
    lines.append(header)
    lines.append("-" * len(header))
    # Sort by importance (matches _DISTANCE_WEIGHTS keys order — weighted
    # metrics first, then unweighted-but-still-informative metrics after).
    weighted_keys = list(_DISTANCE_WEIGHTS.keys())
    other_keys = sorted(
        k for k in lunon_m.keys() if k not in weighted_keys and isinstance(lunon_m.get(k), (int, float))
    )
    for key in weighted_keys + other_keys:
        lunon_v = lunon_m.get(key)
        qianfan_v = qianfan_m.get(key)
        if not isinstance(lunon_v, (int, float)) or not isinstance(qianfan_v, (int, float)):
            continue
        ratio = _ratio(lunon_v, qianfan_v)
        ratio_str = "inf" if ratio == math.inf else f"{ratio:>6.2f}×"
        weight_marker = "*" if key in _DISTANCE_WEIGHTS else " "
        lines.append(f"{weight_marker}{key:<21} {lunon_v:>10.0f} {qianfan_v:>10.0f} {ratio_str:>8}  {_verdict(ratio)}")
    lines.append("(* = metric contributes to the rollup distance score)")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--lunon-jsonl",
        required=True,
        type=Path,
        help="Adapter-output jsonl (one row per task: {id, prompt, article}).",
    )
    ap.add_argument(
        "--ids",
        required=True,
        help="Comma-separated task ids to score (must exist in lunon-jsonl and qianfan-dr-questions/).",
    )
    ap.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path for machine-readable per-task metrics + ratios + distance.",
    )
    args = ap.parse_args()

    requested_ids = [s.strip() for s in args.ids.split(",") if s.strip()]
    if not requested_ids:
        sys.exit("error: --ids must list at least one task id")

    lunon_by_id = _load_lunon_by_id(args.lunon_jsonl)
    if not any(tid in lunon_by_id for tid in requested_ids):
        print(
            f"error: none of the requested ids {requested_ids} were found in {args.lunon_jsonl}",
            file=sys.stderr,
        )
        sys.exit(2)

    per_task: dict[str, dict] = {}
    any_qianfan_found = False
    for tid in requested_ids:
        lunon_article = lunon_by_id.get(tid)
        if not lunon_article:
            print(f"\n### Task {tid} — SKIPPED (no Lunon article in {args.lunon_jsonl.name})", file=sys.stderr)
            continue
        qianfan_path = _resolve_qianfan_path(tid)
        if qianfan_path is None:
            print(
                f"\n### Task {tid} — SKIPPED (no Qianfan reference found in {_QIANFAN_DIRS[0]})",
                file=sys.stderr,
            )
            continue
        any_qianfan_found = True
        try:
            qianfan_body = _read_qianfan_body(qianfan_path)
        except (RuntimeError, subprocess.CalledProcessError) as e:
            print(f"\n### Task {tid} — SKIPPED ({type(e).__name__}: {e})", file=sys.stderr)
            continue

        lunon_m = _augment_with_totals(compute_metrics(lunon_article), article=lunon_article)
        qianfan_m = _augment_with_totals(compute_metrics(qianfan_body), article=qianfan_body)
        distance = _compute_distance(lunon_m, qianfan_m)
        per_task[tid] = {
            "lunon_metrics": lunon_m,
            "qianfan_metrics": qianfan_m,
            "qianfan_ref_path": str(qianfan_path),
            "distance": distance,
        }
        print(_render_human(tid, lunon_m, qianfan_m, distance))

    if not any_qianfan_found:
        sys.exit(3)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps({"tasks": per_task, "weights": _DISTANCE_WEIGHTS}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n[wrote] {args.json_out}", file=sys.stderr)

    if per_task:
        rollup = sum(t["distance"] for t in per_task.values()) / len(per_task)
        print(f"\n### Mean Qianfan distance across {len(per_task)} task(s): {rollup:.3f}")


if __name__ == "__main__":
    main()
