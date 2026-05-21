"""Shared env + cost-tracking infra for the deep_research engine.

- load_env(): mirrors p0_artifacts/gpt55.py — reads the engine .env into a dict.
- assert_phase(): fail-loud DRB_PHASE guard (plan point 9) so P1 spend is never
  silently mis-attributed to 'P?'/'P0'.
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


def assert_phase() -> str:
    """Fail loud if DRB_PHASE is unset or unexpected (plan point 9)."""
    phase = os.environ.get("DRB_PHASE", "").strip()
    if phase not in _VALID_PHASES:
        raise RuntimeError(
            f"DRB_PHASE must be set to one of {sorted(_VALID_PHASES)} before any "
            f"engine/script run (got {phase!r}). Refusing to run and undercount "
            f"P1 spend. Export DRB_PHASE=P1."
        )
    return phase


# Defensive cost-tracking hooks (never break a research run if absent) — same
# pattern as p0_artifacts/gpt55.py lines 40-48.
try:
    import sys as _sys
    _sys.path.insert(0, str(_ROOT / "cost_tracking"))
    from track import log_usage, log_request  # noqa: E402,F401
except Exception:  # noqa: BLE001
    def log_usage(*a, **k):  # type: ignore
        return None

    def log_request(*a, **k):  # type: ignore
        return None
