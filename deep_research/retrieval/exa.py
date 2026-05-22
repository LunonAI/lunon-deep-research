"""Exa as the primary retrieval backend (p1-checklist item 10).

- search(query, mode): mode='auto' default; mode='deep' for archetype in
  {explain-mechanism, predict} (heaviest multi-hop). type=deep is the deeper
  Exa search (NOT the P2-gated deep-reasoning answer mode).
- Each request is cost-logged via track.log_request('exa_search').
"""

import time

import requests

from .._env import get, log_request

_KEY = get("EXA_API_KEY")
_URL = "https://api.exa.ai/search"


def search(
    query: str,
    mode: str = "auto",
    num_results: int = 8,
    include_text: bool = True,
    max_chars: int = 4000,
    max_retries: int = 4,
):
    """Return list[{title,url,text,published_date,score}]. Empty list on failure."""
    if not _KEY:
        raise RuntimeError("EXA_API_KEY missing from .env")
    body = {
        "query": query,
        "type": "auto" if mode != "deep" else "deep",
        "numResults": num_results,
    }
    if include_text:
        body["contents"] = {"text": {"maxCharacters": max_chars}}
    headers = {"x-api-key": _KEY, "Content-Type": "application/json"}
    for attempt in range(max_retries):
        try:
            r = requests.post(_URL, headers=headers, json=body, timeout=60)
        except Exception:  # noqa: BLE001
            time.sleep(2**attempt)
            continue
        if r.status_code == 200:
            log_request("exa_search", note=f"mode={body['type']}")
            out = []
            for it in r.json().get("results", []):
                out.append(
                    {
                        "title": it.get("title", ""),
                        "url": it.get("url", ""),
                        "text": (it.get("text") or "")[:max_chars],
                        "published_date": it.get("publishedDate", ""),
                        "score": it.get("score", 0),
                    }
                )
            return out
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(2**attempt * 3, 30))
            continue
        raise RuntimeError(f"Exa HTTP {r.status_code}: {r.text[:300]}")
    return []
