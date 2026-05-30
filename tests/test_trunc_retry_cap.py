"""Tests for the DR_TRUNC_RETRY_CAP env validation in orchestrate.

PR-A (2026-05-29) added a cut-generation re-roll loop bounded by
`_TRUNC_RETRY_CAP`. Greptile PR #71 flagged that the original
`int(os.environ.get("DR_TRUNC_RETRY_CAP", "2"))` had no validation: a
non-integer crashed the whole module at import with a cryptic ValueError, a
negative value silently disabled re-rolls (``0 < -1`` is false from the first
iteration), and an absurdly large value (e.g. 50) could trigger dozens of
full-section regenerations per section under persistent stream-drops — exactly
the high-contention scenario the re-roll feature addresses.

The fix mirrors `_specialist_timeout_from_env()`: explicit try/except, a clear
message, and a [MIN, MAX] range clamp. These tests pin that validation so a
future refactor back to a bare int() — re-introducing the cryptic import-time
crash or dropping a bound — is caught.
"""

import re

import pytest

from deep_research import orchestrate


def test_trunc_retry_cap_default(monkeypatch):
    """The default (no env) must be 2. delenv first so the assertion can't
    spuriously fail in a shell that exported DR_TRUNC_RETRY_CAP."""
    monkeypatch.delenv("DR_TRUNC_RETRY_CAP", raising=False)
    assert orchestrate._trunc_retry_cap_from_env() == 2


def test_trunc_retry_cap_reads_env_override(monkeypatch):
    """A valid in-band override is honored; clearing it restores the default.
    Tested via the helper (not a module reload) so it can't perturb other
    tests' module state."""
    monkeypatch.setenv("DR_TRUNC_RETRY_CAP", "4")
    assert orchestrate._trunc_retry_cap_from_env() == 4
    monkeypatch.delenv("DR_TRUNC_RETRY_CAP", raising=False)
    assert orchestrate._trunc_retry_cap_from_env() == 2


def test_trunc_retry_cap_zero_is_allowed_killswitch(monkeypatch):
    """0 is a legitimate explicit kill-switch (re-rolls disabled) — it must
    NOT be rejected as out-of-range, unlike a negative value. Pins that the
    lower bound is inclusive of 0 so a future tightening to MIN=1 (which would
    remove the operator's ability to disable the feature) is caught."""
    monkeypatch.setenv("DR_TRUNC_RETRY_CAP", "0")
    assert orchestrate._trunc_retry_cap_from_env() == 0


@pytest.mark.parametrize("raw", ["2x", "", "two", "1.5", "0x2", "  "])
def test_trunc_retry_cap_rejects_non_integer(monkeypatch, raw):
    """A non-integer DR_TRUNC_RETRY_CAP must fail loud at parse time with the
    integer-required message rather than a bare/cryptic int() ValueError at
    module-import time. Pins the failure branch so a future refactor that swaps
    the explicit guard for a bare int() gets caught."""
    monkeypatch.setenv("DR_TRUNC_RETRY_CAP", raw)
    with pytest.raises(ValueError, match="must be a non-negative integer"):
        orchestrate._trunc_retry_cap_from_env()


@pytest.mark.parametrize("raw", ["-1", "-5", "6", "50", "99999"])
def test_trunc_retry_cap_rejects_out_of_range(monkeypatch, raw):
    """Values outside [_TRUNC_RETRY_CAP_MIN, _TRUNC_RETRY_CAP_MAX] must fail
    loud — negative (silently disables re-rolls) and absurdly large (dozens of
    expensive regenerations per section) both reach this guard. Spans
    below-min and above-max so a future one-sided check (e.g. dropping the
    upper bound) is caught."""
    monkeypatch.setenv("DR_TRUNC_RETRY_CAP", raw)
    with pytest.raises(ValueError, match="out of range"):
        orchestrate._trunc_retry_cap_from_env()


def test_trunc_retry_cap_out_of_range_message_names_band(monkeypatch):
    """The out-of-range message must surface the actual [MIN, MAX] band so an
    operator can self-correct without reading source. Asserts the full rendered
    message (re.escape'd brackets) — pins the band to the constants."""
    monkeypatch.setenv("DR_TRUNC_RETRY_CAP", "50")
    expected = (
        f"DR_TRUNC_RETRY_CAP out of range "
        f"[{orchestrate._TRUNC_RETRY_CAP_MIN}, {orchestrate._TRUNC_RETRY_CAP_MAX}]: 50"
    )
    with pytest.raises(ValueError, match=re.escape(expected)):
        orchestrate._trunc_retry_cap_from_env()
