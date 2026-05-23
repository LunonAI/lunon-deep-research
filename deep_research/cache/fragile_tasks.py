"""P2-Wave-2-G: W9 readability cache for fragile-density detection.

The Wave-2-G conditional rule (omit `_DEDUP_RULE` for explain-mechanism
tasks with prior-high Readability) needs to know each task's W9 readability
score at writer-prompt assembly time. This module lazy-loads that lookup
and exposes a single predicate:

    is_fragile_density_task(task_id, threshold=0.50) -> bool

The threshold default (0.50 = μ + 0.5σ on W9; max 0.5850) captures the top
~8% of W9 tasks by Readability. Cross-referenced 2026-05-23 against the
W9 inner_loop_drift archetype log: under (read ≥ 0.50 AND
archetype == "explain-mechanism") only id=56 fires. Other high-Read tasks
are list-all or predict and do not trigger G.

Lookup order:
  1. `DR_W9_RESULTS` env override (used by tests + power users) — read as
     DRB-format raw_results.jsonl.
  2. Repo-local snapshot at `cache/data/w9_readability.json` — a 89-entry
     `{task_id: readability}` map committed to the repo so G works on CI,
     colleagues' machines, and any dev10 environment without external
     dependencies. This is the production default.
  3. If both miss (snapshot deleted AND override unset), the cache is
     empty and `is_fragile_density_task` always returns False. To prevent
     silent dev10 false-PASSes, a one-shot stderr warning is emitted when
     `DR_CAPEL_G != off` AND the cache loaded empty.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import threading

_REPO_SNAPSHOT = pathlib.Path(__file__).resolve().parent / "data" / "w9_readability.json"

_LOCK = threading.Lock()
_CACHE: dict[int, float] | None = None
_EMPTY_WARNING_EMITTED = False


def _load_from_drb_results(path: pathlib.Path) -> dict[int, float]:
    """Parse a DRB raw_results.jsonl file into {task_id: readability}."""
    parsed: dict[int, float] = {}
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tid = d.get("id")
                if tid is None:
                    continue
                try:
                    tid_int = int(tid)
                except (TypeError, ValueError):
                    continue
                parsed[tid_int] = float(d.get("readability", 0.0))
    except (FileNotFoundError, OSError):
        return {}
    return parsed


def _load_from_snapshot(path: pathlib.Path) -> dict[int, float]:
    """Parse the repo-local {task_id: readability} JSON snapshot."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    parsed: dict[int, float] = {}
    if not isinstance(raw, dict):
        return {}
    for k, v in raw.items():
        try:
            parsed[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return parsed


def _emit_empty_warning_if_active() -> None:
    """One-shot stderr warning when G is enabled but the cache loaded empty.

    Without this, a missing snapshot or bad env override would let G silently
    no-op on every task — producing a dev10 drift log indistinguishable from
    "G evaluated and chose not to suppress" and a false-PASS gate signal.
    """
    global _EMPTY_WARNING_EMITTED
    if _EMPTY_WARNING_EMITTED:
        return
    # P2-Wave-2 hardcoded post-sanity-4. The warning fires whenever G *could*
    # be running (default "on") but the cache loaded empty — that's the
    # silent-no-op scenario operators need to see. Only "off" suppresses it.
    if os.environ.get("DR_CAPEL_G", "on") == "off":
        return
    override = os.environ.get("DR_W9_RESULTS", "")
    msg = (
        "[fragile_tasks] WARNING: DR_CAPEL_G is enabled but the W9 "
        "readability cache is empty. G will not fire on any task this run. "
        f"Snapshot path: {_REPO_SNAPSHOT} (exists={_REPO_SNAPSHOT.exists()}). "
        f"DR_W9_RESULTS override: {override or '<unset>'}."
    )
    print(msg, file=sys.stderr, flush=True)
    _EMPTY_WARNING_EMITTED = True


def load_w9_readability() -> dict[int, float]:
    """Lazy-load {task_id: readability} from the W9 cache.

    Idempotent — caches the parsed dict after first load. Thread-safe
    (ThreadPoolExecutor section workers may race). Returns empty dict if
    no source resolves; emits a stderr warning when that happens with
    `DR_CAPEL_G` enabled (so the dev10 operator sees a clear miss instead
    of silent no-op).
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        override = os.environ.get("DR_W9_RESULTS", "").strip()
        if override:
            parsed = _load_from_drb_results(pathlib.Path(override))
        else:
            parsed = _load_from_snapshot(_REPO_SNAPSHOT)
        _CACHE = parsed
        if not parsed:
            _emit_empty_warning_if_active()
        return _CACHE


def is_fragile_density_task(task_id: int | None, threshold: float = 0.50) -> bool:
    """True iff the task's W9 readability score >= threshold.

    Returns False when task_id is None or the W9 cache is empty (fail-soft).
    """
    if task_id is None:
        return False
    cache = load_w9_readability()
    if not cache:
        return False
    try:
        return cache.get(int(task_id), 0.0) >= threshold
    except (TypeError, ValueError):
        return False


def _reset_for_tests() -> None:
    """Test-only: drop the cached lookup so a fresh load can be exercised."""
    global _CACHE, _EMPTY_WARNING_EMITTED
    with _LOCK:
        _CACHE = None
        _EMPTY_WARNING_EMITTED = False
