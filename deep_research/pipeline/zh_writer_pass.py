"""ZH writer-pass (p1-checklist items 18-stack + 27).

Runtime: for ZH tasks, after the refiner, render the report in native-register
Simplified Chinese via the W6-selected OpenRouter model (config role
'zh_writer'). If the role is unset/"" (W6 found both candidates non-viable),
this is a no-op and the Opus draft ships raw (decision logged).

round 10 (2026-06-03): CHUNKED per top-chapter. The old single whole-article
call (max_tokens=32000) truncated on long ZH → failed the 0.85 length guard →
no-op, so ~half the benchmark (every long ZH task) shipped the RAW, unpolished
Opus draft (the #1 Readability gap). Now: short ZH still uses one call; long ZH
(>=80k chars) splits into top chapters via `article_metrics._top_chapters`,
polishes each chapter in its own call (fits the 32k budget), and reassembles —
with per-chunk guards that REVERT any chapter that drops a fact/number/citation
or the numeric-spine headline figure (never fails the task; enhancement only).

W6 selection: select_zh_writer() runs the 5-task ZH smoke, scores with a
native-register critic, applies the falsifiable winner rule (plan point 13).
"""

import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .. import config, llm
from ..clients import openrouter_client
from ..text_metrics import approx_tokens
from . import article_metrics

# --- chunking / guard constants ------------------------------------------------
_CHUNK_THRESHOLD_CHARS = 80_000  # below: single whole-article call (legacy path)
_OUT_TOKEN_BUDGET = 32_000  # matches the per-call max_tokens
_SUBCHUNK_TOK_CEILING = 24_000  # a chapter wanting > this output is sub-chunked
_CHUNK_GUARD_LO = 0.85  # a polished chunk shorter than this → dropped content → revert
_CHUNK_GUARD_HI = 1.6  # a chunk grown past this → padding/hallucination → revert
_CHUNK_WORKERS = int(os.environ.get("DR_ZH_CHUNK_WORKERS", "4"))
_MARKER_RE = re.compile(r"\[\^[^\]]+\]")  # inline citation markers [^N]
_HEDGE_RE = re.compile(r"可能|似乎|大约")

# Runtime register prompt (round 10): targets the corpus-measured gaps vs the reference
# (是因为 pseudo-connectives, choppy paragraphs, gloss overload, bare cross-refs,
# 可能-hedging, in-prose algebra, em-dash overuse) while HARD-freezing facts /
# numbers / citations / structure / length. Tuned for the chunked harness: it
# receives ONE segment (a chapter or the whole short article) and returns the
# SAME segment, polished.
_REGISTER_SYSTEM = (
    "你是为顶尖中文研究机构撰稿的资深分析师，母语为简体中文。下面给你一篇研究报告的"
    "一段内容（通常是其中一章，亦可能是全文）。在不改动任何事实的前提下，仅把它的中文"
    "表达提升到与中文分析师原生撰写无异的专业书面语域，然后原样返回这段内容。\n"
    "只改语言，不改内容。严格遵守：\n"
    "1. 数字冻结：任何数字、单位、日期、百分比、金额（如“约11万条/年”）一字不动，不"
    "换算、不增删、不四舍五入。\n"
    "2. 事实与来源冻结：不增、不减、不移动任何事实或来源；正文内联署名（如“据CAMET”）"
    "原样保留；引用标记 [^N] 原样保留并在重复提及时复用同一编号，不新增、不删除、不改号。\n"
    "3. 结构冻结：标题文字与层级（## N 仍为 ## N、### N.M 仍为 ### N.M）原样保留，不"
    "重编号、不改写标题、不拆分或合并章节。\n"
    "4. 篇幅冻结：纯语域改写，不得缩写、不得删减，输出长度须与原文相当或略长。\n"
    "在上述约束内，按以下顺序提升语域：\n"
    "· 因果衔接：不用“是因为”这类翻译腔伪连词，改用原生因果链。例：把“产能扩张是因为"
    "补贴到位”改为“由于补贴到位，产能因而扩张”。\n"
    "· 段落融合：把“定义—依据—含义”揉成150–200字、用“而/但/则”连缀的流畅段落，不要"
    "碎句罗列。\n"
    "· 去括注：不要连续多个（…）夹注，改用“即…”、冒号展开或“其一…其二…”。\n"
    "· 实义过渡：段间/章首用点明分析作用的话承接（如“这一拆分的趋势含义在于…”），不写"
    "“详见第3章”这类空指针；章首先给核心论断或定义，不以“本节/下文”开头。\n"
    "· 去模糊：把“可能/似乎/大约”换成量化区间（如“由约75–80%升至84%”）。\n"
    "· 不在行文中写算式：“A×B=C”改写为“A与B的乘积为C”。\n"
    "· 破折号克制：以逗号、冒号替代，每千字不超过约12个。\n"
    "只输出改写后的正文本身，不要重复或新增任何标题行，不要任何前言。"
)

