"""Per-role model registry (p1-checklist items 3 & 19).

Every role is swappable at runtime via env `DR_ROLE_<ROLE>=<model-id>` with no
code change / no recompile, so P2 ablations can swap any role. Provider is
inferred from the model id prefix by llm.py.

Model stack (p1-checklist:13-18; divergences logged in plan + SUMMARY):
- Orchestrator/Planner/Scout/Architect/Writer = Claude Opus 4.7
- 5 researcher specialists = Nemotron-3-Super-120B via OpenRouter (paid slug; decision #1)
- Intent / criteria-gen / archetype / inner-loop scorer / grounding / Refiner = GPT-5.5
- ZH writer-pass = chosen at W6 (Qwen3-235B vs DeepSeek-V3.2 via OpenRouter)
"""

import os

GPT55 = "gpt-5.5"
OPUS = "claude-opus-4-8"  # 2026-05-30: 4.7->4.8 (same $5/$25 price, same tokenizer; better effort calibration, adaptive-thinking efficiency, 128k output, cleaner high-max_tokens streaming verified by probe)
NEMOTRON = "nvidia/nemotron-3-super-120b-a12b"  # OpenRouter PAID slug (decision #1)

# ZH writer-pass candidates (OpenRouter); winner wired in after W6 smoke.
# AUDIT F3 (2026-05-30): the shipped default (zh_writer below) is
# deepseek-v4-pro, but it was missing from this candidate list, so a re-run of
# select_zh_writer() could never re-pick the model actually in production. Added
# it as the first candidate (it won W6 by +0.60).
ZH_WRITER_CANDIDATES = ["deepseek/deepseek-v4-pro", "qwen/qwen3-235b-a22b", "deepseek/deepseek-v3.2-exp"]

_DEFAULTS = {
    "orchestrator": OPUS,
    "planner": OPUS,
    "scout": OPUS,
    "architect": OPUS,
    "writer": OPUS,
    "intent": GPT55,
    "archetype": GPT55,
    "criteria_gen": GPT55,
    "inner_scorer": GPT55,
    "grounding": GPT55,
    "refiner": GPT55,
    "refiner_gate": GPT55,  # ART-style pre/post judge (plan v3 §3b)
    # researcher specialists (all Nemotron; isolated contexts per specialist)
    "evidence_gatherer": NEMOTRON,
    "mechanism_explorer": NEMOTRON,
    "comparator": NEMOTRON,
    "critic": NEMOTRON,
    "horizon_scanner": NEMOTRON,
    "generalist": NEMOTRON,
    # W6 winner (2026-05-20 retry w/ robust critic):
    # DeepSeek-V4-Pro mean 8.00 > Qwen3-235B 7.40 > DeepSeek-V3.2-exp 6.6.
    # V4 Pro wins by +0.60 (>0.5 keep threshold). Apache-2.0.
    "zh_writer": os.environ.get("DR_ROLE_ZH_WRITER", "deepseek/deepseek-v4-pro"),
    # Readability rewrite (2026-06-08): the validated whole-article tighten/restructure
    # pass (readability 0.427->0.51, overall 0.527->0.54). Opus won Opus-vs-GPT-5.5.
    "readability_rewriter": os.environ.get("DR_ROLE_READABILITY_REWRITER", OPUS),
    # P2-Wave-1-D: embedding model for D1 cosine-clustering evidence dedup.
    # text-embedding-3-small is deterministic, cheap (~$0.02 per 1M tokens),
    # multilingual (handles EN+ZH), and is the OpenAI workhorse 1536-dim model.
    "embedder": "text-embedding-3-small",
}


def model_for(role: str) -> str:
    """Resolve a role to a model id. Env override `DR_ROLE_<ROLE>` wins."""
    if role not in _DEFAULTS:
        raise KeyError(f"unknown role {role!r}; known: {sorted(_DEFAULTS)}")
    return os.environ.get(f"DR_ROLE_{role.upper()}", _DEFAULTS[role])


def all_roles() -> dict:
    return {r: model_for(r) for r in _DEFAULTS}


# Reasoning effort for the Opus generation roles (2026-05-30). Opus 4.8 accepts
# low|medium|high|xhigh|max ("high" == omitting the param). We default the
# report-content roles to `max`: the leaderboard score, not cost, is the
# objective, and effort carries NO per-token premium -- it only changes how many
# tokens are spent (billed at the standard $5/$25). A/B by setting DR_OPUS_EFFORT
# (global) or DR_EFFORT_<ROLE> (per role), e.g. DR_EFFORT_ARCHITECT=xhigh.
#
# Applied ONLY on the anthropic path (see llm.call -> anthropic_client): xhigh/max
# are anthropic-only effort levels, and only when think=True is the effort passed
# through (output_config.effort). The gpt-5.5 / openrouter roles never receive it.
def effort_for(role: str) -> str:
    """Resolve the reasoning-effort level for an Opus generation `role`.
    Precedence: DR_EFFORT_<ROLE> -> DR_OPUS_EFFORT -> 'low'.

    Default is 'low' (2026-05-31): dev8 proved effort=max/high OVER-GENERATES —
    the architect's JSON plan truncated at the 64k ceiling on every call, and the
    writer ran sections to 56-96k tokens (vs ~8.5k baseline) for NO leaderboard-score
    gain (we already beat the reference on all dims). 'max' as the default was a live
    over-generation/truncation bug. 'low' restores the proven pre-#86 behavior that
    scored 0.582. Raise per-role via DR_EFFORT_<ROLE> or globally via DR_OPUS_EFFORT
    only with a measured A/B that shows a score gain."""
    return os.environ.get(f"DR_EFFORT_{role.upper()}") or os.environ.get("DR_OPUS_EFFORT") or "low"
