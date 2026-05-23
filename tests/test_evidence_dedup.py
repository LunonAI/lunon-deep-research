"""Unit tests for deep_research.pipeline.evidence_dedup (P2-Wave-1-D).

Covers:
- URL normalization edge cases (query strip, anchor drop, host case).
- Title normalization (source prefix strip, punctuation collapse).
- D4 cluster keying: same URL, same title+source, singleton fallback.
- Canonical selection (longest text + eid tie-break).
- Section_ids union across cluster.
- Mode dispatch: off (no-op), url, url+embedding (mocked).
- Fail-soft on embedding API error.
- Determinism (idempotent calls produce identical state).
"""

from unittest.mock import patch

from deep_research.pipeline.evidence_dedup import (
    _cluster_key_d4,
    _cosine,
    _normalize_title,
    _normalize_url,
    _select_canonical,
    dedup_bank,
)
from deep_research.pipeline.memory_bank import MemoryBank


def _bank_with(rows: list[dict]) -> MemoryBank:
    b = MemoryBank()
    for r in rows:
        b.add(
            source_name=r.get("source_name", ""),
            url=r.get("url", ""),
            title=r.get("title", ""),
            text=r.get("text", ""),
            query_id=r.get("query_id", ""),
            section_ids=r.get("section_ids", []),
            specialist=r.get("specialist", ""),
            language=r.get("language", "en"),
        )
    return b


# --- _normalize_url --------------------------------------------------------


def test_normalize_url_drops_anchor_and_trailing_slash():
    assert _normalize_url("https://Example.com/path/?utm=foo#anchor") == "https://example.com/path"


def test_normalize_url_keeps_id_and_q_params():
    assert _normalize_url("https://example.com/page?id=42&utm=foo") == "https://example.com/page?id=42"
    assert _normalize_url("https://example.com/search?q=auction&page=2") == "https://example.com/search?q=auction"


def test_normalize_url_empty_returns_empty():
    assert _normalize_url("") == ""


def test_normalize_url_case_insensitive_host():
    assert _normalize_url("HTTPS://NEWS.YCOMBINATOR.com/item") == _normalize_url("https://news.ycombinator.com/item")


# --- _normalize_title ------------------------------------------------------


def test_normalize_title_strips_source_prefix():
    assert _normalize_title("Reuters - Market Update", "Reuters") == "market update"
    assert _normalize_title("Reuters: Market Update", "Reuters") == "market update"
    assert _normalize_title("Reuters | Market Update", "Reuters") == "market update"


def test_normalize_title_lowercases_and_strips_punct():
    assert _normalize_title("Auction Theory: Mechanisms!", "") == "auction theory mechanisms"


def test_normalize_title_empty_returns_empty():
    assert _normalize_title("", "anything") == ""


# --- _cluster_key_d4 ------------------------------------------------------


def test_cluster_key_same_url_collides():
    a = {"url": "https://example.com/a", "title": "T1", "source_name": "S1", "eid": "E1"}
    b = {"url": "https://example.com/a", "title": "T2", "source_name": "S2", "eid": "E2"}
    assert _cluster_key_d4(a) == _cluster_key_d4(b)


def test_cluster_key_empty_url_falls_back_to_title_source():
    a = {"url": "", "title": "Auction Theory", "source_name": "Smith", "eid": "E1"}
    b = {"url": "", "title": "Auction Theory", "source_name": "Smith", "eid": "E2"}
    assert _cluster_key_d4(a) == _cluster_key_d4(b)


def test_cluster_key_no_url_no_match_falls_back_to_eid():
    """Two different blocks with no URL, no title → distinct keys (eid)."""
    a = {"url": "", "title": "", "source_name": "", "eid": "E1"}
    b = {"url": "", "title": "", "source_name": "", "eid": "E2"}
    assert _cluster_key_d4(a) != _cluster_key_d4(b)


# --- _select_canonical -----------------------------------------------------


def test_select_canonical_longest_text():
    cluster = [
        {"eid": "E1", "text": "short"},
        {"eid": "E2", "text": "this is a much longer text passage"},
        {"eid": "E3", "text": "medium length"},
    ]
    assert _select_canonical(cluster)["eid"] == "E2"


