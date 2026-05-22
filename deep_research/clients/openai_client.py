"""GPT-5.5 client — faithful to p0_artifacts/gpt55.py's proven payload/retry
shape (chat/completions, max_completion_tokens, reasoning_effort, NO
temperature/top_p — gpt-5.x reasoning models reject them), plus:
- optional best-effort `seed` for gate-affecting calls (plan point 12); auto-
  drops seed and retries if the API rejects it.
- auto cost-log on every HTTP 200 (empty-content retries still bill), mirroring
  gpt55.py.
"""

import time

import requests

from .._env import get, log_usage

_KEY = get("OPENAI_API_KEY")
_BASE = (get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
_URL = f"{_BASE}/chat/completions"
# Thread-safe Session reuses TCP+TLS connections (50-200ms saved per call).
# Default pool_maxsize=10 was causing "Connection pool is full, discarding"
# warnings at workers=20 (50+ concurrent calls). Bumped to 100 on BOTH http
# and https adapters; pool_connections matches pool_maxsize so single-host
# cache survives even if we ever hit additional API hosts.
_SESSION = requests.Session()
_ADAPTER = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
_SESSION.mount("http://", _ADAPTER)
_SESSION.mount("https://", _ADAPTER)


def raw_call(
    model,
    user,
    system="",
    reasoning_effort="low",
    max_completion_tokens=6000,
    seed=None,
    max_retries=3,
    timeout=300,
    note="",
):
    """Return (content_str, usage_dict). Raises RuntimeError after retries."""
    if not _KEY:
        raise RuntimeError("OPENAI_API_KEY missing from .env")
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": user})
    headers = {"Authorization": f"Bearer {_KEY}", "Content-Type": "application/json"}
    budget = max_completion_tokens
    use_seed = seed is not None
    last = ""
    for attempt in range(max_retries):
        payload = {
            "model": model,
            "messages": msgs,
            "max_completion_tokens": budget,
            "reasoning_effort": reasoning_effort,
        }
        if use_seed:
            payload["seed"] = seed
        try:
            r = _SESSION.post(_URL, headers=headers, json=payload, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(2**attempt)
            continue
        if r.status_code == 200:
            data = r.json()
            usage = data.get("usage") or {}
            log_usage(data.get("model") or model, usage, note=note or f"reasoning={reasoning_effort}")
            ch = data["choices"][0]
            content = (ch["message"].get("content") or "").strip()
            if content:
                return content, usage
            last = f"empty content (finish={ch.get('finish_reason')})"
            budget = min(int(budget * 1.8), 32000)
            continue
        if r.status_code == 400 and use_seed and "seed" in r.text.lower():
            # model rejects seed — best-effort determinism only; drop & retry
            use_seed = False
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            time.sleep(min(2**attempt * 3, 45))
            continue
        raise RuntimeError(f"OpenAI HTTP {r.status_code}: {r.text[:400]}")
    raise RuntimeError(f"OpenAI {model} failed after {max_retries} retries: {last}")
