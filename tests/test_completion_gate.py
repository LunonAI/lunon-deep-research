"""L1 (2026-05-29): chapter-completion gate helpers.

The inner loop accepted a section on grounding + quality score but never on
COMPLETENESS, so thin-but-coherent chapters passed (the "hollow late chapter"
failure vs Qianfan — id38 §5 = 185 chars vs a multi-thousand-token target).
These pin the completeness helpers that now gate acceptance + drive the
expand-retry + the hollow-chapter telemetry.
"""

from deep_research import orchestrate as o


def test_approx_tokens_en_and_cjk():
    # EN ~4 chars/token; CJK ~1.6 chars/token.
    assert 40 <= o._approx_tokens("x" * 200) <= 60
    assert o._approx_tokens("研究背景与方法" * 10) > o._approx_tokens("x" * 70)  # CJK denser per char


def test_approx_tokens_counts_cjk_extension_a():
    """Greptile PR #69 round-1: CJK Extension A ideographs (U+3400–U+4DBF) are
    billed at the dense CJK rate (~1.6 chars/token), not the sparse ~4 chars/token
    'other' rate — matching cjk_despace._CJK. Before the fix an Ext-A char was
    counted as 'other' and `_approx_tokens` matched the EN baseline exactly."""
    # 16 Ext-A ideographs vs 16 ASCII chars: CJK rate must yield a higher estimate.
    assert o._approx_tokens("㐀㐁㐂㐃㐄㐅㐆㐇㐈㐉㐊㐋㐌㐍㐎㐏") > o._approx_tokens("x" * 16)


def test_approx_tokens_strips_heading_lines():
    body = "## 1 Heading That Is Quite Long And Wordy\n\nshort body."
    # Heading line excluded → count reflects body only, not the long heading.
    assert o._approx_tokens(body) < o._approx_tokens("## h\n\n" + "word " * 100)


def test_section_too_thin_severe_shortfall_flagged():
    assert o._section_too_thin("x" * 185, 1200) is True  # the id38 §5 case


def test_section_full_length_not_thin():
    assert o._section_too_thin("word " * 1200, 1200) is False


def test_section_too_thin_guards_zero_expected():
    # No declared target → never flagged (avoid false positives on untargeted units).
    assert o._section_too_thin("x" * 10, 0) is False
    assert o._section_too_thin("x" * 10, None) is False


def test_section_just_above_half_not_thin():
    # 0.5x is the bar; a section at ~0.6x its target is NOT flagged (only SEVERE
    # shortfalls fire, so legitimately-concise sections aren't churned).
    text = "word " * 760  # ~760 tokens vs 1200 target = 0.63x
    assert o._section_too_thin(text, 1200) is False


def test_expand_feedback_directs_full_development():
    fb = o._expand_feedback(1500)
    assert "COMPLETENESS" in fb and "1500" in fb
    assert "stub" in fb.lower() and "expand" in fb.lower()


def test_expected_tok_for_default_when_no_scaffold():
    assert o._expected_tok_for(None, "S1") == 1200
