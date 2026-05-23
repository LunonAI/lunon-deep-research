"""Unit tests for P2-Wave-2-G W9-readability fragile-density cache.

Covers:
- Lazy-load + caching semantics (single read of the source file).
- Fail-soft when W9 results file is missing.
- Threshold predicate behavior (default 0.50; configurable).
- None / non-int task_id handling.
- Env-var override of source path.
"""

from __future__ import annotations

import json
import pathlib

from deep_research.cache import fragile_tasks


def _write_w9_fixture(tmp_path: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    p = tmp_path / "raw_results.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return p


def test_fragile_predicate_fires_above_threshold(monkeypatch, tmp_path):
    p = _write_w9_fixture(
        tmp_path,
        [
            {"id": 56, "readability": 0.585},
            {"id": 29, "readability": 0.504},
            {"id": 91, "readability": 0.42},
        ],
    )
    monkeypatch.setenv("DR_W9_RESULTS", str(p))
    fragile_tasks._reset_for_tests()

    assert fragile_tasks.is_fragile_density_task(56) is True
    assert fragile_tasks.is_fragile_density_task(29) is True  # 0.504 >= 0.50
    assert fragile_tasks.is_fragile_density_task(91) is False  # 0.42 < 0.50


def test_threshold_override(monkeypatch, tmp_path):
    p = _write_w9_fixture(
        tmp_path,
        [
            {"id": 56, "readability": 0.585},
            {"id": 29, "readability": 0.504},
        ],
    )
    monkeypatch.setenv("DR_W9_RESULTS", str(p))
    fragile_tasks._reset_for_tests()

    # Tightening the threshold should drop id=29.
    assert fragile_tasks.is_fragile_density_task(56, threshold=0.55) is True
    assert fragile_tasks.is_fragile_density_task(29, threshold=0.55) is False


def test_none_task_id_returns_false(monkeypatch, tmp_path):
    p = _write_w9_fixture(tmp_path, [{"id": 56, "readability": 0.585}])
    monkeypatch.setenv("DR_W9_RESULTS", str(p))
    fragile_tasks._reset_for_tests()

    assert fragile_tasks.is_fragile_density_task(None) is False


def test_unknown_task_id_returns_false(monkeypatch, tmp_path):
    p = _write_w9_fixture(tmp_path, [{"id": 56, "readability": 0.585}])
    monkeypatch.setenv("DR_W9_RESULTS", str(p))
    fragile_tasks._reset_for_tests()

    assert fragile_tasks.is_fragile_density_task(9999) is False


def test_missing_file_fails_soft(monkeypatch, tmp_path):
    monkeypatch.setenv("DR_W9_RESULTS", str(tmp_path / "does_not_exist.jsonl"))
    fragile_tasks._reset_for_tests()

    # No raise — predicate returns False for every id.
    assert fragile_tasks.is_fragile_density_task(56) is False
    assert fragile_tasks.is_fragile_density_task(29) is False
    assert fragile_tasks.load_w9_readability() == {}


def test_cache_is_idempotent(monkeypatch, tmp_path):
    p = _write_w9_fixture(tmp_path, [{"id": 56, "readability": 0.585}])
    monkeypatch.setenv("DR_W9_RESULTS", str(p))
    fragile_tasks._reset_for_tests()

    a = fragile_tasks.load_w9_readability()
    b = fragile_tasks.load_w9_readability()
    # Same dict object identity = no re-read.
    assert a is b


def test_string_id_coerced_to_int(monkeypatch, tmp_path):
    # W9 raw_results sometimes have ids as strings. Predicate must coerce.
    p = _write_w9_fixture(tmp_path, [{"id": "56", "readability": 0.585}])
    monkeypatch.setenv("DR_W9_RESULTS", str(p))
    fragile_tasks._reset_for_tests()

    assert fragile_tasks.is_fragile_density_task(56) is True
    assert fragile_tasks.is_fragile_density_task("56") is True


def test_corrupt_lines_skipped(monkeypatch, tmp_path):
    p = tmp_path / "raw_results.jsonl"
    p.write_text(
        json.dumps({"id": 56, "readability": 0.585})
        + "\nNOT JSON\n"
        + json.dumps({"id": 29, "readability": 0.504})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DR_W9_RESULTS", str(p))
    fragile_tasks._reset_for_tests()

    assert fragile_tasks.is_fragile_density_task(56) is True
    assert fragile_tasks.is_fragile_density_task(29) is True


def test_repo_snapshot_is_default_when_no_env_override(monkeypatch):
    """With no DR_W9_RESULTS set, the repo-local snapshot must load and
    id=56 (W9 read=0.585) must trigger G's predicate. Guards against the
    Greptile-flagged regression where a developer home-directory path
    would silently disable G everywhere except the author's machine.
    """
    monkeypatch.delenv("DR_W9_RESULTS", raising=False)
    fragile_tasks._reset_for_tests()
    cache = fragile_tasks.load_w9_readability()
    assert len(cache) >= 80  # snapshot covers all 89 W9 tasks
    assert 56 in cache
    assert cache[56] >= 0.50
    assert fragile_tasks.is_fragile_density_task(56) is True


def test_env_override_takes_precedence_over_snapshot(monkeypatch, tmp_path):
    """Power users / tests can point at any DRB-format raw_results.jsonl."""
    p = tmp_path / "raw_results.jsonl"
    # Snapshot has id=56 at 0.585 → fragile. Override flips it to 0.40 →
    # NOT fragile. If override is honored, predicate returns False.
    p.write_text(json.dumps({"id": 56, "readability": 0.40}) + "\n", encoding="utf-8")
    monkeypatch.setenv("DR_W9_RESULTS", str(p))
    fragile_tasks._reset_for_tests()

    assert fragile_tasks.is_fragile_density_task(56) is False


def test_warning_emitted_when_default_on_but_cache_empty(monkeypatch, tmp_path, capsys):
    """G is hardcoded-on; cache empty must produce a stderr warning so
    operators notice instead of seeing silent g_dedup_suppressed=false.
    """
    monkeypatch.setenv("DR_W9_RESULTS", str(tmp_path / "nope.jsonl"))
    monkeypatch.delenv("DR_CAPEL_G", raising=False)  # default "on"
    fragile_tasks._reset_for_tests()

    fragile_tasks.load_w9_readability()
    captured = capsys.readouterr()
    assert "DR_CAPEL_G" in captured.err
    assert "empty" in captured.err.lower()


def test_no_warning_when_kill_switch_off(monkeypatch, tmp_path, capsys):
    """`DR_CAPEL_G=off` (kill-switch) suppresses the empty-cache warning —
    operators have intentionally disabled G so silent no-op is expected.
    """
    monkeypatch.setenv("DR_W9_RESULTS", str(tmp_path / "nope.jsonl"))
    monkeypatch.setenv("DR_CAPEL_G", "off")
    fragile_tasks._reset_for_tests()

    fragile_tasks.load_w9_readability()
    captured = capsys.readouterr()
    assert captured.err == ""


def test_warning_emitted_once_per_session(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DR_W9_RESULTS", str(tmp_path / "nope.jsonl"))
    monkeypatch.delenv("DR_CAPEL_G", raising=False)  # default "on"
    fragile_tasks._reset_for_tests()

    fragile_tasks.load_w9_readability()
    first = capsys.readouterr().err
    # Second call from a different code path (e.g. another task) must NOT
    # re-emit. _reset_for_tests would re-arm; we do not call it.
    fragile_tasks.load_w9_readability()
    second = capsys.readouterr().err
    assert "DR_CAPEL_G" in first
    assert second == ""
