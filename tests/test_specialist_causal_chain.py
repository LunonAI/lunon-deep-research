"""Unit tests for P3-W0b — specialist `chain` field for multi-step causal preservation.

The mechanism_explorer specialist's `_EXTRACT_SYSTEM` schema previously
emitted findings as `{statement, source_name, url, quote, query_ids}`. Even
when the LLM extracted a 3-step chain ("policy X causes Y, which enables Z,
leading to W"), the chain structure was flattened into a single `statement`
string. The writer's evidence pack could not reconstruct the multi-step
causality and would either skip the chain (criterion 2 of RACE Insight
under-fires) or synthesize one from the flat statement (hallucination risk).

P3-W0b extends the schema with an OPTIONAL `chain: [str, ...]` field plus
the `_sanitize_chain` post-extraction filter. Chains survive through
`memory_bank.MemoryBank.add` and into the writer's `ev_view` as a
`causal_chain` field on the evidence atom.

These tests pin: schema docstring; sanitizer accept/reject behavior;
filter pass-through after sanitation; orchestrator-style ingest preserves
the field through memory_bank.
"""

from deep_research.pipeline import memory_bank, specialists

# --------------------------------------------------------------------------
# 1. Schema docstring pin — drift in the prompt = drift in the LLM contract.
# --------------------------------------------------------------------------


def test_extract_system_documents_chain_field():
    """The optional `chain` field MUST appear in the `_EXTRACT_SYSTEM`
    schema docstring (this is what the LLM extraction reads). If a
    refactor accidentally removes the field, this test surfaces it
    before silent degradation."""
    sys_template = specialists._EXTRACT_SYSTEM
    assert '"chain"' in sys_template, f"chain field missing from extract schema; got: {sys_template}"
    assert "multi-step causal mechanism" in sys_template, (
        f"chain semantic description missing from extract schema; got: {sys_template}"
    )
    assert "mechanism_explorer specialist should populate this" in sys_template, (
        f"specialist guidance missing from extract schema; got: {sys_template}"
    )


def test_extract_system_marks_chain_as_optional():
    """The schema must explicitly mark `chain` as OPTIONAL so other
    specialists (evidence_gatherer, comparator, critic, horizon_scanner)
    don't all add chains to every finding."""
    sys_template = specialists._EXTRACT_SYSTEM
    assert "OPTIONAL" in sys_template, f"chain field not marked OPTIONAL; got: {sys_template}"
    assert "OMIT this field entirely if the finding is not multi-step causal" in sys_template


# --------------------------------------------------------------------------
# 2. `_sanitize_chain` accept/reject behavior.
# --------------------------------------------------------------------------


def test_sanitize_chain_accepts_clean_list_of_strings():
    """Valid input: list of non-empty strings → returned trimmed."""
    out = specialists._sanitize_chain(["X results in Y", "Y enables Z", "Z drives W"])
    assert out == ["X results in Y", "Y enables Z", "Z drives W"], f"got {out}"


def test_sanitize_chain_trims_whitespace_per_link():
    """Each link is trimmed of surrounding whitespace."""
    out = specialists._sanitize_chain(["  X  ", "\nY\n", "Z"])
    assert out == ["X", "Y", "Z"], f"got {out}"


def test_sanitize_chain_drops_empty_strings():
    """Empty / whitespace-only links are dropped (sanitation defense
    against partial LLM output where one link came back blank)."""
    out = specialists._sanitize_chain(["X", "", "  ", "Y"])
    assert out == ["X", "Y"], f"got {out}"


def test_sanitize_chain_caps_at_6_links():
    """A hallucinated 50-link chain is capped at 6 to bound the prompt
    budget per finding."""
    long_chain = [f"link{i}" for i in range(50)]
    out = specialists._sanitize_chain(long_chain)
    assert len(out) == 6, f"got {len(out)} links: {out}"
    assert out == ["link0", "link1", "link2", "link3", "link4", "link5"]


def test_sanitize_chain_caps_each_link_at_240_chars():
    """A pathologically long single link is truncated to 240 chars."""
    long_link = "x" * 500
    out = specialists._sanitize_chain([long_link])
    assert len(out) == 1
    assert len(out[0]) == 240, f"got len={len(out[0])}"


def test_sanitize_chain_rejects_none():
    """None → []."""
    assert specialists._sanitize_chain(None) == []


