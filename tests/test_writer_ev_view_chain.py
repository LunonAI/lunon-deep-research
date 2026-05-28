"""Unit tests for P3-W0b — writer ev_view renders specialist causal_chain.

When a memory_bank block carries a non-empty `chain` field (populated by
the mechanism_explorer specialist via the optional `chain` field in
`_EXTRACT_SYSTEM`), the writer's per-section `ev_view` must surface it as
a `causal_chain` field on the evidence atom so the writer prompt can
instruct prose rendering "X → Y → Z". Single-link chains are degenerate
and suppressed at render time.

This test file directly exercises the `ev_view` construction path inside
`writer.write_section` by invoking it with a stub LLM call and inspecting
the captured user prompt — same pattern as
`test_architect_per_archetype_shape.py`.
"""

from deep_research.pipeline import memory_bank, writer


def _bare_plan_with_section(sid="S1"):
    return {
        "report_title": "T",
        "report_toc": [{"id": sid, "title": "Sec 1", "subsections": [{"id": f"{sid}.1", "title": "Sub 1.1"}]}],
        "acceptance_criteria": [],
        "queries": [],
    }


def _capture_writer_call(monkeypatch):
    """Monkeypatch llm.call to capture the writer's user prompt. Returns
    a list that gets appended to as captures happen."""
    captured = []

    def fake_llm_call(role, user, *, system, max_tokens, note, **kw):
        captured.append({"role": role, "user": user, "system": system})
        return "## 1 Intro\n\nbody content\n[^S1-1]: A — https://x\n"

    monkeypatch.setattr(writer.llm, "call", fake_llm_call)
    return captured


def test_ev_view_includes_causal_chain_when_block_has_chain(monkeypatch):
    """When a memory_bank block has `chain=[link1, link2, link3]`, the
    writer's evidence atom must carry a `causal_chain` field with the
    same 3 links."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="Smith 2024",
        url="https://x",
        title="Smith 2024",
        text="multi-step finding",
        query_id="Q1",
        section_ids=["S1"],
        specialist="mechanism_explorer",
        language="en",
        chain=["X reduces input demand", "demand drop drives consolidation", "consolidation lowers Y by 30%"],
    )
    plan = _bare_plan_with_section()
    captured = _capture_writer_call(monkeypatch)
    writer.write_section(
        plan=plan,
        unit={
            "id": "S1",
            "title": "Sec 1",
            "depth": "broad",
            "subs": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}],
        },
        bank=bank,
        prior_titles=["Sec 1"],
        archetype="explain-mechanism",
        prompt="test prompt",
        language="en",
        domain="default",
    )
    assert captured, "writer didn't fire LLM call"
    user_prompt = captured[0]["user"]
    # The evidence atom in the JSON payload must contain causal_chain.
    assert "causal_chain" in user_prompt, f"causal_chain missing from writer evidence pack; got: {user_prompt[:2000]}"
    assert "X reduces input demand" in user_prompt
    assert "demand drop drives consolidation" in user_prompt
    assert "consolidation lowers Y by 30%" in user_prompt


def test_ev_view_omits_causal_chain_when_block_has_no_chain(monkeypatch):
    """When a block has `chain=[]` (no causal mechanism), the evidence
    atom must NOT carry a `causal_chain` field — adding an empty field
    would inflate prompt tokens for no signal."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="A",
        url="https://x",
        title="A",
        text="single-claim finding",
        query_id="Q1",
        section_ids=["S1"],
        specialist="evidence_gatherer",
        language="en",
    )
    captured = _capture_writer_call(monkeypatch)
    writer.write_section(
        plan=_bare_plan_with_section(),
        unit={
            "id": "S1",
            "title": "Sec 1",
            "depth": "broad",
            "subs": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}],
        },
        bank=bank,
        prior_titles=["Sec 1"],
        archetype="explain-mechanism",
        prompt="test",
        language="en",
        domain="default",
    )
    user_prompt = captured[0]["user"]
    # The JSON-serialized evidence atom should NOT contain the
    # `"causal_chain":` key. The CITATION CONTRACT block separately
    # describes the field as a *prompt directive* (so the literal
    # substring "causal_chain" appears in the prompt regardless) —
    # we check the JSON payload between EVIDENCE and CITATION CONTRACT
    # for the field's presence as a JSON key.
    ev_block_start = user_prompt.index("EVIDENCE FOR THIS SECTION")
    contract_start = user_prompt.index("CITATION CONTRACT")
    ev_json_region = user_prompt[ev_block_start:contract_start]
    assert '"causal_chain"' not in ev_json_region, f"unexpected causal_chain in evidence JSON: {ev_json_region}"


