"""P3-W6.b (2026-05-27): writer STAKEHOLDER-SEGMENTED CLOSING CONTRACT tests.

The architect emits `plan["stakeholder_chapter"]` (architect.py schema
lines 211-222) with 3-5 stakeholder addressee blocks when the prompt
signals plural audience. The post-write validator
`_validate_stakeholder_overlap` has been ACTIVE since PR #42 (P3-W6)
auditing pairwise Jaccard 4-gram overlap < 0.20 — but the writer LLM
had no in-prompt directive instructing it to render the chapter with
non-overlapping blocks. The validator was auditing blind output.

The writer's `stakeholder_block` (writer.py, after framing_block) must:
- Render the contract ONLY when the section currently being written IS
  the stakeholder chapter (matched by title).
- Gate on the architect's 3-5 stakeholder emit-bound.
- Pass each stakeholder's `label` + `content_directive` to the writer
  LLM verbatim.
- Surface the non-overlap discipline so the writer is steered toward
  the validator's < 0.20 Jaccard threshold by construction.
"""

from deep_research.pipeline import memory_bank, writer


def _bare_plan_with_stakeholder(sc, *, sc_section_id="S4", sc_title="Strategic Recommendations"):
    """Plan with a stakeholder chapter at the named section. Two prior
    sections so the writer has context."""
    return {
        "report_title": "T",
        "report_toc": [
            {"id": "S1", "title": "Intro", "subsections": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}]},
            {"id": "S2", "title": "Body", "subsections": [{"id": "S2.1", "title": "Sub", "depth_seeds": []}]},
            {
                "id": sc_section_id,
                "title": sc_title,
                "subsections": [{"id": f"{sc_section_id}.1", "title": "Sub", "depth_seeds": []}],
            },
        ],
        "acceptance_criteria": [],
        "queries": [],
        "stakeholder_chapter": sc,
    }


def _capture_writer_call(monkeypatch):
    captured = []

    def fake_llm_call(role, user, *, system, max_tokens, note, **kw):
        captured.append({"role": role, "user": user, "system": system})
        return "## body\n"

    monkeypatch.setattr(writer.llm, "call", fake_llm_call)
    return captured


def _call_writer(monkeypatch, plan, sid, *, archetype="predict", language="en"):
    captured = _capture_writer_call(monkeypatch)
    bank = memory_bank.MemoryBank()
    section = next(s for s in plan["report_toc"] if s["id"] == sid)
    writer.write_section(
        plan=plan,
        unit={"id": sid, "title": section["title"], "depth": "broad", "subs": section["subsections"]},
        bank=bank,
        prior_titles=[s["title"] for s in plan["report_toc"]],
        archetype=archetype,
        prompt="test",
        language=language,
        domain="default",
    )
    return captured


def _full_sc(n=4, *, title="Strategic Recommendations"):
    """Canonical N-stakeholder chapter (default 4 — Qianfan q14/q3 pattern)."""
    typical_labels = [
        "For Investors",
        "For Policymakers",
        "For Industry",
        "For Researchers",
        "For Practitioners",
    ]
    return {
        "title": title,
        "stakeholders": [
            {
                "id": f"S4.{i + 1}",
                "label": typical_labels[i],
                "content_directive": f"Advice specific to {typical_labels[i]}.",
            }
            for i in range(n)
        ],
    }


# ---------- presence / gating ----------


def test_stakeholder_directive_renders_on_title_match(monkeypatch):
    """When the section being written IS the stakeholder chapter, the
    writer prompt MUST include STAKEHOLDER-SEGMENTED CLOSING CONTRACT
    + each stakeholder's label + content_directive verbatim."""
    plan = _bare_plan_with_stakeholder(_full_sc(n=4))
    captured = _call_writer(monkeypatch, plan, sid="S4")
    user = captured[0]["user"]
    assert "STAKEHOLDER-SEGMENTED CLOSING CONTRACT" in user, (
        f"stakeholder directive missing on the stakeholder chapter section; got: {user[:2000]}"
    )
    # All 4 labels in JSON payload
    for label in ("For Investors", "For Policymakers", "For Industry", "For Researchers"):
        assert label in user, f"stakeholder label `{label}` missing from prompt; got: {user[:3000]}"


