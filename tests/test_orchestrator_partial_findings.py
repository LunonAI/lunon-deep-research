"""Pin the round-4 partial-findings-on-timeout behavior.

Before round 4, a specialist that exceeded the wall-clock cap had its ENTIRE
coverage dropped (the orchestrator caught TimeoutError and `continue`d). Now
`_research_with_timeout` passes a shared `sink` into `research()` and, on
timeout, returns the partial findings gathered before the cut, flagged
`timed_out=True` so the caller still bumps timeout telemetry but ingests the
partial coverage instead of discarding it.

Most tests exercise `_research_with_timeout` directly with a fake `research`
so they stay offline (no Exa / model calls). The CONTRACT test at the bottom
exercises the REAL `specialists.research` with a stubbed search — it would have
caught the Greptile-flagged regression where `research()` lacked the `sink`
kwarg the orchestrator passes (every specialist crashed, all evidence lost).
"""

import time

from deep_research.pipeline import orchestrator
from deep_research.pipeline import specialists


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


def _fake_search(qtext, *, language, domain, mode, num_results):
    """Offline stub for domain_routed.search — returns one fake hit."""
    return [
        {
            "title": "Stub Source",
            "url": "https://example.com/x",
            "text": "A grounded snippet of evidence about the topic under study.",
            "published_date": "2026-01-01",
        }
    ]


def test_real_research_accepts_sink_and_populates_it(monkeypatch):
    """CONTRACT TEST (Greptile PR #87 regression guard): the REAL
    specialists.research must accept the `sink` kwarg the orchestrator passes
    and write its progress through it. The prior bug — research() missing the
    sink param — made every specialist raise TypeError (swallowed by the broad
    except in run()), losing ALL web evidence. The other tests monkeypatch
    research and so could not catch it; this one calls the real function with a
    stubbed (offline) search."""
    monkeypatch.setattr(specialists.domain_routed, "search", _fake_search)
    sink = {"findings": [], "n_searches": 0}
    res = specialists.research(
        "evidence_gatherer",
        [{"id": "Q1", "text": "what is the topic", "target_sections": ["S1"]}],
        language="en",
        domain="default",
        exa_mode="auto",
        sink=sink,
    )
    # research returned normally (no TypeError) ...
    assert res["role"] == "evidence_gatherer"
    assert res["n_searches"] == 1
    # ... and the sink was populated, so a timeout would recover partial coverage.
    assert sink["n_searches"] == 1
    assert isinstance(sink["findings"], list)


def test_orchestrator_calls_research_with_sink_kwarg():
    """Belt-and-suspenders: the kwargs _research_with_timeout passes to
    research() must be a SUBSET of research()'s real parameters, so a future
    signature drift (like the PR #87 missing-sink bug) fails loudly here rather
    than silently at runtime under the broad except."""
    import inspect

    params = set(inspect.signature(specialists.research).parameters)
    # The orchestrator passes these to research() via _research_with_timeout.
    passed = {"role", "queries", "language", "domain", "exa_mode", "model_override", "sink"}
    # `role`/`queries` are positional; the rest keyword. All must exist.
    missing = passed - params - {"role", "queries"}
    assert not missing, f"research() is missing params the orchestrator passes: {missing}"