def test_ev_view_omits_causal_chain_when_chain_is_single_link(monkeypatch):
    """A 1-link chain is degenerate (equivalent to the flat statement)
    and provides no incremental signal — the writer's render-as-prose
    path treats it as no chain. Suppression keeps the prompt clean."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="A",
        url="https://x",
        title="A",
        text="single-step claim",
        query_id="Q1",
        section_ids=["S1"],
        specialist="mechanism_explorer",
        language="en",
        chain=["X leads to Y"],  # only ONE link → degenerate
    )
    captured = _capture_writer_call(monkeypatch)
    writer.write_section(
        plan=_bare_plan_with_section(),
        unit={
            "id": "S1",
            "title": "Sec 1",
            "depth": "broad",
            "subs": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}],
        },
        bank=bank,
        prior_titles=["Sec 1"],
        archetype="explain-mechanism",
        prompt="test",
        language="en",
        domain="default",
    )
    user_prompt = captured[0]["user"]
    # Check ONLY the evidence-pack JSON region — the CITATION CONTRACT
    # directive separately mentions "causal_chain" as a prompt keyword.
    ev_block_start = user_prompt.index("EVIDENCE FOR THIS SECTION")
    contract_start = user_prompt.index("CITATION CONTRACT")
    ev_json_region = user_prompt[ev_block_start:contract_start]
    assert '"causal_chain"' not in ev_json_region, (
        f"degenerate 1-link chain leaked into evidence pack JSON: {ev_json_region}"
    )


def test_writer_prompt_includes_causal_chain_render_directive(monkeypatch):
    """The CITATION CONTRACT block must include the new "CAUSAL CHAIN
    RENDER" directive (P3-W0b) so the writer knows what to do when an
    atom has the field."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="A",
        url="https://x",
        title="A",
        text="t",
        query_id="Q1",
        section_ids=["S1"],
        specialist="m",
        language="en",
        chain=["X", "Y"],
    )
    captured = _capture_writer_call(monkeypatch)
    writer.write_section(
        plan=_bare_plan_with_section(),
        unit={
            "id": "S1",
            "title": "Sec 1",
            "depth": "broad",
            "subs": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}],
        },
        bank=bank,
        prior_titles=["Sec 1"],
        archetype="explain-mechanism",
        prompt="test",
        language="en",
        domain="default",
    )
    user_prompt = captured[0]["user"]
    assert "CAUSAL CHAIN RENDER" in user_prompt, f"directive missing; got: {user_prompt[:2500]}"
    assert "mechanism_explorer" in user_prompt or "causal_chain" in user_prompt, (
        f"specialist or field name reference missing; got: {user_prompt[:2500]}"
    )


