"""W0 API + infra smoke. Run: /usr/bin/python3 -m deep_research.smoke

Tiny prompts to keep cost negligible. Verifies: DRB_PHASE guard (defaults to P1),
all 3 LLM providers (GPT-5.5 / Opus 4.8 / Nemotron-OpenRouter), Exa, Jina, and
that cost rows land in the ledger under phase P1.
"""

import json
import os
import pathlib
import sys

from . import assert_phase, llm
from .retrieval import exa, jina_reader

LEDGER = pathlib.Path(__file__).resolve().parent.parent / "cost_tracking" / "ledger.jsonl"


def _ledger_tail_phases(n=12):
    if not LEDGER.exists():
        return []
    lines = LEDGER.read_text(encoding="utf-8").strip().splitlines()[-n:]
    return [json.loads(x).get("phase") for x in lines]


def main():
    results = {}

    # 1. DRB_PHASE guard: unset defaults to P1, a bad value still fails loud
    saved = os.environ.get("DRB_PHASE")
    os.environ.pop("DRB_PHASE", None)
    results["phase_guard_default"] = "ok (defaults to P1)" if assert_phase() == "P1" else "FAIL (did not default)"
    os.environ["DRB_PHASE"] = "nonsense"
    try:
        assert_phase()
        results["phase_guard_invalid"] = "FAIL (did not raise)"
    except RuntimeError:
        results["phase_guard_invalid"] = "ok (raised as expected)"
    if saved:
        os.environ["DRB_PHASE"] = saved
    else:
        os.environ.pop("DRB_PHASE", None)
    results["phase_guard_positive"] = f"ok phase={assert_phase()}"

    # 2-4. three LLM providers
    try:
        results["gpt5.5"] = llm.call("intent", "Reply with exactly: OK_GPT", max_tokens=2000, reasoning_effort="low")[
            :40
        ]
    except Exception as e:  # noqa: BLE001
        results["gpt5.5"] = f"ERROR {type(e).__name__}: {e}"
    try:
        results["opus4.8"] = llm.call("writer", "Reply with exactly: OK_OPUS", max_tokens=200)[:40]
    except Exception as e:  # noqa: BLE001
        results["opus4.8"] = f"ERROR {type(e).__name__}: {e}"
    try:
        results["nemotron_or"] = llm.call("evidence_gatherer", "Reply with exactly: OK_NEMO", max_tokens=200)[:60]
    except Exception as e:  # noqa: BLE001
        results["nemotron_or"] = f"ERROR {type(e).__name__}: {e}"

    # 5. Exa
    try:
        hits = exa.search("what is commercial due diligence", num_results=3)
        results["exa"] = f"ok {len(hits)} hits; first={hits[0]['url'][:50] if hits else 'none'}"
    except Exception as e:  # noqa: BLE001
        results["exa"] = f"ERROR {type(e).__name__}: {e}"

    # 6. Jina
    try:
        txt = jina_reader.fetch("https://example.com", max_chars=400)
        results["jina"] = f"ok {len(txt)} chars" if txt else "EMPTY"
    except Exception as e:  # noqa: BLE001
        results["jina"] = f"ERROR {type(e).__name__}: {e}"

    # 7. cost ledger phase attribution
    results["ledger_recent_phases"] = _ledger_tail_phases()

    print(json.dumps(results, indent=2, ensure_ascii=False))
    bad = [k for k, v in results.items() if isinstance(v, str) and ("ERROR" in v or "FAIL" in v or v == "EMPTY")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
