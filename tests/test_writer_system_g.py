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


def test_default_off_keeps_dedup_rule(monkeypatch, tmp_path):
    """When DR_CAPEL_G is unset (default off), G never fires."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.delenv("DR_CAPEL_G", raising=False)
    sys_prompt = wr.writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=56)
    assert _DEDUP_FINGERPRINT in sys_prompt


def test_flag_on_id_56_triggers_suppression(monkeypatch, tmp_path):
    """Canonical fragile-density case: id=56 + explain-mechanism + flag on."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.setenv("DR_CAPEL_G", "on")
    sys_prompt = wr.writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=56)
    assert _DEDUP_FINGERPRINT not in sys_prompt


def test_flag_on_wrong_archetype_keeps_dedup(monkeypatch, tmp_path):
    """list-all archetype must NOT trigger G even at high readability."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.setenv("DR_CAPEL_G", "on")
    sys_prompt = wr.writer_system("list-all", "default", "en", ["A", "B"], task_id=29)
    assert _DEDUP_FINGERPRINT in sys_prompt


def test_flag_on_low_readability_keeps_dedup(monkeypatch, tmp_path):
    """explain-mechanism task with W9 read below threshold keeps dedup."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.setenv("DR_CAPEL_G", "on")
    sys_prompt = wr.writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=91)
    assert _DEDUP_FINGERPRINT in sys_prompt


def test_explicit_suppress_dedup_overrides_archetype_and_id(monkeypatch, tmp_path):
    """suppress_dedup=True forces omission regardless of archetype/id."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.delenv("DR_CAPEL_G", raising=False)
    sys_prompt = wr.writer_system("list-all", "default", "en", ["A", "B"], task_id=91, suppress_dedup=True)
    assert _DEDUP_FINGERPRINT not in sys_prompt


def test_no_task_id_no_suppression(monkeypatch, tmp_path):
    """Missing task_id (e.g. smoke run) MUST NOT trigger G even with flag on."""
    _setup_w9(monkeypatch, tmp_path)
    monkeypatch.setenv("DR_CAPEL_G", "on")
    sys_prompt = wr.writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=None)
    assert _DEDUP_FINGERPRINT in sys_prompt


def test_missing_w9_cache_falls_back_to_no_suppression(monkeypatch, tmp_path):
    """If W9 results file is missing, G silently disables."""
    monkeypatch.setenv("DR_W9_RESULTS", str(tmp_path / "missing.jsonl"))
    monkeypatch.setenv("DR_CAPEL_G", "on")
    fragile_tasks._reset_for_tests()
    sys_prompt = wr.writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=56)
    assert _DEDUP_FINGERPRINT in sys_prompt
