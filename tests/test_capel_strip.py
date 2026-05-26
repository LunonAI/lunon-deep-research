"""Unit tests for P2-Wave-2-A CAPEL marker post-strip.

Covers:
- Round-trip strip of well-formed countdown markers.
- Adjacent-marker violation detection (paper's hard rule).
- Marker-only input (model produced no content) -> just whitespace returned.
- Preservation of legitimate angle-bracket constructs that are NOT markers
  (HTML-ish tags, comparison `<` operators).
- Empty / None-ish input fail-soft.
- Stats accounting.
- Wave 0 §11 (2026-05-26): heading-number repair + word-fragment repair
  safety-net passes that catch BPE-subword splits the writer leaks past
  the strengthened CAPEL directive.
"""

from deep_research.pipeline._capel_strip import strip_capel_markers


def test_well_formed_countdown_strips_cleanly():
    text = "<3>The<2>quick<1>brown<0>fox."
    out, stats = strip_capel_markers(text)
    assert "<" not in out
    assert ">" not in out
    assert "The" in out and "quick" in out and "brown" in out and "fox" in out
    assert stats["n_markers_stripped"] == 4
    assert stats["n_violations"] == 0


def test_back_to_back_markers_flagged_as_violation():
    # `<5><4>` with no intervening token = exactly 1 violation.
    text = "Word1 <5><4> Word2 <3>Word3<2>Word4<1>Word5<0>"
    out, stats = strip_capel_markers(text)
    assert stats["n_violations"] == 1
    assert stats["n_markers_stripped"] == 6
    # The two violating markers still get stripped; the output is content-only.
    assert "<" not in out
    assert "Word1" in out and "Word5" in out


def test_triple_marker_run_reports_two_violations():
    # `<5><4><3>` = three markers, no intervening content. The overlapping
    # lookahead counter must report n-1 = 2 violations, not 1 (the non-
    # overlapping `<…><…>` pattern would consume `<5><4>` and miss the
    # `<4><3>` adjacency). Greptile-flagged regression guard.
    text = "alpha <5><4><3> beta <2>gamma<1>delta<0>"
    _, stats = strip_capel_markers(text)
    assert stats["n_violations"] == 2


def test_quadruple_marker_run_reports_three_violations():
    text = "<5><4><3><2>only-content<1>here<0>"
    _, stats = strip_capel_markers(text)
    assert stats["n_violations"] == 3


def test_marker_count_with_whitespace_between_violators():
    # `<5>  <4>` (whitespace only between markers) is still a violation per
    # paper: an intervening content TOKEN is required, not just whitespace.
    text = "<5>  <4>Hello<3>World<0>"
    _, stats = strip_capel_markers(text)
    assert stats["n_violations"] >= 1


def test_preserves_non_marker_angle_brackets():
    # HTML-like tags (alpha chars) and comparison ops MUST NOT be stripped.
    text = "If <a> tag and x < 5 are valid, only <3>real<2>markers<1>strip<0>."
    out, stats = strip_capel_markers(text)
    assert "<a>" in out  # html-ish tag preserved
    assert "x < 5" in out  # comparison operator preserved
    assert stats["n_markers_stripped"] == 4


def test_collapses_doubled_whitespace_left_behind():
    # When markers sit at word boundaries with surrounding spaces, the strip
    # should not leave doubled spaces.
    text = "alpha <3> beta <2> gamma <1> delta <0> epsilon"
    out, _ = strip_capel_markers(text)
    assert "  " not in out  # no doubled spaces
    assert "alpha" in out and "epsilon" in out


def test_empty_input_returns_empty():
    out, stats = strip_capel_markers("")
    assert out == ""
    # Wave 0 §11 + Wave 0.1 §11.7 stats dict shape — pin so drift-log
    # consumers don't break silently on a future stats-shape change.
    assert stats == {
        "n_markers_stripped": 0,
        "n_violations": 0,
        "n_word_repairs": 0,
        "n_heading_repairs": 0,
        "n_bracket_repairs": 0,
    }