def test_sanitize_chain_rejects_single_string():
    """Common LLM mistake: emitting a single string instead of a list.
    Returns [] so downstream consumers see "no chain" rather than a
    one-element chain treated as multi-step."""
    out = specialists._sanitize_chain("X leads to Y to Z")
    assert out == [], f"single string should be rejected; got {out}"


def test_sanitize_chain_rejects_dict():
    """Common LLM mistake: emitting a dict (e.g. {'step1': 'X', 'step2': 'Y'})."""
    out = specialists._sanitize_chain({"step1": "X", "step2": "Y"})
    assert out == [], f"dict should be rejected; got {out}"


def test_sanitize_chain_rejects_mixed_type_list():
    """Mixed-type list (strings + ints / dicts): reject the WHOLE field,
    don't partial-accept. Partial acceptance would silently corrupt the
    downstream data (writer would see a 2-link chain when the LLM
    intended 3 — worse than no chain at all)."""
    out = specialists._sanitize_chain(["X", 42, "Z"])
    assert out == [], f"mixed-type list should be rejected; got {out}"


def test_sanitize_chain_rejects_list_of_dicts():
    """List of dicts (another common LLM mistake: emitting structured
    sub-objects when the schema asks for strings)."""
    out = specialists._sanitize_chain([{"link": "X"}, {"link": "Y"}])
    assert out == [], f"list-of-dicts should be rejected; got {out}"


def test_sanitize_chain_empty_list_passes():
    """Empty list is a valid signal of "no chain" — return as-is."""
    assert specialists._sanitize_chain([]) == []


def test_sanitize_chain_returns_list_not_tuple():
    """Defensive: ensure the return type is always list[str] not tuple
    (downstream JSON serialization expects list)."""
    out = specialists._sanitize_chain(["X", "Y"])
    assert isinstance(out, list), f"got {type(out)}"


# --------------------------------------------------------------------------
# 3. Memory bank stores and surfaces the chain.
# --------------------------------------------------------------------------


def test_memory_bank_add_stores_chain():
    """A multi-step chain passed to `MemoryBank.add` is stored on the
    block and visible via `for_section`."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="Smith 2024",
        url="https://example.com",
        title="Smith 2024",
        text="Policy X reduces Y by 30%",
        query_id="Q1",
        section_ids=["S2"],
        specialist="mechanism_explorer",
        language="en",
        chain=["X reduces input demand", "demand drop drives consolidation", "consolidation lowers Y by 30%"],
    )
    blocks = bank.for_section("S2")
    assert len(blocks) == 1
    assert blocks[0]["chain"] == [
        "X reduces input demand",
        "demand drop drives consolidation",
        "consolidation lowers Y by 30%",
    ], f"got {blocks[0]}"


def test_memory_bank_add_without_chain_defaults_to_empty_list():
    """Pre-P3-W0b callers don't pass `chain` (backward compat) — the
    block stores `chain: []`, no crash."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="A",
        url="",
        title="",
        text="t",
        query_id="Q1",
        section_ids=["S1"],
        specialist="evidence_gatherer",
        language="en",
    )
    blocks = bank.for_section("S1")
    assert blocks[0]["chain"] == [], f"got {blocks[0]}"


def test_memory_bank_add_with_none_chain():
    """Explicit `chain=None` (caller passed None instead of omitting) is
    treated identically to absent — stored as empty list."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="A",
        url="",
        title="",
        text="t",
        query_id="Q1",
        section_ids=["S1"],
        specialist="evidence_gatherer",
        language="en",
        chain=None,
    )
    blocks = bank.for_section("S1")
    assert blocks[0]["chain"] == [], f"got {blocks[0]}"


def test_memory_bank_add_with_empty_chain():
    """Explicit `chain=[]` is the canonical "no chain" form — also stored as empty."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="A",
        url="",
        title="",
        text="t",
        query_id="Q1",
        section_ids=["S1"],
        specialist="evidence_gatherer",
        language="en",
        chain=[],
    )
    blocks = bank.for_section("S1")
    assert blocks[0]["chain"] == []


