"""Round 5 T1-PR2: article-completion gate (final-section re-roll + trim).

id=89 shipped with its body ending mid-word ("...the frameworks<4898", judge
grammar 4.0) because the final section truncated past the per-section CUT
re-roll (which only fires on mid-sentence AND thin). These pin the two layers:
(1) `_repair_final_section` re-rolls a mid-sentence final section; (2)
`_guarantee_complete_ending` deterministically trims the shipped body so it
never ends mid-sentence, References-aware.
"""

from types import SimpleNamespace

import pytest

from deep_research import orchestrate as o

# ---- layer 2: deterministic trim --------------------------------------------


def test_trim_to_last_sentence_cuts_incomplete_tail():
    body = "First sentence is complete. Second one is also done. Then the final clause carries"
    out = o._trim_to_last_sentence(body)
    assert out == "First sentence is complete. Second one is also done."


def test_trim_drops_final_fragment_paragraph_with_no_terminal():
    body = "A complete paragraph ends here.\n\nDangling fragment with no end"
    out = o._trim_to_last_sentence(body)
    assert out == "A complete paragraph ends here."


def test_trim_returns_none_when_no_complete_sentence_anywhere():
    assert o._trim_to_last_sentence("one long run on with no terminal at all") is None


def test_trim_does_not_cut_at_inline_closing_paren():
    # Greptile #89 (P1): a bare closing paren is NOT a sentence boundary. A tail
    # like "...(Smith et al 2023) continues to improve the" must be dropped
    # wholesale, not cut into the fragment "...(Smith et al 2023)".
    body = "The prior chapter is complete.\n\nThe algorithm (based on Smith et al 2023) continues to improve the"
    out = o._trim_to_last_sentence(body)
    assert out == "The prior chapter is complete."
    assert "Smith et al 2023)" not in out


def test_trim_keeps_closer_trailing_a_real_terminal():
    # The flip side: a closing quote/paren that legitimately trails an ender is
    # kept, so a sentence ending in `."` survives intact (not chopped to `.`).
    body = 'First.\n\nShe said "this works." Then the next bit trails off with no'
    out = o._trim_to_last_sentence(body)
    assert out == 'First.\n\nShe said "this works."'


def test_trim_drops_unclosed_code_fence():
    # Greptile #89 (P2): an odd ``` count means a code block truncated mid-stream.
    # Sentence scanning can't close it, so the partial block is dropped and the
    # last complete sentence before it is returned — no dangling open fence.
    body = "Intro paragraph is complete.\n\n```python\nx = compute()\nmore code that never closes"
    out = o._trim_to_last_sentence(body)
    assert out == "Intro paragraph is complete."
    assert "```" not in out


def test_trim_drops_open_fence_inside_final_paragraph():
    # The open fence sits inside the final fragment paragraph: drop the whole
    # fragment (fence included) and fall back to the prior complete sentence.
    body = "Done and complete.\n\nMid paragraph then ```py\nopen = True\nnever closed"
    out = o._trim_to_last_sentence(body)
    assert out == "Done and complete."
    assert "```" not in out


def test_guarantee_trims_body_preserves_references():
    article = (
        "# 1 Intro\nThis chapter is complete.\n\n"
        "# 3 Synthesis\nThe conclusion is solid. But the very last clause just stops here and then\n\n"
        "## References\n[^1]: Source — http://x"
    )
    s = SimpleNamespace(article=article, completion_repair_stats={})
    out = o._guarantee_complete_ending(s)
    assert "stops here and then" not in out
    assert "The conclusion is solid." in out
    assert "## References" in out and "[^1]: Source" in out  # bibliography preserved
    assert s.completion_repair_stats["trimmed"] is True


def test_guarantee_leaves_complete_article_untouched():
    article = "# 1 Intro\nAll done here.\n\n## References\n[^1]: x — http://x"
    s = SimpleNamespace(article=article, completion_repair_stats={})
    out = o._guarantee_complete_ending(s)
    assert out == article
    assert s.completion_repair_stats.get("trimmed") in (None, False)