def test_no_markers_returns_unchanged_text_with_zero_stats():
    text = "Plain paragraph with no markers at all. Numbers like 2025 are fine."
    out, stats = strip_capel_markers(text)
    assert out == text
    assert stats["n_markers_stripped"] == 0
    assert stats["n_violations"] == 0


def test_marker_free_input_with_double_spaces_is_left_alone():
    # Writer output without CAPEL markers MUST be returned verbatim — the
    # whitespace-collapse pass is only triggered when markers were actually
    # stripped, so legitimate double spaces (code blocks, indented quotes)
    # survive untouched. Greptile-flagged contract guard.
    text = "Indented  paragraph  with  intentional  doubled  spaces."
    out, stats = strip_capel_markers(text)
    assert out == text  # bit-identical
    assert stats["n_markers_stripped"] == 0


def test_marker_strip_does_collapse_introduced_doubled_spaces():
    # When markers ARE stripped and the strip leaves runs of whitespace
    # (e.g. `alpha <3> beta`), the collapse pass MUST normalize them.
    text = "alpha <3> beta <2> gamma <1> delta <0> epsilon"
    out, stats = strip_capel_markers(text)
    assert "  " not in out
    assert stats["n_markers_stripped"] == 4


def test_marker_with_5_digits_still_recognized():
    # Marker count for large sections could realistically hit four or five
    # digits (e.g. <12000> for total-article CAPEL). Pattern must accept them.
    text = "<12000>content<11999>"
    _, stats = strip_capel_markers(text)
    assert stats["n_markers_stripped"] == 2


def test_marker_with_six_or_more_digits_not_recognized():
    # A long bracketed numeric run is probably NOT a CAPEL marker. Avoid
    # over-eager stripping.
    text = "Reference [<123456> entry] keep"
    out, stats = strip_capel_markers(text)
    assert "<123456>" in out
    assert stats["n_markers_stripped"] == 0


def test_newlines_preserved_through_strip():
    text = "Heading\n<5>line<4>one\n\n<3>line<2>two<1>here<0>"
    out, _ = strip_capel_markers(text)
    assert "\n\n" in out  # paragraph break survives


# ---- Wave 0 §11: heading-number repair ----------------------------------


def test_heading_dot_number_two_level_repaired():
    # `## 4 . 1` (writer split the dotted number across CAPEL markers) →
    # `## 4.1`. The repair must trigger only after markers were stripped
    # so we route through a real CAPEL strip.
    text = "<5>##<4> 4<3> .<2> 1<1> Section<0>"
    out, stats = strip_capel_markers(text)
    assert "## 4.1 Section" in out
    assert stats["n_heading_repairs"] >= 1


def test_heading_dot_number_three_level_repaired():
    # `## 4 . 1 . 1` → `## 4.1.1`. Multi-pass loop required because a
    # single pass `(\d) \. (\d)` would rewrite to `4.1 . 1` and need
    # another iteration.
    text = "<7>##<6> 4<5> .<4> 1<3> .<2> 1<1> Sub<0>"
    out, stats = strip_capel_markers(text)
    assert "## 4.1.1 Sub" in out
    assert stats["n_heading_repairs"] >= 2


def test_heading_dot_repair_only_touches_heading_lines():
    # Prose like "section 4 . 1 . 1" (rare but legal in citation patterns)
    # MUST NOT be silently rewritten — the heading-line constraint
    # (`^#+\s+`) is the precision guard.
    text = "<10>This<9> is<8> section<7> 4<6> .<5> 1<4> in<3> our<2> paper<1>.<0>"
    out, stats = strip_capel_markers(text)
    # The prose form survives intact (note: the word-fragment repair
    # might not run since the tokens aren't subword-shaped; what matters
    # is the heading repair didn't fire on this prose).
    assert "4 . 1" in out
    assert stats["n_heading_repairs"] == 0


def test_heading_dot_repair_no_trigger_without_markers():
    # Input with no CAPEL markers MUST be returned verbatim — the repair
    # runs only when markers were actually stripped. This protects code
    # blocks or quoted text that legitimately contain `## 4 . 1`.
    text = "## 4 . 1 Already-spaced heading"
    out, stats = strip_capel_markers(text)
    assert out == text
    assert stats["n_heading_repairs"] == 0


