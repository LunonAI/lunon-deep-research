"""OpenRouter client (OpenAI-compatible) — Nemotron researcher specialists and
the ZH writer-pass candidates. Mirrors gpt55.py retry + auto cost-log.

Reproducibility (decision #1): pin ONE underlying provider. Set
`DR_OPENROUTER_PROVIDER=<slug>` to hard-pin; otherwise allow_fallbacks=false and
the served provider is recorded in the cost-log note so it can be pinned once
observed.
"""

import time

import requests

from .._env import get, log_usage

_KEY = get("OPENROUTER_API_KEY")
_URL = "https://openrouter.ai/api/v1/chat/completions"
_PINNED = get("DR_OPENROUTER_PROVIDER")
# round 10 (2026-06-03): when NO provider is explicitly pinned, route by
# THROUGHPUT so OpenRouter serves the model on its FASTEST provider instead of
# the cheapest. The Nemotron specialist EXTRACTS (~14k-token structured output)
# were auto-routed to slow providers (DekaLLM/Nebius) and timing out at the 1000s
# specialist cap → the structured findings were DISCARDED and the run degraded to
# crude snippet evidence AND ate the full timeout. Throughput routing keeps the
# extract inside budget, so we keep the rich findings (better Comprehensiveness/
# Insight) and finish faster. Set DR_OPENROUTER_SORT="" / "off" to disable, or
# "price"/"latency" to choose a different OpenRouter sort key.
# Default ON: an unset/empty env means throughput routing (get() returns "" for
# unset). Explicit "off"/"none" disables it (revert to the _PINNED order).
_SORT = (get("DR_OPENROUTER_SORT") or "throughput").lower()
if _SORT in ("off", "none"):
    _SORT = ""
# Thread-safe Session for TCP+TLS reuse — pool sized for workers=20+
# concurrency (50+ concurrent OpenRouter calls). Mounted on both schemes;
# pool_connections matches pool_maxsize so multi-provider routes don't
# starve. Same pattern as openai_client.
_SESSION = requests.Session()
_ADAPTER = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
_SESSION.mount("http://", _ADAPTER)
_SESSION.mount("https://", _ADAPTER)


def _provider_config(provider):
    """Build the OpenRouter `provider` routing object.

    Per-call `provider` semantics:
      None → default auto-routing. Throughput sort (`_SORT`, default "throughput")
        picks the FASTEST provider and takes PRECEDENCE over a legacy fixed-provider
        pin (`_PINNED`/DR_OPENROUTER_PROVIDER) — pinning DeepInfra was the root cause
        of the slow Nemotron extracts (served slow / fell back to DekaLLM/Nebius and
        blew the 1000s specialist cap). DR_OPENROUTER_SORT=off restores the pin.
      "" → no pin, any provider (still throughput-sorted when `_SORT` is on).
      "X" → STRICT pin to X, no fallback, no sort (repro experiments).
    The served provider is logged per-call in `note=...provider=X` for audit.
    """
    if provider is None:
        cfg = {"allow_fallbacks": True}
        if _SORT:
            cfg["sort"] = _SORT
        elif _PINNED:
            cfg["order"] = [_PINNED]
        return cfg
    if provider == "":
        cfg = {"allow_fallbacks": True}
        if _SORT:
            cfg["sort"] = _SORT
        return cfg
    return {"allow_fallbacks": False, "order": [provider]}


def raw_call(model, user, system="", max_tokens=8000, seed=None, max_retries=3, timeout=180, note="", provider=None):
    # Tighter retry budget for OpenRouter (Nemotron/DeepInfra latency) — caps
    # a single hung extract call at ~3*(180+12)≈10min instead of 28min so a
    # rate-limited worker can't stall an entire task. Specialists.research
    # wraps in try/except + snippet_fallback so a failed retry budget degrades
    # to evidence-from-snippets instead of crashing.
    """Return (content_str, usage_dict). Raises RuntimeError after retries."""
    if not _KEY:
        raise RuntimeError("OPENROUTER_API_KEY missing from .env")
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": user})
    headers = {
        "Authorization": f"Bearer {_KEY}",
        "Content-Type": "application/json",
        "X-Title": "lunon-deep-research",
    }
    provider = _provider_config(provider)
    last = ""
    for attempt in range(max_retries):
        payload = {
            "model": model,
            "messages": msgs,
            "max_tokens": max_tokens,
            "provider": provider,
        }
        if seed is not None:
            payload["seed"] = seed
        try:
            r = _SESSION.post(_URL, headers=headers, json=payload, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(2**attempt)
            continue
        if r.status_code == 200:
            # OpenRouter occasionally returns truncated/non-JSON bodies under
            # provider stress (observed on DeepSeek V4 Pro via AtlasCloud).
            # Treat parse failure as transient + retryable, not fatal.
            try:
                data = r.json()
            except Exception as e:  # noqa: BLE001
                last = f"json-parse error: {type(e).__name__}: {str(e)[:120]}"
                time.sleep(min(2**attempt * 3, 45))
                continue
            usage = data.get("usage") or {}
            served = data.get("provider", "?")
            log_usage(model, usage, note=(note or "openrouter") + f" provider={served}")
            choices = data.get("choices") or []
            content = ""
            if choices:
                content = (choices[0].get("message", {}).get("content") or "").strip()
            if content:
                return content, usage
            last = f"empty content ({data.get('error') or choices})"
            max_tokens = min(int(max_tokens * 1.6), 32000)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            time.sleep(min(2**attempt * 3, 45))
            continue
        raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {r.text[:400]}")
    raise RuntimeError(f"OpenRouter {model} failed after {max_retries} retries: {last}")
