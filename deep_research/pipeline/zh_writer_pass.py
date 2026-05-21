"""ZH writer-pass (p1-checklist items 18-stack + 27).

Runtime: for ZH tasks, after the refiner, render the report in native-register
Simplified Chinese via the W6-selected OpenRouter model (config role
'zh_writer'). If the role is unset/"" (W6 found both candidates non-viable),
this is a no-op and the Opus draft ships raw (decision logged).

W6 selection: select_zh_writer() runs the 5-task ZH smoke (Qwen3-235B vs
DeepSeek-V3.2, Opus upstream), scores with a native-register critic, and
applies the falsifiable winner rule (plan point 13): higher mean critic score,
no task < 6/10; both non-viable (>2 tasks <6) → dropped.
"""
import json

from .. import config, llm
from ..clients import openrouter_client

_PASS_SYSTEM = (
    "你是一名资深中文研究报告编辑。将给定报告改写为地道、专业、书面化的简体中文研究"
    "报告：保持全部事实、数据、来源署名、结构与篇幅不变（不得删减、不得缩写），仅提升"
    "中文表达的地道性与专业语域。保留正文内联的来源署名（如“据麦肯锡2025”），不要把"
    "事实只放进脚注或编号。只输出改写后的完整报告，不要任何前言。"
)

_CRITIC_SYSTEM = (
    "你是中文研究报告语言质量评审。仅就【中文母语地道度与专业书面语域】打分（0-10，"
    "整数），不评估事实正确性。10=与资深中文分析师撰写无异；6=可接受；<6=存在翻译腔/"
    "用词生硬/语域不当。只输出 JSON：{\"score\": <int>, \"reason\": \"<=20字\"}。"
)


def zh_pass(article: str, prompt: str) -> dict:
    """Fail-soft: ANY exception in ZH polish ships the raw Opus article
    instead of failing the task. Polish is an enhancement, not load-bearing."""
    role_model = config.model_for("zh_writer")
    if not role_model:
        return {"article": article, "applied": False, "reason": "zh_writer dropped"}
    try:
        # ZH writers (Qwen3/DeepSeek/etc) aren't served by DeepInfra (our
        # Nemotron pin). Unpin per-call so OpenRouter picks any provider.
        out, _ = openrouter_client.raw_call(
            role_model, f"原始任务：{prompt[:400]}\n\n报告：\n{article}",
            system=_PASS_SYSTEM, max_tokens=32000, note="zh_writer_pass",
            provider="")
    except Exception as e:  # noqa: BLE001
        return {"article": article, "applied": False,
                "reason": f"zh-pass error (raw shipped): {type(e).__name__}: {str(e)[:80]}"}
    out = out.strip()
    if len(out) < 0.85 * len(article):  # guard: don't ship a truncated pass
        return {"article": article, "applied": False, "reason": "zh-pass too short"}
    return {"article": out, "applied": True, "reason": "ok"}


def _critic_score(zh_text: str) -> dict:
    """Robust ZH critic: bumps token budget + falls back to regex-extracted
    score if JSON parse fails (W6 V4 Pro test surfaced one such case)."""
    import re
    try:
        obj = llm.call_json("inner_scorer", zh_text[:24000],
                            system=_CRITIC_SYSTEM, max_tokens=4000, seed=12345,
                            effort="low", note="zh_critic")
        if isinstance(obj, dict):
            return {"score": float(obj.get("score", 0)),
                    "reason": obj.get("reason", "")}
    except Exception:  # noqa: BLE001
        pass
    # Fallback: raw call + regex-extract a single 0-10 integer score
    try:
        from .. import llm as _llm
        raw = _llm.call("inner_scorer", zh_text[:24000], system=_CRITIC_SYSTEM,
                        max_tokens=4000, seed=12345, effort="low",
                        note="zh_critic.fallback")
        m = re.search(r'"score"\s*:\s*([0-9.]+)', raw) or re.search(r'\b([0-9]|10)\s*/\s*10\b', raw) or re.search(r'\b([0-9])\b', raw)
        s = float(m.group(1)) if m else 0.0
        return {"score": s, "reason": "regex-fallback"}
    except Exception as e:  # noqa: BLE001
        return {"score": 0.0, "reason": f"critic-error {str(e)[:60]}"}


def select_zh_writer(zh_drafts: list) -> dict:
    """zh_drafts: [{id, prompt, opus_article}] (5 ZH tasks). Returns the W6
    decision dict; caller writes p1_artifacts/zh_writer_pass_selection.md."""
    candidates = config.ZH_WRITER_CANDIDATES
    per_task, means = [], {}
    for cand in candidates:
        rows = []
        for d in zh_drafts:
            try:
                txt, _ = openrouter_client.raw_call(
                    cand, f"原始任务：{d['prompt'][:400]}\n\n报告：\n"
                    f"{d['opus_article']}", system=_PASS_SYSTEM,
                    max_tokens=32000, note=f"zh_sel.{cand}")
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
        decision = {"winner": "", "dropped": True,
                    "reason": "both non-viable (>2 tasks <6/10) — ship Opus raw"}
    else:
        winner = max(viables, key=lambda c: means[c])
        decision = {"winner": winner, "dropped": False,
                    "reason": f"highest mean ({means[winner]:.2f}), viable"}
    decision["means"] = means
    decision["per_task"] = per_task
    return decision