# ---- Wave 0 §11: word-fragment repair -----------------------------------


def test_three_fragment_proper_noun_run_repaired():
    # The id=91 smoke canonical example: `Sagittarius` landed as `Sag itt
    # arius`. Three-tier rule should rejoin.
    text = "<5>The<4> Sag<3> itt<2> arius<1> Cloth<0>"
    out, stats = strip_capel_markers(text)
    assert "Sagittarius" in out
    assert "Sag itt arius" not in out
    assert stats["n_word_repairs"] >= 1


def test_three_fragment_lowercase_content_word_repaired():
    # `ass ault ist` → `assaultist`. All lowercase, three short pieces,
    # none in stopwords, joined length 10 — three-tier rule should fire.
    text = "<5>The<4> ass<3> ault<2> ist<1> struck<0>"
    out, stats = strip_capel_markers(text)
    assert "assaultist" in out
    assert stats["n_word_repairs"] >= 1


def test_three_fragment_mixed_case_first_letter_repaired():
    # `A ldebar an` → `Aldebaran`. First piece is 1-char capitalized,
    # second 6 chars (over threshold for individual piece but the rule
    # allows up to 5 per piece — `ldebar` is 6 so this would not match
    # the 3+ rule. This test pins the boundary: 6-char middle pieces
    # are NOT repaired, leaving them as-is. We expect no repair here.
    text = "<5>The<4> A<3> ldebar<2> an<1> star<0>"
    out, _ = strip_capel_markers(text)
    # The repair MUST NOT fire because a 6-char middle piece exceeds the
    # 5-char-per-fragment limit. Better to leave fragmented than to
    # falsely rejoin something that may not be a word.
    assert "A ldebar an" in out


def test_three_fragment_run_blocked_by_stopword():
    # `the cat sat` — three short alphabetic adjacent tokens but `the`
    # and `sat` are stopwords. The repair MUST NOT fire.
    text = "<5>So<4> the<3> cat<2> sat<1> here<0>"
    out, stats = strip_capel_markers(text)
    assert "the cat sat" in out
    assert stats["n_word_repairs"] == 0


def test_three_fragment_run_blocked_by_short_joined_length():
    # `a b c` — three single-char tokens. Joined "abc" is only 3 chars,
    # well below the 8-char "this is a real word" threshold. Plus "a" is
    # a stopword. MUST NOT fire.
    text = "<5>x<4> a<3> b<2> c<1> y<0>"
    out, stats = strip_capel_markers(text)
    assert "a b c" in out
    assert stats["n_word_repairs"] == 0


def test_two_fragment_capital_lowercase_short_first_repaired():
    # `Sc orpio` → `Scorpio`. First piece 2-char capitalized (≤2 BPE-shape
    # signature), second piece 5-char lowercase, neither stopword, joined
    # 7 chars. Two-tier rule should fire.
    text = "<5>The<4> Sc<3> orpio<2> sign<1> rules<0>"
    out, stats = strip_capel_markers(text)
    assert "Scorpio" in out
    assert stats["n_word_repairs"] >= 1


def test_two_fragment_capital_lowercase_short_second_repaired():
    # `Lib ra` → `Libra`. First 3-char cap, second 2-char lowercase (≤2
    # BPE signature on the second piece).
    text = "<5>The<4> Lib<3> ra<2> constellation<1> rises<0>"
    out, stats = strip_capel_markers(text)
    assert "Libra" in out
    assert stats["n_word_repairs"] >= 1


def test_two_fragment_both_three_chars_NOT_repaired():
    # `Tax man` (3+3) — neither piece ≤2 chars, so the BPE-signature
    # guard blocks the rejoin even though the joined form `Taxman` is a
    # word. Better to leave the legitimate "Tax man" intact than to
    # falsely glue compound nouns.
    text = "<5>The<4> Tax<3> man<2> arrived<1> late<0>"
    out, stats = strip_capel_markers(text)
    assert "Tax man" in out
    assert stats["n_word_repairs"] == 0


