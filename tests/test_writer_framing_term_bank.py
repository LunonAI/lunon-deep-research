"""Unit tests for P3-W2 — writer framing-chapter / term-bank dispatch.

§1 receives the FRAMING CHAPTER CONTRACT (instructions to emit scope /
rubric / roadmap / vocabulary sub-sections + the term lists to introduce).
Non-§1 sections receive the NAMED TERM BANK (instructions to reuse the
published vocabulary + rubric items unmodified).

Tests pin: §1 vs non-§1 dispatch; vocabulary serialization with ZH unicode;
rubric format with id+label+weight; suppression when framing_chapter is
absent or empty.
"""

from deep_research.pipeline import memory_bank, writer


def _bare_plan_with_framing(fc):
    return {
        "report_title": "T",
        "report_toc": [
            {"id": "S1", "title": "Sec 1", "subsections": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}]},
            {"id": "S2", "title": "Sec 2", "subsections": [{"id": "S2.1", "title": "Sub", "depth_seeds": []}]},
        ],
        "acceptance_criteria": [],
        "queries": [],
        "framing_chapter": fc,
    }


def _capture_writer_call(monkeypatch):
    captured = []

    def fake_llm_call(role, user, *, system, max_tokens, note, **kw):
        captured.append({"role": role, "user": user, "system": system})
        return "## body\n"

    monkeypatch.setattr(writer.llm, "call", fake_llm_call)
    return captured


def _call_writer(monkeypatch, plan, sid="S1", archetype="predict", language="en"):
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


def _full_fc(**overrides):
    fc = {
        "title": "Framework",
        "sub_sections": [
            {"id": "S1.1", "type": "scope", "title": "Scope", "content_directive": "..."},
            {"id": "S1.2", "type": "rubric", "title": "Rubric", "content_directive": "..."},
            {"id": "S1.3", "type": "roadmap", "title": "Roadmap", "content_directive": "..."},
            {"id": "S1.4", "type": "vocabulary", "title": "Vocabulary", "content_directive": "..."},
        ],
        "published_vocabulary": ["axiom1", "axiom2", "axiom3"],
        "published_rubric_items": [
            {"id": "R-1", "label": "Quality", "weight": 0.5},
            {"id": "R-2", "label": "Speed", "weight": 0.5},
        ],
    }
    fc.update(overrides)
    return fc


def test_s1_section_receives_framing_chapter_contract(monkeypatch):
    """§1 prompt must include FRAMING CHAPTER CONTRACT directive +
    sub_sections + vocabulary + rubric."""
    plan = _bare_plan_with_framing(_full_fc())
    captured = _call_writer(monkeypatch, plan, sid="S1")
    user = captured[0]["user"]
    assert "FRAMING CHAPTER CONTRACT" in user, f"directive missing; got: {user[:2000]}"
    assert "axiom1" in user and "axiom2" in user
    assert "R-1" in user and "Quality" in user


def test_non_s1_section_receives_named_term_bank(monkeypatch):
    """Non-§1 prompts must include NAMED TERM BANK with vocabulary +
    rubric reference instructions."""
    plan = _bare_plan_with_framing(_full_fc())
    captured = _call_writer(monkeypatch, plan, sid="S2")
    user = captured[0]["user"]
    assert "NAMED TERM BANK" in user, f"term bank missing; got: {user[:2000]}"
    assert "axiom1" in user
    # PR-B (2026-05-29): the entity-evaluation path now exposes only the rubric
    # LABEL, not the `R-N` id (the id drove the bare-R-N leak in prose).
    assert "Quality" in user  # the rubric item's label
    assert "R-1" not in user  # the internal id must NOT be shown here
    # P3b-D1: rubric directive is a COMPARATIVE VERDICT, not descriptive narration.
    assert "COMPARATIVE VERDICT" in user
    assert "cite the item" not in user  # old descriptive phrasing retired


