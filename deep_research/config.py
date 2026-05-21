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
OPUS = "claude-opus-4-7"
NEMOTRON = "nvidia/nemotron-3-super-120b-a12b"  # OpenRouter PAID slug (decision #1)

# ZH writer-pass candidates (OpenRouter); winner wired in after W6 smoke.
ZH_WRITER_CANDIDATES = ["qwen/qwen3-235b-a22b", "deepseek/deepseek-v3.2-exp"]

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
}


def model_for(role: str) -> str:
    """Resolve a role to a model id. Env override `DR_ROLE_<ROLE>` wins."""
    if role not in _DEFAULTS:
        raise KeyError(f"unknown role {role!r}; known: {sorted(_DEFAULTS)}")
    return os.environ.get(f"DR_ROLE_{role.upper()}", _DEFAULTS[role])


def all_roles() -> dict:
    return {r: model_for(r) for r in _DEFAULTS}
