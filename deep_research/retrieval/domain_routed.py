"""Domain-routed retrieval (p1-checklist item 11).

Finance → SEC EDGAR full-text + Exa; Health → PubMed (E-utilities) + Exa;
Science → arXiv + Exa; default → Exa. ZH tasks → zh_path (item 12). All
domain APIs are keyless public endpoints; results normalized to the Exa shape
{title,url,text,published_date,score} so the rest of the pipeline is uniform.
"""

import time
import xml.etree.ElementTree as ET

import requests

from .._env import log_request
from . import exa, finance_apis, zh_path

_FIN = (
    "finance",
    "business",
    "market",
    "invest",
    "econom",
    "stock",
    "fund",
    "bank",
    "insurance",
    "dividend",
    "valuation",
    # ZH
    "金融",
    "经济",
    "市场",
    "投资",
    "保险",
    "基金",
    "股票",
    "银行",
    "财务",
    "财政",
    "收益",
    "估值",
    "分红",
    "证券",
    "理财",
    "中产",
)
_HEALTH = (
    "health",
    "medic",
    "clinic",
    "disease",
    "patient",
    "drug",
    "therap",
    "biolog",
    "epidemi",
    # ZH
    "健康",
    "医疗",
    "医学",
    "疾病",
    "病人",
    "药物",
    "诊断",
    "治疗",
    "临床",
    "生物",
    "流行病",
)
_SCI = (
    "science",
    "physic",
    "chemis",
    "math",
    "algorithm",
    "quantum",
    "model",
    "research",
    "engineering",
    "ai ",
    "machine learning",
    # ZH
    "科学",
    "物理",
    "化学",
    "数学",
    "算法",
    "量子",
    "模型",
    "工程",
    "人工智能",
    "机器学习",
    "深度学习",
    "研究",
)


def classify_domain(prompt: str, topic: str = "") -> str:
    t = (topic + " " + prompt[:400]).lower()
    if any(k in t for k in _FIN):
        return "finance"
    if any(k in t for k in _HEALTH):
        return "health"
    if any(k in t for k in _SCI):
        return "science"
    return "default"


def _get(url, params=None, timeout=30):
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "lunon-deep-research/1.0"})
            if r.status_code == 200:
                return r
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2**attempt)
    return None


def _sec_edgar(query, n=5):
    """EDGAR full-text search JSON API (keyless)."""
    out = []
    r = _get("https://efts.sec.gov/LATEST/search-index", params={"q": query, "forms": "10-K"})
    if r is None:
        return out
    log_request("exa_search", note="sec_edgar")
    try:
        hits = (r.json().get("hits", {}) or {}).get("hits", [])
        for h in hits[:n]:
            src = h.get("_source", {})
            adsh = (src.get("adsh") or "").replace("-", "")
            cik = (src.get("cik") or [""])[0] if isinstance(src.get("cik"), list) else src.get("cik", "")
            disp = src.get("display_names", [""])
            url = (
                (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K")
                if cik
                else "https://www.sec.gov/edgar"
            )
            txt = f"{disp[0] if disp else ''} 10-K filing {src.get('file_date', '')} (accession {adsh})"
            out.append({"title": txt, "url": url, "text": txt, "published_date": src.get("file_date", ""), "score": 0})
    except Exception:  # noqa: BLE001
        pass
    return out


def _pubmed(query, n=5):
    out = []
    r = _get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={"db": "pubmed", "term": query, "retmax": n, "retmode": "json"},
    )
    if r is None:
        return out
    log_request("exa_search", note="pubmed")
    ids = (r.json().get("esearchresult", {}) or {}).get("idlist", [])
    if not ids:
        return out
    s = _get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
    )
    if s is None:
        return out
    res = s.json().get("result", {})
    for pid in ids:
        d = res.get(pid, {})
        if d:
            out.append(
                {
                    "title": d.get("title", ""),
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
                    "text": f"{d.get('title', '')}. {d.get('fulljournalname', '')} "
                    f"{d.get('pubdate', '')}. {', '.join(a.get('name', '') for a in d.get('authors', [])[:3])}",
                    "published_date": d.get("pubdate", ""),
                    "score": 0,
                }
            )
    return out


def _arxiv(query, n=5):
    out = []
    r = _get("http://export.arxiv.org/api/query", params={"search_query": f"all:{query}", "max_results": n})
    if r is None:
        return out
    log_request("exa_search", note="arxiv")
    try:
        root = ET.fromstring(r.text)
        for e in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = (e.findtext("{http://www.w3.org/2005/Atom}title", "") or "").strip()
            summ = (e.findtext("{http://www.w3.org/2005/Atom}summary", "") or "").strip()
            idu = e.findtext("{http://www.w3.org/2005/Atom}id", "")
            pub = e.findtext("{http://www.w3.org/2005/Atom}published", "")
            out.append(
                {"title": title, "url": idu, "text": f"{title}. {summ}"[:1500], "published_date": pub, "score": 0}
            )
    except Exception:  # noqa: BLE001
        pass
    return out


def search(query: str, *, language: str, domain: str, mode: str = "auto", num_results: int = 6):
    """Domain + Exa blended results (Exa always included as the spine)."""
    if language == "zh":
        return zh_path.search(query, mode=mode, num_results=num_results)
    extra = []
    if domain == "finance":
        extra = finance_apis.finance_evidence(query) or _sec_edgar(query)
    elif domain == "health":
        extra = _pubmed(query)
    elif domain == "science":
        extra = _arxiv(query)
    base = exa.search(query, mode=mode, num_results=num_results)
    # de-dup by url, domain sources first (authoritative), then Exa breadth
    seen, merged = set(), []
    for r in extra + base:
        u = r.get("url", "")
        if u and u not in seen:
            seen.add(u)
            merged.append(r)
    return merged
