"""ART-style refiner gate (plan v3 §3b, Branch B = monitor-mode).

Pulls from:
  - ART (arXiv 2311.07961): "self-refinement is detrimental in the majority of cases"
  - Refine-n-Judge (arXiv 2508.01543): judge picks the better of pre/post
  - Mr Dre (arXiv 2601.13217): DRAs regress on 16-27% of revised content

Pattern: after the refiner runs, compare pre-refiner draft to post-refiner article
via an LLM judge. Log the verdict to `cost_tracking/ledger.jsonl`. In **monitor
mode** (P1 default): NEVER actually revert — just log telemetry. The active-revert
behavior is gated on Step 1c (refiner_value_analysis.md) which currently lacks
counterfactual data; we collect Step 4 telemetry first, graduate to active in P2.

The 0.02 revert threshold is a placeholder and flagged as a P2 calibration item
(proper calibration requires measuring inner_loop scorer test-retest variance).
"""
import json

from .. import llm
from .._env import log_usage


_MODE_MONITOR = "monitor"  # log only, never revert
_MODE_ACTIVE = "active"    # revert if judge says pre > post + threshold

# Threshold: post must be at least this much worse than pre to trigger a revert
# in active mode. 0.02 is a heuristic — see P2 calibration TODO.
_REVERT_THRESHOLD = 0.02

_SYSTEM = (
    "You are a strict research-report comparison judge using the "
    "DeepResearch-Bench RACE rubric. You receive TWO versions of the SAME "
    "report (PRE = before final refiner pass, POST = after refiner). Compare "
    "them on the four dimensions: Comprehensiveness, Insight, Instruction-"
    "Following, Readability. Reward depth, specificity, quantified evidence, "
    "explicit mechanisms, clean structure, NON-redundancy, NO meta-commentary, "
    "consistent numbering. Penalize verbose padding, repetition across "
    "sections, future-dated speculation without sources, methodology disclaimers. "
    "\n\nOutput ONLY JSON: {\"winner\": \"PRE\"|\"POST\"|\"TIE\", "
    "\"delta\": number in [-1.0, +1.0] (positive = POST better, negative = PRE "
    "better; ~0.0 = tie), \"rationale\": str (one sentence naming the deciding "
    "factor)}."
)


def compare(pre_article: str, post_article: str, *, language: str,
            archetype: str = "", task_fp: str = "", mode: str = _MODE_MONITOR
            ) -> dict:
    """Compare pre/post refiner versions of a report.

    Returns dict: {decision, winner, delta, rationale, action, mode}.
    - decision: "keep_post" (default) | "revert_to_pre" (only in active mode)
    - action describes what the gate DID (in monitor mode, action is always
      'logged_only' regardless of winner)
    """
    # Truncate to fit context window — keep first + last portions of each
    # article (head + tail), since middle content is usually less diagnostic
    def trim(t: str, limit: int = 12000) -> str:
        if len(t) <= limit:
            return t
        half = limit // 2
        return t[:half] + "\n\n[... truncated ...]\n\n" + t[-half:]

    user = (
        f"LANGUAGE: {language}\nARCHETYPE: {archetype}\n\n"
        f"PRE (before final refiner):\n{trim(pre_article)}\n\n"
        f"POST (after refiner):\n{trim(post_article)}"
    )

    try:
        verdict = llm.call_json(
            "refiner_gate", user, system=_SYSTEM, max_tokens=400,
            seed=0, effort="low", note="refiner_gate"
        )
    except Exception as e:  # noqa: BLE001 — gate is advisory, never block ship
        verdict = {"winner": "TIE", "delta": 0.0,
                   "rationale": f"gate-error: {type(e).__name__}",
                   "degraded": True}

    if not isinstance(verdict, dict):
        verdict = {"winner": "TIE", "delta": 0.0,
                   "rationale": "non-dict gate output", "degraded": True}

    winner = verdict.get("winner", "TIE")
    delta = float(verdict.get("delta", 0.0) or 0.0)
    rationale = verdict.get("rationale", "")[:200]

    # Decide what the gate WOULD do; what it ACTUALLY does depends on mode
    would_revert = (winner == "PRE" and delta <= -_REVERT_THRESHOLD)
    if mode == _MODE_ACTIVE:
        decision = "revert_to_pre" if would_revert else "keep_post"
        action = "reverted_to_pre" if would_revert else "kept_post"
    else:
        # Monitor mode: log only, never revert
        decision = "keep_post"
        action = "logged_only_would_revert" if would_revert else "logged_only"

    # Audit log to ledger so we can replay decisions in P2 calibration
    log_usage(
        "refiner_gate",
        {},  # token counts already captured by the inner llm.call_json
        note=(
            f"refiner_gate mode={mode} winner={winner} delta={delta:+.3f} "
            f"action={action} task_fp={task_fp[:60]}"
        ),
    )

    return {
        "decision": decision,
        "winner": winner,
        "delta": delta,
        "rationale": rationale,
        "action": action,
        "mode": mode,
        "would_revert": would_revert,
        "pre_words": len(pre_article.split()),
        "post_words": len(post_article.split()),
    }