def test_memory_bank_add_rejects_non_list_chain_defensively():
    """Greptile PR #36 round-2: even though `_sanitize_chain` upstream
    guarantees list[str], `MemoryBank.add` keeps a defensive
    `isinstance(chain, list)` guard so a future caller that skips the
    sanitizer can't silently corrupt the block by passing a truthy
    non-list. Specifically, a raw string would otherwise be iterated
    char-by-char by `list(...)` and produce a phantom chain like
    `["A", " ", "→", " ", "B"]` — semantically broken, no error raised.

    The guard converts any non-list (string, dict, int, tuple) to []
    rather than partial-accept. This is symmetric with
    `_sanitize_chain`'s whole-field-rejection design."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="A",
        url="",
        title="",
        text="t",
        query_id="Q1",
        section_ids=["S1"],
        specialist="m",
        language="en",
        chain="A → B → C",  # WRONG type: bare string instead of list
    )
    blocks = bank.for_section("S1")
    # Without the isinstance guard this would be ["A", " ", "→", " ", "B", " ", "→", " ", "C"].
    assert blocks[0]["chain"] == [], f"non-list chain not rejected: {blocks[0]['chain']}"


def test_memory_bank_add_rejects_dict_chain_defensively():
    """Symmetric coverage: a dict (another truthy non-list) is also
    rejected rather than being iterated for its keys."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="A",
        url="",
        title="",
        text="t",
        query_id="Q1",
        section_ids=["S1"],
        specialist="m",
        language="en",
        chain={"step1": "X", "step2": "Y"},  # WRONG type: dict
    )
    blocks = bank.for_section("S1")
    assert blocks[0]["chain"] == [], f"dict chain not rejected: {blocks[0]['chain']}"


def test_memory_bank_add_stores_chain_as_independent_list():
    """Defensive: the block's `chain` must be an INDEPENDENT list so
    mutating the caller's original list doesn't reflect into bank state
    (would create a silent data race in batch ingest)."""
    bank = memory_bank.MemoryBank()
    original = ["X", "Y", "Z"]
    bank.add(
        source_name="A",
        url="",
        title="",
        text="t",
        query_id="Q1",
        section_ids=["S1"],
        specialist="m",
        language="en",
        chain=original,
    )
    original.append("MUTATED")
    blocks = bank.for_section("S1")
    assert blocks[0]["chain"] == ["X", "Y", "Z"], f"got {blocks[0]['chain']}"


# --------------------------------------------------------------------------
# 4. Specialist.research integration — findings get `chain` sanitized.
# --------------------------------------------------------------------------


def test_research_sanitizes_chain_on_findings(monkeypatch):
    """`research()` calls extraction LLM and post-filters findings. The
    `chain` field on each finding must be sanitized by the time the
    function returns — downstream consumers shouldn't have to re-validate."""

    # Fake search → return one result
    def fake_search(q, language, domain, mode, num_results):
        return [{"title": "T", "url": "https://x", "text": "evidence", "published_date": "", "qid": "Q1"}]

    monkeypatch.setattr(specialists.domain_routed, "search", fake_search)

    # Fake LLM extraction → return findings with a mix of valid/invalid chains
    def fake_call_json(role, user, *, system, max_tokens, note, retries=1):
        return {
            "findings": [
                {
                    "statement": "Clean multi-step finding",
                    "source_name": "Source A",
                    "url": "https://a",
                    "quote": "...",
                    "query_ids": ["Q1"],
                    "chain": ["X causes Y", "Y enables Z"],
                },
                {
                    "statement": "Malformed-chain finding",
                    "source_name": "Source B",
                    "url": "https://b",
                    "quote": "...",
                    "query_ids": ["Q1"],
                    "chain": "X to Y to Z",  # WRONG type — single string
                },
                {
                    "statement": "No-chain finding",
                    "source_name": "Source C",
                    "url": "https://c",
                    "quote": "...",
                    "query_ids": ["Q1"],
                },
            ]
        }

    monkeypatch.setattr(specialists.llm, "call_json", fake_call_json)

    out = specialists.research(
        "mechanism_explorer", [{"id": "Q1", "text": "what drives X?"}], language="en", domain="default", exa_mode="auto"
    )
    findings = out["findings"]
    assert len(findings) == 3, f"got {len(findings)}: {findings}"

    # Finding 0: clean chain — preserved
    assert findings[0]["chain"] == ["X causes Y", "Y enables Z"]
    # Finding 1: malformed chain — sanitized to [] (sanitizer rejects single-string)
    assert findings[1]["chain"] == [], f"malformed chain not sanitized: {findings[1]}"
    # Finding 2: no chain field originally — now present and empty
    assert findings[2]["chain"] == [], f"missing chain not defaulted: {findings[2]}"


