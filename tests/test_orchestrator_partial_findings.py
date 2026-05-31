"""Pin the round-4 partial-findings-on-timeout behavior.

Before round 4, a specialist that exceeded the wall-clock cap had its ENTIRE
coverage dropped (the orchestrator caught TimeoutError and `continue`d). Now
`_research_with_timeout` passes a shared `sink` into `research()` and, on
timeout, returns the partial findings gathered before the cut, flagged
`timed_out=True` so the caller still bumps timeout telemetry but ingests the
partial coverage instead of discarding it.

These tests exercise `_research_with_timeout` directly with a fake `research`
so they stay offline (no Exa / model calls).
"""

import time

from deep_research.pipeline import orchestrator


def _slow_research_that_fills_sink(role, qlist, *, language, domain, exa_mode, model_override="", sink=None):
    """Fake specialist: write two partial findings into the sink, then block
    well past any test timeout so the caller must time out."""
    if sink is not None:
        sink["n_searches"] = 1
        sink["findings"].append({"text": "atom-1", "url": "u1"})
        sink["findings"].append({"text": "atom-2", "url": "u2"})
        sink["n_searches"] = 2
    time.sleep(30)  # exceed the tiny test timeout; never actually returns
    return {"role": role, "findings": sink["findings"] if sink else [], "n_searches": 2}


def _fast_research(role, qlist, *, language, domain, exa_mode, model_override="", sink=None):
    findings = [{"text": "done", "url": "u"}]
    if sink is not None:
        sink["findings"].extend(findings)
        sink["n_searches"] = 1
    return {"role": role, "findings": findings, "n_searches": 1}


def test_timeout_returns_partial_findings(monkeypatch):
    monkeypatch.setattr(orchestrator, "research", _slow_research_that_fills_sink)
    res = orchestrator._research_with_timeout(
        "horizon_scanner",
        [{"text": "q"}],
        language="en",
        domain="tech",
        exa_mode="auto",
        model_override="",
        timeout_s=1,
    )
    # the whole role is NOT dropped — partial coverage survives
    assert res["timed_out"] is True
    assert len(res["findings"]) == 2, f"expected 2 partial findings, got {res['findings']}"
    assert res["n_searches"] == 2
    assert res["role"] == "horizon_scanner"


def test_normal_completion_has_no_timeout_flag(monkeypatch):
    monkeypatch.setattr(orchestrator, "research", _fast_research)
    res = orchestrator._research_with_timeout(
        "comparator",
        [{"text": "q"}],
        language="en",
        domain="tech",
        exa_mode="auto",
        model_override="",
        timeout_s=10,
    )
    assert not res.get("timed_out")
    assert len(res["findings"]) == 1
