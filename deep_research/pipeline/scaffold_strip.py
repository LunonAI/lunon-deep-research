"""Phase 1 A2 (2026-06-04): deterministic meta-scaffolding strip.

Qianfan #1 articles carry ~0 meta-scaffolding sections (full-100 corpus); ours
emit 3-9 per article: per-chapter recaps (本章小结/本章综合), report roadmaps
(报告路线图/章节导读/章节导览), reading-path nav (§N→§M阅读路径/各章…映射), and
source-credibility-grading preambles (来源可信度分级). The GPT-5.5 judge penalizes
these as "层级过多/重复小节" — a top readability loss across all dev6 tasks.

This removes whole heading-delimited meta sections by TITLE match. It runs BEFORE
footnote_normalize/numbering_fix so (a) any `[^N]` markers inside a removed
section become unused defs that footnote_normalize auto-drops (no orphans) and
(b) numbering_fix renumbers the heading tree to close the gap left behind.

Contract (mirrors the other deterministic post-passes): pure
`(article, *, language) -> (article, stats)`, fail-soft (returns input unchanged
on any error), idempotent. NEVER removes an H1 chapter (only H2+ subsections) and
never matches inside a fenced code block.
"""

from __future__ import annotations

import re

# Title-anchored meta-scaffold patterns, matched against the heading TITLE text
# AFTER the leading "N.M"/"§" numbering is stripped. Each alternative is a
# distinctive scaffold phrase that does not occur in a substantive chapter title.
_SCAFFOLD_TITLE_RE = re.compile(
    r"本[章节](?:小结|总结|综合|回顾|要点|概览|总览)|小结与展望|阶段性小结"
    r"|报告路线图|章节路线图|路线图与|章节导航|章节导读|章节导览|报告导航|阅读导航"
    r"|阅读路径|阅读路线|阅读指南|阅读地图"
    r"|各章.{0,8}映射|交付物映射|章节映射|研究问题映射|章节速览"
    r"|来源可信度分级|可信度分级|可信度说明"
)
_LEAD_NUM_RE = re.compile(r"^\s*(?:§\s*)?[\d.]+[ \t]*[、.]?[ \t]*")
_FENCE_RE = re.compile(r"^[ \t]*(?:```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
# Citation-safety: a candidate scaffold section with more than this many citation
# markers is treated as content (e.g. a real source/credibility list) and kept.
_CITE_RE = re.compile(r"\[\^[A-Za-z0-9._-]+\]")
_MAX_SCAFFOLD_CITES = 12


def _heading_lines(text: str) -> list[tuple[int, int, str]]:
    """(char_start, level, title) for real ATX headings, skipping fenced code."""
    out: list[tuple[int, int, str]] = []
    pos = 0
    in_fence = False
    for line in text.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            m = _HEADING_RE.match(line)
            if m:
                out.append((pos, len(m.group(1)), m.group(2)))
        pos += len(line)
    return out


def strip_meta_sections(article: str, *, language: str | None = None) -> tuple[str, dict]:
    stats: dict = {"sections_removed": 0, "chars_removed": 0, "titles": []}
    if not isinstance(article, str) or not article.strip():
        return article, stats
    try:
        heads = _heading_lines(article)
        if not heads:
            return article, stats
        spans: list[tuple[int, int, str]] = []
        for i, (start, lvl, title) in enumerate(heads):
            if lvl < 2:
                continue  # never remove an H1 chapter
            bare = _LEAD_NUM_RE.sub("", title).strip()
            if not _SCAFFOLD_TITLE_RE.search(bare):
                continue
            # section span = heading start → next heading of same-or-shallower level
            end = len(article)
            for j in range(i + 1, len(heads)):
                if heads[j][1] <= lvl:
                    end = heads[j][0]
                    break
            # Citation-safety guard: a genuine meta-scaffold recap/roadmap carries
            # few/no citations; a section titled e.g. "数据来源清单与可信度分级" can hold
            # real sources. Never strip a citation-heavy section (would lose
            # references). Pure-scaffold sections are unaffected.
            if len(_CITE_RE.findall(article[start:end])) > _MAX_SCAFFOLD_CITES:
                continue
            spans.append((start, end, title))
        if not spans:
            return article, stats
        # Drop spans nested inside an already-selected (shallower) span so a
        # roadmap H2 with scaffold H3 children is removed exactly once.
        spans.sort()
        merged: list[tuple[int, int, str]] = []
        for s, e, t in spans:
            if merged and s < merged[-1][1]:
                continue
            merged.append((s, e, t))
        out = article
        for s, e, t in sorted(merged, reverse=True):
            stats["chars_removed"] += e - s
            stats["titles"].append(t[:48])
            out = out[:s] + out[e:]
        stats["sections_removed"] = len(merged)
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out, stats
    except Exception:  # noqa: BLE001 — post-pass must never break the run
        return article, stats