_CRITIC_SYSTEM = (
    "你是中文研究报告语言质量评审。仅就【中文母语地道度与专业书面语域】打分（0-10，"
    "整数），不评估事实正确性。10=与资深中文分析师撰写无异；6=可接受；<6=存在翻译腔/"
    '用词生硬/语域不当。只输出 JSON：{"score": <int>, "reason": "<=20字"}。'
)


def _split_leading_headings(text: str) -> tuple[str, str]:
    """Freeze ONLY the chunk's OWN top heading (its first heading line + the blank
    lines around it) so the model can't renumber/retitle the chapter — reattached
    verbatim. A stacked sub-heading (## N immediately followed by ### N.M before any
    prose) STAYS in the body so the model keeps its sub-section context (Greptile
    #101 issue 1); numbering_fix repairs any in-body sub-heading numbering."""
    lines = text.splitlines(keepends=True)
    h = 0
    while h < len(lines) and not lines[h].strip():  # leading blanks
        h += 1
    if h < len(lines) and lines[h].lstrip().startswith("#"):  # the chunk's OWN heading (one line)
        h += 1
        while h < len(lines) and not lines[h].strip():  # + its trailing blanks
            h += 1
    return "".join(lines[:h]), "".join(lines[h:])


def _drop_echoed_heading(out: str, head: str) -> str:
    """If the model echoed/fabricated the frozen CHAPTER heading at the start of its
    output (despite the prompt forbidding it), drop ONLY that exact duplicate line —
    never a legitimate in-body sub-heading — so the reattached `head` isn't doubled
    (Greptile #101 issue 2)."""
    head_heading = next((ln.strip() for ln in head.splitlines() if ln.lstrip().startswith("#")), "")
    if not head_heading:
        return out
    lines = out.splitlines(keepends=True)
    i = 0
    while i < len(lines) and not lines[i].strip():  # skip blanks the model may have led with
        i += 1
    if i < len(lines) and lines[i].strip() == head_heading:
        return "".join(lines[i + 1 :]).lstrip("\n")
    return out