def test_stakeholder_directive_absent_on_non_stakeholder_sections(monkeypatch):
    """Non-stakeholder sections (S1, S2) must NOT receive the directive."""
    plan = _bare_plan_with_stakeholder(_full_sc(n=4))
    for sid in ("S1", "S2"):
        captured = _call_writer(monkeypatch, plan, sid=sid)
        user = captured[0]["user"]
        assert "STAKEHOLDER-SEGMENTED CLOSING CONTRACT" not in user, (
            f"directive leaked into non-stakeholder section {sid}; got: {user[:2000]}"
        )


def test_stakeholder_directive_absent_when_plan_field_null(monkeypatch):
    """Architect emits `stakeholder_chapter: None` when the prompt has
    no plural-audience signal; the writer skips the directive."""
    plan = _bare_plan_with_stakeholder(_full_sc(n=4))
    plan["stakeholder_chapter"] = None
    captured = _call_writer(monkeypatch, plan, sid="S4")
    user = captured[0]["user"]
    assert "STAKEHOLDER-SEGMENTED CLOSING CONTRACT" not in user


def test_stakeholder_directive_absent_on_title_mismatch(monkeypatch):
    """Title drift → directive does not render. Safety net against
    a renamed chapter silently triggering the wrong section."""
    plan = _bare_plan_with_stakeholder(_full_sc(n=4, title="Stakeholder Recommendations"))
    # Section S4 has title "Strategic Recommendations" (from _bare_plan
    # default); plan says chapter is titled "Stakeholder Recommendations".
    captured = _call_writer(monkeypatch, plan, sid="S4")
    user = captured[0]["user"]
    assert "STAKEHOLDER-SEGMENTED CLOSING CONTRACT" not in user, (
        f"directive fired despite title mismatch; got: {user[:2000]}"
    )


# ---------- count bounds (must mirror architect.py:213 3-5 emit-bound) ----------


def test_stakeholder_directive_renders_for_3_stakeholders(monkeypatch):
    """3 is the lower bound (architect.py:213). Directive must fire."""
    plan = _bare_plan_with_stakeholder(_full_sc(n=3))
    captured = _call_writer(monkeypatch, plan, sid="S4")
    user = captured[0]["user"]
    assert "STAKEHOLDER-SEGMENTED CLOSING CONTRACT" in user
    assert "3 REQUIRED stakeholder sub-sections" in user


def test_stakeholder_directive_renders_for_5_stakeholders(monkeypatch):
    """5 is the upper bound (architect.py:213). Directive must fire."""
    plan = _bare_plan_with_stakeholder(_full_sc(n=5))
    captured = _call_writer(monkeypatch, plan, sid="S4")
    user = captured[0]["user"]
    assert "STAKEHOLDER-SEGMENTED CLOSING CONTRACT" in user
    assert "5 REQUIRED stakeholder sub-sections" in user


def test_stakeholder_directive_absent_for_2_stakeholders(monkeypatch):
    """Below the architect's 3-stakeholder lower bound → directive
    skipped. This catches a malformed plan with only 2 stakeholders
    (validator wouldn't fire the pairwise check anyway since it
    requires ≥2 — but writer also skips the directive to avoid
    rendering a degenerate 2-stakeholder closing)."""
    sc = _full_sc(n=2)
    plan = _bare_plan_with_stakeholder(sc)
    captured = _call_writer(monkeypatch, plan, sid="S4")
    user = captured[0]["user"]
    assert "STAKEHOLDER-SEGMENTED CLOSING CONTRACT" not in user, (
        f"directive fired with only 2 stakeholders (below architect 3-min); got: {user[:3000]}"
    )


def test_stakeholder_directive_absent_for_6_stakeholders(monkeypatch):
    """Above the architect's 5-stakeholder upper bound → directive
    skipped. Wider acceptance would create a dead branch when the
    architect produces a 6+ stakeholder chapter (which currently it
    cannot per architect.py:213)."""
    sc = _full_sc(n=5)
    sc["stakeholders"].append({"id": "S4.6", "label": "For Extras", "content_directive": "Extra."})
    plan = _bare_plan_with_stakeholder(sc)
    captured = _call_writer(monkeypatch, plan, sid="S4")
    user = captured[0]["user"]
    assert "STAKEHOLDER-SEGMENTED CLOSING CONTRACT" not in user