def test_research_chain_handles_extraction_failure_gracefully(monkeypatch):
    """When LLM extraction crashes and `_snippet_fallback` fires, the
    fallback findings don't have chain (fallback never produces causal
    chains — they're degraded snippet text). Sanitation must still
    survive the path without crashing."""
    monkeypatch.setattr(
        specialists.domain_routed,
        "search",
        lambda *a, **k: [{"title": "T", "url": "https://x", "text": "t", "published_date": "", "qid": "Q1"}],
    )

    def raising_call(role, user, *, system, max_tokens, note, retries=1):
        raise RuntimeError("simulated extraction failure")

    monkeypatch.setattr(specialists.llm, "call_json", raising_call)
    out = specialists.research(
        "mechanism_explorer", [{"id": "Q1", "text": "x"}], language="en", domain="default", exa_mode="auto"
    )
    # Fallback path produces findings without chain (they're snippet-derived).
    # The contract here is "no crash + findings exist" — chain absence is
    # the correct semantics for fallback path.
    assert out["findings"], "fallback path produced 0 findings"
    for f in out["findings"]:
        # snippet_fallback doesn't add chain field; downstream consumers
        # (orchestrator.ingest) read `f.get("chain") or []` which is None
        # or absent here — both yield empty chain downstream.
        assert "chain" not in f or f.get("chain") == []


# --------------------------------------------------------------------------
# 5. End-to-end: chain survives through to a writer-visible block.
# --------------------------------------------------------------------------


def test_chain_survives_specialist_to_memory_bank_pipeline(monkeypatch):
    """E2E: specialist emits chain → research() sanitizes → orchestrator-
    style ingest preserves → memory_bank.for_section returns it visible
    to writer. This is the contract the writer's evidence-pack render
    path depends on."""

    def fake_search(q, language, domain, mode, num_results):
        return [{"title": "T", "url": "https://x", "text": "t", "published_date": "", "qid": "Q1"}]

    monkeypatch.setattr(specialists.domain_routed, "search", fake_search)

    def fake_call_json(role, user, *, system, max_tokens, note, retries=1):
        return {
            "findings": [
                {
                    "statement": "demand shock raises prices",
                    "source_name": "FRED",
                    "url": "https://fred.example",
                    "quote": "...",
                    "query_ids": ["Q1"],
                    "chain": ["shock raises spot price", "spot price rolls into futures", "futures lift retail by 8%"],
                },
            ]
        }

    monkeypatch.setattr(specialists.llm, "call_json", fake_call_json)
    res = specialists.research(
        "mechanism_explorer", [{"id": "Q1", "text": "x"}], language="en", domain="default", exa_mode="auto"
    )

    # Mimic orchestrator.ingest's bank.add call (minus the boilerplate).
    bank = memory_bank.MemoryBank()
    for f in res["findings"]:
        bank.add(
            source_name=f.get("source_name", ""),
            url=f.get("url", ""),
            title=f.get("source_name", ""),
            text=f.get("statement", ""),
            query_id="Q1",
            section_ids=["S2"],
            specialist="mechanism_explorer",
            language="en",
            chain=f.get("chain") or [],
        )
    blocks = bank.for_section("S2")
    assert len(blocks) == 1
    assert blocks[0]["chain"] == [
        "shock raises spot price",
        "spot price rolls into futures",
        "futures lift retail by 8%",
    ], f"got {blocks[0]}"


# --------------------------------------------------------------------------
# 6. Existing memory bank tests still pass — back-compat regression check.
# --------------------------------------------------------------------------


def test_memory_bank_source_table_unaffected_by_chain():
    """The `source_table()` method aggregates by URL — it shouldn't be
    affected by the new `chain` field on blocks."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="A",
        url="https://a",
        title="A",
        text="t",
        query_id="Q1",
        section_ids=["S1"],
        specialist="m",
        language="en",
        chain=["X", "Y"],
    )
    bank.add(
        source_name="B",
        url="https://b",
        title="B",
        text="t",
        query_id="Q1",
        section_ids=["S1"],
        specialist="m",
        language="en",
    )
    tbl = bank.source_table()
    assert set(tbl.keys()) == {"https://a", "https://b"}, f"got {tbl}"


def test_memory_bank_stats_unaffected_by_chain():
    """`stats()` reports counts — chain field shouldn't add new keys."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="A",
        url="",
        title="",
        text="t",
        query_id="Q1",
        section_ids=["S1"],
        specialist="m",
        language="en",
        chain=["X", "Y"],
    )
    s = bank.stats()
    assert s == {"n_evidence": 1, "n_sections_with_evidence": 1}, f"got {s}"
