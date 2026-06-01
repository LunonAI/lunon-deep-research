"""Round 5 T1-PR3: runaway-block clamp + lowered section budget ceiling.

id=89's §2.3 was a single FLAT 18,544-word block (50% of the body) — the
"disorganized wall" the judge scored formatting 2.0. The init_format ceiling
(now 18000) prevents the BUDGET; `_clamp_runaway_blocks` is the deterministic
post-assembly backstop for a block that ran away anyway.
"""

import pytest

from deep_research import orchestrate as o
from deep_research.pipeline import init_format

# ---- _truncate_to_token_budget ----------------------------------------------


def test_truncate_under_budget_returns_full():
    text = "Short and complete. Done."
    assert o._truncate_to_token_budget(text, 10_000) == text


def test_truncate_over_budget_cuts_at_sentence_boundary():
    text = "Sentence one is here. " * 40  # ~200 tokens
    out = o._truncate_to_token_budget(text, 30)
    assert out is not None
    assert out.endswith(".")  # ends on a complete sentence
    assert o.text_metrics.approx_tokens(out) <= o.text_metrics.approx_tokens(text)
    assert len(out) < len(text)
    # Greptile #90: pin the approximate-ceiling contract. The result may overshoot
    # max_tokens by a few % on CJK-dense text (see _truncate_to_token_budget
    # docstring); a loose bound keeps that contract visible and catches a char-
    # estimate regression that drifts far outside the budget. (This pure-EN case
    # actually lands at/under budget.)
    assert o.text_metrics.approx_tokens(out) <= int(30 * 1.2)


def test_truncate_does_not_cut_at_bare_closing_paren():
    # Greptile #90: a bare closer (`)`) is NOT a sentence boundary. When the char
    # budget lands mid-sentence just after a parenthetical, the backward scan must
    # skip the `)` and cut at the prior real ENDER — never leaving the fragment
    # "...(Jones 2021)". Mirrors _trim_to_last_sentence's inline-paren guard.
    text = (
        "Complete sentence one here. "
        "Now a clause with a citation (Jones 2021) keeps running on and on and on "
        "without any terminator for a long stretch of words"
    )
    out = o._truncate_to_token_budget(text, 30)
    assert out is not None
    assert out.endswith(".")  # cut at the real ender, not the bare paren
    assert not out.rstrip().endswith(")")
    assert "(Jones 2021)" not in out  # the mid-sentence parenthetical is dropped wholesale


def test_truncate_does_not_leave_dangling_code_fence():
    # Greptile follow-up: truncating a runaway block must not cut inside a code
    # fence and ship a dangling open ```. Enders inside the unclosed block are
    # skipped; the cut falls back to a sentence ender OUTSIDE the block so the
    # returned prefix has balanced fences (mirrors _trim_to_last_sentence).
    text = (
        "Intro sentence is complete here. ```python\n"
        + "x = 1  # filler comment line.\n" * 12
        + "```\ntrailing prose runs on after the block without a terminator for a long stretch of words here"
    )
    out = o._truncate_to_token_budget(text, 30)
    assert out is not None
    assert out.count("```") % 2 == 0  # balanced fences — no dangling open block
    assert "```" not in out  # cut before the fence opened
    assert out.endswith(".")


def test_truncate_no_boundary_returns_none():
    text = "word " * 400  # no sentence terminal anywhere
    assert o._truncate_to_token_budget(text, 30) is None


# ---- _clamp_runaway_blocks --------------------------------------------------


def _small_threshold(monkeypatch, n=30):
    monkeypatch.setattr(o, "_runaway_block_tokens", lambda: n)