def test_two_fragment_short_proper_noun_plus_consonant_verb_NOT_repaired():
    # `Mu wore` — Mu is a real 2-char proper noun (Saint Seiya canon,
    # which is precisely the id=91 archetype). Without the consonant-
    # start guard on the second piece, this would falsely join to
    # `Muwore`. The guard recognises that "wore" begins with a consonant
    # (typical of standalone English content words) whereas BPE-frag
    # suffixes like `oga`/`orpio`/`anon` begin with vowels.
    text = "<5>The<4> Mu<3> wore<2> the<1> cloth<0>"
    out, stats = strip_capel_markers(text)
    assert "Mu wore" in out
    assert stats["n_word_repairs"] == 0


def test_two_fragment_short_proper_noun_plus_consonant_3char_NOT_repaired():
    # `Mu ran` — same logic, 3-char content verb starting with consonant.
    # The ≥3-char + consonant-start guard blocks even though the joined
    # form `Muran` is 5 chars (meets the joined-length floor).
    text = "<5>Then<4> Mu<3> ran<2> away<1> fast<0>"
    out, stats = strip_capel_markers(text)
    assert "Mu ran" in out
    assert stats["n_word_repairs"] == 0


def test_two_fragment_short_proper_noun_plus_vowel_suffix_repaired():
    # `Hy oga` — the consonant-start guard does NOT block when the
    # second piece starts with a vowel (BPE-fragmentation signature).
    # This is the canonical Saint-Seiya proper-noun rejoin case from
    # the id=91 smoke.
    text = "<5>The<4> Hy<3> oga<2> arrived<1> swiftly<0>"
    out, stats = strip_capel_markers(text)
    assert "Hyoga" in out
    assert stats["n_word_repairs"] >= 1


def test_two_fragment_single_letter_first_piece_repaired():
    # `K anon` — single-uppercase-letter first piece, lowercase suffix
    # starting with vowel. The regex `[A-Z][a-z]{0,4}` accepts the
    # 1-char first piece; the stopword filter on "i"/"a"/etc. prevents
    # false positives like "I am" / "A few" (where the first letter is
    # in the stopword set).
    text = "<5>The<4> K<3> anon<2> wielded<1> Saga<0>"
    out, stats = strip_capel_markers(text)
    assert "Kanon" in out
    assert stats["n_word_repairs"] >= 1


def test_two_fragment_single_letter_stopword_first_NOT_repaired():
    # `I am` / `A few` — single-letter first pieces that ARE stopwords
    # (`i`, `a`). The stopword filter must block even though the regex
    # matches the surface pattern.
    text = "<5>Yes<4> I<3> am<2> here<1> now<0>"
    out, stats = strip_capel_markers(text)
    assert "I am" in out
    assert stats["n_word_repairs"] == 0


def test_two_fragment_pair_blocked_by_stopword():
    # `He saw` — He is a stopword. MUST NOT fire even though pattern matches.
    text = "<5>Yesterday<4> He<3> saw<2> something<1> strange<0>"
    out, stats = strip_capel_markers(text)
    assert "He saw" in out
    assert stats["n_word_repairs"] == 0


def test_two_fragment_pair_blocked_by_lowercase_first():
    # `to me` — first piece "to" is lowercase (not capitalized), so the
    # Capital+lowercase pattern doesn't even match. But also stopword.
    text = "<5>handed<4> to<3> me<2> the<1> book<0>"
    out, _ = strip_capel_markers(text)
    assert "to me" in out


def test_two_fragment_pair_blocked_by_second_capital():
    # `New York` — second piece is capitalized, signals two independent
    # proper nouns rather than a fragmented single word. The pattern
    # `([A-Z][a-z]{1,4}) ([a-z]{2,5})` requires second-piece lowercase.
    text = "<5>visited<4> New<3> York<2> last<1> spring<0>"
    out, _ = strip_capel_markers(text)
    assert "New York" in out


def test_word_repair_does_not_run_without_markers():
    # Plain text containing `Sag itt arius` already in the source MUST be
    # left alone — the repair runs only when CAPEL markers were stripped,
    # because the bug exists only in the CAPEL output path.
    text = "Sag itt arius is a constellation."
    out, stats = strip_capel_markers(text)
    assert out == text
    assert stats["n_word_repairs"] == 0


