"""Pipeline orchestration entrypoint.

run(query, language) -> {"article": str}

Flow (assembled across W1-W5):
  intent -> archetype-route -> scout -> criteria_spec -> architect
  -> orchestrator(dispatch 5 specialists, isolated ctx) -> memory_bank
  -> writer(per-section WebWeaver retrieval) -> per-section quality loop
  (grounding -> inner_loop, regen-with-evidence-inline) -> assemble
  -> refiner(GPT-5.5, archetype-aware) -> [zh: zh_writer_pass]

DR_STUB=1 short-circuits to a trivial article — ONLY for adapter infra tests,
never for evals (eval paths must not set DR_STUB).
"""

import os

from . import assert_phase


def run(query: str, language: str, task_id: int | None = None) -> dict:
    assert_phase()
    if os.environ.get("DR_STUB") == "1":
        return {"article": f"[STUB:{language}] {query[:60]}"}
    from .orchestrate import pipeline  # assembled in W1-W5

    return {"article": pipeline(query, language, task_id=task_id)}
