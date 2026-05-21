"""ZH light path (p1-checklist item 12; decision #3).

No SerpApi Baidu key is funded; v4 §2.4 scopes the full Baidu stack to P2.
P1 ZH retrieval = Exa (Simplified-Chinese query, type=auto) + optional Jina
reader for thin snippets. W7 measures the ZH/EN RACE gap; >~5 pts triggers the
decision-#3 P1.5 patch (Jina-based direct Baidu SERP scrape — DR_ZH_BAIDU=1).
"""
import os
import time

import requests

from .._env import log_request
from . import exa, jina_reader


def _baidu_scrape(query, n=6):
    """P1.5 patch (decision #3): keyless Baidu SERP via Jina reader proxy.
    Off by default; enabled by DR_ZH_BAIDU=1 once W7 shows a >5pt ZH gap."""
    url = "https://www.baidu.com/s?wd=" + requests.utils.quote(query)
    md = jina_reader.fetch(url, max_chars=6000)
    out = []
    if md:
        log_request("jina_fetch", note="zh_baidu_scrape")
        # crude extraction: jina returns markdown links; keep first n external
        import re
        for m in re.finditer(r"\[([^\]]{8,120})\]\((https?://[^\s)]+)\)", md):
            t, u = m.group(1), m.group(2)
            if "baidu.com" in u:
                continue
            out.append({"title": t, "url": u, "text": t,
                        "published_date": "", "score": 0})
            if len(out) >= n:
                break
    return out


def search(query: str, mode: str = "auto", num_results: int = 6):
    res = exa.search(query, mode=mode, num_results=num_results, max_chars=2500)
    if os.environ.get("DR_ZH_BAIDU") == "1":
        try:
            res = _baidu_scrape(query, n=num_results) + res
        except Exception:  # noqa: BLE001
            pass
    seen, out = set(), []
    for r in res:
        u = r.get("url", "")
        if u and u not in seen:
            seen.add(u)
            out.append(r)
    time.sleep(0)  # placeholder; rate-limit hook if needed
    return out
