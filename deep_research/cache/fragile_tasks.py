"""P2-Wave-2-G: W9 readability cache for fragile-density detection.

The Wave-2-G conditional rule (omit `_DEDUP_RULE` for explain-mechanism
tasks with prior-high Readability) needs to know each task's W9 readability
score at writer-prompt assembly time. This module lazy-loads that lookup
from the frozen W9 raw_results.jsonl and exposes a single predicate:

    is_fragile_density_task(task_id, threshold=0.50) -> bool

The threshold default (0.50 = μ + 0.5σ on W9; max 0.5850) captures the top
~8% of W9 tasks by Readability. Cross-referenced 2026-05-23 against the
W9 inner_loop_drift archetype log: under (read ≥ 0.50 AND
archetype == "explain-mechanism") only id=56 fires. Other high-Read tasks
are list-all or predict and do not trigger G.

Fail-soft: if the W9 file is missing (other machines, different result-set
names) the predicate returns False unconditionally — G effectively disables
itself rather than crashing the pipeline.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading

_DEFAULT_W9_PATH = "/home/connor/dev/deep_research_bench/results/race/lunon-p1-2026-05-21-final/raw_results.jsonl"

_LOCK = threading.Lock()
_CACHE: dict[int, float] | None = None


def _w9_results_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("DR_W9_RESULTS", _DEFAULT_W9_PATH))


def load_w9_readability() -> dict[int, float]:
    """Lazy-load {task_id: readability} from W9 frozen results.

    Idempotent — caches the parsed dict after first load. Thread-safe
    (ThreadPoolExecutor section workers may race). Returns empty dict if
    the source file is missing or unreadable.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        parsed: dict[int, float] = {}
        try:
            with _w9_results_path().open(encoding="utf-8") as fh:
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
            parsed = {}
        _CACHE = parsed
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
    global _CACHE
    with _LOCK:
        _CACHE = None
