"""Unit tests for the E1 section-opening compliance gate.

History:
- v2 semantic gate REWARDED "Building on §N..." / "this section examines..."
  vocabulary because the writer-prompt rule at that time told the writer to
  produce framework-recap openings.
- v3 (2026-05-26, gap-map §12.A) flipped the writer-prompt rule: the same
  vocabulary is now an antipattern banned by `_SECTION_OPENING_PROSE_LEAD_RULE`
  in `deep_research/writing_rules.py`. The compliance gate had to invert in
  lockstep — otherwise post-merge smoke runs would report v3-correct openers
  as non-compliant and v3-forbidden openers as compliant (backwards).

These tests pin the v3 inversion so any future revert to v2 reward-logic
fails loud before the script ships against post-v3 smoke output.
"""

from __future__ import annotations

from scripts.p2_e_compliance import e1_section_opening_recap


def _article(opener: str) -> str:
    """Wrap a single section opener in a two-section article. The first
    section is the article opener (skipped by the gate); the second is
    the section being graded."""
    return (
        "## 1 Article opener\n\n"
        "The framework establishes four pillars across the corpus.\n\n"
        "## 2 Section under test\n\n"
        f"{opener}\n"
    )


def test_v3_correct_definition_opener_is_compliant():
    """A definition-style opener (one of v3's four acceptable templates)
    must pass BOTH gates: prose-before-data + no forbidden tokens."""
    out = e1_section_opening_recap(
        _article(
            "The Cloth is the franchise's defining invention, and its "
            "conceptual genesis is unusually well documented across the "
            "1986-1990 publication run.\n\n"
            "| Aspect | Detail |\n|---|---|\n| Origin | Kurumada |\n"
        )
    )
    assert out["applicable"] is True
    # n_sections in the result counts CANDIDATES (sections[1:]) — the
    # article opener at sections[0] is skipped because the §1 exemption
    # means it doesn't get graded.
    assert out["n_sections"] == 1
    assert out["n_compliant"] == 1, out
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
    assert out["n_compliant"] == 1, out


def test_v3_forbidden_building_on_opener_fails_semantic_gate():
    """'Building on §1...' was REWARDED by v2 and is FORBIDDEN by v3.
    Under v3 it must fail the semantic gate. Structural passes (prose
    lead) so it lands in the n_only_structural bucket."""
    out = e1_section_opening_recap(
        _article(
            "Building on the framework established in §1, this section "
            "examines the stratification of Cloths across the canon.\n"
        )
    )
    assert out["n_compliant"] == 0
    assert out["n_only_structural_ok"] == 1, out
    assert out["n_only_semantic_ok"] == 0


def test_v3_forbidden_meta_subject_opener_fails_semantic_gate():
    """'This section examines...' is a v3-forbidden meta-subject opener
    (the opening sentence's subject is the document itself, not the topic)."""
    out = e1_section_opening_recap(_article("This section examines the Cosmo-tier hierarchy in detail.\n"))
    assert out["n_compliant"] == 0
    assert out["n_only_structural_ok"] == 1, out


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
    assert out["n_compliant"] == 0
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
    assert out["n_compliant"] == 1, out


def test_table_first_opener_fails_structural_gate():
    """Table-first openings were the v1 failure mode on id=91 (0/50
    compliance). v3 preserves the structural gate unchanged — section
    must open with prose before any data block."""
    out = e1_section_opening_recap(_article("| Rank | Count |\n|---|---|\n| Gold | 12 |\n| Silver | 24 |\n"))
    assert out["n_compliant"] == 0
    # Semantic gate passes (no forbidden vocab in the opener — there's no
    # prose at all), so this lands in n_only_semantic_ok.
    assert out["n_only_semantic_ok"] == 1, out


def test_zh_meta_subject_opener_fails_semantic_gate():
    """ZH equivalents of meta-subject phrasings are also v3-forbidden;
    the regex must catch '本节考察' / '本章介绍' etc."""
    out = e1_section_opening_recap(_article("本节考察青铜圣斗士的圣衣分类与历史演变。\n"))
    assert out["n_compliant"] == 0
    assert out["n_only_structural_ok"] == 1, out


def test_gate_applicable_only_when_article_has_multiple_sections():
    """Articles with <2 sections have no section to grade (sections[0]
    is the article opener and is always skipped)."""
    out = e1_section_opening_recap("## 1 Only section\n\nProse only.\n")
    assert out["applicable"] is False
