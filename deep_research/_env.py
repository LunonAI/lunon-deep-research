"""Shared env + cost-tracking infra for the deep_research engine.

- load_env(): mirrors p0_artifacts/gpt55.py — reads the engine .env into a dict.
- assert_phase(): resolve the DRB_PHASE cost label (plan point 9), defaulting to
  P1 when unset so a fresh public clone runs with no internal config; a non-empty
  but unrecognized value still fails loud to catch typos in internal runs.
- log_usage / log_request: cost_tracking hooks (import-safe, never raise into caller),
  mirroring the gpt55.py auto-log pattern for the new Claude/OpenRouter clients.
"""

import os
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_ENV_PATH = _ROOT / ".env"

_VALID_PHASES = {"P0", "P1", "P2", "P2.5", "P3", "P4"}


def load_env(path: pathlib.Path = _ENV_PATH) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()


def get(key: str, default: str = "") -> str:
    """Engine config: .env first, then process env, then default."""
    return ENV.get(key) or os.environ.get(key, default)


def int_env(name: str, default: int) -> int:
    """Parse an integer engine knob from the process environment, failing loud
    with a clear, actionable message naming the env var rather than letting a
    bare ``int()`` raise a cryptic ``ValueError`` at module-import time (which
    would crash the whole pipeline before any user-facing error handling runs).

    An unset or empty value falls back to ``default``, preserving the historical
    ``int(os.environ.get(name) or default)`` semantics these knobs used. Reads
    ``os.environ`` only (not the .env file) to keep that behaviour identical."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(
            f"{name} must be an integer; got {raw!r}. Unset it to use the default ({default})."
        ) from None


def drb_candidates() -> tuple:
    """Ordered candidate locations for the external DeepResearch Bench harness.

    ``$DRB_REPO`` first (the repo convention), then a home-dir checkout, then the
    legacy dev-box path. Read from ``os.environ`` (not the .env file) and built at
    CALL time so a caller that exports ``$DRB_REPO`` after import is still honored.
    """
    home_path = os.path.expanduser("~/dev/deep_research_bench")
    candidates = [os.environ.get("DRB_REPO"), home_path]
    # Add the legacy dev-box path only when it differs from the home-dir
    # expansion (i.e. $HOME != /home/connor) so we never probe the same
    # directory twice.
    legacy = "/home/connor/dev/deep_research_bench"
    if legacy != home_path:
        candidates.append(legacy)
    return tuple(candidates)


def drb_root() -> pathlib.Path:
    """Resolve the external DeepResearch Bench harness root.

    Returns the first :func:`drb_candidates` entry that exists on disk, else
    falls back to the home-dir default (``~/dev/deep_research_bench``) so callers
    can still construct sub-paths and fail loudly at read time — rather than
    baking a hardcoded ``/home/connor`` default into the engine.
    """
    for c in drb_candidates():
        if c and os.path.isdir(c):
            return pathlib.Path(c)
    return pathlib.Path(os.path.expanduser("~/dev/deep_research_bench"))


def assert_phase() -> str:
    """Resolve the cost-attribution phase, defaulting to ``P1`` when unset.

    ``DRB_PHASE`` is a Lunon-internal cost-tracking label; a fresh public clone
    has no reason to set it, so an unset/empty value falls back to the ``P1``
    norm rather than refusing to run. A *non-empty but unrecognized* value is
    still a typo we fail loud on, preserving the guard's value for internal runs
    that set the phase explicitly."""
    phase = os.environ.get("DRB_PHASE", "").strip()
    if not phase:
        return "P1"
    if phase not in _VALID_PHASES:
        raise RuntimeError(
            f"DRB_PHASE must be one of {sorted(_VALID_PHASES)} (got {phase!r}). Unset it to use the default (P1)."
        )
    return phase


# Defensive cost-tracking hooks (never break a research run if absent) — same
# pattern as p0_artifacts/gpt55.py lines 40-48.
try:
    import sys as _sys

    _sys.path.insert(0, str(_ROOT / "cost_tracking"))
    from track import log_request, log_usage  # noqa: E402,F401
except Exception:  # noqa: BLE001

    def log_usage(*a, **k):  # type: ignore
        return None

    def log_request(*a, **k):  # type: ignore
        return None