# ---------- content preservation / non-overlap signal ----------


def test_stakeholder_content_directive_preserved_in_payload(monkeypatch):
    """The architect's per-stakeholder `content_directive` must reach
    the writer (otherwise the directive's structure-only payload would
    let the writer LLM invent content with no per-stakeholder anchor)."""
    sc = _full_sc(n=3)
    sc["stakeholders"][0]["content_directive"] = (
        "Investors should prioritize ARR-positive Series-B picks in semiconductor."
    )
    plan = _bare_plan_with_stakeholder(sc)
    captured = _call_writer(monkeypatch, plan, sid="S4")
    user = captured[0]["user"]
    assert "ARR-positive Series-B picks in semiconductor" in user, (
        f"content_directive lost in JSON serialisation; got: {user[:3000]}"
    )


def test_stakeholder_directive_includes_non_overlap_signal(monkeypatch):
    """The directive must surface the Jaccard non-overlap rule so the
    writer is steered by construction toward the validator's threshold.
    Greptile PR #46 round-2: the threshold value is sourced live from
    `wr._STAKEHOLDER_JACCARD_MAX` (today 0.20). Check the live-rendered
    value is in the prompt so a future threshold change automatically
    propagates without test churn."""
    from deep_research import writing_rules as wr

    plan = _bare_plan_with_stakeholder(_full_sc(n=4))
    captured = _call_writer(monkeypatch, plan, sid="S4")
    user = captured[0]["user"]
    expected_threshold = f"{wr._STAKEHOLDER_JACCARD_MAX:.2f}"
    assert expected_threshold in user, (
        f"directive missing the live-rendered Jaccard threshold ({expected_threshold}); got: {user[:3000]}"
    )
    assert "NON-OVERLAP" in user or "non-overlap" in user.lower(), (
        f"directive missing non-overlap discipline language; got: {user[:3000]}"
    )


def test_stakeholder_directive_includes_qianfan_opening_phrases(monkeypatch):
    """The directive cites canonical Qianfan opening phrases so the
    writer LLM has concrete sentence forms to model. Pin one of them
    as a sanity check that the phrasing wasn't dropped."""
    plan = _bare_plan_with_stakeholder(_full_sc(n=4))
    captured = _call_writer(monkeypatch, plan, sid="S4")
    user = captured[0]["user"]
    assert "the priority is" in user, f"Qianfan opening phrase template ('the priority is') missing; got: {user[:3000]}"


# ---------- malformed inputs (Greptile pre-scan) ----------


def test_stakeholder_directive_skips_stakeholder_with_missing_label(monkeypatch):
    """A stakeholder entry missing `label` must NOT crash; it's silently
    excluded from the count. If filtering drops to <3, directive skips."""
    sc = {
        "title": "Strategic Recommendations",
        "stakeholders": [
            {"id": "S4.1", "label": "For Investors", "content_directive": "A"},
            {"id": "S4.2", "content_directive": "B"},  # no label — dropped
            {"id": "S4.3", "label": "For Policymakers", "content_directive": "C"},
        ],
    }
    plan = _bare_plan_with_stakeholder(sc)
    captured = _call_writer(monkeypatch, plan, sid="S4")
    user = captured[0]["user"]
    # 2 valid stakeholders after filter → below 3-min → no directive
    assert "STAKEHOLDER-SEGMENTED CLOSING CONTRACT" not in user


def test_stakeholder_directive_handles_non_dict_plan_field(monkeypatch):
    """Defensive: `stakeholder_chapter` as a non-dict (list / string)
    must not crash the writer — silent skip."""
    plan = _bare_plan_with_stakeholder(_full_sc(n=3))
    plan["stakeholder_chapter"] = ["malformed"]
    captured = _call_writer(monkeypatch, plan, sid="S4")
    user = captured[0]["user"]
    assert "STAKEHOLDER-SEGMENTED CLOSING CONTRACT" not in user
