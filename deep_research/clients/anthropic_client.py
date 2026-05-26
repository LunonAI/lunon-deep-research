"""Claude Opus 4.7 client (anthropic SDK), mirroring gpt55.py's retry +
auto cost-log discipline. Used for orchestrator/planner/scout/architect/writer.

Cost hook: Anthropic usage shape (input_tokens/output_tokens) is logged via
track.log_usage, which already accepts that shape (track.py:57-58).
"""

import sys
import time

import anthropic
import httpx

from .._env import get, log_usage

_KEY = get("ANTHROPIC_API_KEY")
_BASE = get("ANTHROPIC_BASE_URL") or None  # SDK default if empty

# Layered timeouts for the Anthropic streaming path (2026-05-25 follow-up
# after the CAPEL smoke hang on id=56). The SDK's default is `NOT_GIVEN`,
# which falls back to a 600s overall budget that did NOT bound our hung
# call — observed a writer streaming call sitting >60min with one ESTABLISHED
# TCP socket and 4 CLOSE_WAIT sockets piling up. The explicit `read=600`
# below means if a streaming chunk doesn't arrive within 10 min we raise
# httpx.ReadTimeout → wrapped as anthropic.APITimeoutError → caught by our
# _RETRYABLE retry loop. Connect timeout stays short (network failures
# should surface fast). Pool stays small to keep stale-connection cleanup
# aggressive (the CLOSE_WAIT pile-up we observed suggests pool issues).
_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0)

# Greptile PR #26 follow-up (2026-05-26): cap the empty-content max_tokens
# escalation (raw_call line ~142) at the same value tests/test_architect.py
# pins for architect's initial literal — 28000. Below that ceiling we stay
# inside Anthropic's edge-cut tolerance window (smoke-5 proved 32000 + think
# streams reliably get cut). When the next person raises this, the test pin
# in test_architect.py + tests below should be raised in lockstep.
_MAX_TOKENS_ESCALATION_CEILING = 28000

_client = anthropic.Anthropic(
    api_key=_KEY,
    timeout=_TIMEOUT,
    **({"base_url": _BASE} if _BASE else {}),
)

_RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
    # 2026-05-25 follow-up: the 77min CAPEL smoke for id=56 died with
    # `httpx.RemoteProtocolError: peer closed connection without sending
    # complete message body (incomplete chunked read)` mid-architect-stream.
    # The anthropic SDK does NOT wrap mid-stream httpx errors as
    # APIConnectionError — they propagate up unwrapped. Catching
    # httpx.TransportError covers the transport-layer errors we actually
    # want to retry: RemoteProtocolError, ReadTimeout, ConnectError, plus
    # the rest of the transport family. Greptile PR #26 follow-up
    # (2026-05-26): narrowed from `httpx.HTTPError` (the whole-tree root)
    # to `httpx.TransportError` so we DON'T accidentally retry on
    # httpx.HTTPStatusError (4xx/5xx after .raise_for_status), which
    # should fail fast. Without this transport-layer catch the adapter's
    # outer task-level retry (deep_research/adapter.py:112) fires instead,
    # which means redoing the whole task's planning + research from scratch
    # — observed cost: $1.21 burned on a doubled architect attempt with no
    # article output.
    httpx.TransportError,
)


def raw_call(model, user, system="", max_tokens=8000, think=False, effort="low", max_retries=3, note=""):
    """Return (text_str, usage_dict). Raises RuntimeError after retries.

    Opus 4.7 API: reasoning is controlled by output_config.effort; think=True
    enables adaptive thinking (thinking.type='adaptive'). Default: plain (no
    thinking) to control cost. (The old thinking.type='enabled'+budget_tokens
    form is rejected by Opus 4.7.)
    """
    if not _KEY:
        raise RuntimeError("ANTHROPIC_API_KEY missing from .env")
    kw = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        kw["system"] = system
    if think:
        kw["thinking"] = {"type": "adaptive"}
        kw["output_config"] = {"effort": effort}
    last = ""
    for attempt in range(max_retries):
        attempt_t0 = time.time()
        try:
            # Streaming required for any request the SDK predicts will take
            # >10 minutes — true post-PR-22 for the architect's max_tokens=32000
            # + think=True path. Non-streaming `messages.create(**kw)` raises
            # ValueError pre-flight without ever hitting the API. Using
            # `messages.stream(**kw)` + `.get_final_message()` yields the same
            # response object (content, usage, stop_reason all populate
            # identically) without the SDK's non-streaming duration guard.
            with _client.messages.stream(**kw) as stream:
                resp = stream.get_final_message()
        except _RETRYABLE as e:
            last = f"{type(e).__name__}: {e}"
            elapsed = time.time() - attempt_t0
            backoff = min(2**attempt * 3, 45)
            # Diagnostic logging (2026-05-26 follow-up after the smoke-6
            # incident where scout.synth took 1h43min via silent retries with
            # NO log signal until the eventual success). Print each retry to
            # stderr so the operator can see retry storms in real time
            # instead of staring at a hung adapter for an hour.
            print(
                f"[anthropic_client] retry note={note!r} attempt={attempt + 1}/{max_retries} "
                f"elapsed={elapsed:.1f}s err={type(e).__name__}: {str(e)[:120]} "
                f"backoff={backoff}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(backoff)
            continue
        except anthropic.APIStatusError as e:
            if e.status_code in (429, 500, 502, 503, 504, 529):
                last = f"HTTP {e.status_code}"
                elapsed = time.time() - attempt_t0
                backoff = min(2**attempt * 3, 45)
                print(
                    f"[anthropic_client] retry note={note!r} attempt={attempt + 1}/{max_retries} "
                    f"elapsed={elapsed:.1f}s HTTP {e.status_code} backoff={backoff}s",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(backoff)
                continue
            raise RuntimeError(f"Anthropic HTTP {e.status_code}: {str(e)[:400]}")
        u = resp.usage
        # Capture full Anthropic usage shape — including cache_* fields which
        # bill at 1.25× input (cache_creation) and 0.1× input (cache_read).
        # Currently 0 since we don't use cache_control, but forward-safe.
        usage = {
            "input_tokens": getattr(u, "input_tokens", 0) or 0,
            "output_tokens": getattr(u, "output_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        }
        log_usage(model, usage, note=note or "claude")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        if text:
            return text, usage
        last = f"empty content (stop={resp.stop_reason})"
        # Greptile PR #26 follow-up (2026-05-26): empty-content escalation
        # cap held at _MAX_TOKENS_ESCALATION_CEILING (28000), matching the
        # `architect max_tokens ≤ 28000` pin in tests/test_architect.py.
        # Pre-fix the cap was 32000 — exactly the value smoke-5 proved
        # Anthropic's edge cuts. With messages.create() the SDK's pre-flight
        # guard would refuse a 32000-token non-streaming retry; with
        # messages.stream() (the smoke-5 follow-up switch) that guard is
        # absent, so an empty-content retry could escalate the architect's
        # initial 24000 → 32000 → re-enter the same edge-cut failure mode.
        kw["max_tokens"] = min(int(kw["max_tokens"] * 1.6), _MAX_TOKENS_ESCALATION_CEILING)
    raise RuntimeError(f"Anthropic {model} failed after {max_retries} retries: {last}")