def test_non_s1_section_does_not_receive_framing_contract_directive(monkeypatch):
    """Non-§1 sections must NOT receive the FRAMING CHAPTER CONTRACT
    directive (would tell them to write a framing chapter themselves)."""
    plan = _bare_plan_with_framing(_full_fc())
    captured = _call_writer(monkeypatch, plan, sid="S2")
    user = captured[0]["user"]
    assert "FRAMING CHAPTER CONTRACT" not in user, f"leaked into non-§1: {user[:2000]}"


def test_s1_section_does_not_receive_term_bank(monkeypatch):
    """§1 introduces the vocabulary itself — being told to "reuse" it
    would be circular."""
    plan = _bare_plan_with_framing(_full_fc())
    captured = _call_writer(monkeypatch, plan, sid="S1")
    user = captured[0]["user"]
    assert "NAMED TERM BANK" not in user, f"S1 got the reuse bank: {user[:2000]}"


def test_framing_omitted_when_absent_from_plan(monkeypatch):
    """A plan without framing_chapter (back-compat with pre-P3-W2 plans)
    fires neither directive."""
    plan = _bare_plan_with_framing(_full_fc())
    plan.pop("framing_chapter")
    captured = _call_writer(monkeypatch, plan, sid="S1")
    user = captured[0]["user"]
    assert "FRAMING CHAPTER CONTRACT" not in user
    assert "NAMED TERM BANK" not in user


def test_framing_omitted_when_empty_vocab_and_rubric(monkeypatch):
    """A framing_chapter with empty vocabulary + rubric (e.g. backfilled
    after the architect omitted the field): no term bank to share."""
    fc = _full_fc(published_vocabulary=[], published_rubric_items=[])
    plan = _bare_plan_with_framing(fc)
    captured = _call_writer(monkeypatch, plan, sid="S2")
    user = captured[0]["user"]
    assert "NAMED TERM BANK" not in user


def test_zh_vocabulary_preserved_in_prompt(monkeypatch):
    """ZH vocabulary terms must serialize unmodified (ensure_ascii=False)."""
    fc = _full_fc(published_vocabulary=["新质生产力", "五篇大文章", "硬科技"])
    plan = _bare_plan_with_framing(fc)
    captured = _call_writer(monkeypatch, plan, sid="S2", language="zh")
    user = captured[0]["user"]
    assert "新质生产力" in user
    assert "\\u65b0" not in user, "ZH chars got ASCII-escaped — ensure_ascii=False regression"


def test_vocab_only_no_rubric(monkeypatch):
    """A framing chapter with vocabulary but no rubric items (legitimate
    for list-all archetypes): non-§1 prompt gets vocabulary but no rubric."""
    fc = _full_fc(published_rubric_items=[])
    plan = _bare_plan_with_framing(fc)
    captured = _call_writer(monkeypatch, plan, sid="S2")
    user = captured[0]["user"]
    assert "NAMED TERM BANK" in user
    assert "axiom1" in user
    # The "Rubric items:" line should NOT appear because rubric is empty.
    assert "Rubric items:" not in user, f"rubric line shouldn't fire with empty rubric: {user}"
    assert "COMPARATIVE VERDICT" not in user  # verdict directive is rubric-gated


def test_rubric_only_no_vocab(monkeypatch):
    """Rare: rubric without vocabulary. Non-§1 prompt still gets the
    rubric reference instructions."""
    fc = _full_fc(published_vocabulary=[])
    plan = _bare_plan_with_framing(fc)
    captured = _call_writer(monkeypatch, plan, sid="S2")
    user = captured[0]["user"]
    assert "NAMED TERM BANK" in user
    # PR-B: rubric exposed by LABEL, not the `R-N` id.
    assert "Quality" in user
    assert "R-1" not in user
    # The "Vocabulary:" line should NOT appear because vocab is empty.
    assert "Vocabulary:" not in user
