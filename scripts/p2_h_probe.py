"""Wave 0 H — ZH-cleaner failure probe.

Per docs/zh_scoring_failure_analysis.md §8.1: the harness ArticleCleaner
drops 11 ZH articles in W9 with the generic "Failed to clean article" error.
The clean_article.py:294-297 line returns this error when:
  (a) the cleaner LLM call returns None after 3 retries, OR
  (b) the cleaner LLM returns a string but < 100 characters after .strip()

Read-only inspection cannot distinguish (a) from (b). This script directly
calls the cleaner LLM on the largest failing ZH article (id=8) with the
exact harness clean_article_prompt_zh, and captures:
  - The full response text (or stop reason if None)
  - Response character/word counts
  - Whether the response is < 100 chars (would trigger H8 mechanism b)
  - Whether the response is empty (would trigger H7)
  - Time-to-first-token / total latency

Cost: ~$2 (one GPT-5.5 call on a ~3500-char ZH article).

Outputs to p2_artifacts/H_probe_result.md.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deep_research import llm  # noqa: E402

# The harness's clean_article_prompt_zh is at /home/connor/dev/deep_research_bench/prompt/clean_prompt.py.
# We hard-quote the prompt body here to avoid coupling to that path; verify
# byte-equality if the harness ever changes the prompt.
CLEAN_PROMPT_ZH_TEMPLATE = """
<system_role>你是一名专业的文章编辑，擅长整理和清洗文章内容。</system_role>

<user_prompt>
下面给你的内容可能是一篇完整研究文章，也可能只是其中的一个连续片段（chunk）。
请只针对输入的这部分内容进行清洗，不要假设、补全或引用片段之外的上下文。

清洗目标：去除所有引用链接、引用标记（如[1]、[2]、1、2 等或其他复杂引用格式）、参考文献列表、脚注，并确保文章内容连贯流畅。
保留文章的所有其他原本内容、只移除引用。如果文章中使用引用标记中的内容作为语句的一部分，保留这其中的文字内容，移除其他标记。

特殊情况：如果输入的这段内容整段都属于某个文章的参考文献区（reference 列表 / 脚注定义等），不包含任何正文，请返回空字符串。

输入内容：
"{article}"

请返回清洗后的全文，不要添加任何额外说明或评论。
</user_prompt>
"""


def load_article(article_id: str = "8") -> dict:
    path = ROOT / "p1_artifacts" / "p1_final.jsonl"
    with path.open() as f:
        for line in f:
            d = json.loads(line)
            if str(d["id"]) == article_id:
                return d
    raise RuntimeError(f"id={article_id} not found in {path}")


def classify_result(article_len: int, response: str | None) -> dict:
    """Map the response into the hypothesis taxonomy from
    docs/zh_scoring_failure_analysis.md §6."""
    if response is None:
        return {
            "outcome": "H8(i-or-iii) — LLM returned None / errored / timed out",
            "fix_path": "harness-side fork OR engine-side trigger-phrase trim",
        }
    n_chars = len(response.strip())
    if n_chars == 0:
        return {
            "outcome": "H7 — LLM returned empty string (article mis-classified as reference list)",
            "fix_path": "harness-side fork — relax empty-acceptance contract in clean_prompt.py:12 for inputs > 5,000 chars",
        }
    if n_chars < 100:
        return {
            "outcome": f"H8(mechanism-b) — LLM returned {n_chars} chars (<100 threshold)",
            "fix_path": "harness-side fork — relax _is_valid_result threshold in clean_article.py:31-33",
        }
    if n_chars < article_len * 0.5:
        return {
            "outcome": f"H8(unexpected) — LLM returned {n_chars} chars (passes harness threshold but very short for {article_len}-char input)",
            "fix_path": "investigate further; could be content-filter partial response",
        }
    return {
        "outcome": f"REPRODUCES SUCCESS — LLM returned {n_chars} chars on this attempt",
        "fix_path": "the failure is intermittent (3-of-3 retry failure on harness side is bad luck OR specific seed/state); harness-side fix = bump retry budget from 3 to 6",
    }


def main(article_id: str = "8") -> int:
    art = load_article(article_id)
    article_text = art["article"]
    print(f"Loaded id={article_id} ({len(article_text)} chars, language={art.get('id')}).")

    # Format the prompt using the harness's template. Note: harness uses
    # Python f-string substitution {article} → article body.
    user_prompt = CLEAN_PROMPT_ZH_TEMPLATE.format(article=article_text)

    print(f"Calling cleaner LLM via engine llm.call (role='criteria_gen', resolves to gpt-5.5)...")
    t0 = time.time()
    err = None
    response = None
    try:
        # criteria_gen role is GPT-5.5 (mirrors RACE_MODEL default in the harness)
        response = llm.call(
            "criteria_gen",
            user_prompt,
            system="",
            max_tokens=20000,  # generous; cleaner needs to return ~3.5k char output
            effort="low",
            note="p2_h_probe.clean_zh_id8",
            timeout=300,
            max_retries=1,
        )
    except Exception as e:
        err = repr(e)
    dt = time.time() - t0
    print(f"Latency: {dt:.1f}s; error: {err}")
    if response is not None:
        print(f"Response chars: {len(response)} ({len(response.strip())} after strip).")
        print(f"--- first 500 chars of response ---")
        print(response[:500])
        print(f"--- end first 500 ---")
    classification = classify_result(len(article_text), response if err is None else None)
    print(f"\nClassification: {classification['outcome']}")
    print(f"Fix path:       {classification['fix_path']}")

    # Write structured output
    out_path = ROOT / "p2_artifacts" / "H_probe_result.md"
    with out_path.open("w") as f:
        f.write("# Wave 0 H — ZH-Cleaner Failure Probe Result\n\n")
        f.write(f"**Date:** 2026-05-22\n")
        f.write(f"**Article probed:** id={article_id} ({len(article_text)} chars, ZH)\n")
        f.write(f"**Model used:** GPT-5.5 via engine `llm.call('criteria_gen', ...)` — mirrors harness RACE_MODEL default.\n")
        f.write(f"**Latency:** {dt:.1f}s\n")
        f.write(f"**Error:** {err}\n")
        f.write(f"**Response chars:** {len(response) if response else 'n/a'}\n\n")
        f.write("## Classification\n\n")
        f.write(f"**Outcome:** {classification['outcome']}\n\n")
        f.write(f"**Fix path:** {classification['fix_path']}\n\n")
        if response is not None:
            f.write("## Response preview (first 500 chars)\n\n```\n")
            f.write(response[:500])
            f.write("\n```\n\n")
        f.write("## Method\n\n")
        f.write(
            "Loaded id=8's article from p1_artifacts/p1_final.jsonl. Formatted the harness's "
            "`clean_article_prompt_zh` (copied verbatim from "
            "/home/connor/dev/deep_research_bench/prompt/clean_prompt.py) with the article body. "
            "Called engine `llm.call('criteria_gen', ...)` which routes to GPT-5.5 (matching the "
            "harness's RACE_MODEL default). Captured response text, latency, and any exception.\n"
        )
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    article_id = sys.argv[1] if len(sys.argv) > 1 else "8"
    sys.exit(main(article_id))