def test_select_canonical_tie_break_by_lowest_eid():
    """Equal text length → lowest eid wins (earliest-recorded)."""
    cluster = [
        {"eid": "E5", "text": "same length"},
        {"eid": "E2", "text": "same length"},
    ]
    assert _select_canonical(cluster)["eid"] == "E2"


# --- _cosine ---------------------------------------------------------------


def test_cosine_identical_vectors():
    assert _cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0


def test_cosine_orthogonal_vectors():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_zero_vector_returns_zero():
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_negatively_correlated():
    assert _cosine([1.0, 0.0], [-1.0, 0.0]) == -1.0


# --- dedup_bank end-to-end -------------------------------------------------


def test_dedup_off_is_noop():
    bank = _bank_with(
        [
            {"url": "https://a.com/x", "source_name": "A", "text": "t1", "section_ids": ["1"]},
            {"url": "https://a.com/x", "source_name": "A", "text": "t2", "section_ids": ["1"]},
        ]
    )
    n_before = len(bank._items)
    stats = dedup_bank(bank, mode="off")
    assert stats == {"mode": "off", "n_before": n_before, "n_after": n_before}
    assert len(bank._items) == 2


def test_dedup_url_collapses_same_url_blocks():
    bank = _bank_with(
        [
            {
                "url": "https://Example.com/path?utm=foo",
                "source_name": "Example",
                "title": "Foo",
                "text": "short",
                "section_ids": ["1"],
            },
            {
                "url": "https://example.com/path/#anchor",
                "source_name": "Example",
                "title": "Foo",
                "text": "this is the longer canonical text",
                "section_ids": ["2"],
            },
        ]
    )
    stats = dedup_bank(bank, mode="url")
    assert stats["d4_collapsed"] == 1
    assert stats["d4_clusters"] == 1
    assert len(bank._items) == 1
    # Canonical = longer text. section_ids unioned.
    remaining = next(iter(bank._items.values()))
    assert remaining["text"] == "this is the longer canonical text"
    assert set(remaining["section_ids"]) == {"1", "2"}


def test_dedup_url_rebuilds_by_section_index():
    bank = _bank_with(
        [
            {"url": "https://a.com/x", "source_name": "A", "text": "short", "section_ids": ["1"]},
            {"url": "https://a.com/x", "source_name": "A", "text": "longer text here", "section_ids": ["2"]},
            {"url": "https://b.com/y", "source_name": "B", "text": "unique", "section_ids": ["1"]},
        ]
    )
    dedup_bank(bank, mode="url")
    # _by_section should be rebuilt with merged sids on canonical.
    assert "1" in bank._by_section and "2" in bank._by_section
    # Section 1 has both: canonical (was in 1+2 after merge) AND b.com/y unique block
    assert len(bank._by_section["1"]) == 2
    # Section 2 has only the canonical (merged from collapse)
    assert len(bank._by_section["2"]) == 1


def test_dedup_url_no_dups_no_change():
    bank = _bank_with(
        [
            {"url": "https://a.com/x", "source_name": "A", "text": "t1", "section_ids": ["1"]},
            {"url": "https://b.com/y", "source_name": "B", "text": "t2", "section_ids": ["2"]},
        ]
    )
    stats = dedup_bank(bank, mode="url")
    assert stats["d4_collapsed"] == 0
    assert stats["d4_clusters"] == 0
    assert len(bank._items) == 2


def test_dedup_idempotent_url_mode():
    bank = _bank_with(
        [
            {"url": "https://a.com/x", "source_name": "A", "text": "t1", "section_ids": ["1"]},
            {"url": "https://a.com/x", "source_name": "A", "text": "longer text", "section_ids": ["1"]},
        ]
    )
    s1 = dedup_bank(bank, mode="url")
    s2 = dedup_bank(bank, mode="url")
    # Second call: nothing to collapse anymore.
    assert s1["d4_collapsed"] == 1
    assert s2["d4_collapsed"] == 0
    assert len(bank._items) == 1


# --- D1 embedding mode -----------------------------------------------------