def test_guarantee_flags_unrepairable_tail():
    # A body that is one run-on fragment with no complete sentence anywhere:
    # nothing safe to trim to -> ship as-is but flag still_incomplete.
    article = "fragment with no terminal anywhere at all"
    s = SimpleNamespace(article=article, completion_repair_stats={})
    out = o._guarantee_complete_ending(s)
    assert out == article
    assert s.completion_repair_stats["still_incomplete"] is True


# ---- layer 1: bounded final-section re-roll ---------------------------------


def _fake_state(sections):
    return SimpleNamespace(
        sections=sections,
        plan={"toc": []},
        memory_bank=None,
        archetype={"archetype": "explain-mechanism"},
        domain="tech",
        design_guide=None,
        scaffold=None,
        task_id=None,
        completion_repair_stats={},
    )


def _patch_units(monkeypatch, n):
    units = [{"id": f"S{i}", "title": f"Sec {i}"} for i in range(1, n + 1)]
    monkeypatch.setattr(o.writer, "outline_units", lambda plan: units)


def test_reroll_fixes_mid_sentence_final_section(monkeypatch):
    _patch_units(monkeypatch, 2)
    monkeypatch.setattr(o, "_write_with_guide", lambda *a, **k: ("Regenerated complete final section.", {}))
    s = _fake_state(["First section is complete.", "final section that just stops mid"])
    o._repair_final_section(s, "the query", "en")
    assert s.sections[-1] == "Regenerated complete final section."
    assert s.completion_repair_stats["final_mid_sentence"] is True
    assert s.completion_repair_stats["reroll_fixed"] is True
    assert s.completion_repair_stats["reroll_attempts"] == 1


def test_reroll_noop_when_final_section_complete(monkeypatch):
    called = {"n": 0}

    def _wwg(*a, **k):
        called["n"] += 1
        return ("x", {})

    monkeypatch.setattr(o, "_write_with_guide", _wwg)
    s = _fake_state(["First is complete.", "And the final section is complete too."])
    o._repair_final_section(s, "q", "en")
    assert called["n"] == 0  # no re-roll fired
    assert s.completion_repair_stats["final_mid_sentence"] is False


def test_reroll_bounded_keeps_last_attempt_when_still_cut(monkeypatch):
    _patch_units(monkeypatch, 1)
    monkeypatch.setattr(o, "_write_with_guide", lambda *a, **k: ("still ends mid", {}))
    monkeypatch.setattr(o, "_COMPLETION_REPAIR_CAP", 2)
    s = _fake_state(["only section ends mid"])
    o._repair_final_section(s, "q", "en")
    assert s.completion_repair_stats["reroll_attempts"] == 2
    assert s.completion_repair_stats["reroll_fixed"] is False
    assert s.sections[-1] == "still ends mid"  # latest attempt kept for the trim layer


def test_reroll_disabled_at_cap_zero(monkeypatch):
    monkeypatch.setattr(o, "_COMPLETION_REPAIR_CAP", 0)
    monkeypatch.setattr(o, "_write_with_guide", lambda *a, **k: ("x.", {}))
    s = _fake_state(["complete.", "ends mid here"])
    o._repair_final_section(s, "q", "en")
    assert s.completion_repair_stats["final_mid_sentence"] is True
    assert s.completion_repair_stats["reroll_attempts"] == 0


def test_reroll_survives_write_exception(monkeypatch):
    _patch_units(monkeypatch, 1)

    def _boom(*a, **k):
        raise RuntimeError("transient")

    monkeypatch.setattr(o, "_write_with_guide", _boom)
    s = _fake_state(["only section ends mid"])
    o._repair_final_section(s, "q", "en")  # must not raise
    assert s.completion_repair_stats["final_mid_sentence"] is True
    assert s.sections[-1] == "only section ends mid"


def test_cap_env_validation(monkeypatch):
    monkeypatch.setenv("DR_COMPLETION_REPAIR_CAP", "9")  # above MAX
    with pytest.raises(ValueError):
        o._completion_repair_cap_from_env()
    monkeypatch.setenv("DR_COMPLETION_REPAIR_CAP", "notanint")
    with pytest.raises(ValueError):
        o._completion_repair_cap_from_env()
