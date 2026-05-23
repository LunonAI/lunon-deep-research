"""Per-experiment compliance check: did the prompt change actually produce
the intended STRUCTURAL change in writer output?

This is the FREE signal that runs before any LLM-judge call. Use it to
catch prompt-isn't-being-followed cases (where the writer ignored the
new directive) without spending $50+ on full evaluation.

Each experiment registers a `compliance_check(article) -> dict` function.
The CLI runs it across all articles in a jsonl and reports per-task
compliance + aggregate fire rate.

Usage:
  python3 scripts/p2_e_compliance.py \\
    --experiment e1_section_opening_recap \\
    --jsonl p2_artifacts/e1_articles.jsonl \\
    --out p2_artifacts/e1_compliance.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable
from pathlib import Path

# ---- E1: section-opening framework-recap directive ------------------------


_SECTION_HEADER_RE = re.compile(r"^(#{1,3}|^\d+(?:\.\d+)?)\s+\S", re.MULTILINE)
# Tokens the writer uses when recapping a previously-established framework.
# Calibrated against Qianfan corpus: openings like "Building on the
# framework introduced in §1...", "Using the dimension matrix from
# Chapter 1...", "Applied to the rubric set out above, ...".
_RECAP_TOKENS = re.compile(
    r"(?:building on|extends? the framework|using the (?:dimension|rubric|matrix)|"
    r"applied to the (?:framework|rubric|dimensions)|"
    r"under the (?:framework|rubric)|"
    r"per the (?:framework|rubric|dimensions)|"
    r"using the (?:taxonomy|classification)|"
    r"with this (?:framework|rubric|taxonomy) in (?:place|hand)|"
    # ZH equivalents
    r"沿用|延续上述|应用上一节|遵循前述|依据前述|按前文|"
    r"在上述框架下|在前述基础上|基于上文|根据第\d+章)",
    re.IGNORECASE,
)
# Where a section opens by stating what the section ADDS (also rewarded).
_SECTION_PURPOSE_TOKENS = re.compile(
    r"(?:this (?:chapter|section) (?:adds|extends|populates|builds|operationalises|operationalizes)|"
    r"本(?:节|章)(?:补充|拓展|添加|建立|应用|延伸|具体化)|"
    r"the present (?:section|chapter))",
    re.IGNORECASE,
)


def e1_section_opening_recap(article: str) -> dict:
    """E1 compliance: each non-§1 section opens with a recap OR explicit
    purpose statement (Qianfan rhetorical pattern, methodology_deep §1)."""
    # Split into sections by H2/H3 headers (Markdown only; numbered prefixes
    # caught downstream).
    sections = re.split(r"(?=^#{1,3}\s+\S)", article, flags=re.MULTILINE)
    sections = [s for s in sections if s.strip()]
    if len(sections) < 2:
        return {"n_sections": len(sections), "n_with_recap": 0, "rate": 0.0, "applicable": False}
    # Skip first section (it's the article title or §1).
    candidates = sections[1:]
    n_with_recap = 0
    per_section = []
    for s in candidates:
        head = s[:600]  # first ~600 chars of section
        has_recap = bool(_RECAP_TOKENS.search(head))
        has_purpose = bool(_SECTION_PURPOSE_TOKENS.search(head))
        if has_recap or has_purpose:
            n_with_recap += 1
        per_section.append(
            {
                "header": (s.split("\n", 1)[0] or "")[:80],
                "has_recap": has_recap,
                "has_purpose": has_purpose,
            }
        )
    return {
        "n_sections": len(candidates),
        "n_with_recap": n_with_recap,
        "rate": round(n_with_recap / max(1, len(candidates)), 3),
        "applicable": True,
        "per_section": per_section,
    }


# ---- registry -------------------------------------------------------------


_REGISTRY: dict[str, Callable[[str], dict]] = {
    "e1_section_opening_recap": e1_section_opening_recap,
}


# ---- CLI ------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--experiment",
        required=True,
        choices=sorted(_REGISTRY.keys()),
        help="which experiment's compliance pattern to apply",
    )
    ap.add_argument("--jsonl", required=True, help="adapter output jsonl to audit")
    ap.add_argument("--out", required=True, help="output JSON path with per-task compliance")
    args = ap.parse_args()

    check = _REGISTRY[args.experiment]
    rows = []
    rates = []
    for line in Path(args.jsonl).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        article = d.get("article", "")
        result = check(article)
        result["task_id"] = d.get("id")
        rows.append(result)
        if result.get("applicable"):
            rates.append(result.get("rate", 0))

    aggregate = {
        "experiment": args.experiment,
        "n_articles": len(rows),
        "mean_rate": round(sum(rates) / max(1, len(rates)), 3),
        "per_article": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(aggregate, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[compliance] {args.experiment}: mean compliance rate = {aggregate['mean_rate']}")
    for r in rows:
        if r.get("applicable"):
            print(f"  id={r['task_id']:>3}  rate={r['rate']:>5.2f}  sections={r['n_with_recap']}/{r['n_sections']}")


if __name__ == "__main__":
    main()