def test_dedup_url_embedding_calls_embed_and_collapses_paraphrases():
    """Mock the embed() call to return vectors where blocks A and B are
    semantically equal (cosine 1.0), but C is orthogonal."""
    bank = _bank_with(
        [
            {"url": "https://a.com/1", "source_name": "A", "text": "Fed raised rates 25bp", "section_ids": ["1"]},
            {"url": "https://b.com/2", "source_name": "B", "text": "Fed raised rates 25bp", "section_ids": ["2"]},
            {"url": "https://c.com/3", "source_name": "C", "text": "unrelated topic", "section_ids": ["1"]},
        ]
    )

    def fake_embed(role, texts, **kwargs):
        # Build distinguishable embeddings: A & B get [1,0,0], C gets [0,1,0]
        out = []
        for t in texts:
            if "unrelated" in t.lower():
                out.append([0.0, 1.0, 0.0])
            else:
                out.append([1.0, 0.0, 0.0])
        return out

    with patch("deep_research.pipeline.evidence_dedup.llm.embed", side_effect=fake_embed):
        stats = dedup_bank(bank, mode="url+embedding")

    assert stats["d4_collapsed"] == 0  # different URLs, D4 doesn't catch
    assert stats["d1_collapsed"] == 1  # A and B collapse via embedding
    assert len(bank._items) == 2


def test_dedup_d1_fails_soft_on_embed_error():
    """An embedding API exception should NOT propagate. Bank stays at post-D4."""
    bank = _bank_with(
        [
            {"url": "https://a.com/1", "source_name": "A", "text": "t1", "section_ids": ["1"]},
            {"url": "https://b.com/2", "source_name": "B", "text": "t2", "section_ids": ["2"]},
        ]
    )

    def boom(role, texts, **kwargs):
        raise RuntimeError("simulated embedding outage")

    with patch("deep_research.pipeline.evidence_dedup.llm.embed", side_effect=boom):
        stats = dedup_bank(bank, mode="url+embedding")

    assert "d1_error" in stats
    assert "simulated embedding outage" in stats["d1_error"]
    assert len(bank._items) == 2  # bank unchanged after D4 (no D4 dups either)


def test_dedup_d1_skipped_when_bank_has_lt_2_items():
    """D1 should short-circuit when the post-D4 bank has fewer than 2 blocks."""
    bank = _bank_with([{"url": "https://a.com/1", "source_name": "A", "text": "t1", "section_ids": ["1"]}])
    call_count = {"n": 0}

    def counting_embed(role, texts, **kwargs):
        call_count["n"] += 1
        return [[1.0]]

    with patch("deep_research.pipeline.evidence_dedup.llm.embed", side_effect=counting_embed):
        dedup_bank(bank, mode="url+embedding")

    assert call_count["n"] == 0  # never invoked


# --- Integration with assign_primary_sections ------------------------------


def test_dedup_before_primary_tagging_keeps_canonical_tagged():
    """After dedup_bank then assign_primary_sections, canonical block gets
    a primary_section_id like any other block. Order matters: dedup MUST run
    first per orchestrate.py hook."""
    bank = _bank_with(
        [
            {
                "url": "https://a.com/x",
                "source_name": "A",
                "text": "short",
                "section_ids": ["1"],
                "title": "Foo",
            },
            {
                "url": "https://a.com/x",
                "source_name": "A",
                "text": "longer canonical text wins",
                "section_ids": ["2"],
                "title": "Foo",
            },
        ]
    )
    dedup_bank(bank, mode="url")
    bank.assign_primary_sections({"report_toc": [{"id": "1", "title": "Foo"}, {"id": "2", "title": "Bar"}]})
    canonical = next(iter(bank._items.values()))
    # The canonical block's section_ids = ["1", "2"] after union;
    # assign_primary will pick best overlap with section titles.
    assert canonical.get("primary_section_id") in {"1", "2"}


if __name__ == "__main__":
    import sys

    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for f in funcs:
        try:
            f()
            print(f"PASS {f.__name__}")
        except AssertionError as e:
            failed.append((f.__name__, e))
            print(f"FAIL {f.__name__}: {e}")
        except Exception as e:
            failed.append((f.__name__, e))
            print(f"ERROR {f.__name__}: {type(e).__name__}: {e}")
    if failed:
        sys.exit(1)
    print(f"\n{len(funcs)} tests passed")