def _polish_chunk(text: str, prompt: str, role_model: str, spine_literal: str) -> tuple[str, dict]:
    """Polish ONE segment. Returns (polished_or_verbatim_original, stat). Reverts
    to the verbatim original on: exception, < 0.85x shrink, > 1.6x growth,
    numeric-spine-figure loss, or citation-marker loss. Never raises."""
    orig = text
    head, body = _split_leading_headings(text)
    if not body.strip():  # heading-only / blank → nothing to polish
        return orig, {"applied": False, "reason": "no-body"}
    spine_clause = (
        f"（务必逐字保留核心数字“{spine_literal}”，出现处不得改成其他写法。）"
        if spine_literal and spine_literal in orig
        else ""
    )
    try:
        out, _ = openrouter_client.raw_call(
            role_model,
            f"原始任务：{prompt[:400]}\n\n待润色正文（保持编号、数字、引用标记不变）：{spine_clause}\n{body}",
            system=_REGISTER_SYSTEM,
            max_tokens=_OUT_TOKEN_BUDGET,
            note="zh_writer_pass.chunk",
            provider="",  # ZH writers aren't on our Nemotron provider pin
        )
    except Exception as e:  # noqa: BLE001 — enhancement only; revert this chunk
        return orig, {"applied": False, "reason": f"err:{type(e).__name__}"}
    out = out.strip()
    if head:
        out = head + _drop_echoed_heading(out, head).strip()
    # Restore the chunk's ORIGINAL trailing whitespace (the blank line(s) that
    # separate chapters) so the verbatim reassembly never runs two chapters
    # together — and so an identity polish round-trips byte-for-byte.
    out = out + orig[len(orig.rstrip()) :]
    if len(out) < _CHUNK_GUARD_LO * len(orig):
        return orig, {"applied": False, "reason": "short"}
    if len(out) > _CHUNK_GUARD_HI * len(orig):
        return orig, {"applied": False, "reason": "overgrown"}
    if spine_literal and spine_literal in orig and spine_literal not in out:
        return orig, {"applied": False, "reason": "spine-mutated"}
    # Count-preserving (multiset) check, not set-subset: the register prompt forbids
    # deleting marker occurrences ("不删除"), so a chunk that collapses repeated cites
    # (e.g. 5×[^1] → 1×[^1]) without shrinking past the length floor must still revert
    # — set-subset would silently pass it (Greptile #101 follow-up).
    if Counter(_MARKER_RE.findall(orig)) - Counter(_MARKER_RE.findall(out)):
        return orig, {"applied": False, "reason": "citation-lost"}
    return out, {"applied": True, "reason": "ok"}


def _polish_oversized(chap: str, prompt: str, role_model: str, spine_literal: str) -> tuple[str, dict]:
    """A single chapter too large for one 32k call: keep the heading verbatim and
    polish the body in paragraph batches under the sub-chunk ceiling, reassemble."""
    head, body = _split_leading_headings(chap)
    paras = body.split("\n\n")
    batches: list[str] = []
    cur = ""
    for p in paras:
        cand = (cur + "\n\n" + p) if cur else p
        if cur and approx_tokens(cand) > _SUBCHUNK_TOK_CEILING:
            batches.append(cur)
            cur = p
        else:
            cur = cand
    if cur:
        batches.append(cur)
    out_parts, reverted = [], 0
    for b in batches:
        polished, st = _polish_chunk(b, prompt, role_model, spine_literal)
        if not st.get("applied"):
            reverted += 1
        out_parts.append(polished)
    return head + "\n\n".join(out_parts), {
        "applied": reverted < len(batches),
        "reason": f"subchunk {len(batches) - reverted}/{len(batches)}",
        "subchunks": len(batches),
    }


def _register_proxies(text: str) -> dict:
    """Cheap, zero-LLM register proxies for the drift log (the ground-truth signal
    that the pass moved the measured the reference gaps)."""
    import statistics

    paras = [p for p in text.split("\n\n") if p.strip() and not p.lstrip().startswith("#")]
    med = round(statistics.median([len(p) for p in paras])) if paras else 0
    n = max(1, len(text))
    return {
        "shi_yinwei": text.count("是因为"),
        "median_para_chars": med,
        "emdash_per_1k": round(text.count("—") / n * 1000, 1),
        "hedges": len(_HEDGE_RE.findall(text)),
    }


def _zh_pass_single(article: str, prompt: str, role_model: str, spine_literal: str) -> dict:
    polished, st = _polish_chunk(article, prompt, role_model, spine_literal)
    applied = st.get("applied", False)
    return {
        "article": polished if applied else article,
        "applied": applied,
        "reason": ("ok (single)" if applied else f"single: {st.get('reason', '')}"),
        "stats": {"mode": "single", **st},
    }


