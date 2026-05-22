"""Intent extraction before Scout (p1-checklist item 4; arXiv 2603.27435).

GPT-5.5 extracts the user's explicit + implicit intents/requirements from the
prompt. These are injected into the Architect plan as explicit coverage targets
(folded into acceptance_criteria) so instruction-following is anchored early.
"""

from .. import llm

_SYSTEM = (
    "You extract the user's research intents from a deep-research prompt. "
    'Output ONLY JSON: {"intents": [ {"intent": str, "kind": '
    '"explicit"|"implicit", "deliverable": str} ... ]}. '
    "explicit = stated verbatim in the prompt (named entities, required "
    "dimensions, requested metrics, time frames, the final ask). implicit = a "
    "requirement a domain expert would infer is necessary to satisfy the "
    "explicit ask (e.g. baseline definitions, comparison axes, risk framing). "
    "Each `deliverable` states the concrete artifact that satisfies the intent "
    "(a table, a ranking, a number, a recommendation, a causal chain). "
    "Be exhaustive on explicit intents; 6-16 total. Match the prompt's language."
)


def extract(prompt: str, language: str) -> list:
    """Return list[{intent, kind, deliverable}]."""
    obj = llm.call_json(
        "intent",
        f"Prompt language: {language}\n\nPROMPT:\n{prompt}\n\nExtract the intents as specified.",
        system=_SYSTEM,
        max_tokens=6000,
        reasoning_effort="medium",
        seed=7,
        note="intent",
    )
    intents = obj.get("intents") if isinstance(obj, dict) else obj
    return intents if isinstance(intents, list) else []
