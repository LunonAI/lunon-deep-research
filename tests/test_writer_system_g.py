"""Unit tests for P2-Wave-2-G `writer_system` `_DEDUP_RULE` suppression.

The G heuristic: when DR_CAPEL_G is on AND archetype=="explain-mechanism"
AND task_id maps to W9 readability >= 0.50, omit `_DEDUP_RULE`. All other
configurations keep the rule.

Tests use a tmp W9 results fixture so they don't depend on the canonical
DRB results tree.
"""

from __future__ import annotations

import json
import pathlib

from deep_research import writing_rules as wr
from deep_research.cache import fragile_tasks


def _setup_w9(monkeypatch, tmp_path: pathlib.Path) -> None:
    p = tmp_path / "raw_results.jsonl"
    rows = [
        {"id": 56, "readability": 0.585},  # explain-mechanism + high read → triggers G
        {"id": 29, "readability": 0.504},  # list-all + high read → no G
        {"id": 91, "readability": 0.42},  # below threshold → no G
        {"id": 8, "readability": 0.38},  # below threshold → no G
    ]
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    monkeypatch.setenv("DR_W9_RESULTS", str(p))
    fragile_tasks._reset_for_tests()


_DEDUP_FINGERPRINT = "CROSS-SECTION NON-REDUNDANCY"


def test_kill_switch_off_keeps_dedup_rule(monkeypatch, tmp_path):
    """`DR_CAPEL_G=off` is the post-hardcode kill-switch: G never fires."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys_prompt = wr.writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=56)
    assert _DEDUP_FINGERPRINT in sys_prompt


def test_default_id_56_triggers_suppression(monkeypatch, tmp_path):
    """Canonical fragile-density case: id=56 + explain-mechanism. Post-hardcode
    the flag defaults to `on`, so unsetting it must STILL trigger G."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.delenv("DR_CAPEL_G", raising=False)
    sys_prompt = wr.writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=56)
    assert _DEDUP_FINGERPRINT not in sys_prompt


def test_default_wrong_archetype_keeps_dedup(monkeypatch, tmp_path):
    """list-all archetype must NOT trigger G even at high readability."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.delenv("DR_CAPEL_G", raising=False)
    sys_prompt = wr.writer_system("list-all", "default", "en", ["A", "B"], task_id=29)
    assert _DEDUP_FINGERPRINT in sys_prompt


def test_default_low_readability_keeps_dedup(monkeypatch, tmp_path):
    """explain-mechanism task with W9 read below threshold keeps dedup."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.delenv("DR_CAPEL_G", raising=False)
    sys_prompt = wr.writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=91)
    assert _DEDUP_FINGERPRINT in sys_prompt


def test_explicit_suppress_dedup_overrides_non_firing_case(monkeypatch, tmp_path):
    """suppress_dedup=True works even when G's auto-fire path would NOT have
    triggered (list-all archetype + sub-threshold task_id). Verifies the
    explicit arg is independent of the auto-fire logic."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.delenv("DR_CAPEL_G", raising=False)  # default-on; G active
    sys_prompt = wr.writer_system("list-all", "default", "en", ["A", "B"], task_id=91, suppress_dedup=True)
    assert _DEDUP_FINGERPRINT not in sys_prompt


def test_explicit_suppress_redundant_when_g_would_fire(monkeypatch, tmp_path):
    """When G's auto-fire WOULD have suppressed dedup (explain-mech + id=56),
    suppress_dedup=True is redundant but harmless — the result is still no
    `_DEDUP_RULE` in the prompt. Proves the explicit arg composes with auto-fire."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.delenv("DR_CAPEL_G", raising=False)  # default-on; G active
    sys_prompt = wr.writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=56, suppress_dedup=True)
    assert _DEDUP_FINGERPRINT not in sys_prompt


def test_explicit_suppress_overrides_kill_switch(monkeypatch, tmp_path):
    """The explicit suppress_dedup=True overrides the kill-switch — even with
    `DR_CAPEL_G=off` disabling G's auto-fire path, the explicit arg still
    omits `_DEDUP_RULE`. Critical for callers that want unconditional control
    regardless of env state."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.setenv("DR_CAPEL_G", "off")  # G's auto-fire path fully disabled
    sys_prompt = wr.writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=56, suppress_dedup=True)
    assert _DEDUP_FINGERPRINT not in sys_prompt


def test_no_task_id_no_suppression(monkeypatch, tmp_path):
    """Missing task_id (e.g. smoke run) MUST NOT trigger G even at default-on."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.delenv("DR_CAPEL_G", raising=False)
    sys_prompt = wr.writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=None)
    assert _DEDUP_FINGERPRINT in sys_prompt


def test_missing_w9_cache_falls_back_to_no_suppression(monkeypatch, tmp_path):
    """If W9 results file is missing, G silently disables (cache empty)."""
    monkeypatch.setenv("DR_W9_RESULTS", str(tmp_path / "missing.jsonl"))
    monkeypatch.delenv("DR_CAPEL_G", raising=False)
    fragile_tasks._reset_for_tests()
    sys_prompt = wr.writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=56)
    assert _DEDUP_FINGERPRINT in sys_prompt
