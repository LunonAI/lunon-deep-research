r"""Unit tests for the E1 section-opening compliance gate.

History:
- v2 semantic gate REWARDED "Building on §N..." / "this section examines..."
  vocabulary because the writer-prompt rule at that time told the writer to
  produce framework-recap openings.
- v3 (2026-05-26, gap-map §12.A) flipped the writer-prompt rule: the same
  vocabulary is now an antipattern banned by `_SECTION_OPENING_PROSE_LEAD_RULE`
  in `deep_research/writing_rules.py`. The compliance gate had to invert in
  lockstep — otherwise post-merge smoke runs would report v3-correct openers
  as non-compliant and v3-forbidden openers as compliant (backwards).
- v3 (round-3, 2026-05-26): the §1 exemption was narrowed — only the topic-
  restriction is exempt; all FORBIDDEN antipatterns still apply to the
  article opener. The gate now grades sections[0] too. The meta-subject
  regex's verb slot was opened from a closed list to `\w+` so common
  synonyms (explores / focuses / investigates / ...) no longer slip past.

These tests pin the v3 inversion AND the v3 §1-grading behaviour so any
future regression to v2 logic (reward-vocab or skip-§1) fails loud before
the script ships against post-v3 smoke output.
"""

from __future__ import annotations

from scripts.p2_e_compliance import e1_section_opening_recap


def _article(opener: str) -> str:
    """Wrap a section opener in a two-section article. Under v3 BOTH
    sections are graded — sections[0] (this article opener) is intentionally
    written as a clean, prose-leading, no-forbidden-token sentence so it
    always passes, isolating the test's signal to the second section's
    grade. Tests that specifically exercise §1 grading construct their own
    articles inline."""
    return (
        "## 1 Article opener\n\n"
        "The franchise establishes four canonical pillars across the corpus, "
        "anchored in 1986-1990 publication evidence.\n\n"
        "## 2 Section under test\n\n"
        f"{opener}\n"
    )


def test_v3_correct_definition_opener_is_compliant():
    """A definition-style opener (one of v3's four acceptable templates)
    must pass BOTH gates: prose-before-data + no forbidden tokens. Both
    sections in the fixture are clean v3-correct openers so n_compliant
    equals n_sections."""
    out = e1_section_opening_recap(
        _article(
            "The Cloth is the franchise's defining invention, and its "
            "conceptual genesis is unusually well documented across the "
            "1986-1990 publication run.\n\n"
            "| Aspect | Detail |\n|---|---|\n| Origin | Kurumada |\n"
        )
    )
    assert out["applicable"] is True
    # n_sections counts ALL sections under v3 (§1 is graded too).
    assert out["n_sections"] == 2
    assert out["n_compliant"] == 2, out
    assert out["rate"] == 1.0


def test_v3_correct_quantified_claim_opener_is_compliant():
    """Quantified-claim openings ('Topic-noun verb number/anchor...') must
    pass — they were one of v3's named acceptable templates."""
    out = e1_section_opening_recap(
        _article(
            "Within Athena's army, the eighty-eight Cloths are stratified "
            "into three principal ranks: Bronze, Silver, and Gold.\n"
        )
    )
    assert out["n_compliant"] == 2, out


def test_v3_forbidden_building_on_opener_fails_semantic_gate():
    """'Building on §1...' was REWARDED by v2 and is FORBIDDEN by v3.
    Under v3 it must fail the semantic gate. Structural passes (prose
    lead) so the bad section lands in the n_only_structural bucket;
    the clean §1 opener passes both gates."""
    out = e1_section_opening_recap(
        _article(
            "Building on the framework established in §1, this section "
            "examines the stratification of Cloths across the canon.\n"
        )
    )
    assert out["n_compliant"] == 1
    assert out["n_only_structural_ok"] == 1, out
    assert out["n_only_semantic_ok"] == 0


def test_v3_forbidden_meta_subject_opener_fails_semantic_gate():
    """'This section examines...' is a v3-forbidden meta-subject opener
    (the opening sentence's subject is the document itself, not the topic)."""
    out = e1_section_opening_recap(_article("This section examines the Cosmo-tier hierarchy in detail.\n"))
    assert out["n_compliant"] == 1
    assert out["n_only_structural_ok"] == 1, out


def test_v3_meta_subject_regex_catches_synonyms_outside_v2_verb_list():
    """v3 round-3: the meta-subject verb slot uses `\\w+` so common verbs
    not in the original closed list (explores / focuses / investigates /
    provides / highlights / offers / summarises) still fail the gate.
    Each variant gets a fresh article so the assertions stay independent."""
    for verb in (
        "explores",
        "focuses on",
        "investigates",
        "provides",
        "highlights",
        "offers",
        "summarises",
        "summarizes",
        "explains",
    ):
        out = e1_section_opening_recap(_article(f"This section {verb} the Cosmo-tier hierarchy in detail.\n"))
        assert out["n_compliant"] == 1, (verb, out)
        assert out["n_only_structural_ok"] == 1, (verb, out)


def test_v3_meta_subject_regex_does_not_match_possessive():
    """'This section's four-pillar framework is...' is NOT a meta-subject
    opener — the topic noun ('four-pillar framework') is the actual subject.
    The `\\s+\\w+` requirement ensures the apostrophe-s case doesn't
    falsely match."""
    out = e1_section_opening_recap(
        _article(
            "This section's four-pillar framework is grounded in the "
            "1986-1990 publication evidence and held stable across arcs.\n"
        )
    )
    # Both sections should pass: §1 is clean and §2's possessive doesn't
    # trip the meta-subject pattern.
    assert out["n_compliant"] == 2, out