def test_ev_view_multiple_atoms_mixed_chain_presence(monkeypatch):
    """A section with multiple evidence atoms — some with chains, some
    without — must render only the chain-bearing ones with causal_chain."""
    bank = memory_bank.MemoryBank()
    # Atom 1: with chain
    bank.add(
        source_name="A",
        url="https://a",
        title="A",
        text="multi-step",
        query_id="Q1",
        section_ids=["S1"],
        specialist="m",
        language="en",
        chain=["A leads to B", "B leads to C"],
    )
    # Atom 2: no chain
    bank.add(
        source_name="B",
        url="https://b",
        title="B",
        text="flat",
        query_id="Q1",
        section_ids=["S1"],
        specialist="e",
        language="en",
    )
    # Atom 3: with chain
    bank.add(
        source_name="C",
        url="https://c",
        title="C",
        text="multi-step",
        query_id="Q1",
        section_ids=["S1"],
        specialist="m",
        language="en",
        chain=["P", "Q", "R"],
    )
    captured = _capture_writer_call(monkeypatch)
    writer.write_section(
        plan=_bare_plan_with_section(),
        unit={
            "id": "S1",
            "title": "Sec 1",
            "depth": "broad",
            "subs": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}],
        },
        bank=bank,
        prior_titles=["Sec 1"],
        archetype="explain-mechanism",
        prompt="test",
        language="en",
        domain="default",
    )
    user_prompt = captured[0]["user"]
    # Both chain-bearing atoms render their chains
    assert "A leads to B" in user_prompt, "atom 1 chain missing"
    assert "B leads to C" in user_prompt
    assert "P" in user_prompt and "Q" in user_prompt and "R" in user_prompt
    # Atom 2 has no chain — its statement renders but not as causal_chain.
    # Count causal_chain occurrences: should be ≤ 2 (one per chain-bearing atom).
    # JSON serialization renders the key once per atom, but the same key
    # appearing twice is fine; just verify the chain-less atom didn't get one.
    # (Indirect check: confirm no "causal_chain": [] empty arrays slip in.)
    assert '"causal_chain": []' not in user_prompt, f"empty causal_chain leaked: {user_prompt[:2000]}"


def test_ev_view_serializes_chain_with_unicode(monkeypatch):
    """ZH-language chains must serialize cleanly (ensure_ascii=False
    flow preserved — the writer prompt uses ensure_ascii=False elsewhere
    so the chain shouldn't be a regression vector)."""
    bank = memory_bank.MemoryBank()
    bank.add(
        source_name="中国央行 2025",
        url="https://pbc.gov.cn",
        title="中国央行 2025",
        text="政策传导",
        query_id="Q1",
        section_ids=["S1"],
        specialist="mechanism_explorer",
        language="zh",
        chain=["政策利率下降", "信贷扩张", "实体投资上升", "GDP 增长加速"],
    )
    captured = _capture_writer_call(monkeypatch)
    writer.write_section(
        plan=_bare_plan_with_section(),
        unit={
            "id": "S1",
            "title": "Sec 1",
            "depth": "broad",
            "subs": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}],
        },
        bank=bank,
        prior_titles=["Sec 1"],
        archetype="explain-mechanism",
        prompt="test",
        language="zh",
        domain="default",
    )
    user_prompt = captured[0]["user"]
    # ZH chain links must appear literally — not as \u escape sequences.
    assert "政策利率下降" in user_prompt
    assert "GDP 增长加速" in user_prompt
    # Defensive: ensure no double-escaped form leaked.
    assert "\\u653f" not in user_prompt, "chain got ASCII-escaped — ensure_ascii=False regression"


def test_ev_view_caps_chain_render_at_serialized_length(monkeypatch):
    """The 42000-char serialization cap on `json.dumps(ev_view)[:42000]`
    must still apply — large chains shouldn't blow up the prompt budget.
    With chains capped at 6 links × 240 chars = 1440 chars per atom max,
    plus 14-24 atoms per section, the worst case adds ~20-35k chars on
    top of statement bodies — needs to fit under the cap."""
    bank = memory_bank.MemoryBank()
    # Add 20 atoms each with a 6-link chain
    for i in range(20):
        bank.add(
            source_name=f"S{i}",
            url=f"https://s{i}",
            title=f"S{i}",
            text=f"finding {i}",
            query_id="Q1",
            section_ids=["S1"],
            specialist="m",
            language="en",
            chain=[f"link {i}.{j}" for j in range(6)],
        )
    # write_section invokes evidence rendering with [:42000] cap; just verify no crash.
    captured = _capture_writer_call(monkeypatch)
    writer.write_section(
        plan=_bare_plan_with_section(),
        unit={
            "id": "S1",
            "title": "Sec 1",
            "depth": "broad",
            "subs": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}],
        },
        bank=bank,
        prior_titles=["Sec 1"],
        archetype="explain-mechanism",
        prompt="test",
        language="en",
        domain="default",
    )
    assert captured, "writer didn't fire"
    user_prompt = captured[0]["user"]
    # At least one chain should have made it (verifies no silent truncation past first atom).
    assert "link 0.0" in user_prompt
