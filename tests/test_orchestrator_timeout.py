"""Tests for the per-specialist wall-clock timeout layer in orchestrator.run.

The 2026-05-25 CAPEL smoke for id=56 hung indefinitely because the 5th
specialist (horizon_scanner) got stuck mid-flight (either in an Exa search
or its Nemotron extract) and the orchestrator's `for role in order:` loop
had no per-iteration wall-clock bound. Only the OpenRouter HTTP layer's
180s × 3 retries capped any single LLM call, leaving inter-call hangs
unbounded.

The fix wraps each `research(role, ...)` call in a ThreadPoolExecutor with
`.result(timeout=240)`. On expiry the specialist's findings are dropped,
a TIMEOUT marker is appended to the digest, an `n_specialist_timeouts`
counter increments, and the loop continues to the next role.

These tests prove:
  - a hung specialist gets killed at the wall-clock cap (not waited on)
  - the orchestrator continues past it (does NOT crash the task)
  - the telemetry counter increments correctly
  - non-timeout failures still use the existing snippet_fallback / log path
"""

import concurrent.futures
import time

from deep_research.pipeline import orchestrator


def _hang_research(*_args, **_kwargs):
    """Simulate a hung specialist — sleep longer than any reasonable cap."""
    time.sleep(60)
    return {"role": "?", "findings": [], "n_searches": 0}


def _fast_research(*_args, role="generalist", **_kwargs):
    """Simulate a healthy specialist — returns one stub finding instantly."""
    return {
        "role": role,
        "findings": [
            {"statement": "stub", "source_name": "T", "url": "u", "quote": "q", "query_ids": ["Q1"]},
        ],
        "n_searches": 1,
    }


def test_research_with_timeout_kills_hung_specialist(monkeypatch):
    """The _research_with_timeout helper must raise concurrent.futures.TimeoutError
    when the underlying research() call exceeds the wall-clock cap. Pre-fix
    there was no helper — a hung research() call had no bound."""
    # Monkeypatch research to hang for longer than the timeout.
    monkeypatch.setattr(orchestrator, "research", _hang_research)

    t0 = time.time()
    try:
        orchestrator._research_with_timeout(
            "evidence_gatherer",
            [{"id": "Q1", "text": "x", "target_sections": []}],
            language="en",
            domain="default",
            exa_mode="auto",
            model_override="",
            timeout_s=1.5,  # short timeout for fast test
        )
        raised = None
    except concurrent.futures.TimeoutError as e:
        raised = e
    elapsed = time.time() - t0

    assert raised is not None, "timeout must raise concurrent.futures.TimeoutError"
    # Must surface within ~timeout_s, not wait the full sleep(60). Allow
    # generous headroom (5s) for thread scheduling overhead.
    assert elapsed < 5.0, f"_research_with_timeout took {elapsed:.1f}s; should have surfaced near the 1.5s cap"


def test_orchestrator_continues_after_specialist_timeout(monkeypatch, capsys):
    """When one specialist hangs and times out, the orchestrator must
    complete the task (without that specialist's findings) — NOT raise
    an exception or stall the whole pipeline. This is the regression
    fix for the 2026-05-25 CAPEL smoke incident.

    Greptile PR #26 round-3 follow-up (2026-05-26): also asserts the
    main-loop timeout handler emits a `[orchestrator] main-loop role=X
    TIMEOUT after Ns; skipping` line on stderr — symmetric with the
    gap-fill handler. Pre-fix the main loop only appended to digest_parts
    (which isn't real-time and may be compacted away by COMPACT_EVERY=8),
    leaving an operator tailing stderr during a dev-run with no signal
    that a specialist had timed out."""
    calls = {"hang": 0, "fast": 0}

    def fake_research(role, qlist, **kw):
        if role == "horizon_scanner":
            calls["hang"] += 1
            time.sleep(60)  # hang
            return {"role": role, "findings": [], "n_searches": 0}
        calls["fast"] += 1
        return _fast_research(role=role)

    monkeypatch.setattr(orchestrator, "research", fake_research)
    monkeypatch.setattr(orchestrator, "_gap_review", lambda *_a, **_kw: {"review": [], "gap_fill": []})
    monkeypatch.setattr(orchestrator, "_compact", lambda *_a, **_kw: "")
    # Shrink the timeout so the test runs fast.
    monkeypatch.setattr(orchestrator, "_SPECIALIST_TIMEOUT_S", 1.5)

    # Plan with queries routed to multiple roles, including horizon_scanner.
    plan = {
        "queries": [
            {"id": "Q1", "text": "q1", "specialist_role": "evidence_gatherer", "target_sections": ["S1"]},
            {"id": "Q2", "text": "q2", "specialist_role": "horizon_scanner", "target_sections": ["S1"]},
            {"id": "Q3", "text": "q3", "specialist_role": "critic", "target_sections": ["S1"]},
        ],
        "report_toc": [{"id": "S1", "title": "x"}],
    }

    t0 = time.time()
    result = orchestrator.run(plan, prompt="p", language="en", archetype="trend", domain="default")
    elapsed = time.time() - t0

    # Critical: the run COMPLETED rather than hanging. Pre-fix this would
    # have hung indefinitely on horizon_scanner.
    assert result is not None
    assert "memory_bank" in result
    # The timeout counter must have incremented for the hung specialist.
    assert result["n_specialist_timeouts"] >= 1, (
        f"n_specialist_timeouts={result['n_specialist_timeouts']}; "
        f"expected >= 1 for the hung horizon_scanner specialist"
    )
    # The other specialists must have run successfully — the hang didn't
    # poison the rest of the dispatch loop.
    assert calls["fast"] >= 1, f"healthy specialists did not run: fast={calls['fast']}"
    # Wall clock should be bounded — single hang timeout, not multiplied.
    # Allow generous slack (10s) for thread scheduling + healthy specialists' work.
    assert elapsed < 10.0, f"total elapsed {elapsed:.1f}s suggests multiple hangs were not bounded"

    # Greptile PR #26 round-3 follow-up: stderr line must fire in real time
    # for operator visibility. The digest entry alone is not sufficient
    # because it's only visible after the run completes and may be
    # compacted away by COMPACT_EVERY=8.
    captured = capsys.readouterr()
    assert "main-loop" in captured.err and "TIMEOUT" in captured.err and "horizon_scanner" in captured.err, (
        f"main-loop timeout must emit a stderr line naming the hung role for operator visibility; got: {captured.err!r}"
    )


