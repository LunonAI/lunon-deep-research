"""Round 5 T1-PR1: residual-scaffolding strip (CAPEL open-markers only).

Covers:
- The literal id=89 leaks: open CAPEL markers (`<5093`, `<4788`, `<6904`,
  `<4898`) that sat at PARAGRAPH/LINE ends, plus a marker at the EOF
  truncation seam ("...frameworks<4898" -> "...frameworks").
- PRECISION: an inline numeric comparison ("values <50 mg/L", "<4898 units")
  is followed by a space+word, not a line break, so it is NEVER matched; and
  legitimate `R-N` / acceptance-criterion `AC10` content is left untouched
  (those are NOT stripped — they corrupt real content, per id=89 inspection).
- Span-masking: a real `<5093` at a line end inside a code fence / table row
  survives.
- Closed markers `<4898>` are LEFT for _capel_strip.
- Idempotency, whitespace hygiene, fail-soft on empty/None input.
"""

from deep_research.pipeline.scaffold_strip import strip_residual_scaffolding


def test_id89_open_capel_marker_at_eof_removed():
    text = "the same conclusion that carries forward: the frameworks<4898"
    out, stats = strip_residual_scaffolding(text)
    assert out == "the same conclusion that carries forward: the frameworks"
    assert stats["capel_open"] == 1
    assert stats["n_total"] == 1


def test_id89_line_end_markers_removed_no_trailing_space():
    # The actual id=89 forms: marker glued to the preceding word OR after a
    # space, both immediately before a paragraph break.
    text = "...first and only later,<5093\n\nThe Mechanics layer must have a sink,<4788\n\nProcedural content."
    out, stats = strip_residual_scaffolding(text)
    assert "<5093" not in out and "<4788" not in out
    assert "later,\n\nThe Mechanics" in out
    assert "sink,\n\nProcedural" in out  # marker stripped, comma glued directly to paragraph break
    assert stats["capel_open"] == 2


def test_marker_spaced_both_sides_before_newline_no_trailing_space():
    # Defensive case the regex lookahead `[ \t]*(?:\n|$)` permits but the
    # observed id=89 leaks never hit: a marker padded by a space on BOTH sides
    # with the trailing space sitting right before a paragraph break. Both
    # spaces must go so no " \n" trailing whitespace is left behind.
    text = "word <5093 \n\nNext para."
    out, stats = strip_residual_scaffolding(text)
    assert "<5093" not in out
    assert "word\n\nNext para." in out
    assert " \n" not in out  # no trailing whitespace before the break
    assert stats["capel_open"] == 1


def test_marker_multiple_trailing_spaces_before_newline_all_stripped():
    # The lookahead `[ \t]*` permits a RUN of trailing spaces before the break.
    # All of them (plus the leading space) must go so nothing trails the word.
    text = "tail<4788   \n\nNext para."
    out, stats = strip_residual_scaffolding(text)
    assert "<4788" not in out
    assert "tail\n\nNext para." in out
    assert " \n" not in out
    assert stats["capel_open"] == 1


def test_inline_comparison_is_not_eaten():
    # The precision guarantee: a comparison mid-line (space+word after) is safe.
    text = "Studies with <50 participants and budgets <4898 units were excluded."
    out, stats = strip_residual_scaffolding(text)
    assert out == text
    assert stats["capel_open"] == 0


def test_legit_rn_and_ac_content_untouched():
    # id=89 reality: R-N is a rubric table row and AC10 is prose ("acceptance
    # criterion AC10") — both legitimate content this pass must NOT remove.
    text = "| R-1 | Theoretical Novelty | 15% |\n\nThe roadmap satisfies acceptance criterion AC10 and AC28.\n"
    out, stats = strip_residual_scaffolding(text)
    assert out == text
    assert stats["n_total"] == 0


def test_closed_marker_left_for_capel_strip():
    # `<4898>` (closed) is the existing _capel_strip's job — the end-of-line
    # lookahead rejects it (next char `>`).
    text = "word<4898>\n\nword"
    out, stats = strip_residual_scaffolding(text)
    assert out == text
    assert stats["n_total"] == 0


def test_code_fence_is_protected():
    text = "Prose leak<5093\n\n```python\nif a <5093\n    pass\n```\n\nMore prose,<4788\n"
    out, stats = strip_residual_scaffolding(text)
    # the real `<5093` inside the fence survives; the two prose leaks go
    assert "if a <5093" in out
    assert "leak<5093" not in out and ",<4788" not in out
    assert stats["capel_open"] == 2


def test_table_line_protected():
    text = "| col | <5093 |\n| --- | --- |\nProse,<4788\n"
    out, stats = strip_residual_scaffolding(text)
    assert "| col | <5093 |" in out  # table row untouched
    assert "<4788" not in out
    assert stats["capel_open"] == 1


def test_idempotent():
    text = "lead,<5093\n\nmid tail<4898"
    once, _ = strip_residual_scaffolding(text)
    twice, stats2 = strip_residual_scaffolding(once)
    assert once == twice
    assert stats2["n_total"] == 0


def test_no_markers_returns_verbatim():
    text = "Clean prose with no scaffolding at all.\n\nSecond para."
    out, stats = strip_residual_scaffolding(text)
    assert out == text
    assert stats["n_total"] == 0


def test_failsoft_empty_and_none():
    assert strip_residual_scaffolding("")[0] == ""
    assert strip_residual_scaffolding(None)[0] is None
    assert strip_residual_scaffolding("")[1]["n_total"] == 0
