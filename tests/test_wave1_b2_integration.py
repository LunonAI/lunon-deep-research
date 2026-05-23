"""Integration tests for P2-Wave-1-B2 serial writer + cross-section context.

Verifies end-to-end that:
- DR_WEBWEAVER=off behaves byte-identically to legacy parallel write.
- DR_WEBWEAVER=serial routes through the serial loop and accumulates
  prior_sections in writer prompts.
- The writer's prompt actually carries the PRIOR SECTIONS WRITTEN block
  and the B3 directive when mode != off.
- Memory bank's placeholder evidence is rendered with `see_elsewhere: true`
  in the writer prompt's evidence-view JSON.

Mocks `deep_research.llm.call` so no API calls fire.
"""

import os
from contextlib import contextmanager
from unittest.mock import patch

from deep_research.pipeline import writer
from deep_research.pipeline.memory_bank import MemoryBank


@contextmanager
def env(**overrides):
    """Temporarily set env vars; restore on exit."""
    old = {k: os.environ.get(k) for k in overrides}
    os.environ.update({k: v for k, v in overrides.items() if v is not None})
    for k, v in overrides.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _make_bank_and_plan():
    """Two-section plan, three eids: one primary-to-§1, one primary-to-§2,
    one cross-cutting (§1+§2) that primary-tags to §2 via overlap."""
    plan = {
        "report_toc": [
            {"id": "1", "title": "Auction Theory", "subsections": [], "depth_target": "broad"},
            {"id": "2", "title": "Game Mechanics", "subsections": [], "depth_target": "broad"},
        ],
        "acceptance_criteria": [],
        "report_title": "Test",
    }
    bank = MemoryBank()
    bank.add(
        source_name="Smith 2024",
        url="https://example.com/a",
        title="Auction primer",
        text="auction theory background reading",
        query_id="q1",
        section_ids=["1"],
        specialist="evidence_gatherer",
        language="en",
    )
    bank.add(
        source_name="Jones 2024",
        url="https://example.com/b",
        title="Game mechanics primer",
        text="game mechanics fundamentals",
        query_id="q2",
        section_ids=["2"],
        specialist="evidence_gatherer",
        language="en",
    )
    bank.add(
        source_name="Wei 2025",
        url="https://example.com/c",
        title="Cross-cutting",
        text="game mechanics extended discussion",
        query_id="q3",
        section_ids=["1", "2"],
        specialist="evidence_gatherer",
        language="en",
    )
    bank.assign_primary_sections(plan)
    return bank, plan


def test_legacy_mode_byte_identical_writer_prompt():
    """DR_WEBWEAVER=off should produce the exact same writer prompt shape
    as pre-Wave-1 (no PRIOR SECTIONS WRITTEN, no B3 directive)."""
    bank, plan = _make_bank_and_plan()
    captured = {}

    def fake_call(role, user, *, system="", **kwargs):
        captured["user"] = user
        captured["system"] = system
        return "MOCK SECTION TEXT"

    unit = {"id": "2", "title": "Game Mechanics", "subs": [], "depth": "broad"}
    with env(DR_WEBWEAVER=None), patch("deep_research.pipeline.writer.llm.call", side_effect=fake_call):
        writer.write_section(
            unit,
            plan,
            bank,
            prompt="how do games work",
            language="en",
            archetype="explain-mechanism",
            domain="default",
            prior_titles=["Auction Theory", "Game Mechanics"],
        )

    user = captured["user"]
    # Legacy markers
    assert "EVIDENCE FOR THIS SECTION ONLY" in user
    # Wave-1 markers should NOT appear
    assert "PRIOR SECTIONS WRITTEN" not in user
    assert "WAVE-1-B3" not in user
    assert "see_elsewhere" not in user


