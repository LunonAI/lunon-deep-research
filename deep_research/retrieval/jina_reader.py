"""Jina Reader page fetch (r.jina.ai) — cost-logged via track.log_request.

Used to pull full clean page text/markdown for evidence grounding when an Exa
snippet is insufficient.
"""
import time

import requests

from .._env import get, log_request

_KEY = get("JINA_API_KEY")


def fetch(url: str, max_chars: int = 12000, max_retries: int = 3) -> str:
    """Return clean page text/markdown ('' on failure)."""
    headers = {"X-Return-Format": "markdown"}
    if _KEY:
        headers["Authorization"] = f"Bearer {_KEY}"
    target = f"https://r.jina.ai/{url}"
    for attempt in range(max_retries):
        try:
            r = requests.get(target, headers=headers, timeout=60)
        except Exception:  # noqa: BLE001
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            log_request("jina_fetch")
            return r.text[:max_chars]
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(2 ** attempt * 3, 30))
            continue
        return ""
    return ""
