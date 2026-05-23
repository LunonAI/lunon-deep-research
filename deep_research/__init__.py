"""Standalone deep-research engine (P1).

Public contract (p1-checklist item 1):
    deep_research(query: str, language: str) -> {"article": str}

Benchmark-only. One module, one contract, one adapter (adapter.py).
"""

from ._env import assert_phase


def deep_research(query: str, language: str, task_id: int | None = None) -> dict:
    """Run the full pipeline for one task. language in {'en','zh'}.

    task_id (optional): DRB harness task id, used by P2-Wave-2-G's
    W9-readability fragile-density heuristic. Callers without an id (smoke
    runs, ad-hoc scripts) may omit it; G silently no-ops when absent.
    """
    from .engine import run

    return run(query, language, task_id=task_id)


__all__ = ["deep_research", "assert_phase"]
