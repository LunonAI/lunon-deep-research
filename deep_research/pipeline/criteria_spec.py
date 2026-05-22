"""Criteria-as-spec (p1-checklist item 14).

Regenerate per-task evaluation criteria from the prompt using the harness's OWN
criteria_prompt_{en,zh}.py templates + dimension-weight template (the same
procedure utils/generate_criteria.py runs). Using the harness's own prompts is
exactly what makes this generalize rather than overfit (v4 §2.3 / technique 1).

Output mirrors data/criteria_data/criteria.jsonl:
  {dimension_weight: {dim: w}, criterions: {dim: [{criterion, explanation, weight}]}}

Each sub-criterion is then foldable into the Architect plan as a coverage
obligation (architect.py).
"""

import json
import re

from .. import harness_bridge as hb
from .. import llm

_DIMS = ["comprehensiveness", "insight", "instruction_following", "readability"]
_JSON_OUT = re.compile(r"<json_output>(.*?)</json_output>", re.DOTALL | re.IGNORECASE)


def _parse_harness_json(text: str):
    """Replicate utils/generate_criteria.parse_llm_output_as_json — the harness
    criteria/weight prompts wrap output in <json_output>...</json_output>."""
    m = _JSON_OUT.search(text)
    s = m.group(1).strip() if m else text.strip()
    if s.startswith("```json"):
        s = s[7:]
    if s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    try:
        return json.loads(s.strip())
    except json.JSONDecodeError:
        return llm.extract_json(text)


def _grade_call(user: str) -> str:
    # criteria_gen role = GPT-5.5; faithful to the harness LLM-as-generator step.
    return llm.call("criteria_gen", user, max_tokens=9000, effort="medium", seed=7, note="criteria_gen")


def regenerate(prompt: str, language: str) -> dict:
    lang = "zh" if language == "zh" else "en"
    templates = hb.CRITERIA_PROMPTS[lang]

    def _one_dim(dim):
        user = templates[dim].format(task_prompt=prompt)
        data = None
        for _ in range(2):  # harness RETRY_ATTEMPTS pattern
            data = _parse_harness_json(_grade_call(user))
            if isinstance(data, list) and data:
                break
        if isinstance(data, dict) and "criteria" in data:
            data = data["criteria"]
        return dim, (data if isinstance(data, list) else [])

    # 4 dims + weight call run concurrently (independent GPT-5.5 calls)
    from concurrent.futures import ThreadPoolExecutor

    wuser = hb.WEIGHT_PROMPT[lang].format(task_prompt=prompt)
    with ThreadPoolExecutor(max_workers=5) as ex:
        fut_w = ex.submit(lambda: _parse_harness_json(_grade_call(wuser)))
        criterions = dict(ex.map(_one_dim, _DIMS))
        w = fut_w.result()
    weights = {}
    if isinstance(w, dict):
        for d in _DIMS:
            try:
                weights[d] = float(w.get(d, w.get(d.split("_")[0], 0)) or 0)
            except (TypeError, ValueError):
                weights[d] = 0.0
    if not any(weights.values()):  # harness static fallback ratios (v4 §2.3)
        weights = {"comprehensiveness": 0.29, "insight": 0.35, "instruction_following": 0.21, "readability": 0.15}

    return {"dimension_weight": weights, "criterions": criterions}


def as_coverage_obligations(spec: dict) -> list:
    """Flatten regenerated sub-criteria into Architect acceptance obligations."""
    out = []
    for dim, items in (spec.get("criterions") or {}).items():
        for c in items:
            if isinstance(c, dict) and c.get("criterion"):
                out.append(
                    {
                        "dimension": dim,
                        "criterion": c["criterion"],
                        "explanation": c.get("explanation", ""),
                        "weight": c.get("weight", 0),
                    }
                )
    return out
