"""Archetype router (p1-checklist item 16).

Classifies a prompt into one of 6 archetypes using the EXACT classifier system
prompt from p0_artifacts/archetype_classify.py (so runtime classification
matches the precomputed p0_artifacts/archetype_map.jsonl distribution).

Drives: Exa Auto vs Deep (item 10 — deep for explain-mechanism|predict),
specialist mix, archetype-specific writer/refiner emphasis.
"""

from . import llm

ARCHETYPES = ["list-all", "compare", "trend", "explain-mechanism", "predict", "recommend"]

# Verbatim from p0_artifacts/archetype_classify.py SYSTEM (single-prompt form).
_SYSTEM = (
    "You are a precise task-intent classifier for deep-research prompts "
    "(prompts may be English or Chinese). Assign the SINGLE dominant archetype "
    "from this closed set:\n"
    "- list-all: compile/collect/enumerate a comprehensive set of items "
    "('list all', 'gather and organize', '收集整理', '盘点').\n"
    "- compare: cross-compare named entities/options along dimensions "
    "('compare X vs Y', '横向比较', 'pros and cons of each').\n"
    "- trend: track evolution/change over time, developments, history-to-now "
    "trajectory, current state of a fast-moving area ('发展趋势', 'latest').\n"
    "- explain-mechanism: explain how/why something works, the causal "
    "mechanism, principles, root causes ('原理', 'how does', 'why does').\n"
    "- predict: forecast a future state, outlook, potential, what will happen "
    "('未来', 'predict', 'forecast', 'potential', 'projection').\n"
    "- recommend: advise an action/choice, pick the best option, what should "
    "be done ('推荐', 'recommend', 'which should I', 'best strategy', '评估出最').\n"
    "Pick the dominant intent if multiple apply. Output ONLY a JSON object "
    '{"archetype": "<one of the set>", "rationale": "<<=18 words>"}.'
)

# Archetypes whose heaviest multi-hop reasoning warrants Exa Deep (item 10).
DEEP_ARCHETYPES = {"explain-mechanism", "predict"}


def classify(prompt: str) -> dict:
    """Return {'archetype': str, 'rationale': str}."""
    obj = llm.call_json(
        "archetype",
        "Classify this prompt. Return the JSON object only.\n\n" + prompt,
        system=_SYSTEM,
        max_tokens=4000,
        reasoning_effort="low",
        seed=7,
        note="archetype",
    )
    if not isinstance(obj, dict):  # B-13 defensive: coerce list/other → dict
        obj = obj[0] if isinstance(obj, list) and obj and isinstance(obj[0], dict) else {}
    a = str(obj.get("archetype", "")).strip().lower()
    if a not in ARCHETYPES:
        a = "list-all"  # safe high-coverage default
    return {"archetype": a, "rationale": obj.get("rationale", "")}


def uses_deep_exa(archetype: str) -> bool:
    return archetype in DEEP_ARCHETYPES
