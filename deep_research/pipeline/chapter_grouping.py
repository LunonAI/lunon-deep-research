"""Phase 1 A1-REAL (2026-06-04): post-generation thematic chapter grouping.

Qianfan #1 renders many-entity (list-all/compare) reports as ~8-11 thematic H1
chapters with each entity an H2 subsection (id-91: 11 H1 / 78 H2). We over-promote
to 19-47 flat H1 (one chapter per entity). The round-5 group-and-nest REGRESSED
because it grouped at GENERATION time — cutting write_section calls ~5x, starving
per-entity word budget and fragmenting the bold-axis micro-template (InstFollow).

This groups at ASSEMBLY time instead: generation is byte-identical (every entity
still its own full-budget write_section call with the byte-identical template), and
we deterministically (a) demote each entity heading one level and (b) insert ~9
thematic chapter headers. After numbering_fix renumber+promote, group headers and
framing chapters land at H1 and entities at H2 — Qianfan's exact shape — with the
round-5 starvation structurally impossible (no generation change).

ONE cheap LLM call assigns the ordered entity sections to thematic chapters by
returning per-chapter COUNTS over the in-order list (guarantees contiguity, order,
and zero entity loss: counts must sum to N). The restructure is deterministic and
content-preserving. Fail-soft: any error / bad counts / out-of-band group count /
no entity match -> returns the article UNCHANGED (the conservative promotion guard
then bounds H1 as the fallback). Kill-switch DR_CHAPTER_GROUPING=off.
"""

from __future__ import annotations

import json
import os
import re

from .. import config
from ..clients import openrouter_client

_ENABLED = os.environ.get("DR_CHAPTER_GROUPING", "on") != "off"
# Only group when the entity run is wide enough to be over Qianfan's ~10-12 band.
_MIN_ENTITIES_TO_GROUP = 14
_MIN_GROUPS = 4
_MAX_GROUPS = 12

_FENCE_RE = re.compile(r"^[ \t]*(?:```|~~~)")
_TOP_RE = re.compile(r"^##(?!#)[ \t]+(.+?)[ \t]*$")  # numbered top chapter `## N Title`
_NUM_PREFIX = re.compile(r"^\s*(?:§\s*)?\d+(?:\.\d+)*\.?\s+")


def _top_sections(article: str) -> list[tuple[int, int, str]]:
    """(line_char_start, body_char_start, title) for each `##` top section,
    skipping fenced code. body_char_start is the offset just after the heading line."""
    out: list[tuple[int, int, str]] = []
    pos = 0
    in_fence = False
    for line in article.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            m = _TOP_RE.match(line)
            if m:
                out.append((pos, pos + len(line), m.group(1)))
        pos += len(line)
    return out


def _norm(s: str) -> str:
    return _NUM_PREFIX.sub("", s).strip().lower()


def _entity_run(sections: list[tuple[int, int, str]], entities: list[str]) -> tuple[int, int]:
    """Return the [start, end) index range over `sections` that are entity
    chapters — the longest CONTIGUOUS run whose titles match an entity name.
    Framing/synthesis chapters (non-entity) are left outside the run as H1."""
    if not entities:
        return (0, 0)
    ent_norms = [_norm(e) for e in entities if e]
    def is_entity(title: str) -> bool:
        t = _norm(title)
        return any(en and (en in t or t in en) for en in ent_norms)
    flags = [is_entity(t) for _, _, t in sections]
    best = (0, 0)
    i = 0
    n = len(flags)
    while i < n:
        if flags[i]:
            j = i
            while j < n and flags[j]:
                j += 1
            if (j - i) > (best[1] - best[0]):
                best = (i, j)
            i = j
        else:
            i += 1
    return best


