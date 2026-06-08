"""Readability rewrite — the validated post-generation lever (2026-06-08).

WHY THIS EXISTS / WHAT IT DOES
  The full-100 GPT-5.5 RACE measurement showed our sole losing dim was
  Readability (0.427 < 0.5): our reports are 5-6x longer than the reference the
  judge prefers, and the harness cleaner butchers long ZH. The validated fix
  (overall 0.527 -> 0.540, readability 0.427 -> 0.51, BEATS the #1 reference's 0.480)
  is a single WHOLE-ARTICLE rewrite that collapses the bloated multi-chapter
  draft into a tight, reference-length, highly-readable report while preserving
  facts/numbers/citations. Aggressive whole-article rewriting beat every gentler
  variant (per-chapter condense, scaffold-strip, renumber) and GPT-5.5-vs-Opus
  (Opus won overall). Higher-effort GENERATION did NOT help (substance is
  content-bound) — so this rewrite is the lever, not engine effort.

  Previously this lived in throwaway `scripts/maxread_*.py` applied by hand AFTER
  generation. This module makes it a first-class pipeline stage so every
  `deep_research()` run produces the readable version natively.

PLACEMENT (orchestrate): runs AFTER refiner/validation/zh_writer_pass (the last
  content stages) and BEFORE the deterministic cleanup chain (xref_repair,
  footnote_normalize, numbering_fix, cjk_despace) — so those passes re-normalize
  the rewritten article's citations + heading numbers (better FACT than the
  hand-run scripts, which skipped them).

SAFETY: fail-soft (returns the original draft on any error / guard trip), so it
  can never break a completed run. Guards revert on: empty output, growth
  (>1.05x = didn't condense), catastrophic over-summarization (<0.10x), or loss
  of the numeric-spine headline figure.

Env: DR_READABILITY_REWRITE=off kills it; role/model via DR_ROLE_READABILITY_REWRITER.
"""

from __future__ import annotations

import re

from .. import config, llm

_MARKER_RE = re.compile(r"\[\^[^\]]+\]")
_NUM_RE = re.compile(r"\d[\d,.]*")
_OUT_TOKEN_BUDGET = 32_000
_GUARD_LO = 0.10  # below this fraction of the original -> summarized away -> revert
_GUARD_HI = 1.05  # at/above original length -> didn't condense -> revert

_SYS_EN = (
    "You are a top research analyst. Rewrite the report below to MAXIMIZE readability as judged "
    "against a concise reference report: crystal-clear structure, smooth logical flow, focused "
    "well-segmented paragraphs, scannable bold key points, clean sequential headings (<=2 levels), "
    "native professional register. PRIORITIZE clarity over exhaustive coverage — shorten aggressively "
    "(aim ~55-75k chars). Preserve the central findings, the key numbers/data, and retain as many "
    "distinct [^N] citation markers as you reasonably can on the claims they support; cut sprawl, "
    "redundancy, deep nesting, meta-scaffolding (roadmaps/summaries), and any leaked internal tokens. "
    "Output ONLY the report markdown — no preamble, no commentary, no code fence."
)
_SYS_ZH = (
    "你是顶尖研究分析师。把下面的报告改写为【可读性最大化】版本（对标一篇简洁的参考报告评判）："
    "结构极清晰、逻辑顺畅、段落聚焦且分段良好、用加粗标出要点、标题干净连续（不超过两级）、母语专业"
    "书面语域。以清晰优先于面面俱到——大幅精简（目标约2.5-3.5万字）。保留核心结论、关键数字与数据，"
    "并尽量保留各处不同的引用标记[^N]于其支撑的论断；删去冗余、过深层级、套话脚手架（路线图/小结）"
    "与泄漏标记。只输出报告 markdown 正文，不要任何前言、说明或代码围栏。"
)


def _spine_literal(numeric_spine) -> str:
    if isinstance(numeric_spine, dict):
        resolved = numeric_spine.get("resolved")
        if isinstance(resolved, dict):
            return str(resolved.get("literal") or "")
    return ""


def rewrite(article: str, language: str, *, numeric_spine=None) -> dict:
    """Whole-article readability rewrite. Returns {article, applied, stats}.
    Fail-soft: ships the original draft on any error or guard trip."""
    if not isinstance(article, str) or not article.strip():
        return {"article": article, "applied": False, "stats": {"reason": "empty-input"}}
    role = "readability_rewriter"
    spine = _spine_literal(numeric_spine)
    system = _SYS_ZH if language == "zh" else _SYS_EN
    try:
        out = llm.call(role, article, system=system, max_tokens=_OUT_TOKEN_BUDGET, note="readability_rewrite")
    except Exception as e:  # noqa: BLE001 — enhancement only; never break the run
        return {"article": article, "applied": False, "stats": {"reason": f"err:{type(e).__name__}"}}
    out = (out or "").strip()
    pre_n, post_n = len(article), len(out)
    stats = {
        "pre_chars": pre_n, "post_chars": post_n,
        "ratio": round(post_n / max(1, pre_n), 3),
        "cites_pre": len(_MARKER_RE.findall(article)), "cites_post": len(_MARKER_RE.findall(out)),
    }
    if not out:
        return {"article": article, "applied": False, "stats": {**stats, "reason": "empty-output"}}
    if post_n > _GUARD_HI * pre_n:
        return {"article": article, "applied": False, "stats": {**stats, "reason": "grew"}}
    if post_n < _GUARD_LO * pre_n:
        return {"article": article, "applied": False, "stats": {**stats, "reason": "over-summarized"}}
    if spine and spine in article and spine not in out:
        return {"article": article, "applied": False, "stats": {**stats, "reason": "spine-lost"}}
    return {"article": out, "applied": True, "stats": {**stats, "reason": "ok"}}
