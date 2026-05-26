"""Tests pinning the post-2026-05-26-smoke quality changes for Qianfan parity.

The 2026-05-26 CAPEL smoke for id=56 surfaced two structural gaps vs the
#1-leaderboard Qianfan corpus:
  1. **Footnote silence** — writer emitted 14 `[^X]:` definition lines but
     ZERO inline `[^X]` markers, so `footnote_normalize` dropped all 14 as
     unused and the article shipped with no References block. Qianfan id=56
     has 326 inline markers + 45 definitions (heavy reuse).
  2. **Length gap** — article hit 18,850 words; Qianfan id=56 is 80,243
     words (4.26× short). Up +33% from W9 (14,118 words) but the
     length-ceiling 2.2× multiplier wasn't enough.

Fixes shipped:
  - writer.py CITATION CONTRACT block making `[^sid-N]` footnotes
    MANDATORY (not "encouraged"), URL optional, reuse-friendly,
    explicitly Qianfan-aligned in the user-prompt evidence block.
  - writing_rules.CLEANING_RESISTANT_RULE rule 3 rewritten: footnotes
    MANDATORY (not URL-conditional), academic-citation format, ~7× reuse
    pattern documented.
  - writing_rules._LENGTH_TARGET_MULT 2.2 → 4.0 to push target word
    count up ~2× (~36k words/article target vs prior ~20k).

These tests pin the changes so a future refactor that silently reverts
any of them is caught loudly.
"""

import inspect

from deep_research import writing_rules
from deep_research.pipeline import writer


def test_length_target_multiplier_in_qianfan_aligned_range():
    """`_LENGTH_TARGET_MULT` controls the per-domain word target by
    multiplying the historical W9-era catalog medians. Pin in the
    post-2026-05-26-smoke calibrated band.

    Lower bound 3.0: anything below the smoke's empirical 2.2 (which
    produced 18.8k for id=56 vs Qianfan's 80k) is a regression toward
    the pre-fix length gap.

    Upper bound 6.0: higher multipliers risk the writer filling space
    with repetitive content when the architect outline depth (8-12 H2 ×
    3-6 H3 × 2-4 H4) doesn't keep pace. Length and outline depth need
    to grow together; runaway multiplier without architect compliance
    produces filler that the RACE Insight judge penalises."""
    assert 3.0 <= writing_rules._LENGTH_TARGET_MULT <= 6.0, (
        f"_LENGTH_TARGET_MULT={writing_rules._LENGTH_TARGET_MULT} outside "
        f"the post-2026-05-26-smoke calibrated band [3.0, 6.0]. The "
        f"2.2× value pre-smoke produced 18.8k-word articles for id=56 "
        f"vs Qianfan's 80k (4.26× short); the bump to 4.0× was the "
        f"deliberate fix."
    )


def test_cleaning_resistant_rule_makes_footnotes_mandatory():
    """Rule 3 of CLEANING_RESISTANT_RULE was 'ENCOURAGED when an evidence
    atom has a non-empty url field' pre-2026-05-26. That gating produced
    0 footnotes in the smoke because:
      (a) the writer treated 'ENCOURAGED' as optional and skipped,
      (b) the URL-conditional gating excluded all academic-citation
          evidence (most of our evidence has source_name + text but
          empty url field for paywalled/PDF sources).

    Rule rewritten 2026-05-26 to MANDATORY with URL optional. Pin both
    the MANDATORY framing and the URL-optional clause so a future
    refactor that re-narrows the rule is caught."""
    rule = writing_rules.CLEANING_RESISTANT_RULE
    assert "MANDATORY" in rule, (
        "CLEANING_RESISTANT_RULE rule 3 must say MANDATORY (the smoke "
        "proved 'ENCOURAGED' = writer skips footnotes entirely)."
    )
    assert "URL is" in rule and "OPTIONAL" in rule, (
        "CLEANING_RESISTANT_RULE must mark URL as OPTIONAL — Qianfan's "
        "326-footnote articles use academic citations without URLs."
    )
    # And the Qianfan-aligned reuse guidance must be present.
    assert "REUSE markers" in rule, (
        "CLEANING_RESISTANT_RULE must document the reuse pattern — "
        "Qianfan reuses each [^N] ~7× on average; without this guidance "
        "the writer invents a new number per sentence and the inline-to-"
        "definition ratio collapses."
    )


def test_writer_section_user_prompt_carries_citation_contract():
    """The writer.write_section user-prompt evidence block was previously
    'cite by inline source NAME; you may also add a numeric [n]' — silent
    on `[^X]` footnotes and ACTIVELY steering the writer to name-only
    citations. Pin the post-2026-05-26 CITATION CONTRACT block that
    makes `[^sid-N]` footnotes mandatory in the user prompt (where the
    writer's attention actually lands), not just buried in the system
    prompt's CLEANING_RESISTANT_RULE."""
    src = inspect.getsource(writer.write_section)
    assert "CITATION CONTRACT" in src, (
        "writer.write_section user prompt must include the CITATION "
        "CONTRACT block — the post-2026-05-26 smoke fix that makes "
        "[^sid-N] footnotes mandatory at the user-prompt layer."
    )
    # And the Qianfan parity reference must be in the prompt — gives the
    # writer the empirical target (326 markers) that motivated the change.
    assert "Qianfan" in src and "326" in src, (
        "CITATION CONTRACT must reference Qianfan's 326-marker target so the writer knows the empirical bar."
    )
    # The old name-only steering must be GONE — it was the active
    # countermand to the system prompt's footnote rule.
    assert "cite by inline source NAME" not in src, (
        "The pre-fix 'cite by inline source NAME' phrase must be gone — "
        "it steered writers AWAY from footnotes in the smoke."
    )


def test_writer_section_user_prompt_uses_section_id_template():
    """The CITATION CONTRACT must use `[^{sid}-N]` form (section-scoped
    via the actual section id at write time), not bare `[^N]`.
    `footnote_normalize.py` parses section-scoped tokens to avoid
    cross-section marker collisions; bare `[^N]` markers from
    independent section writers would collide and get stripped."""
    src = inspect.getsource(writer.write_section)
    # The f-string template should reference {sid} inside footnote markers
    # so each section gets its own scoped numbering.
    assert "{sid}-N" in src or "{sid}-3" in src, (
        "CITATION CONTRACT must use section-scoped `[^{sid}-N]` template "
        "so footnote_normalize can collide-safely renumber. Bare [^N] "
        "markers would be stripped as orphans."
    )
