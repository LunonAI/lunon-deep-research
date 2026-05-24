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

# ---- E1.v2: section-opening framework-recap (table-aware) -----------------
#
# v1 (committed earlier today, see git log) tested at 9.2% compliance because
# the writer chose table-first openings on taxonomy archetypes (id=91 had
# 0/50 sections with prose-recap because every section opened with a markdown
# table directly under the heading). v2 splits compliance into a STRUCTURAL
# gate (first content block must be prose, NOT a table/list) and a SEMANTIC
# gate (recap-or-new-value vocabulary in the prose). Tracks both so we can
# diagnose future failure modes precisely.


# First-line-of-section-body test: does the section open with a markdown
# table row (`|...|`), a bulleted list (`- ` / `* ` / `+ `), or a bare
# heading (`#`)? If yes, the structural gate FAILS — there's no prose
# recap paragraph before the data block.
_TABLE_OR_LIST_LEAD_RE = re.compile(r"^\s*(?:\|[^\n]*\||[-*+]\s+\S|#{1,4}\s+\S)")

_RECAP_TOKENS = re.compile(
    r"(?:building on|extends? the (?:framework|rubric|taxonomy|matrix)|"
    r"using the (?:dimension|rubric|matrix|taxonomy|framework|classification)|"
    r"applied to the (?:framework|rubric|dimensions|matrix|taxonomy)|"
    r"under the (?:framework|rubric|taxonomy)|"
    r"per the (?:framework|rubric|dimensions|taxonomy)|"
    r"with this (?:framework|rubric|taxonomy) in (?:place|hand)|"
    r"within the framework (?:set out|established|introduced)|"
    r"(?:returns? to|revisits?) the (?:framework|rubric|dimensions)|"
    # New-value-statement tokens (Qianfan's "this section adds/operationalizes")
    r"this (?:chapter|section) (?:adds|extends|populates|builds|"
    r"operationalises|operationalizes|catalogues|catalogs|examines|"
    r"records|maps|measures|operationalise|operationalize)|"
    r"the present (?:section|chapter)|"
    # Named-artefact section references (the E1 narrowing post-bonus-audit):
    r"§\s*\d+(?:\.\d+)?(?:'s|s')?\s+(?:framework|rubric|taxonomy|matrix|"
    r"dimensions|four-pillar|three-tier|spine|axis)|"
    r"section\s+\d+(?:\.\d+)?(?:'s|s')?\s+(?:framework|rubric|taxonomy|"
    r"matrix|dimensions)|"
    # ZH equivalents
    r"沿用|延续上述|应用上一节|遵循前述|依据前述|按前文|"
    r"在(?:上述|前述)(?:框架|维度|分类)下?|在前述基础上|"
    r"基于(?:上文|前述|第\d+章)|根据第\d+章|"
    r"本(?:节|章)(?:补充|拓展|添加|建立|应用|延伸|具体化|"
    r"考察|分析|讨论|研究|记录|测量)|"
    r"第\s*\d+\s*(?:节|章)(?:的|所述)?(?:框架|维度|分类|分析|结论))",
    re.IGNORECASE,
)


def e1_section_opening_recap(article: str) -> dict:
    """E1.v2 compliance: structural + semantic two-gate check.

    A section is COMPLIANT iff:
      (structural) first non-heading content line is PROSE — not a markdown
                   table row, not a bulleted list, not another heading.
      (semantic)   the first 700 chars of section body contain a recap or
                   new-value-statement token (broadened token set from v1).

    Both gates tracked separately so we can diagnose failure modes:
      - structural_ok + semantic_ok = compliant (target)
      - structural_ok only = prose lead but no recap vocab (vocab mismatch)
      - semantic_ok only = recap vocab buried after a table-first lead
      - neither = section ignored the directive entirely
    """
    sections = re.split(r"(?=^#{1,3}\s+\S)", article, flags=re.MULTILINE)
    sections = [s for s in sections if s.strip()]
    if len(sections) < 2:
        return {"n_sections": len(sections), "n_compliant": 0, "rate": 0.0, "applicable": False}
    candidates = sections[1:]
    n_compliant = 0
    n_only_structural = 0  # prose-lead but no recap vocab
    n_only_semantic = 0  # recap vocab but table-first
    n_neither = 0
    per_section = []
    for s in candidates:
        body = s.split("\n", 1)[1] if "\n" in s else ""
        body_stripped = body.lstrip("\n").lstrip()
        # LEVEL 1 structural: first content line must be prose (not table /
        # list / nested heading).
        first_line = body_stripped.split("\n", 1)[0] if body_stripped else ""
        is_data_block_lead = bool(_TABLE_OR_LIST_LEAD_RE.match(first_line))
        structural_ok = not is_data_block_lead and bool(first_line)
        # LEVEL 2 semantic: recap-or-purpose vocabulary in first 700 chars
        # of body.
        head = body[:700]
        semantic_ok = bool(_RECAP_TOKENS.search(head))
        compliant = structural_ok and semantic_ok
        if compliant:
            n_compliant += 1
        elif structural_ok:
            n_only_structural += 1
        elif semantic_ok:
            n_only_semantic += 1
        else:
            n_neither += 1
        per_section.append(
            {
                "header": (s.split("\n", 1)[0] or "")[:80],
                "structural_ok": structural_ok,
                "semantic_ok": semantic_ok,
                "compliant": compliant,
            }
        )
    n = len(candidates)
    return {
        "n_sections": n,
        "n_compliant": n_compliant,
        "n_only_structural_ok": n_only_structural,
        "n_only_semantic_ok": n_only_semantic,
        "n_neither": n_neither,
        "rate": round(n_compliant / max(1, n), 3),
        "structural_rate": round((n_compliant + n_only_structural) / max(1, n), 3),
        "semantic_rate": round((n_compliant + n_only_semantic) / max(1, n), 3),
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
        if not r.get("applicable"):
            continue
        # v2 surfaces structural + semantic separately so we can diagnose
        # failure mode (table-first vs vocab-mismatch).
        if "structural_rate" in r:
            print(
                f"  id={r['task_id']:>3}  compliant={r['rate']:>5.2f}  "
                f"struct={r['structural_rate']:>5.2f}  "
                f"sem={r['semantic_rate']:>5.2f}  "
                f"({r['n_compliant']}/{r['n_sections']}; "
                f"struct-only={r['n_only_structural_ok']}, "
                f"sem-only={r['n_only_semantic_ok']}, "
                f"neither={r['n_neither']})"
            )
        else:
            print(f"  id={r['task_id']:>3}  rate={r['rate']:>5.2f}")


if __name__ == "__main__":
    main()