def _zh_pass_chunked(article: str, prompt: str, role_model: str, spine_literal: str) -> dict:
    headings = article_metrics._headings(article)
    chapters = article_metrics._top_chapters(article, headings)
    if len(chapters) < 2:  # no top-chapter structure → fall back to one call
        return _zh_pass_single(article, prompt, role_model, spine_literal)
    # _top_chapters EXCLUDES the title/preamble before chapter 1 — capture it or
    # the abstract (which carries the spine literal) is lost on reassembly. The
    # chapter slices are contiguous to end-of-article, so the preamble length is
    # exactly article_len - joined_chapters_len — robust vs str.index, which would
    # mis-locate the boundary if a heading repeats verbatim (Greptile #101 issue 3).
    preamble = article[: len(article) - sum(len(c) for c in chapters)]
    units = ([preamble] if preamble.strip() else []) + list(chapters)

    def polish_unit(u: str) -> tuple[str, dict]:
        if approx_tokens(u) > _SUBCHUNK_TOK_CEILING:
            return _polish_oversized(u, prompt, role_model, spine_literal)
        return _polish_chunk(u, prompt, role_model, spine_literal)

    with ThreadPoolExecutor(max_workers=_CHUNK_WORKERS) as ex:
        results = list(ex.map(polish_unit, units))  # ex.map preserves input order
    out_parts = [r[0] for r in results]
    reassembled = "".join(out_parts)  # contiguous verbatim slices → lossless join
    n_reverted = sum(1 for r in results if not r[1].get("applied"))
    stats = {
        "mode": "chunked",
        "n_units": len(units),
        "n_reverted": n_reverted,
        "n_subchunked": sum(1 for r in results if "subchunks" in r[1]),
        "revert_reasons": [r[1].get("reason") for r in results if not r[1].get("applied")],
        "proxies_pre": _register_proxies(article),
        "proxies_post": _register_proxies(reassembled),
    }
    if len(reassembled) < _CHUNK_GUARD_LO * len(article):  # mass shrink → ship raw
        return {"article": article, "applied": False, "reason": "reassembled too short", "stats": stats}
    return {
        "article": reassembled,
        "applied": n_reverted < len(units),
        "reason": f"ok ({len(units) - n_reverted}/{len(units)} chunks polished)",
        "stats": stats,
    }


def zh_pass(article: str, prompt: str, *, numeric_spine: dict | None = None) -> dict:
    """Fail-soft ZH register polish. SHORT articles: one whole-article call. LONG
    (>=80k chars): chunked per top chapter so the 32k budget never truncates the
    polish to nothing. `numeric_spine` (the merged generative-spine plan field)
    lets the per-chunk guard revert any chapter that mutates the headline figure.
    ANY error ships the raw Opus article (enhancement, not load-bearing)."""
    role_model = config.model_for("zh_writer")
    if not role_model:
        return {"article": article, "applied": False, "reason": "zh_writer dropped", "stats": {}}
    spine_literal = ""
    if isinstance(numeric_spine, dict):
        resolved = numeric_spine.get("resolved")
        if isinstance(resolved, dict):
            spine_literal = str(resolved.get("literal") or "")
    try:
        if len(article) < _CHUNK_THRESHOLD_CHARS:
            return _zh_pass_single(article, prompt, role_model, spine_literal)
        return _zh_pass_chunked(article, prompt, role_model, spine_literal)
    except Exception as e:  # noqa: BLE001 — outermost guard: never fail the task
        return {
            "article": article,
            "applied": False,
            "reason": f"zh-pass error (raw shipped): {type(e).__name__}: {str(e)[:80]}",
            "stats": {},
        }


