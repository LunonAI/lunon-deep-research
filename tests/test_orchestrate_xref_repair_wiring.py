"""P3-W3.b (2026-05-27): orchestrator wiring + drift surface for xref_repair.

The `_MID_PARAGRAPH_XREF_RULE` writer directive (writing_rules.py, P3-W3)
landed in PR #39 and is the primary force producing clean cross-references
in writer output. The `pipeline.xref_repair.repair()` module also landed in
PR #39 with full unit-test coverage (see tests/test_xref_repair.py), but
the post-merge audit found it was NEVER imported or called from
`deep_research.orchestrate` — so the safety-net for "Building on §X"
template regressions and dangling forward-refs sat dormant.

These tests pin the wire-up so a future refactor that drops the import
or moves the call out of the post-pass chain is caught at CI rather
than only after a dev4 / W13 run silently regresses.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path

from deep_research import orchestrate
from deep_research.pipeline import xref_repair


@dataclass
class _FakeState:
    """Stand-in for `PipelineState` so we can exercise `_persist_drift`
    without bringing up the full pipeline. Mirrors only the fields the
    drift writer reads (see test_drift_instrumentation._FakeState)."""

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
    mermaid_validate_stats: dict = field(default_factory=dict)
    xref_repair_stats: dict = field(default_factory=dict)


def _read_last_drift(drift_path: Path) -> dict:
    last_line = ""
    for line in drift_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last_line = line
    return json.loads(last_line)


def test_orchestrate_imports_xref_repair():
    """The xref_repair module must be importable from the pipeline package
    namespace the orchestrator pulls in. Pre-fix the module existed but
    was never imported anywhere outside its own test file."""
    src = inspect.getsource(orchestrate)
    assert "xref_repair" in src, (
        "xref_repair is not imported / referenced in orchestrate.py — "
        "the post-pass repair will never run on writer output; "
        f"got source length {len(src)} chars"
    )


def test_orchestrate_invokes_xref_repair_repair_function():
    """Importing alone is not enough — the orchestrator must actually
    CALL `xref_repair.repair()` somewhere in the post-pass chain.
    Mirrors the same shape as `test_orchestrate_pipeline_wires_mermaid_validate_call`."""
    src = inspect.getsource(orchestrate)
    assert "xref_repair.repair" in src, (
        "xref_repair is imported but `repair()` is never called — "
        "Building on §X templates + dangling forward-refs will pass "
        "through to articles unrepaired"
    )


def test_orchestrate_xref_repair_runs_after_zh_pass_before_mermaid():
    """Ordering: xref_repair must run AFTER `zh_writer_pass` (so the
    ZH-language touch-up has its shot at the article first) and BEFORE
    `mermaid_validate.repair` (so any sentence deletions xref makes
    don't leave orphan mermaid fence tokens for the next pass to
    mishandle). Both must run BEFORE `footnote_normalize.normalize`
    so `[^N]` markers inside deleted sentences are removed before
    global renumbering."""
    src = inspect.getsource(orchestrate)
    zh_pos = src.index("zh_writer_pass.zh_pass")
    xref_pos = src.index("xref_repair.repair")
    mermaid_pos = src.index("mermaid_validate.repair")
    footnote_pos = src.index("footnote_normalize.normalize")
    assert zh_pos < xref_pos, (
        f"xref_repair.repair must run AFTER zh_writer_pass.zh_pass — got zh_pos={zh_pos}, xref_pos={xref_pos}"
    )
    assert xref_pos < mermaid_pos, (
        f"xref_repair.repair must run BEFORE mermaid_validate.repair "
        f"so any sentence deletions don't leave orphan mermaid fence "
        f"tokens for mermaid_validate to mishandle; got xref_pos={xref_pos}, "
        f"mermaid_pos={mermaid_pos}"
    )
    assert xref_pos < footnote_pos, (
        f"xref_repair.repair must run BEFORE footnote_normalize.normalize "
        f"so [^N] markers inside deleted sentences are pulled out of the "
        f"article before global renumber; got xref_pos={xref_pos}, "
        f"footnote_pos={footnote_pos}"
    )


def test_orchestrate_persists_xref_stats_on_state():
    """The wire-up assignment `s.xref_repair_stats = xr_stats` must be
    present so the drift telemetry can surface the stats downstream.
    A future refactor that returns `xr_stats` without writing it back
    onto state would silently drop telemetry."""
    src = inspect.getsource(orchestrate)
    assert "s.xref_repair_stats = " in src, (
        "xref_repair.repair() is called but its stats are not assigned "
        "to PipelineState — drift telemetry will not surface the stats; "
        "expected `s.xref_repair_stats = xr_stats` somewhere in the body"
    )


def test_persist_drift_includes_xref_repair_stats(tmp_path, monkeypatch):
    """The drift logger must forward `xref_repair_stats` into the
    `xref_repair` field of the drift record so dev4 / W13 analysers
    can correlate safety-net firing with article quality."""
    drift_file = tmp_path / "drift.jsonl"
    monkeypatch.setattr(orchestrate, "_DRIFT_PATH", drift_file)

    state = _FakeState(
        xref_repair_stats={
            "templates_repaired": 2,
            "dangling_refs_rewritten": 5,
            "sentences_deleted": 1,
        }
    )
    orchestrate._persist_drift(state, language="en", query="test query")

    rec = _read_last_drift(drift_file)
    assert "xref_repair" in rec, f"drift record missing `xref_repair` key — got keys: {sorted(rec.keys())}"
    assert rec["xref_repair"]["templates_repaired"] == 2
    assert rec["xref_repair"]["dangling_refs_rewritten"] == 5
    assert rec["xref_repair"]["sentences_deleted"] == 1


def test_persist_drift_xref_repair_defaults_to_empty(tmp_path, monkeypatch):
    """Pre-P3-W3.b state snapshots have no `xref_repair_stats` field;
    the drift log must surface an empty dict rather than KeyError or
    absent key. Mirrors the mermaid_validate default-empty contract."""
    drift_file = tmp_path / "drift.jsonl"
    monkeypatch.setattr(orchestrate, "_DRIFT_PATH", drift_file)

    state = _FakeState()  # xref_repair_stats defaults to {}
    orchestrate._persist_drift(state, language="en", query="test")

    rec = _read_last_drift(drift_file)
    assert "xref_repair" in rec, (
        f"drift record missing `xref_repair` key even with empty input — got: {sorted(rec.keys())}"
    )
    assert rec["xref_repair"] == {}


def test_xref_repair_repair_signature_matches_orchestrate_call():
    """Defence-in-depth: the orchestrate.py call site does
    `_phase("xref_repair", xref_repair.repair, s.article)` — so the
    repair() function must accept one positional `text` arg and return
    a 2-tuple `(text, stats)`. If a future refactor changes the
    signature (e.g., requires a `heading_set` second arg), this test
    fires before dev4."""
    out = xref_repair.repair("plain text with no cross-refs.")
    assert isinstance(out, tuple) and len(out) == 2, (
        f"xref_repair.repair() must return a 2-tuple (text, stats); got: {type(out)}"
    )
    text, stats = out
    assert isinstance(text, str), f"first element must be str; got {type(text)}"
    assert isinstance(stats, dict), f"second element must be dict; got {type(stats)}"
    assert set(stats.keys()) == {"templates_repaired", "dangling_refs_rewritten", "sentences_deleted"}, (
        f"stats keys mismatch — drift logger forwards `xref_repair_stats` verbatim, "
        f"so renaming/adding keys requires the test to be updated; got: {sorted(stats.keys())}"
    )


def test_xref_repair_repair_idempotent_on_clean_article():
    """Running repair() twice on a clean article produces the same
    output and zero stats — required for the post-pass to be safe to
    run inside retry loops."""
    clean = (
        "# Title\n\n## 1 First Chapter\n\nThe first paragraph introduces the topic. "
        "Subsequent analysis builds on this foundation (Section 2.1).\n\n"
        "## 2 Second Chapter\n\n### 2.1 Subsection\n\nDetails follow.\n"
    )
    out1, stats1 = xref_repair.repair(clean)
    out2, stats2 = xref_repair.repair(out1)
    assert out1 == out2, "repair() is not idempotent — running twice changed the text"
    assert stats2["templates_repaired"] == 0
    assert stats2["dangling_refs_rewritten"] == 0
    assert stats2["sentences_deleted"] == 0


def test_xref_repair_repair_handles_empty_and_none():
    """Fail-soft contract: empty string + non-string inputs return
    unchanged with all-zero stats. The orchestrate.py wire-up calls
    repair() on `s.article`; if upstream produces an empty article
    (degenerate failure case), the post-pass must not raise."""
    out_empty, stats_empty = xref_repair.repair("")
    assert out_empty == ""
    assert stats_empty == {"templates_repaired": 0, "dangling_refs_rewritten": 0, "sentences_deleted": 0}

    # Non-string defensive path (e.g. upstream produced None)
    out_none, stats_none = xref_repair.repair(None)  # type: ignore[arg-type]
    assert out_none is None
    assert stats_none == {"templates_repaired": 0, "dangling_refs_rewritten": 0, "sentences_deleted": 0}
