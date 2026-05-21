"""Standalone deep-research engine (P1).

Public contract (p1-checklist item 1):
    deep_research(query: str, language: str) -> {"article": str}

Benchmark-only. One module, one contract, one adapter (adapter.py).
"""
from ._env import assert_phase


def deep_research(query: str, language: str) -> dict:
    """Run the full pipeline for one task. language in {'en','zh'}."""
    from .engine import run
    return run(query, language)


__all__ = ["deep_research", "assert_phase"]