def test_v3_forbidden_section_n_ref_in_opener_fails_semantic_gate():
    """Any §N reference in the OPENING sentence is v3-forbidden, even
    when paired with a named artefact. Body §N refs remain allowed —
    that's why the semantic check is windowed to the opener only."""
    out = e1_section_opening_recap(
        _article(
            "Under the rubric from §3, the speed taxonomy resolves into "
            "three tiers separated by canon-stated Mach bands.\n"
        )
    )
    assert out["n_compliant"] == 1
    assert out["n_only_structural_ok"] == 1, out


def test_v3_body_text_section_n_ref_does_not_taint_compliant_opener():
    """A v3-correct opener followed by a body §N reference must still
    pass — the v3 rule bans §N refs in openings, not in body text.
    This is the test that would have failed under a naive 'search the
    whole body' implementation."""
    out = e1_section_opening_recap(
        _article(
            "Kurumada repeatedly grounded his metaphysics in concrete "
            "velocity claims, producing a quantitative ladder.\n\n"
            "The complete list is enumerated in §3's named-artefact "
            "framework, which we revisit below for cross-reference.\n"
        )
    )
    assert out["n_compliant"] == 2, out


def test_table_first_opener_fails_structural_gate():
    """Table-first openings were the v1 failure mode on id=91 (0/50
    compliance). v3 preserves the structural gate unchanged — section
    must open with prose before any data block."""
    out = e1_section_opening_recap(_article("| Rank | Count |\n|---|---|\n| Gold | 12 |\n| Silver | 24 |\n"))
    assert out["n_compliant"] == 1
    # Semantic gate passes for §2 (no forbidden vocab in the opener —
    # there's no prose at all), so this lands in n_only_semantic_ok.
    assert out["n_only_semantic_ok"] == 1, out


def test_zh_meta_subject_opener_fails_semantic_gate():
    """ZH equivalents of meta-subject phrasings are also v3-forbidden;
    the regex must catch '本节考察' / '本章介绍' etc."""
    out = e1_section_opening_recap(_article("本节考察青铜圣斗士的圣衣分类与历史演变。\n"))
    assert out["n_compliant"] == 1
    assert out["n_only_structural_ok"] == 1, out


def test_zh_meta_subject_regex_catches_synonyms_outside_v2_verb_list():
    """v3 round-3 extended the ZH verb list. Synonyms not in the original
    set (探讨 / 涉及 / 涵盖 / 关注 / 聚焦 / 阐释 / 旨在) must still fail."""
    for verb in ("探讨", "涉及", "涵盖", "关注", "聚焦", "阐释", "旨在"):
        out = e1_section_opening_recap(_article(f"本节{verb}圣斗士速度等级的演变。\n"))
        assert out["n_compliant"] == 1, (verb, out)
        assert out["n_only_structural_ok"] == 1, (verb, out)


def test_v3_grades_section_zero_meta_subject_opener_as_non_compliant():
    """§1 grading (v3 round-3, gap from Greptile review): the article
    opener is no longer exempt from FORBIDDEN antipatterns. An article
    that opens with 'This report examines...' must FAIL the gate even
    though it's the first section — pre-fix the script silently skipped
    sections[0] and reported this as compliant by default."""
    article = (
        "## 1 Article opener\n\n"
        "This report examines the franchise's Cosmo-tier hierarchy across "
        "the 1986-1990 canon.\n\n"
        "## 2 Second section\n\n"
        "The Bronze rank originated in the Sanctuary arc, where Kurumada "
        "first formalised the tier system.\n"
    )
    out = e1_section_opening_recap(article)
    # §1 fails semantic (meta-subject), §2 passes both gates.
    assert out["n_sections"] == 2, out
    assert out["n_compliant"] == 1, out
    assert out["n_only_structural_ok"] == 1, out


def test_v3_grades_section_zero_section_n_opener_as_non_compliant():
    """§1 can't legitimately contain §N refs anyway (no earlier section
    to reference), but the gate must still catch them — a writer that
    emits '§1 introduces the framework' as the literal opener should
    fail loud, not pass by skip."""
    article = (
        "## 1 Article opener\n\n"
        "§1 introduces the four-pillar framework that anchors the rest "
        "of the analysis.\n\n"
        "## 2 Second section\n\n"
        "The Bronze rank originated in the Sanctuary arc.\n"
    )
    out = e1_section_opening_recap(article)
    assert out["n_compliant"] == 1, out
    assert out["n_only_structural_ok"] == 1, out


def test_v3_grades_section_zero_clean_opener_as_compliant():
    """The positive case: a v3-correct §1 opener (subject-noun-first,
    no forbidden tokens, prose-before-data) must pass both gates."""
    article = (
        "## 1 Article opener\n\n"
        "The franchise's Cosmo-tier hierarchy is one of the most carefully "
        "documented power systems in 1980s shonen manga.\n"
    )
    out = e1_section_opening_recap(article)
    assert out["n_sections"] == 1
    assert out["n_compliant"] == 1, out


def test_gate_applicable_when_article_has_any_sections():
    """Single-section articles are still gradeable under v3 — that single
    section is sections[0] and the §1 grading rule applies."""
    out = e1_section_opening_recap(
        "## 1 Only section\n\n"
        "The Bronze rank originated in the Sanctuary arc, where Kurumada "
        "first formalised the tier system.\n"
    )
    assert out["applicable"] is True
    assert out["n_sections"] == 1
    assert out["n_compliant"] == 1, out


def test_gate_not_applicable_on_empty_article():
    """An article with no parseable sections is non-applicable."""
    out = e1_section_opening_recap("")
    assert out["applicable"] is False
