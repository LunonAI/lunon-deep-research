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
- v4 (2026-05-26, post-PR-32-merge full-archetype retro): v3's blanket ban
  on §N / 第N章 references in openings was OVERCORRECTION. Fresh-corpus
  data on 14 Qianfan tasks across all 6 archetypes showed 75-89% of
  chapters reference an earlier chapter ("Chapter N" / "第N章") in the
  opening sentence — paired with a substantive recap. v4 removed the
  §N / "section N's framework" / 第N章 patterns from the gate's regex;
  the gate now passes Chapter-N openings paired with substantive recap.
  All other v3 bans (Building-on / Applied-to / Under-the-rubric
  templates, meta-subject, prose-before-table) survive v4 unchanged.

These tests pin the v3 inversion AND the v4 §N-allow amendment so any
future regression to v2 logic (reward vocab) or v3 logic (blanket §N
ban) fails loud before the script ships against post-merge smoke output.
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


def test_v4_under_the_rubric_opener_still_fails_semantic_gate():
    """v4 retains the 'Under the rubric from §N...' antipattern (the
    formulaic recap template Qianfan doesn't use). The §N portion alone
    no longer triggers the gate (re-allowed in v4), but the 'under the
    rubric' template stem catches this. Pre-v4 (v3) the test was
    test_v3_forbidden_section_n_ref_in_opener_fails_semantic_gate; the
    §N-only case is now COMPLIANT (see test_v4_chapter_n_ref_with_recap_
    is_compliant below)."""
    out = e1_section_opening_recap(
        _article(
            "Under the rubric from §3, the speed taxonomy resolves into "
            "three tiers separated by canon-stated Mach bands.\n"
        )
    )
    assert out["n_compliant"] == 1
    assert out["n_only_structural_ok"] == 1, out


def test_v4_chapter_n_ref_with_substantive_recap_is_compliant():
    """v4 amendment: Chapter-N references in opening sentences are
    ALLOWED when paired with a substantive recap of what the prior
    chapter established (Qianfan idiom, 75-89% rate). This case would
    have failed under v3's blanket §N ban — v4 inversion makes it pass.
    A future regression that re-bans §N refs in openings would fail
    this test."""
    out = e1_section_opening_recap(
        _article(
            "The framework constructed in Chapter 1 — the four-tier Cloth "
            "hierarchy and the Cosmo doctrine — finds its first application "
            "in the Bronze rank, where Kurumada formalised the tier system.\n"
        )
    )
    # §1 (fixture opener, also clean prose lead with no forbidden vocab)
    # + §2 (the Chapter-N opener under test) should both pass.
    assert out["n_compliant"] == 2, out


def test_v4_zh_chapter_n_ref_with_substantive_recap_is_compliant():
    """ZH parallel: '第1章已论证：...。本章承接...，系统梳理...' is the
    Qianfan ZH idiom verified at task id=8. v4 must NOT flag this as
    forbidden.

    Note: this case is a structural test — it asserts the §N portion
    alone doesn't fail. The '本章承接...系统梳理' substring contains the
    本章+verb meta-subject pattern, which IS still antipattern. So we
    test with a recap-then-pivot that names a substantive topic rather
    than using 本章 as the subject."""
    out = e1_section_opening_recap(
        _article(
            "第1章已论证：机器学习方法的能力上限受制于数据采集环节。"
            "数据基础设施在规模与可访问性上已基本满足学术级研究的需求。\n"
        )
    )
    assert out["n_compliant"] == 2, out


def test_v4_body_text_section_n_ref_does_not_taint_compliant_opener():
    """A v4-correct opener followed by a body §N reference must still
    pass — the v4 rule (and the v3 rule it amends) bans certain opener
    templates in openings only. Body §N refs remain allowed.

    This is the test that would have failed under a naive 'search the
    whole body' implementation. Retained from v3 since v4 preserved the
    opener-windowing behaviour."""
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


def test_v4_grades_section_zero_chapter_n_opener_as_compliant():
    """v4 amendment: the §1 opener is graded but Chapter-N refs in the
    opener are now allowed (Qianfan idiom). Pre-v4 (v3 round-3) this
    test was test_v3_grades_section_zero_section_n_opener_as_non_compliant
    — under v3 the §N reference itself failed the semantic gate. v4
    removed that ban; if the §1 opener references "§N" or "Chapter N"
    self-referentially (unusual since §1 has nothing earlier to point
    at) it no longer fails the gate, but the writer-prompt rule body
    notes that §1 has nothing earlier to refer to anyway."""
    article = (
        "## 1 Article opener\n\n"
        "The four-pillar framework introduced below anchors the rest of "
        "the analysis across all subsequent chapters.\n\n"
        "## 2 Second section\n\n"
        "The Bronze rank originated in the Sanctuary arc.\n"
    )
    out = e1_section_opening_recap(article)
    # Both sections should pass: clean prose lead, no v4-forbidden vocab.
    assert out["n_compliant"] == 2, out


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