def test_orchestrator_run_returns_zero_timeouts_when_all_specialists_complete(monkeypatch):
    """Healthy-path baseline: when no specialist hangs, n_specialist_timeouts
    must be 0. Protects against a future refactor that accidentally
    increments the counter on the success path."""
    monkeypatch.setattr(orchestrator, "research", _fast_research)
    monkeypatch.setattr(orchestrator, "_gap_review", lambda *_a, **_kw: {"review": [], "gap_fill": []})
    monkeypatch.setattr(orchestrator, "_compact", lambda *_a, **_kw: "")

    plan = {
        "queries": [
            {"id": "Q1", "text": "x", "specialist_role": "evidence_gatherer", "target_sections": ["S1"]},
        ],
        "report_toc": [{"id": "S1", "title": "x"}],
    }
    result = orchestrator.run(plan, prompt="p", language="en", archetype="explain-mechanism", domain="default")
    assert result["n_specialist_timeouts"] == 0


def test_specialist_timeout_constant_is_set_and_sane():
    """Pin the _SPECIALIST_TIMEOUT_S default — must be set, must be in
    a sane range (>= 60s to cover legitimate slow specialists, <= 600s
    to avoid effectively-unbounded behavior the pre-fix code had). This
    pins the DEFAULT (no DR_SPECIALIST_TIMEOUT_S in the CI env); a run may
    deliberately override higher for high-concurrency."""
    assert hasattr(orchestrator, "_SPECIALIST_TIMEOUT_S")
    assert 60 <= orchestrator._SPECIALIST_TIMEOUT_S <= 600


def test_specialist_timeout_reads_env_override(monkeypatch):
    """DR_SPECIALIST_TIMEOUT_S overrides the 240s default so high-concurrency
    runs can raise the cap instead of dropping specialists. Tested via the
    helper (not a module reload) so it can't perturb other tests' module
    state."""
    monkeypatch.setenv("DR_SPECIALIST_TIMEOUT_S", "450")
    assert orchestrator._specialist_timeout_from_env() == 450
    monkeypatch.delenv("DR_SPECIALIST_TIMEOUT_S", raising=False)
    assert orchestrator._specialist_timeout_from_env() == 240


def test_gap_fill_timeout_logs_to_stderr_and_digest(monkeypatch, capsys):
    """Greptile PR #26 follow-up (2026-05-26): gap-fill timeouts MUST be
    visible — pre-fix the gap-fill handler only bumped
    `n_specialist_timeouts` without a digest entry or stderr line, leaving
    a downstream drift-log reader unable to distinguish main-loop vs
    gap-fill contributions to the counter. The fix makes gap-fill match
    the main-loop's digest-append + stderr-print pattern.

    This test feeds a plan that completes its main loop fast, then has
    _gap_review return a gap_fill item whose research() hangs — verifying
    both the stderr message AND the digest marker fire."""

    def fake_research(role, qlist, **_kw):
        # First call (main loop) returns fast.
        if qlist and qlist[0].get("id") != "gapfill":
            return _fast_research(role=role)
        # Gap-fill call hangs past the timeout.
        time.sleep(60)
        return {"role": role, "findings": [], "n_searches": 0}

    monkeypatch.setattr(orchestrator, "research", fake_research)
    monkeypatch.setattr(
        orchestrator,
        "_gap_review",
        lambda *_a, **_kw: {
            "review": [],
            "gap_fill": [{"specialist_role": "evidence_gatherer", "brief": "fill the gap"}],
        },
    )
    # Stub _compact to a deterministic join so the digest assertion below
    # can look for the gap-fill TIMEOUT marker without invoking the real LLM.
    monkeypatch.setattr(orchestrator, "_compact", lambda parts: "\n".join(parts) if parts else "")
    monkeypatch.setattr(orchestrator, "_SPECIALIST_TIMEOUT_S", 1.5)

    plan = {
        "queries": [
            {"id": "Q1", "text": "q1", "specialist_role": "evidence_gatherer", "target_sections": ["S1"]},
        ],
        "report_toc": [{"id": "S1", "title": "x"}],
    }
    result = orchestrator.run(plan, prompt="p", language="en", archetype="explain-mechanism", domain="default")

    # The gap-fill hang must show as a stderr line — operator visibility.
    captured = capsys.readouterr()
    assert "gap-fill" in captured.err and "TIMEOUT" in captured.err, (
        f"gap-fill timeout must emit a stderr line for operator visibility; got: {captured.err!r}"
    )
    # And as a digest entry — drift-log readers see the marker in the
    # compacted digest.
    digest = result.get("digest", "")
    assert "gap-fill TIMEOUT" in digest, f"gap-fill timeout must append a digest marker; got: {digest!r}"
    # Counter increments.
    assert result["n_specialist_timeouts"] >= 1
