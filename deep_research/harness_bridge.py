"""Bridge to the external DRB harness prompt machinery (LAZY import).

Centralizes the only coupling between the engine and the external
deep_research_bench harness so criteria-regeneration (item 14) and the
criteria-aware inner loop (item 15) use the harness's *own* prompts — the
property that makes them generalize (v4 §2.3 / technique 1), not overfit.

AUDIT A2 (2026-05-30): the harness imports used to run at MODULE-IMPORT time,
so importing `deep_research.harness_bridge` (and, transitively,
`pipeline.criteria_spec` → `orchestrate`) raised ModuleNotFoundError on any
machine / CI runner without the external repo on disk — which is what stopped
the test suite from importing the package at all. The harness import is now
DEFERRED to first use behind `_harness()` (cached). The package imports
standalone; the external repo is only required when criteria regeneration
actually runs, and its absence raises a clear, actionable error THERE rather
than a cryptic import failure at the top of the dependency graph.

Public surface (unchanged for callers):
- CRITERIA_PROMPTS[lang] -> {dim: template}      (criteria_prompt_{en,zh}.py)
- WEIGHT_PROMPT[lang]                              (dimension-weight template)
- score_prompt(language) -> generate_merged_score_prompt template
- extract_json_from_markdown(text)
- format_criteria_list(criteria_data)
The four module-level names resolve lazily via PEP 562 ``__getattr__``.
"""

import functools
import os
import sys

# Names that trigger the deferred harness import on first attribute access.
_LAZY_ATTRS = frozenset({"CRITERIA_PROMPTS", "WEIGHT_PROMPT", "format_criteria_list", "extract_json_from_markdown"})


def _drb_candidates() -> tuple:
    """Resolve candidate harness locations at CALL time, not import time.

    Honors `$DRB_REPO` first (the repo convention), then probes well-known
    per-machine locations. Evaluating these inside `_harness()` (rather than
    binding them to a module-level constant at import) means a caller that sets
    `$DRB_REPO` *after* importing this module — but before the first criteria
    regeneration — is still honored.
    """
    return (
        os.environ.get("DRB_REPO"),
        os.path.expanduser("~/dev/deep_research_bench"),
        "/home/connor/dev/deep_research_bench",  # legacy Linux path
    )


@functools.lru_cache(maxsize=1)
def _harness() -> dict:
    """Import the external DRB harness prompt modules on FIRST USE.

    Cached, so the import + sys.path insertion happen at most once. Raises a
    clear, deferred ImportError when the harness repo isn't on disk OR is
    present but missing an expected symbol — naming the env var and the searched
    paths — instead of the opaque top-of-import-graph failure this module used
    to produce.
    """
    candidates = _drb_candidates()
    drb = next((p for p in candidates if p and os.path.isdir(p)), None)
    if drb and drb not in sys.path:
        sys.path.insert(0, drb)
    try:
        from deepresearch_bench_race import format_criteria_list
        from prompt.criteria_prompt_en import (
            generate_eval_criteria_prompt_comp as en_comp,
        )
        from prompt.criteria_prompt_en import (
            generate_eval_criteria_prompt_insight as en_ins,
        )
        from prompt.criteria_prompt_en import (
            generate_eval_criteria_prompt_Inst as en_inst,
        )
        from prompt.criteria_prompt_en import (
            generate_eval_criteria_prompt_readability as en_read,
        )
        from prompt.criteria_prompt_en import (
            generate_eval_dimension_weight_prompt as en_weight,
        )
        from prompt.criteria_prompt_zh import (
            generate_eval_criteria_prompt_comp as zh_comp,
        )
        from prompt.criteria_prompt_zh import (
            generate_eval_criteria_prompt_insight as zh_ins,
        )
        from prompt.criteria_prompt_zh import (
            generate_eval_criteria_prompt_Inst as zh_inst,
        )
        from prompt.criteria_prompt_zh import (
            generate_eval_criteria_prompt_readability as zh_read,
        )
        from prompt.criteria_prompt_zh import (
            generate_eval_dimension_weight_prompt as zh_weight,
        )
        from prompt.score_prompt_en import generate_merged_score_prompt as en_score
        from prompt.score_prompt_zh import generate_merged_score_prompt as zh_score
        from utils.json_extractor import extract_json_from_markdown
    except ImportError as e:
        # ImportError (not just ModuleNotFoundError) so a harness that is on
        # disk but missing an expected symbol surfaces here with context,
        # rather than as a bare ImportError deep in the import machinery.
        raise ImportError(
            "DRB harness prompt machinery is not importable. Criteria "
            "regeneration (deep_research.pipeline.criteria_spec) requires the "
            "external deep_research_bench repo on disk. Set $DRB_REPO or place "
            f"it at ~/dev/deep_research_bench. Searched: {candidates}. "
            f"Underlying import error: {e}"
        ) from e
    return {
        "CRITERIA_PROMPTS": {
            "en": {
                "comprehensiveness": en_comp,
                "insight": en_ins,
                "instruction_following": en_inst,
                "readability": en_read,
            },
            "zh": {
                "comprehensiveness": zh_comp,
                "insight": zh_ins,
                "instruction_following": zh_inst,
                "readability": zh_read,
            },
        },
        "WEIGHT_PROMPT": {"en": en_weight, "zh": zh_weight},
        "_score": {"en": en_score, "zh": zh_score},
        "format_criteria_list": format_criteria_list,
        "extract_json_from_markdown": extract_json_from_markdown,
    }


def __getattr__(name: str):
    """PEP 562 lazy module attributes.

    `harness_bridge.CRITERIA_PROMPTS`, `.WEIGHT_PROMPT`, `.format_criteria_list`
    and `.extract_json_from_markdown` resolve on first access by triggering the
    deferred harness import — preserving the prior public attribute surface
    (callers like `criteria_spec` keep using `hb.CRITERIA_PROMPTS[lang]`
    unchanged) while keeping plain ``import`` side-effect-free.
    """
    if name in _LAZY_ATTRS:
        return _harness()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def score_prompt(language: str) -> str:
    return _harness()["_score"]["zh" if language == "zh" else "en"]