def test_serial_mode_includes_prior_sections_and_b3_directive():
    bank, plan = _make_bank_and_plan()
    captured = {}

    def fake_call(role, user, *, system="", **kwargs):
        captured["user"] = user
        return "MOCK SECTION TEXT"

    unit = {"id": "2", "title": "Game Mechanics", "subs": [], "depth": "broad"}
    prior_sections = [{"sid": "1", "title": "Auction Theory", "summary": "Auctions are markets where bidders compete."}]
    with env(DR_WEBWEAVER="serial"), patch("deep_research.pipeline.writer.llm.call", side_effect=fake_call):
        writer.write_section(
            unit,
            plan,
            bank,
            prompt="how do games work",
            language="en",
            archetype="explain-mechanism",
            domain="default",
            prior_titles=["Auction Theory", "Game Mechanics"],
            prior_sections=prior_sections,
        )

    user = captured["user"]
    assert "PRIOR SECTIONS WRITTEN" in user
    assert "Auctions are markets where bidders compete" in user
    assert "WAVE-1-B3" in user
    assert "see_elsewhere" in user or "primary scope" in user


def test_serial_mode_placeholder_evidence_in_prompt():
    """The cross-cutting eid (sections=['1','2']) primary-tags to §2 (by token
    overlap with 'Game Mechanics'). When writing §1 in serial mode, it should
    appear as a placeholder with `see_elsewhere: true`."""
    bank, plan = _make_bank_and_plan()
    # Verify primary tagging first
    cross_eid = [eid for eid, b in bank._items.items() if b.get("section_ids") == ["1", "2"]][0]
    assert bank._items[cross_eid]["primary_section_id"] == "2"

    captured = {}

    def fake_call(role, user, *, system="", **kwargs):
        captured["user"] = user
        return "MOCK"

    unit = {"id": "1", "title": "Auction Theory", "subs": [], "depth": "broad"}
    with env(DR_WEBWEAVER="serial"), patch("deep_research.pipeline.writer.llm.call", side_effect=fake_call):
        writer.write_section(
            unit,
            plan,
            bank,
            prompt="how do auctions work",
            language="en",
            archetype="explain-mechanism",
            domain="default",
            prior_titles=["Auction Theory", "Game Mechanics"],
            prior_sections=[],
        )

    user = captured["user"]
    # Cross-cutting eid should be a placeholder (see_elsewhere) in §1's prompt
    assert "see_elsewhere" in user
    # Primary-§1 eid (Smith 2024) should appear in full
    assert "Smith 2024" in user
    assert "auction theory background reading" in user
    # Cross-cutting eid's text should NOT be in §1's prompt (it's a placeholder)
    assert "game mechanics extended discussion" not in user


def test_serial_mode_no_prior_sections_block_when_empty():
    """First section in serial mode has prior_sections=[]. The content block
    (with "Central frame:" lines) should NOT appear (no prior sections yet),
    even though the B3 directive itself mentions the phrase as guidance.
    """
    bank, plan = _make_bank_and_plan()
    captured = {}

    def fake_call(role, user, *, system="", **kwargs):
        captured["user"] = user
        return "MOCK"

    unit = {"id": "1", "title": "Auction Theory", "subs": [], "depth": "broad"}
    with env(DR_WEBWEAVER="serial"), patch("deep_research.pipeline.writer.llm.call", side_effect=fake_call):
        writer.write_section(
            unit,
            plan,
            bank,
            prompt="how do auctions work",
            language="en",
            archetype="explain-mechanism",
            domain="default",
            prior_titles=["Auction Theory", "Game Mechanics"],
            prior_sections=[],
        )

    user = captured["user"]
    # The actual block uses "Central frame:" — that should NOT appear with no priors.
    assert "Central frame:" not in user
    # B3 directive is still on (mode != off) — writer still receives the
    # placeholder explanation even for the first section.
    assert "WAVE-1-B3" in user


def test_orchestrate_summarize_helper():
    """_summarize_section_for_context truncates to max_words and preserves sid/title."""
    from deep_research.orchestrate import _summarize_section_for_context

    text = " ".join(f"word{i}" for i in range(500))
    out = _summarize_section_for_context("3.1", "Sub", text, max_words=10)
    assert out["sid"] == "3.1"
    assert out["title"] == "Sub"
    assert out["summary"].split() == [f"word{i}" for i in range(10)]


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