def test_stats_dict_contains_all_wave0_keys():
    # Wave 0 §11 added `n_word_repairs` + `n_heading_repairs`; Wave 0.1
    # §11.7 added `n_bracket_repairs`. Pin all keys so drift-log
    # consumers don't break silently on a future stats-shape change.
    text = "<3>The<2>quick<1>fox<0>"
    _, stats = strip_capel_markers(text)
    assert set(stats.keys()) == {
        "n_markers_stripped",
        "n_violations",
        "n_word_repairs",
        "n_heading_repairs",
        "n_bracket_repairs",
    }


# ---- Wave 0.1 §11.7: footnote-bracket whitespace repair ----------------


def test_footnote_bracket_trailing_space_repaired():
    # Canonical id=91 smoke pattern: writer split `[^S1-1]` across CAPEL
    # markers as `[^S1-1<N>]`, strip left `[^S1-1 ]`. Normalize's regex
    # `\[\^([A-Za-z0-9._-]+)\]` rejects the trailing space, so 47 of 180
    # markers were silently dropped + zero defs were parsed downstream.
    text = "<5>see<4> [^S1-1<3>]<2> for<1> source<0>"
    out, stats = strip_capel_markers(text)
    assert "[^S1-1]" in out
    assert "[^S1-1 ]" not in out
    assert stats["n_bracket_repairs"] >= 1


def test_footnote_bracket_internal_spaces_repaired():
    # The more aggressive id=91 case: `[^ S8 -1 ]` (whitespace before AND
    # after each piece of the token because the writer treated `S8`, `-`,
    # `1` as three subword tokens with CAPEL markers between them).
    text = "<10>cite<9> [^<8>S8<7>-<6>1<5>]<4> here<3> end<0>"
    out, stats = strip_capel_markers(text)
    assert "[^S8-1]" in out
    assert "[^ " not in out
    assert " ]" not in out or "[^" not in out  # no internal space in any bracket
    assert stats["n_bracket_repairs"] >= 1


def test_footnote_bracket_already_clean_not_counted():
    # A well-formed `[^S1-3]` with no whitespace inside must NOT bump the
    # repair counter — n_bracket_repairs measures BPE-corruption recovery,
    # not every bracket the strip touches.
    text = "<5>cite<4> [^S1-3]<3> for<2> details<1>.<0>"
    out, stats = strip_capel_markers(text)
    assert "[^S1-3]" in out
    assert stats["n_bracket_repairs"] == 0


def test_footnote_bracket_definition_line_also_repaired():
    # Definition lines `[^S1-3]: source` carry the same bracket form as
    # inline markers; if the writer subword-split the token there too,
    # the definition would also be unparseable by `_DEFINITION_RE`
    # (same token char class). Repair must clean both.
    text = "<5>[^S1<4>-<3>3]<2>:<1> McKinsey 2025<0>"
    out, stats = strip_capel_markers(text)
    assert "[^S1-3]" in out
    assert stats["n_bracket_repairs"] >= 1


def test_footnote_bracket_repair_does_not_touch_non_footnote_brackets():
    # Markdown link reference syntax like `[footnote text][1]` is NOT a
    # caret-bracket footnote. The repair regex only matches `[^...]`,
    # so the bracketed reference text stays untouched.
    text = "<5>see<4> [link text][1]<3> and<2> footnote<1>.<0>"
    out, stats = strip_capel_markers(text)
    assert "[link text][1]" in out
    assert stats["n_bracket_repairs"] == 0


def test_footnote_bracket_repair_does_not_run_without_markers():
    # The no-markers-equals-verbatim contract applies to bracket repair
    # too — if no CAPEL markers were stripped, a `[^S1-1 ]` already in
    # the source text stays as-is. (The bug only exists in the CAPEL
    # output path, so the repair is gated on marker presence.)
    text = "Pre-existing [^S1-1 ] in source text."
    out, stats = strip_capel_markers(text)
    assert out == text
    assert stats["n_bracket_repairs"] == 0
