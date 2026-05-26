"""Wave 1 §7.4 (2026-05-26): semantic-depth derivation in
`scripts/p2_qianfan_distance.py`.

Pre-Wave-1, the per-task distance scorer derived `h{N}_total` virtual
fields by summing `md_h{N} + num_h{N}` from `p2_qianfan_profile.
compute_metrics`. That formula misses the most common Lunon / Qianfan
heading shape: `## 4.1.1 Section name` — markdown hash-depth 2 but
semantically depth 3 (three-dot numbering). `_HEADING_MD` matched it as
md_h2; `_HEADING_NUM` (which requires the LINE to start with a digit)
didn't match because of the `##` prefix. Result: a flat-numbered
article with N `## N.N` semantic-H3 headings got reported as N H2.

The Wave 1 fix re-scans headings independently and derives semantic
depth as `max(hash_depth, dot_count + 1)`. These tests pin the
classification per heading shape so a future tweak doesn't silently
re-introduce the hash-only counting.
"""

import sys
from pathlib import Path

# The scorer lives under scripts/; add it to sys.path so we can import the
# semantic-depth helper directly without running the full CLI.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from p2_qianfan_distance import _augment_with_totals, _semantic_depth_counts  # noqa: E402


def test_pure_markdown_heading_depth_matches_hash_count():
    """`## Foo` → semantic H2; `### Foo` → H3; `#### Foo` → H4.
    No numbering present, semantic depth = markdown hash-depth."""
    article = "# Title\n\n## A\n\n### B\n\n### C\n\n#### D\n\n#### E\n"
    counts = _semantic_depth_counts(article)
    assert counts.get(1, 0) == 1  # `# Title`
    assert counts.get(2, 0) == 1  # `## A`
    assert counts.get(3, 0) == 2  # `### B`, `### C`
    assert counts.get(4, 0) == 2  # `#### D`, `#### E`


def test_bare_numbered_heading_depth_from_dot_count():
    """`1 Foo` → H1; `1.1 Foo` → H2; `1.1.1 Foo` → H3; `1.1.1.1 Foo` → H4."""
    article = "1 Intro\n\n1.1 Sub\n\n1.1.1 Leaf\n\n1.1.1.1 Deep\n\n2 Next\n"
    counts = _semantic_depth_counts(article)
    assert counts.get(1, 0) == 2  # `1 Intro`, `2 Next`
    assert counts.get(2, 0) == 1  # `1.1 Sub`
    assert counts.get(3, 0) == 1  # `1.1.1 Leaf`
    assert counts.get(4, 0) == 1  # `1.1.1.1 Deep`


def test_hybrid_heading_uses_max_of_hash_and_dot():
    """`## 4.1.1 Foo` is the canonical Lunon / Qianfan hybrid form. Hash
    depth = 2; dot-count = 2, so dot-derived depth = 3. Semantic depth =
    max(2, 3) = 3. Pre-Wave-1, this was counted as H2 (hash-only), which
    inflated h2_total and made Qianfan's flat-numbered articles look 4×
    H2-heavier than they really were."""
    article = "# Title\n\n## 4 Section\n\n## 4.1 Sub\n\n## 4.1.1 Leaf\n\n## 4.1.1.1 Deep\n\n"
    counts = _semantic_depth_counts(article)
    # `## 4 Section` → max(2, 1) = 2 (h2)
    # `## 4.1 Sub` → max(2, 2) = 2 (h2)
    # `## 4.1.1 Leaf` → max(2, 3) = 3 (h3) — the load-bearing case
    # `## 4.1.1.1 Deep` → max(2, 4) = 4 (h4)
    assert counts.get(1, 0) == 1  # `# Title`
    assert counts.get(2, 0) == 2  # `## 4 Section`, `## 4.1 Sub`
    assert counts.get(3, 0) == 1  # `## 4.1.1 Leaf`
    assert counts.get(4, 0) == 1  # `## 4.1.1.1 Deep`


def test_h5_h6_bucket_to_h4plus():
    """compute_metrics uses `h4plus` (no separate H5/H6); the semantic
    scan must follow the same bucketing so the distance score doesn't
    overweight rare H5/H6 lines."""
    article = "##### Five\n\n###### Six\n\n#### Four\n"
    counts = _semantic_depth_counts(article)
    # All three bucket to depth 4
    assert counts.get(4, 0) == 3


def test_non_heading_lines_ignored():
    """Plain prose, code blocks, lists, and tables MUST NOT be counted
    as headings even if they happen to start with digits."""
    article = (
        "Plain paragraph with some text.\n\n"
        "1. Item one\n2. Item two\n\n"  # ordered list — should NOT count
        "| a | b |\n| - | - |\n| 1 | 2 |\n\n"
        "    indented code block\n\n"
    )
    counts = _semantic_depth_counts(article)
    # Bare ordered-list items DO match `^N\.?\s+\S`, which is a known
    # false-positive for the bare-numbered heading pattern shared with
    # compute_metrics's `_HEADING_NUM`. Pin EXACTLY what we count so a
    # future tightening that excludes list items is a visible behavior
    # change rather than a silent drift.
    assert counts.get(1, 0) == 2  # "1. Item one", "2. Item two" — overcounted
    # Markdown table rows, indented code, prose: all skipped.
    assert counts.get(2, 0) == 0
    assert counts.get(3, 0) == 0


def test_augment_with_article_uses_semantic_scan():
    """When `_augment_with_totals` is called with the article text, the
    h{N}_total fields come from the semantic-depth scan (NOT from the
    pre-Wave-1 md+num sum). This is the path the distance scorer's main
    loop uses."""
    article = "# Title\n\n## 4.1.1 Leaf\n\n## Foo\n"
    # Synthesize a metrics dict as compute_metrics would produce it.
    # Pre-Wave-1 path would give h2_total = md_h2 + num_h2 = 2 + 0 = 2.
    # Wave 1 path gives h2_total = 1 (just `## Foo`), h3_total = 1 (`## 4.1.1 Leaf`).
    m = {"md_h2": 2, "md_h3": 0, "md_h4plus": 0, "num_h2": 0, "num_h3": 0, "num_h4plus": 0}
    out = _augment_with_totals(m, article=article)
    assert out["h2_total"] == 1  # just `## Foo`
    assert out["h3_total"] == 1  # `## 4.1.1 Leaf` correctly recognised as H3
    assert out["h4plus_total"] == 0


def test_augment_without_article_falls_back_to_md_plus_num():
    """For callers that have a metrics dict but not the article text,
    `_augment_with_totals` falls back to the pre-Wave-1 md+num sum.
    This keeps the function usable in test/script contexts that don't
    have the raw article handy, without silently changing behaviour."""
    m = {"md_h2": 5, "md_h3": 10, "md_h4plus": 3, "num_h2": 2, "num_h3": 1, "num_h4plus": 0}
    out = _augment_with_totals(m)  # no article arg
    # Sum of md + num per depth
    assert out["h2_total"] == 7  # 5 + 2
    assert out["h3_total"] == 11  # 10 + 1
    assert out["h4plus_total"] == 3  # 3 + 0