def _call_grouper(topic: str, titles: list[str], *, model: str) -> list[dict] | None:
    """One cheap LLM call → [{title, count}, ...] covering `titles` in order,
    counts summing to len(titles). None on any failure."""
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    n = len(titles)
    system = (
        "You organize the sections of a research report into thematic top-level "
        "chapters that match how a top-tier analyst would group them."
    )
    user = (
        f"Report topic:\n{topic}\n\n"
        f"Below are {n} report sections, IN ORDER, each covering one entity/item. "
        f"Group them into {_MIN_GROUPS}-{_MAX_GROUPS} thematic chapters following the "
        f"domain's NATURAL taxonomy (e.g. by class/faction, era/movement, or "
        f"region/sector). Keep the GIVEN ORDER: each chapter is a run of CONSECUTIVE "
        f"sections. Every section belongs to exactly one chapter.\n\n"
        f"Return ONLY JSON: {{\"chapters\":[{{\"title\":\"<chapter title>\",\"count\":<n sections>}}, ...]}} "
        f"where the counts are in order and SUM TO EXACTLY {n}.\n\n"
        f"Sections:\n{numbered}"
    )
    try:
        out, _ = openrouter_client.raw_call(model, user, system=system, max_tokens=2000, note="chapter_grouping")
    except Exception:  # noqa: BLE001
        return None
    if not out:
        return None
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        chapters = data.get("chapters")
        if not isinstance(chapters, list):
            return None
        clean = []
        for c in chapters:
            title = str(c.get("title", "")).strip()
            count = int(c.get("count"))
            if not title or count <= 0:
                return None
            clean.append({"title": title, "count": count})
        return clean or None
    except (ValueError, TypeError, KeyError):
        return None


def group_into_chapters(
    article: str, *, language: str | None = None, plan: dict | None = None, archetype: str | None = None
) -> tuple[str, dict]:
    stats = {"applied": False, "reason": "", "n_entities": 0, "n_chapters": 0}
    if not _ENABLED or archetype not in ("list-all", "compare"):
        stats["reason"] = "disabled-or-archetype"
        return article, stats
    if not isinstance(article, str) or not article.strip() or not isinstance(plan, dict):
        stats["reason"] = "no-input"
        return article, stats
    try:
        em = plan.get("entity_matrix") or {}
        entities = [str(e) for e in (em.get("entities") or []) if e]
        sections = _top_sections(article)
        lo, hi = _entity_run(sections, entities)
        run = sections[lo:hi]
        stats["n_entities"] = len(run)
        if len(run) < _MIN_ENTITIES_TO_GROUP:
            stats["reason"] = f"entity-run-too-small ({len(run)})"
            return article, stats

        topic = str(plan.get("title") or plan.get("topic") or (entities[:1] or [""])[0])[:400]
        titles = [t for _, _, t in run]
        chapters = _call_grouper(topic, titles, model=config.model_for("chapter_grouper"))
        if not chapters:
            stats["reason"] = "grouper-failed"
            return article, stats
        if not (_MIN_GROUPS <= len(chapters) <= _MAX_GROUPS):
            stats["reason"] = f"group-count-out-of-band ({len(chapters)})"
            return article, stats
        if sum(c["count"] for c in chapters) != len(run):
            stats["reason"] = "counts-mismatch"
            return article, stats

        # Deterministic restructure. Walk the entity run in order; for each
        # chapter, emit a `## {title}` header before its first entity and demote
        # every entity heading `## ...` -> `### ...` (number stripped; renumber
        # reassigns). Splice back into the article around [lo:hi] verbatim.
        run_start = run[0][0]
        run_end = sections[hi][0] if hi < len(sections) else len(article)
        pieces: list[str] = []
        idx = 0
        for ch in chapters:
            pieces.append(f"## {ch['title']}\n\n")
            for _ in range(ch["count"]):
                line_start, body_start, title = run[idx]
                seg_end = run[idx + 1][0] if idx + 1 < len(run) else run_end
                body = article[body_start:seg_end]
                clean_title = _NUM_PREFIX.sub("", title).strip()
                pieces.append(f"### {clean_title}\n{body}")
                idx += 1
        regrouped = article[:run_start] + "".join(pieces) + article[run_end:]
        regrouped = re.sub(r"\n{3,}", "\n\n", regrouped)
        stats["applied"] = True
        stats["n_chapters"] = len(chapters)
        stats["reason"] = "ok"
        return regrouped, stats
    except Exception as e:  # noqa: BLE001 — post-pass must never break the run
        stats["reason"] = f"error:{type(e).__name__}"
        return article, stats
