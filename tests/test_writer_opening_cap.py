"""Greptile PR #86: code-level backstop on the opening's visible length.

Pre-Opus-4.8 `write_opening` used `max_tokens=1400`, which physically bounded
the opening output. PR #86 raised max_tokens to 24000 and enabled `think=True`
so max-effort thinking has room — but thinking and prose then share that one
budget, removing the implicit cap on visible prose. `_cap_opening_length`
restores a code-level cap (`_OPENING_TOKEN_BACKSTOP`) on the VISIBLE opening so
a runaway preamble can't sail past every downstream stage (no validator checks
the opening's length).

These tests pin: (1) a well-formed opening is returned byte-identical (never
truncated), (2) a catastrophic overshoot is truncated to within the backstop,
(3) the `# Title` head and markdown structure survive the truncation, and (4)
the CJK-aware estimator drives the cap so a ZH opening is bounded by tokens, not
raw character count.
"""

from deep_research.pipeline.writer import _OPENING_TOKEN_BACKSTOP, _cap_opening_length
from deep_research.text_metrics import approx_tokens


def test_wellformed_opening_passes_through_unchanged():
    # ~200-token target / ~300 hard max: well under the 1400 backstop, so the
    # cap must be a strict no-op (identity), not a re-rendering.
    opening = (
        "# The State of Edge AI in 2026\n\n"
        "The edge-inference market crossed an inflection point this year. "
        "Three forces converged: cheaper NPUs, mature on-device runtimes, and "
        "regulatory pressure pushing inference off the cloud. This report maps "
        "where that leaves vendors and buyers heading into 2027."
    )
    assert approx_tokens(opening) < _OPENING_TOKEN_BACKSTOP
    assert _cap_opening_length(opening) == opening


def test_overshoot_is_truncated_within_backstop():
    bloat = "# Title\n\n" + ("This sentence pads the opening past the backstop. " * 400)
    assert approx_tokens(bloat) > _OPENING_TOKEN_BACKSTOP
    capped = _cap_opening_length(bloat)
    assert approx_tokens(capped) <= _OPENING_TOKEN_BACKSTOP


def test_truncation_preserves_title_head_and_sentence_boundary():
    bloat = "# Title\n\n" + ("This sentence pads the opening past the backstop. " * 400)
    capped = _cap_opening_length(bloat)
    # The markdown title must survive so the opening-template check still sees a
    # valid head (truncation slices the original string in place, never rejoins).
    assert capped.startswith("# Title\n\n")
    # Cut lands on a sentence terminator, not mid-word.
    assert capped.rstrip().endswith(".")


def test_pathological_run_without_boundary_still_capped():
    # No sentence/paragraph boundary at all: the char-budget fallback must still
    # bound the output rather than returning the whole runaway string.
    run = "x" * (_OPENING_TOKEN_BACKSTOP * 40)
    capped = _cap_opening_length(run)
    assert len(capped) < len(run)
    assert approx_tokens(capped) <= _OPENING_TOKEN_BACKSTOP + 1


def test_cjk_opening_bounded_by_tokens_not_chars():
    # A CJK opening packs ~1.6 chars/token, so a char-based cap would wrongly
    # let ~2.5x the intended length through. Pad past the token backstop and
    # confirm the token-aware cap still fires.
    cjk_bloat = "# 标题\n\n" + ("这是一个用于测试的开篇段落。" * 600)
    assert approx_tokens(cjk_bloat) > _OPENING_TOKEN_BACKSTOP
    capped = _cap_opening_length(cjk_bloat)
    assert approx_tokens(capped) <= _OPENING_TOKEN_BACKSTOP
    assert capped.startswith("# 标题")
