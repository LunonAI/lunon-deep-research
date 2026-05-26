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


# ---- Wave 0 §11 (2026-05-26): subword-split prohibition ----------------


def test_directive_prohibits_subword_splitting():
    # The pre-Wave-0 directive said "one content token" which the writer
    # interpreted at the BPE-subword level — producing `Sag itt arius`
    # in id=91 smoke output. The strengthened directive must say
    # "ONE COMPLETE WORD" or equivalent so the writer understands
    # `Sagittarius` is one token, not three BPE pieces.
    out = capel_directive(1200)
    assert "ONE COMPLETE WORD" in out or "complete english word" in out.lower()


def test_directive_shows_subword_forbidden_example():
    # A worked FORBIDDEN example is critical for the directive to land —
    # without seeing what "wrong" looks like, the writer over-generalises
    # from "one token per marker". The example must use a recognisable
    # multi-syllable word with its subword fragmentation shown.
    out = capel_directive(1200)
    assert "FORBIDDEN" in out
    # The canonical Sagittarius example from the id=91 smoke; pinning the
    # exact word so a future "cleanup" rewrite can't silently drop the
    # demonstration without us noticing.
    assert "Sagittarius" in out or "Sag" in out


def test_directive_explains_dotted_numbers_as_single_token():
    # 16 of 29 headings in id=91 smoke had `## 4 . 1 . 1` corruption —
    # writer split `4.1.1` across markers because it didn't understand
    # dotted numbers count as one token. The directive must explicitly
    # call this out so future writes get it right at the source.
    out = capel_directive(1200)
    # Either the specific example (4.1.1) or an equivalent statement.
    assert "4.1.1" in out or "dotted" in out.lower() or "atomic" in out.lower()


def test_directive_forbids_subword_split_to_hit_counter():
    # The closing instruction should explicitly prohibit subword splits
    # as a length-control tactic — the writer's prior failure mode was to
    # use BPE fragmentation to make the marker counter land precisely.
    # `STOP early` already covered the padding case; the Wave 0 addition
    # is the parallel rule for subword splitting.
    out = capel_directive(1200)
    text_lower = out.lower()
    assert "subword" in text_lower or "split" in text_lower
