"""Wave 0 F validation: run cross-ref-aware renumbering against 89 W9 articles
and verify the plan's correctness criterion:

  "For every cross-ref in the rewritten output, the substituted target points
   to the same conceptual section it did before renumbering. Zero broken refs."

We verify by parsing each article's headings (capturing old_num → title), then
running renumber_headings, then parsing post headings (capturing new_num →
title), then iterating over every cross-ref in BOTH pre and post and verifying
that the title that the cross-ref points to is unchanged.

A "broken ref" is a cross-ref whose pre-renumber target title differs from its
post-renumber target title.

Outputs a one-pager at p2_artifacts/F_validation_result.md.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deep_research.pipeline import numbering_fix as nf  # noqa: E402

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
LEADING_NUM_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")
# Use the same substitution regex as the engine — read both the prefix and the
# captured number so we can locate the target after rewriting.
SUB_RE = nf._CROSS_REF_SUB_RE


def parse_headings(text: str) -> dict[str, str]:
    """Return {old_num_str: clean_title} for every H2+ heading with a leading
    number. H1 is excluded — the engine assigns H1 no number (it's the report
    title), so the engine's heading_map never contains H1 entries. To match
    the engine's policy in the validation, we also exclude H1 here.
    If multiple H2+ share an old_num, the LAST occurrence wins — same
    convention as renumber_headings's heading_map.
    """
    out: dict[str, str] = {}
    for m in HEADING_RE.finditer(text):
        hashes = m.group(1)
        if len(hashes) == 1:  # H1 — engine never adds to heading_map.
            continue
        title_raw = m.group(2)
        lead = LEADING_NUM_RE.match(title_raw)
        if not lead:
            continue
        num = lead.group().strip().rstrip(".")
        clean = LEADING_NUM_RE.sub("", title_raw)
        out[num] = clean
    return out


def find_xrefs(text: str) -> list[str]:
    """Return the captured-num for every cross-ref in the body."""
    return [m.group("num") for m in SUB_RE.finditer(text)]


def main() -> int:
    raw_path = ROOT / "p1_artifacts" / "p1_final.jsonl"
    articles = []
    with raw_path.open() as f:
        for line in f:
            d = json.loads(line)
            articles.append(d)
    # Restrict to the 89 W9 scored articles. Use scored_results raw_results.jsonl
    # for the canonical 89-id set; fall back to all 100 if not present.
    # P2_SCORED_PATH env-override makes this reproducible on other machines.
    scored_path_env = os.environ.get("P2_SCORED_PATH")
    scored_path = (
        Path(scored_path_env)
        if scored_path_env
        else Path.home() / "dev/deep_research_bench/results/race/lunon-p1-2026-05-21-final/raw_results.jsonl"
    )
    scored_ids: set | None = None
    if scored_path.exists():
        scored_ids = set()
        with scored_path.open() as f:
            for line in f:
                d = json.loads(line)
                # id field in scored output is int; raw output is str
                scored_ids.add(str(d.get("id", "")))
    else:
        print(
            f"WARNING: scored_path not found ({scored_path}); falling back to all articles. "
            f"Set P2_SCORED_PATH to the harness's raw_results.jsonl to reproduce the 89-W9 result.",
            file=sys.stderr,
        )

    eligible = []
    for d in articles:
        if scored_ids is not None and str(d["id"]) not in scored_ids:
            continue
        eligible.append(d)
    print(f"Total articles in p1_final: {len(articles)}; eligible (scored): {len(eligible)}")

    results = []
    broken_refs = []
    pre_renumber_skipped = 0
    pre_renumber_applied = 0
    n_articles_with_xrefs = 0
    n_xref_total_pre = 0
    n_xref_total_post = 0
    n_xref_rewritten_total = 0
    n_xref_orphaned_total = 0

    for d in eligible:
        article = d["article"]
        # Run the engine's strip + collapse + renumber in order — same as
        # numbering_fix.run() (so we validate against the post-clean state the
        # writer actually emits).
        pre_clean, _ = nf.strip_stage_directions(article)
        pre_clean, _ = nf.collapse_empty_sections(pre_clean)
        pre_map = parse_headings(pre_clean)
        pre_xrefs = find_xrefs(pre_clean)
        if pre_xrefs:
            n_articles_with_xrefs += 1
        n_xref_total_pre += len(pre_xrefs)

        post, stats = nf.renumber_headings(pre_clean)
        post_map = parse_headings(post)
        post_xrefs = find_xrefs(post)
        n_xref_total_post += len(post_xrefs)
        n_xref_rewritten_total += stats["cross_refs_rewritten"]
        n_xref_orphaned_total += stats["cross_refs_orphaned"]
        if stats["applied"]:
            pre_renumber_applied += 1
        else:
            pre_renumber_skipped += 1

        # Build the inverse map: heading_map old_num → new_num from the engine.
        old_to_new = stats.get("heading_map", {})
        # For each pre-cross-ref, determine: did its target survive correctly?
        article_broken = []
        for i, pre_num in enumerate(pre_xrefs):
            if pre_num in pre_map:
                pre_title = pre_map[pre_num]
                # The post xrefs list has the same length and order (the regex
                # iterates left-to-right deterministically; substitutions don't
                # change the count of cross-refs).
                if i >= len(post_xrefs):
                    article_broken.append({"i": i, "issue": "xref dropped from post"})
                    continue
                post_num = post_xrefs[i]
                post_title = post_map.get(post_num)
                if post_title != pre_title:
                    article_broken.append(
                        {
                            "i": i,
                            "pre_num": pre_num,
                            "pre_title": pre_title,
                            "post_num": post_num,
                            "post_title": post_title or "(orphan)",
                        }
                    )
            else:
                # Orphan in pre — the cross-ref didn't match any heading.
                # We expect engine to leave it alone (orphan in post too).
                if i < len(post_xrefs) and post_xrefs[i] != pre_num:
                    article_broken.append(
                        {
                            "i": i,
                            "issue": "orphan rewritten",
                            "pre_num": pre_num,
                            "post_num": post_xrefs[i],
                        }
                    )

        results.append(
            {
                "id": d["id"],
                "n_headings": len(pre_map),
                "n_xrefs_pre": len(pre_xrefs),
                "n_xrefs_post": len(post_xrefs),
                "rewritten": stats["cross_refs_rewritten"],
                "orphaned": stats["cross_refs_orphaned"],
                "broken": article_broken,
                "old_to_new_size": len(old_to_new),
            }
        )
        if article_broken:
            broken_refs.append(
                {
                    "id": d["id"],
                    "broken": article_broken,
                }
            )

    print("\n=== F validation summary ===")
    print(f"Eligible articles:               {len(eligible)}")
    print(f"Articles with ≥1 cross-ref:      {n_articles_with_xrefs}")
    print(f"  (eligibility rate for F lift): {n_articles_with_xrefs / max(1, len(eligible)) * 100:.1f}%")
    print(f"Total cross-refs in pre-bodies:  {n_xref_total_pre}")
    print(f"Total cross-refs in post-bodies: {n_xref_total_post}")
    print(f"Total rewritten by engine:       {n_xref_rewritten_total}")
    print(f"Total orphaned by engine:        {n_xref_orphaned_total}")
    print(f"Articles with broken refs:       {len(broken_refs)}")
    if broken_refs:
        print("\nBroken-ref detail (first 10):")
        for b in broken_refs[:10]:
            print(f"  id={b['id']}: {b['broken'][:3]}")
        return 1
    print("\nF correctness invariant: PASSED. Zero broken cross-refs across the eligible set.")

    # Write the result doc
    out_path = ROOT / "p2_artifacts" / "F_validation_result.md"
    with out_path.open("w") as f:
        f.write("# Wave 0 F — Cross-Reference-Aware Renumbering Validation\n\n")
        f.write("**Date:** 2026-05-22\n")
        f.write("**Status:** PASSED — zero broken cross-refs across all W9-scored articles.\n\n")
        f.write("## Plan correctness criterion\n\n")
        f.write(
            'Plan §3 F: "For every cross-ref in the rewritten output, the substituted target points '
            'to the same conceptual section it did before renumbering. Zero broken refs."\n\n'
        )
        f.write("## Result\n\n")
        f.write(f"- Eligible (W9-scored) articles: **{len(eligible)}**\n")
        f.write(f"- Articles with ≥1 cross-ref in body: **{n_articles_with_xrefs}**\n")
        f.write(
            f"- Eligibility rate (articles where F's lift matters): "
            f"**{n_articles_with_xrefs / max(1, len(eligible)) * 100:.1f}%**\n"
        )
        f.write(f"- Total cross-refs in pre-renumber bodies: **{n_xref_total_pre}**\n")
        f.write(f"- Total cross-refs in post-renumber bodies: **{n_xref_total_post}**\n")
        f.write(f"- Total cross-refs rewritten by engine: **{n_xref_rewritten_total}**\n")
        f.write(f"- Total cross-refs orphaned (no mapping target): **{n_xref_orphaned_total}**\n")
        f.write(f"- Articles with broken refs after renumber: **{len(broken_refs)}**\n\n")
        f.write("## Eligibility-bounded lift envelope (plan §3 F)\n\n")
        eligibility_rate = n_articles_with_xrefs / max(1, len(eligible))
        f.write(
            f"Pre-F path skipped renumber when cross-refs were detected — "
            f"approximately **{eligibility_rate * 100:.0f}%** of W9 articles. "
            f"Post-F, that subset gets renumbered AND cross-refs preserved. "
            f"The per-eligible-article ΔRead estimate of +0.005/+0.012/+0.022 "
            f"(plan §3 F) applies to roughly the **{n_articles_with_xrefs}** "
            f"affected articles in any future W-run.\n\n"
        )
        f.write("## Per-article rewrite counts (top 10 by activity)\n\n")
        results.sort(key=lambda r: -r["rewritten"])
        f.write("| id | headings w/ numbers | pre xrefs | post xrefs | rewritten | orphaned |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in results[:10]:
            f.write(
                f"| {r['id']} | {r['n_headings']} | {r['n_xrefs_pre']} | "
                f"{r['n_xrefs_post']} | {r['rewritten']} | {r['orphaned']} |\n"
            )
        f.write("\n## Method\n\n")
        f.write(
            "For each W9-scored article: parse pre-renumber headings → "
            "build {old_num: clean_title}. Find all in-body cross-refs (pre_xrefs). "
            "Run `numbering_fix.renumber_headings`. Parse post-renumber headings → "
            "build {new_num: clean_title}. Find all post-cross-refs. For each cross-ref index, "
            "verify the title that the pre_num pointed to equals the title that the post_num "
            "points to. Mismatch = broken ref. Orphan (pre_num not in pre_map) is acceptable IF "
            "the engine left it alone (post_num == pre_num).\n"
        )
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
