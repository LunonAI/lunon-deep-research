"""Fetch the reference (or any DRB leaderboard model) articles directly from the
DeepResearch Bench Hugging Face Space so we can run direct Lunon-vs-reference
A/B judging against the live leaderboard's #1 vintage.

Why this exists:
  The reference submission at the top of the DRB leaderboard (model id
  `reference_deepresearch_0430`, overall 58.03) is only browseable via the
  HF Space data viewer — its article text is not in either of the two
  pasted .docx vendor corpora we have on hand, nor in the public Baidu
  GitHub repo (whose `reference-deepresearch[-pro]_datas/reports/<id>.md`
  files are a different, lower-scoring vintage at 54.48 / 53.07). An
  earlier converter in this branch tried to recover structure from
  copy-pasted .docx text using prose section-number regex, but the paste
  step had already flattened markdown tables to tab-separated rows and
  stripped **bold**/*italic* emphasis — biasing any A/B judge against
  the reference in ways unrelated to substance.

  The HF Space's Gradio `/fetch` endpoint, by contrast, returns the
  original markdown — tables, emphasis, footnotes, and headings intact.

Usage:
  python3 scripts/p2_reference_fetch_articles.py \\
    --model reference_deepresearch_0430 \\
    --ids 14,56,91 \\
    --out p2_artifacts/reference_articles.jsonl

Output schema (one line per id, matching `p2_within_task_ab.py`):
  {"id": <int>, "prompt": <str>, "article": <str>}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from gradio_client import Client

_SPACE = "muset-ai/DeepResearch-Bench-Leaderboard"
# The Space wraps the article in this header; strip it so consumers see the
# raw markdown the model produced. Leading whitespace after stripping is
# also removed via .lstrip() to keep output starting at the first heading.
_ARTICLE_HEADER_RE = re.compile(r"\A### Generated Article 📖\s*\n+")
# The user-task markdown the Space returns looks like:
#   ### User Task 🎯\n\n**Task ID:** 91\n\n**Description:** <prompt>
# Capture everything after "**Description:**" as the prompt.
_DESCRIPTION_RE = re.compile(r"\*\*Description:\*\*\s*(.+)", re.DOTALL)
# Dropdown choice strings the Space exposes are formatted "<id>. <prefix>…".
_TASK_DISP_ID_RE = re.compile(r"^(\d+)\.\s")


def _build_task_disp_map(client: Client) -> tuple[dict[int, str], set[str]]:
    """Return (id -> dropdown display string, set of valid model names)."""
    on_load = client.predict(api_name="/on_load")
    task_choices = on_load[1]["choices"]
    model_choices = on_load[0]["choices"]
    disp_by_id: dict[int, str] = {}
    for choice_value, _label in task_choices:
        m = _TASK_DISP_ID_RE.match(choice_value)
        if m:
            disp_by_id[int(m.group(1))] = choice_value
    models = {value for value, _label in model_choices}
    return disp_by_id, models


def _strip_article_wrapper(article_md: str) -> str:
    return _ARTICLE_HEADER_RE.sub("", article_md, count=1).lstrip()


def _extract_prompt(user_md: str) -> str:
    m = _DESCRIPTION_RE.search(user_md)
    return m.group(1).strip() if m else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--model",
        default="reference_deepresearch_0430",
        help="DRB leaderboard model name (default: live #1)",
    )
    ap.add_argument(
        "--ids",
        required=True,
        help="comma-separated DRB task ids to fetch (e.g. 14,56,91)",
    )
    ap.add_argument("--out", required=True, help="output jsonl path")
    ap.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="seconds to sleep between Space calls (default 0.5)",
    )
    args = ap.parse_args()

    try:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    except ValueError as exc:
        print(f"ERROR: --ids must be comma-separated ints, got {args.ids!r}: {exc}", file=sys.stderr)
        sys.exit(2)
    if not ids:
        print("ERROR: --ids resolved to empty list", file=sys.stderr)
        sys.exit(2)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    # Wrap both the Client constructor and the preflight metadata load —
    # both make network calls to the HF Space and share the same fatal
    # failure mode (transient outage, schema drift, DNS hiccup). Without
    # this, a Space blip surfaces as an uncaught traceback instead of a
    # clean error consistent with the per-task /fetch handler below.
    try:
        client = Client(_SPACE)
        disp_by_id, available_models = _build_task_disp_map(client)
    except Exception as exc:
        print(f"ERROR: failed to load Space metadata: {exc!r}", file=sys.stderr)
        sys.exit(2)
    if args.model not in available_models:
        print(
            f"ERROR: model {args.model!r} not on leaderboard. Available: {sorted(available_models)}",
            file=sys.stderr,
        )
        sys.exit(2)

    n_written = 0
    with Path(args.out).open("w", encoding="utf-8") as f:
        for tid in ids:
            disp = disp_by_id.get(tid)
            if disp is None:
                # No network call made — skip the throttle sleep.
                print(f"  WARN: task id {tid} not on leaderboard", file=sys.stderr)
                continue
            try:
                user_md, article_md, _html = client.predict(model=args.model, task_disp=disp, api_name="/fetch")
            except Exception as exc:
                print(f"  WARN: fetch failed for id={tid}: {exc!r}", file=sys.stderr)
                # Network call was made (and failed) — still throttle so
                # bursty errors don't hammer the Space.
                time.sleep(args.delay)
                continue
            article = _strip_article_wrapper(article_md)
            if not article:
                print(f"  WARN: empty article body for id={tid}", file=sys.stderr)
                time.sleep(args.delay)
                continue
            prompt = _extract_prompt(user_md)
            if not prompt:
                # Symmetric to the article guard above: a Space format drift
                # or a task genuinely missing its **Description:** marker
                # would otherwise produce a corrupt jsonl record (empty
                # prompt + valid article) that p2_within_task_ab.py would
                # judge against an empty task description.
                print(
                    f"  WARN: empty prompt for id={tid} (description marker missing?)",
                    file=sys.stderr,
                )
                time.sleep(args.delay)
                continue
            f.write(
                json.dumps(
                    {"id": tid, "prompt": prompt, "article": article},
                    ensure_ascii=False,
                )
                + "\n"
            )
            print(f"  ok: id={tid:>3}  article_chars={len(article):>7}")
            n_written += 1
            time.sleep(args.delay)

    print(f"[reference-fetch] wrote {n_written}/{len(ids)} articles to {args.out}")
    # Exit nonzero when any requested id failed to land in the output so a
    # CI caller (or shell `set -e`) can distinguish partial-failure from
    # the empty-`--ids` case rejected at the top of main(). Strict by
    # default — the per-task WARN lines above already explain which ids
    # are missing.
    if n_written != len(ids):
        sys.exit(1)


if __name__ == "__main__":
    main()
