"""Tests for the Anthropic streaming client config + timeout layering.

The 2026-05-25 CAPEL smoke for id=56 hung indefinitely on a single Anthropic
call (writer or refiner, observed via netstat: 1 ESTABLISHED + 4 CLOSE_WAIT
sockets, 0 ledger activity for 7+ min). Root cause: the SDK default timeout
(NOT_GIVEN → ~600s overall) does NOT bound streaming-read intervals, so a
mid-stream chunk delay left the connection hanging. The client now passes
an explicit httpx.Timeout with `read=600` so streaming chunk gaps over
10 min surface as httpx.ReadTimeout → anthropic.APITimeoutError → caught
by raw_call's retry loop.

These tests pin the timeout config so a refactor that drops the explicit
timeout (and silently regresses the hang surface) gets caught loudly.
"""

import httpx

from deep_research.clients import anthropic_client


def test_anthropic_client_has_explicit_timeout():
    """Client MUST be constructed with an explicit httpx.Timeout — the SDK
    default (`NOT_GIVEN`) was load-bearing in the 2026-05-25 hang."""
    # The Anthropic SDK exposes the underlying httpx client at `_client`.
    inner = anthropic_client._client
    assert inner.timeout is not None, "Anthropic client must have an explicit timeout"
    # Cross-check the module-level _TIMEOUT constant is the one wired in —
    # belt-and-suspenders against a refactor that builds two different
    # timeout objects and uses the wrong one.
    assert isinstance(anthropic_client._TIMEOUT, httpx.Timeout)


def test_anthropic_streaming_read_timeout_at_least_60s():
    """The read timeout must be long enough to cover legitimate streaming
    responses (writer.write_section at max_tokens=14000 + think=True can
    legitimately stream for several minutes) but bounded so a hung connection
    surfaces rather than waiting forever.

    Pinning a lower bound (60s) rather than the exact value keeps this test
    from breaking on tuning — but it MUST be set explicitly (not None / not
    SDK default)."""
    t = anthropic_client._TIMEOUT
    # httpx.Timeout exposes per-phase timeouts as `.connect`, `.read`,
    # `.write`, `.pool` attributes.
    assert t.read is not None, "read timeout must be set explicitly"
    assert t.read >= 60.0, f"read timeout {t.read}s too short for streaming writer calls"
    # And bounded — must NOT be infinity / None / 0. Anything >1 hour is
    # effectively unbounded for our purposes.
    assert t.read <= 3600.0, f"read timeout {t.read}s is effectively unbounded; defeats the hang-bound purpose"


def test_anthropic_connect_timeout_short():
    """Network-level connect failures should surface fast (not block for
    minutes). Pin a sensible upper bound."""
    t = anthropic_client._TIMEOUT
    assert t.connect is not None, "connect timeout must be set explicitly"
    assert t.connect <= 30.0, f"connect timeout {t.connect}s too long; network failures should surface fast"


def test_httpx_transport_error_is_in_retryable():
    """Smoke-5 (2026-05-25) failed with `httpx.RemoteProtocolError: peer
    closed connection without sending complete message body` from inside
    the anthropic streaming context manager. The SDK does NOT wrap mid-stream
    httpx errors as APIConnectionError — they propagate up unwrapped.

    `httpx.TransportError` is the parent class of RemoteProtocolError,
    ReadTimeout, ConnectError, etc. — exactly the transport-layer errors
    we want to retry. Greptile PR #26 follow-up (2026-05-26) narrowed this
    from `httpx.HTTPError` (the whole-tree root) to `httpx.TransportError`
    so we don't accidentally retry on httpx.HTTPStatusError (4xx/5xx after
    .raise_for_status), which should fail fast."""
    assert httpx.TransportError in anthropic_client._RETRYABLE, (
        "httpx.TransportError must be in _RETRYABLE to catch mid-stream "
        "connection cuts (smoke-5 regression). Without it, transient "
        "RemoteProtocolError / ReadTimeout etc. propagate up and trigger "
        "the much-more-expensive adapter-level full-task retry."
    )


def test_httpx_status_error_is_NOT_in_retryable():
    """Greptile PR #26 follow-up (2026-05-26): `httpx.HTTPStatusError`
    (raised by `.raise_for_status()` on 4xx/5xx responses) should NOT be
    silently retried — it represents a real server-side decision (rate
    limit, auth failure, bad request) that needs operator attention. The
    narrowing from `httpx.HTTPError` to `httpx.TransportError` was
    specifically to exclude HTTPStatusError; pin that fact so a future
    refactor can't accidentally re-broaden the catch."""
    # Construct an HTTPStatusError instance (without a real request/response
    # we just need the type identity for the isinstance check below).
    assert not issubclass(httpx.HTTPStatusError, tuple(anthropic_client._RETRYABLE)), (
        "httpx.HTTPStatusError must NOT satisfy isinstance against _RETRYABLE — "
        "4xx/5xx responses should fail fast, not retry 3× silently."
    )


def test_httpx_remote_protocol_error_is_subclass_of_retryable():
    """Belt-and-suspenders: the specific exception we observed (smoke-5)
    must satisfy isinstance against _RETRYABLE. Catches a future refactor
    that swaps `httpx.TransportError` for some narrower httpx class that
    doesn't cover RemoteProtocolError."""
    # httpx.RemoteProtocolError inherits from httpx.TransportError; assert
    # the exception WOULD be caught by `except _RETRYABLE`.
    assert issubclass(httpx.RemoteProtocolError, tuple(anthropic_client._RETRYABLE)), (
        "httpx.RemoteProtocolError must satisfy isinstance against _RETRYABLE — "
        "this is the exact exception class that took down smoke-5"
    )


def test_max_tokens_escalation_ceiling_bounded_under_edge_cut_zone():
    """Greptile PR #26 follow-up (2026-05-26): the empty-content retry path
    in raw_call escalates `max_tokens` by ×1.6 each iteration, capped at
    `_MAX_TOKENS_ESCALATION_CEILING`. Pre-fix the cap was 32000 — exactly
    the value smoke-5 proved Anthropic's edge cuts. For the architect's
    initial 24000 the escalation would land at 24000 × 1.6 = 38400 →
    clamped to 32000, re-entering the failure zone the smoke-5 follow-up
    explicitly reverted from.

    Pin the ceiling at 28000 (matches the architect max_tokens upper bound
    in tests/test_architect.py::test_architect_max_tokens_bounded_...).
    When the next person raises this, the architect test must move in
    lockstep."""
    assert hasattr(anthropic_client, "_MAX_TOKENS_ESCALATION_CEILING")
    assert anthropic_client._MAX_TOKENS_ESCALATION_CEILING <= 28000, (
        f"_MAX_TOKENS_ESCALATION_CEILING={anthropic_client._MAX_TOKENS_ESCALATION_CEILING} "
        f"would let empty-content retries escalate back into the "
        f"Anthropic-edge-cut zone (smoke-5 hit RemoteProtocolError at 32000)."
    )
    # And not absurdly low — needs to be at least the architect's nominal
    # 24000 so a single bump still has somewhere to go. (24000 × 1.6 = 38400
    # clamped to 28000 = ~17% headroom, which is what we want for one retry.)
    assert anthropic_client._MAX_TOKENS_ESCALATION_CEILING >= 24000, (
        f"_MAX_TOKENS_ESCALATION_CEILING={anthropic_client._MAX_TOKENS_ESCALATION_CEILING} "
        f"too low — the escalation should give an empty-content retry at "
        f"least some headroom above the architect's nominal 24000."
    )