def _critic_score(zh_text: str) -> dict:
    """Robust ZH critic: bumps token budget + falls back to regex-extracted
    score if JSON parse fails (W6 V4 Pro test surfaced one such case)."""
    try:
        obj = llm.call_json(
            "inner_scorer",
            zh_text[:24000],
            system=_CRITIC_SYSTEM,
            max_tokens=4000,
            seed=12345,
            effort="low",
            note="zh_critic",
        )
        if isinstance(obj, dict):
            return {"score": float(obj.get("score", 0)), "reason": obj.get("reason", "")}
    except Exception:  # noqa: BLE001
        pass
    # Fallback: raw call + regex-extract a single 0-10 integer score
    try:
        raw = llm.call(
            "inner_scorer",
            zh_text[:24000],
            system=_CRITIC_SYSTEM,
            max_tokens=4000,
            seed=12345,
            effort="low",
            note="zh_critic.fallback",
        )
        m = (
            re.search(r'"score"\s*:\s*([0-9.]+)', raw)
            or re.search(r"\b([0-9]|10)\s*/\s*10\b", raw)
            or re.search(r"\b([0-9])\b", raw)
        )
        s = float(m.group(1)) if m else 0.0
        return {"score": s, "reason": "regex-fallback"}
    except Exception as e:  # noqa: BLE001
        return {"score": 0.0, "reason": f"critic-error {str(e)[:60]}"}


def _smoke_chunk(article: str) -> str:
    """Runtime-shaped W6 smoke input: the body of the first top chapter (its heading
    split off, exactly as _polish_chunk feeds the model at runtime), or the whole
    short article when it has no top-chapter structure. Keeps select_zh_writer
    scoring candidates on the SAME per-chunk shape they run under in production, not
    a whole multi-chapter article (Greptile #101 follow-up)."""
    chapters = article_metrics._top_chapters(article, article_metrics._headings(article))
    seg = chapters[0] if chapters else article
    _, body = _split_leading_headings(seg)
    return body.strip() or seg.strip()


def select_zh_writer(zh_drafts: list) -> dict:
    """zh_drafts: [{id, prompt, opus_article}] (5 ZH tasks). Returns the W6
    decision dict; caller writes p1_artifacts/zh_writer_pass_selection.md. Scores
    each candidate under the runtime _REGISTER_SYSTEM prompt on a per-chunk sample
    (Greptile #101 follow-up) so the winner is the best model for the actual chunked
    runtime path, not the retired whole-article rewrite."""
    candidates = config.ZH_WRITER_CANDIDATES
    samples = [(d, _smoke_chunk(d["opus_article"])) for d in zh_drafts]
    per_task, means = [], {}
    for cand in candidates:
        rows = []
        for d, sample in samples:
            try:
                txt, _ = openrouter_client.raw_call(
                    cand,
                    f"原始任务：{d['prompt'][:400]}\n\n待润色正文（保持编号、数字、引用标记不变）：\n{sample}",
                    system=_REGISTER_SYSTEM,
                    max_tokens=_OUT_TOKEN_BUDGET,
                    note=f"zh_sel.{cand}",
                    provider="",  # ZH writers aren't on our Nemotron provider pin
                )
                sc = _critic_score(txt)
            except Exception as e:  # noqa: BLE001
                sc = {"score": 0.0, "reason": f"gen-error {e}"}
            rows.append({"id": d["id"], **sc})
        means[cand] = sum(r["score"] for r in rows) / max(1, len(rows))
        per_task.append({"candidate": cand, "rows": rows})

    def viable(cand):
        rows = next(p["rows"] for p in per_task if p["candidate"] == cand)
        below = sum(1 for r in rows if r["score"] < 6)
        return below <= 2

    viables = [c for c in candidates if viable(c)]
    if not viables:
        decision = {"winner": "", "dropped": True, "reason": "both non-viable (>2 tasks <6/10) — ship Opus raw"}
    else:
        winner = max(viables, key=lambda c: means[c])
        decision = {"winner": winner, "dropped": False, "reason": f"highest mean ({means[winner]:.2f}), viable"}
    decision["means"] = means
    decision["per_task"] = per_task
    return decision
