"""P2-Wave-1-D: evidence-layer deduplication.

Two-pass dedup of the orchestrator's memory_bank, run once pre-loop before
the writer / assign_primary_sections:

  D4 — URL + title normalization.
    Normalize the URL (lowercased host, path stripped of trailing /, query
    dropped except `id=` and `q=`, anchor dropped) and the title (lowercased,
    punctuation stripped, leading site-name prefix removed). Cluster blocks
    by `normalized_url` or by (`normalized_title`, `source_name`) when the
    URL is empty. Canonical = longest text, eid tie-break. Union all
    section_ids across the cluster onto the canonical block. Pure Python,
    deterministic, zero LLM cost. Removes "same URL retrieved by multiple
    specialists" duplicates which empirically dominate Lunon's bank.

  D1 — OpenAI text-embedding-3-small + cosine ≥ 0.85.
    On the post-D4 bank, embed `source_name + first 500 chars of text` for
    every remaining block. O(n²) pairwise cosine; cluster anything at or
    above threshold. Same canonical-selection rule as D4. Catches paraphrase
    duplicates (two outlets quoting the same Fed report, etc.) that D4's
    URL-match misses. Cost ~$2-5 per 100-article W-run.

Sequencing: D MUST run BEFORE `bank.assign_primary_sections()`. Otherwise
the primary-tagging operates on a not-yet-deduped bank and dangling
primary_section_ids end up referencing dropped eids. The orchestrator hook
at `orchestrate.py:162` calls `dedup_bank` first, then assign_primary.

Modes (env: DR_EVIDENCE_DEDUP):
    off            — no-op (legacy).
    url            — D4 only. Fast, deterministic, no API call.
    url+embedding  — D4 + D1 layered. Default flip-target post-Wave-1 dev10.

Fail-soft: D1 embedding API failures DO NOT raise; the bank stays post-D4
and the pipeline continues. D4 failures are not anticipated (pure Python).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlparse

from .. import llm

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_DEFAULT_COSINE_THRESHOLD = 0.85
_EMBED_TEXT_PREFIX_CHARS = 500


def _normalize_url(url: str) -> str:
    """Canonicalize a URL for D4 cluster-key comparison.

    Strips: scheme (we re-add https), trailing path slash, all query params
    except `id=` and `q=` (semantic markers for content-id and search-query),
    URL fragment. Lowercased host + path. Returns "" for empty input.
    """
    if not url:
        return ""
    try:
        p = urlparse(url.strip().lower())
    except ValueError:
        return url.strip().lower()
    host = (p.hostname or "").rstrip(".")
    path = (p.path or "/").rstrip("/")
    keep = []
    for k, v in parse_qsl(p.query or "", keep_blank_values=False):
        if k.lower() in ("id", "q"):
            keep.append((k.lower(), v))
    query = "&".join(f"{k}={v}" for k, v in sorted(keep))
    suffix = f"?{query}" if query else ""
    return f"https://{host}{path}{suffix}"


def _normalize_title(title: str, source_name: str = "") -> str:
    """Canonicalize a title for D4 cluster-key fallback when URL is empty.

    Lowercased, punctuation collapsed to space, leading "Source - " /
    "Source: " / "Source | " prefix stripped if it matches `source_name`.
    """
    if not title:
        return ""
    t = title.lower().strip()
    if source_name:
        sn = source_name.lower().strip()
        for sep in (" - ", " — ", " – ", ": ", " | "):
            prefix = sn + sep
            if t.startswith(prefix):
                t = t[len(prefix) :]
                break
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def _cluster_key_d4(block: dict) -> tuple:
    """Cluster key. Two blocks share a key iff they're D4 duplicates.

    Preference order:
      1. Same `normalized_url` (most common collision mode).
      2. Same (`normalized_title`, lowercased `source_name`) when URL absent.
      3. Singleton (own eid) as a fallback so we never accidentally merge
         distinct sources with empty URL+title.
    """
    url = _normalize_url(block.get("url", ""))
    if url:
        return ("url", url)
    title = _normalize_title(block.get("title", ""), block.get("source_name", ""))
    src = (block.get("source_name", "") or "").lower().strip()
    if title and src:
        return ("title_src", title, src)
    return ("eid", block.get("eid", ""))


def _select_canonical(blocks: list[dict]) -> dict:
    """Within a cluster, pick the longest-text block. Tie-break: lowest eid.

    Lowest eid means earliest-recorded — preserves chronological provenance
    when text lengths tie, which is rare in practice but worth pinning.
    """

    def sort_key(b: dict) -> tuple[int, int]:
        text_len = len(b.get("text", "") or "")
        # eids look like "E12" — strip the prefix and parse as int.
        eid_digits = re.sub(r"\D", "", b.get("eid", "0")) or "0"
        return (-text_len, int(eid_digits))

    return min(blocks, key=sort_key)


def _rebuild_by_section(bank) -> None:
    """Rebuild `_by_section` index from the current `_items`. Called after a
    collapse pass mutates the items dict — simpler and less error-prone than
    threading section-id rewrites through the collapse loop."""
    bank._by_section = {}
    for eid, block in bank._items.items():
        for sid in block.get("section_ids", []) or []:
            bank._by_section.setdefault(sid, []).append(eid)


def _collapse_clusters(bank, clusters: list[list[dict]]) -> int:
    """For each cluster of ≥2 blocks: pick canonical, union section_ids,
    drop the rest. Rebuilds `_by_section` at the end. Returns count of
    dropped (non-canonical) blocks."""
    n_collapsed = 0
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        canonical = _select_canonical(cluster)
        canonical_eid = canonical["eid"]
        merged_sids: set[str] = set(canonical.get("section_ids", []) or [])
        for b in cluster:
            merged_sids.update(b.get("section_ids", []) or [])
        canonical["section_ids"] = sorted(merged_sids)
        for b in cluster:
            if b["eid"] != canonical_eid:
                bank._items.pop(b["eid"], None)
                n_collapsed += 1
    if n_collapsed:
        _rebuild_by_section(bank)
    return n_collapsed


def _d4_url_pass(bank) -> dict:
    """Run URL + title normalization dedup. Returns stats dict."""
    by_key: dict[tuple, list[dict]] = {}
    for b in bank._items.values():
        by_key.setdefault(_cluster_key_d4(b), []).append(b)
    clusters = [v for v in by_key.values() if len(v) > 1]
    n_collapsed = _collapse_clusters(bank, clusters)
    return {"n_collapsed": n_collapsed, "n_clusters": len(clusters)}


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embedding vectors. Returns 0.0 for
    zero-norm inputs (defensive — text-embedding-3-small does not produce
    zero vectors in practice, but the guard avoids divide-by-zero on
    pathological inputs)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na**0.5) * (nb**0.5))


def _d1_embedding_pass(bank, threshold: float = _DEFAULT_COSINE_THRESHOLD) -> dict:
    """Run cosine-similarity dedup on the (post-D4) bank.

    Embeds `source_name + first 500 chars of text` per remaining block.
    Pairwise cosine — O(n²) but n ≤ 300 in typical W-runs, fast in Python.
    Threshold ≥ 0.85 by default; tunable for future calibration.
    """
    items = list(bank._items.values())
    if len(items) < 2:
        return {"n_collapsed": 0, "n_eids_embedded": 0, "n_clusters": 0}

    texts: list[str] = []
    for b in items:
        text = (b.get("source_name", "") or "") + " " + (b.get("text", "") or "")
        # Trim to first N chars — embedding semantics are dominated by the
        # head of a passage and shorter inputs keep token cost bounded.
        texts.append(text[:_EMBED_TEXT_PREFIX_CHARS] or " ")

    embeddings = llm.embed("embedder", texts, note="evidence_dedup.d1")
    if len(embeddings) != len(items):
        # Mismatch shouldn't happen if openai_client.embed preserves order;
        # fail-soft rather than risk a bad cluster decision.
        return {"n_collapsed": 0, "n_eids_embedded": len(items), "n_clusters": 0, "error": "len mismatch"}

    clusters: list[list[dict]] = []
    visited: set[str] = set()
    for i in range(len(items)):
        if items[i]["eid"] in visited:
            continue
        cluster = [items[i]]
        visited.add(items[i]["eid"])
        for j in range(i + 1, len(items)):
            if items[j]["eid"] in visited:
                continue
            if _cosine(embeddings[i], embeddings[j]) >= threshold:
                cluster.append(items[j])
                visited.add(items[j]["eid"])
        if len(cluster) > 1:
            clusters.append(cluster)

    n_collapsed = _collapse_clusters(bank, clusters)
    return {"n_collapsed": n_collapsed, "n_eids_embedded": len(items), "n_clusters": len(clusters)}


def dedup_bank(bank, mode: str = "off") -> dict:
    """Top-level dedup entry — call from `orchestrate.py` BEFORE
    `bank.assign_primary_sections()`.

    Modes:
        ``off``           — no-op. Returns count snapshot.
        ``url``           — D4 only (URL + title normalization). Deterministic.
        ``url+embedding`` — D4 then D1 (embeddings + cosine ≥ 0.85). D1 is
                            fail-soft: an embeddings API failure leaves the
                            bank at its post-D4 state and the pipeline
                            continues.
    """
    n_before = len(bank._items)
    out: dict = {"mode": mode, "n_before": n_before}
    if mode == "off":
        out["n_after"] = n_before
        return out

    if mode in ("url", "url+embedding"):
        d4 = _d4_url_pass(bank)
        out["d4_collapsed"] = d4["n_collapsed"]
        out["d4_clusters"] = d4["n_clusters"]

    if mode == "url+embedding":
        try:
            d1 = _d1_embedding_pass(bank)
            out["d1_collapsed"] = d1["n_collapsed"]
            out["d1_eids_embedded"] = d1["n_eids_embedded"]
            out["d1_clusters"] = d1.get("n_clusters", 0)
            if "error" in d1:
                out["d1_error"] = d1["error"]
        except Exception as e:  # noqa: BLE001 — fail-soft, never break pipeline
            out["d1_error"] = f"{type(e).__name__}: {e}"

    out["n_after"] = len(bank._items)
    return out
