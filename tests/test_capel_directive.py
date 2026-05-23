"""Unit tests for P2-Wave-2-A `capel_directive` instruction builder.

The directive's contract:
- Instructs writer to emit `<N>` ... `<0>` countdown markers.
- N is derived from target_tokens conservatively (×0.75 tokens→words).
- Cites the paper (arXiv 2508.13805).
- States the "never back-to-back" rule.
- Notes post-processing strips markers (writer should not worry).
- Tells writer to STOP early rather than pad.
"""

from deep_research.writing_rules import capel_directive


def test_directive_includes_paper_citation():
    out = capel_directive(1200)
    assert "2508.13805" in out


def test_directive_starts_with_correct_n_marker():
    # 1200 tokens * 0.75 = 900 → `<900>` is the opener.
    out = capel_directive(1200)
    assert "<900>" in out
    assert "<0>" in out


def test_smaller_target_floored_to_50():
    # Below 67 tokens, the floor of 50 markers should kick in.
    out = capel_directive(40)
    assert "<50>" in out


def test_zero_target_floored_to_50():
    out = capel_directive(0)
    assert "<50>" in out


def test_directive_mentions_back_to_back_prohibition():
    out = capel_directive(500)
    assert "back-to-back" in out.lower() or "never appear back-to-back" in out.lower()


def test_directive_mentions_post_processing_strip():
    out = capel_directive(500)
    assert "strip" in out.lower()


def test_directive_tells_writer_to_stop_early():
    out = capel_directive(500)
    # "STOP early rather than padding" or similar instruction must appear.
    assert "STOP" in out
    assert "pad" in out.lower()