def test_clamp_truncates_runaway_block_preserves_others(monkeypatch):
    _small_threshold(monkeypatch)
    article = (
        "# 1 Intro\nShort intro sentence here.\n\n"
        "# 2 Runaway\n" + "Sentence in the wall is here. " * 60 + "\n\n"
        "# 3 Next\nThe next chapter is fine.\n"
    )
    out, stats = o._clamp_runaway_blocks(article)
    assert stats["blocks_clamped"] == 1
    assert stats["tokens_removed"] > 0
    assert "# 1 Intro" in out and "# 2 Runaway" in out and "# 3 Next" in out  # all headings kept
    assert "The next chapter is fine." in out  # block after the runaway intact
    assert o.text_metrics.approx_tokens(out) < o.text_metrics.approx_tokens(article)


def test_clamp_noop_when_all_blocks_small(monkeypatch):
    _small_threshold(monkeypatch, 10_000)
    article = "# 1 A\nshort.\n\n# 2 B\nalso short.\n"
    out, stats = o._clamp_runaway_blocks(article)
    assert out == article
    assert stats["blocks_clamped"] == 0


def test_clamp_gate_off_disables(monkeypatch):
    _small_threshold(monkeypatch)
    monkeypatch.setenv("DR_RUNAWAY_CLAMP", "off")
    article = "# 2 Runaway\n" + "Sentence here is fine. " * 60 + "\n"
    out, stats = o._clamp_runaway_blocks(article)
    assert out == article
    assert stats["blocks_clamped"] == 0


def test_clamp_no_headings_unchanged(monkeypatch):
    _small_threshold(monkeypatch)
    article = "Just prose with no headings at all. " * 50
    out, stats = o._clamp_runaway_blocks(article)
    assert out == article
    assert stats["blocks_clamped"] == 0


def test_clamp_preamble_before_first_heading_preserved(monkeypatch):
    # Greptile #90: the prior fixture started with `# Title` at position 0, so
    # `article[:heads[0]]` was empty and the preamble path was never exercised.
    # Use real text BEFORE the first heading and clamp a later runaway block, so
    # the non-empty `out = [article[:heads[0]]]` seed is verified to survive.
    _small_threshold(monkeypatch)
    preamble = "Front-matter preamble before any heading, left untouched.\n\n"
    article = preamble + "# 1 Runaway\n" + "Sentence in the wall is here. " * 60 + "\n\n# 2 Tail\nfine.\n"
    out, stats = o._clamp_runaway_blocks(article)
    assert out.startswith(preamble)  # non-empty preamble preserved verbatim at the head
    assert stats["blocks_clamped"] == 1  # the runaway block was still clamped
    assert "# 2 Tail" in out and "fine." in out  # the block after the runaway is intact


def test_runaway_block_tokens_env_validation(monkeypatch):
    monkeypatch.setenv("DR_RUNAWAY_BLOCK_TOKENS", "1000")  # below MIN
    with pytest.raises(ValueError):
        o._runaway_block_tokens()
    monkeypatch.setenv("DR_RUNAWAY_BLOCK_TOKENS", "x")
    with pytest.raises(ValueError):
        o._runaway_block_tokens()
    monkeypatch.setenv("DR_RUNAWAY_BLOCK_TOKENS", "12000")
    assert o._runaway_block_tokens() == 12_000


# ---- init_format ceiling ----------------------------------------------------


def test_section_budget_ceiling_lowered_to_18000():
    assert init_format.SECTION_BUDGET_CEILING == 18_000


def test_ceiling_caps_a_mega_section_budget():
    # A single deeply-seeded chapter whose leaf floor blows past the ceiling is
    # capped at 18000 tokens (≈13.5k words), not the old 30000 (≈22.5k = runaway).
    subs = [{"id": f"S1.{i}", "title": f"Sub {i}", "depth_seeds": ["a", "b", "c", "d"]} for i in range(30)]
    plan = {
        "report_toc": [{"id": "S1", "title": "Mega", "depth_target": "deep", "subsections": subs}],
        "_outline_audit": {"archetype": "explain-mechanism"},
    }
    out = init_format.run(init_format.InitFormatInput(plan=plan, language="en", domain="default"))
    assert out.scaffold.sections[0].expected_length_tokens == 18_000
