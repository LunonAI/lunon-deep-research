"""Bridge to the external DRB harness prompt machinery (read-only import).

Centralizes the only coupling between the engine and
/home/connor/dev/deep_research_bench so criteria-regeneration (item 14) and the
criteria-aware inner loop (item 15) use the harness's *own* prompts — the
property that makes them generalize (v4 §2.3 / technique 1), not overfit.

Exposes:
- CRITERIA_PROMPTS[lang] -> {dim: template}      (criteria_prompt_{en,zh}.py)
- WEIGHT_PROMPT[lang]                              (dimension-weight template)
- score_prompt(lang)  -> generate_merged_score_prompt template
- extract_json_from_markdown(text)
- format_criteria_list(criteria_data)
"""
import sys

_DRB = "/home/connor/dev/deep_research_bench"
if _DRB not in sys.path:
    sys.path.insert(0, _DRB)

from prompt.criteria_prompt_en import (  # noqa: E402
    generate_eval_dimension_weight_prompt as _en_weight,
    generate_eval_criteria_prompt_comp as _en_comp,
    generate_eval_criteria_prompt_insight as _en_ins,
    generate_eval_criteria_prompt_Inst as _en_inst,
    generate_eval_criteria_prompt_readability as _en_read,
)
from prompt.criteria_prompt_zh import (  # noqa: E402
    generate_eval_dimension_weight_prompt as _zh_weight,
    generate_eval_criteria_prompt_comp as _zh_comp,
    generate_eval_criteria_prompt_insight as _zh_ins,
    generate_eval_criteria_prompt_Inst as _zh_inst,
    generate_eval_criteria_prompt_readability as _zh_read,
)
from prompt.score_prompt_en import generate_merged_score_prompt as _en_score  # noqa: E402
from prompt.score_prompt_zh import generate_merged_score_prompt as _zh_score  # noqa: E402
from utils.json_extractor import extract_json_from_markdown  # noqa: E402,F401
from deepresearch_bench_race import format_criteria_list  # noqa: E402,F401

CRITERIA_PROMPTS = {
    "en": {"comprehensiveness": _en_comp, "insight": _en_ins,
           "instruction_following": _en_inst, "readability": _en_read},
    "zh": {"comprehensiveness": _zh_comp, "insight": _zh_ins,
           "instruction_following": _zh_inst, "readability": _zh_read},
}
WEIGHT_PROMPT = {"en": _en_weight, "zh": _zh_weight}


def score_prompt(language: str) -> str:
    return _zh_score if language == "zh" else _en_score
