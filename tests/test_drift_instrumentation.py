"""Wave 1 §7.1 + §7.2 (2026-05-26): drift-log instrumentation tests.

The pre-Wave-1 `_persist_drift` writer surfaced footnote_normalize_stats
(n_definitions, n_inline_markers, n_orphans_stripped, ...) but not:
  - `n_specialist_timeouts` from the orchestrator (added in PR #26 to
    its return dict but never threaded into state / drift telemetry)
  - the derived `inline_def_ratio` field that gives analysers a single
    "reuse density" knob to spot writers that emit fresh markers per
    cite (ratio ≈ 1 = no reuse; the reference averages ratio ≈ 7)

These tests pin the drift-log shape so a future refactor that drops
either field is caught at CI time rather than after a dev4 / W13 run
fails to surface the relevant signal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from deep_research import orchestrate


@dataclass
class _FakeState:
    """Stand-in for `PipelineState` so we can exercise `_persist_drift`
    without bringing up the full pipeline. Mirrors only the fields the
    drift writer reads."""

    task_fp: str = ""
    archetype: dict = field(default_factory=dict)
    domain: str = "default"
    section_scores: list = field(default_factory=list)
    failing_rationales: list = field(default_factory=list)
    refiner_passes: int = 1
    validation_log: list = field(default_factory=list)
    article: str = ""
    tool_calls: int = 0
    numbering_fix_stats: dict = field(default_factory=dict)
    refiner_gate_verdict: dict = field(default_factory=dict)
    evidence_dedup_stats: dict = field(default_factory=dict)
    capel_stats: dict = field(default_factory=dict)
    g_dedup_suppressed: bool = False
    footnote_normalize_stats: dict = field(default_factory=dict)
    n_specialist_timeouts: int = 0


def _read_last_drift(drift_path: Path) -> dict:
    """Read the most recent JSON line from the drift log."""
    last_line = ""
    for line in drift_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last_line = line
    return json.loads(last_line)


def test_persist_drift_includes_n_specialist_timeouts(tmp_path, monkeypatch):
    """Wave 1 §7.1: the orchestrator's `n_specialist_timeouts` count
    must surface in the drift log so dev4 / W13 analysers can correlate
    timeout pressure with quality drift."""
    drift_file = tmp_path / "drift.jsonl"
    monkeypatch.setattr(orchestrate, "_DRIFT_PATH", drift_file)

    state = _FakeState(n_specialist_timeouts=2)
    orchestrate._persist_drift(state, language="en", query="test query")

    rec = _read_last_drift(drift_file)
    assert rec["n_specialist_timeouts"] == 2


def test_persist_drift_n_specialist_timeouts_defaults_to_zero(tmp_path, monkeypatch):
    """Pre-PR-26 orchestrator return dicts don't have the key; the field
    must default to 0 rather than KeyError or be absent from the log."""
    drift_file = tmp_path / "drift.jsonl"
    monkeypatch.setattr(orchestrate, "_DRIFT_PATH", drift_file)

    state = _FakeState()  # n_specialist_timeouts defaults to 0
    orchestrate._persist_drift(state, language="en", query="test")

    rec = _read_last_drift(drift_file)
    assert "n_specialist_timeouts" in rec
    assert rec["n_specialist_timeouts"] == 0


def test_persist_drift_includes_inline_def_ratio(tmp_path, monkeypatch):
    """Wave 1 §7.2: `inline_def_ratio` is derived from existing
    `n_inline_markers` / `n_definitions` so analysers can spot the
    "no reuse" failure mode (ratio ≈ 1) vs the reference's ~7× reuse
    pattern."""
    drift_file = tmp_path / "drift.jsonl"
    monkeypatch.setattr(orchestrate, "_DRIFT_PATH", drift_file)

    state = _FakeState(
        footnote_normalize_stats={
            "n_definitions": 45,
            "n_inline_markers": 326,  # the reference id=56 actual values
            "n_orphans_stripped": 0,
            "n_unused_dropped": 0,
            "n_renumbered": 45,
        }
    )
    orchestrate._persist_drift(state, language="en", query="test")

    rec = _read_last_drift(drift_file)
    # 326 / 45 ≈ 7.244 — the reference's documented reuse density.
    assert "inline_def_ratio" in rec["footnote_normalize"]
    assert abs(rec["footnote_normalize"]["inline_def_ratio"] - 7.244) < 0.01


def test_persist_drift_inline_def_ratio_handles_zero_definitions(tmp_path, monkeypatch):
    """When normalize emitted no definitions (e.g. id=91 post-Wave-0
    smoke where every marker was malformed and dropped), the ratio must
    be `None` rather than throwing ZeroDivisionError."""
    drift_file = tmp_path / "drift.jsonl"
    monkeypatch.setattr(orchestrate, "_DRIFT_PATH", drift_file)

    state = _FakeState(
        footnote_normalize_stats={
            "n_definitions": 0,
            "n_inline_markers": 105,  # markers present but unparseable
        }
    )
    orchestrate._persist_drift(state, language="en", query="test")

    rec = _read_last_drift(drift_file)
    assert rec["footnote_normalize"]["inline_def_ratio"] is None


def test_persist_drift_inline_def_ratio_one_when_no_reuse(tmp_path, monkeypatch):
    """The diagnostic case: 1 inline marker per definition = ratio 1.0,
    signalling the writer is making a fresh marker per cite (zero
    reuse). the reference's pattern would give ~7."""
    drift_file = tmp_path / "drift.jsonl"
    monkeypatch.setattr(orchestrate, "_DRIFT_PATH", drift_file)

    state = _FakeState(
        footnote_normalize_stats={
            "n_definitions": 10,
            "n_inline_markers": 10,
        }
    )
    orchestrate._persist_drift(state, language="en", query="test")

    rec = _read_last_drift(drift_file)
    assert rec["footnote_normalize"]["inline_def_ratio"] == 1.0


def test_persist_drift_swallows_all_exceptions(tmp_path, monkeypatch):
    """Pre-Wave-1 contract: `_persist_drift` is best-effort — any
    exception (disk full, corrupt state, etc.) MUST be swallowed so
    drift-logging failure never affects the task outcome. The Wave 1
    additions must preserve this contract."""
    # Point the drift path at a directory that doesn't exist and cannot
    # be created (e.g. under a file). This simulates a write failure.
    bad_path = tmp_path / "file_not_dir" / "drift.jsonl"
    (tmp_path / "file_not_dir").write_text("not a directory")
    monkeypatch.setattr(orchestrate, "_DRIFT_PATH", bad_path)

    state = _FakeState(n_specialist_timeouts=1)
    # MUST NOT raise — even though the write will fail under the hood.
    orchestrate._persist_drift(state, language="en", query="test")
