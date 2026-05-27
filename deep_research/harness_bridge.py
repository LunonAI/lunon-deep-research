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

import os
import sys

# DRB harness location discovery. Honor `$DRB_REPO` first (the repo
# convention), then probe well-known per-machine locations. The prior
# hardcoded `/home/connor/dev/deep_research_bench` was a Linux-only
# path baked in when the project lived on the old laptop; it broke
# every import on the current Mac, which collapsed pytest collection
# for any test transitively depending on this module
# (`tests/test_orchestrate_xref_repair_wiring.py`,
# `tests/test_drift_instrumentation.py`). When none of the candidates
# resolve, leave sys.path alone and let the downstream
# `from deepresearch_bench_race import …` raise its native
# ModuleNotFoundError so the failure mode is clear.
_DRB_CANDIDATES = (
    os.environ.get("DRB_REPO"),
    os.path.expanduser("~/dev/deep_research_bench"),
    "/home/connor/dev/deep_research_bench",  # legacy Linux path
)
_DRB = next((p for p in _DRB_CANDIDATES if p and os.path.isdir(p)), None)
if _DRB and _DRB not in sys.path:
    sys.path.insert(0, _DRB)

from deepresearch_bench_race import format_criteria_list  # noqa: E402,F401
from prompt.criteria_prompt_en import (
    generate_eval_criteria_prompt_comp as _en_comp,
)
from prompt.criteria_prompt_en import (
    generate_eval_criteria_prompt_insight as _en_ins,
)
from prompt.criteria_prompt_en import (
    generate_eval_criteria_prompt_Inst as _en_inst,
)
from prompt.criteria_prompt_en import (
    generate_eval_criteria_prompt_readability as _en_read,
)
from prompt.criteria_prompt_en import (  # noqa: E402
    generate_eval_dimension_weight_prompt as _en_weight,
)
from prompt.criteria_prompt_zh import (
    generate_eval_criteria_prompt_comp as _zh_comp,
)
from prompt.criteria_prompt_zh import (
    generate_eval_criteria_prompt_insight as _zh_ins,
)
from prompt.criteria_prompt_zh import (
    generate_eval_criteria_prompt_Inst as _zh_inst,
)
from prompt.criteria_prompt_zh import (
    generate_eval_criteria_prompt_readability as _zh_read,
)
from prompt.criteria_prompt_zh import (  # noqa: E402
    generate_eval_dimension_weight_prompt as _zh_weight,
)
from prompt.score_prompt_en import generate_merged_score_prompt as _en_score  # noqa: E402
from prompt.score_prompt_zh import generate_merged_score_prompt as _zh_score  # noqa: E402
from utils.json_extractor import extract_json_from_markdown  # noqa: E402,F401

CRITERIA_PROMPTS = {
    "en": {
        "comprehensiveness": _en_comp,
        "insight": _en_ins,
        "instruction_following": _en_inst,
        "readability": _en_read,
    },
    "zh": {
        "comprehensiveness": _zh_comp,
        "insight": _zh_ins,
        "instruction_following": _zh_inst,
        "readability": _zh_read,
    },
}
WEIGHT_PROMPT = {"en": _en_weight, "zh": _zh_weight}


def score_prompt(language: str) -> str:
    return _zh_score if language == "zh" else _en_score
