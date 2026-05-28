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


def test_cleaning_resistant_rule_has_citation_density_ceiling():
    """P3b-opt2: rule 3 must state a per-1k density CEILING (not just the
    mandatory-insertion framing) so the writer stops over-citing (~19.5/1k
    measured vs Qianfan ~6.3/1k). The ~326-marker figure is reframed as a
    ceiling, not a floor to maximize."""
    rule = writing_rules.CLEANING_RESISTANT_RULE
    assert "TARGET DENSITY" in rule
    assert "per 1,000 words" in rule
    assert "Do NOT" in rule and "8/1k" in rule
    assert "citation salad" in rule.lower() or "salad" in rule.lower()


def test_writer_section_user_prompt_carries_citation_contract():
    """The writer.write_section user-prompt evidence block was previously
    'cite by inline source NAME; you may also add a numeric [n]' — silent
    on `[^X]` footnotes and ACTIVELY steering the writer to name-only
    citations. Pin the post-2026-05-26 CITATION CONTRACT block that
    makes `[^sid-N]` footnotes mandatory in the user prompt (where the
    writer's attention actually lands), not just buried in the system
    prompt's CLEANING_RESISTANT_RULE.

    Wave 2 §2.1c (2026-05-26) restructured the contract to address the
    post-Wave-1 smoke failure mode (writer emitted clean inline markers
    but 0 def lines, dropping every citation). Pin both the
    long-standing PR #27 CITATION CONTRACT presence + the Wave 2
    structural-numbering and def-emission additions."""
    src = inspect.getsource(writer.write_section)
    assert "CITATION CONTRACT" in src, (
        "writer.write_section user prompt must include the CITATION "
        "CONTRACT block — the post-2026-05-26 smoke fix that makes "
        "[^sid-N] footnotes mandatory at the user-prompt layer."
    )
    # The Qianfan reference must be there in some form — gives the
    # writer the empirical anchor (Wave 1 smoke distance 1.966 or
    # earlier Qianfan ~7× reuse density).
    assert "Qianfan" in src, "CITATION CONTRACT must reference Qianfan empirical anchor."
    # The old name-only steering must be GONE — it was the active
    # countermand to the system prompt's footnote rule.
    assert "cite by inline source NAME" not in src, (
        "The pre-fix 'cite by inline source NAME' phrase must be gone — "
        "it steered writers AWAY from footnotes in the smoke."
    )


def test_writer_section_citation_contract_forbids_missing_defs():
    """Wave 2 §2.1c: the post-Wave-1 smoke surfaced the writer emitting
    clean inline markers but 0 `[^X]: source` def lines, causing every
    citation to be stripped as orphan. The strengthened contract must
    explicitly forbid this failure mode with a worked example and the
    downstream consequence (orphans stripped, citation surface gone)."""
    src = inspect.getsource(writer.write_section)
    assert "FORBIDDEN" in src, (
        "CITATION CONTRACT must include an explicit FORBIDDEN section "
        "for the missing-def-lines failure mode (Wave 2 §2.1c)."
    )
    # The consequence chain must be spelled out so the writer knows what
    # happens when defs are skipped.
    src_lower = src.lower()
    assert "orphan" in src_lower or "strip" in src_lower, (
        "FORBIDDEN section must spell out the orphan-stripping consequence "
        "so the writer doesn't silently skip def emission again."
    )


def test_writer_section_evidence_atoms_pre_assigned_markers():
    """Wave 2 §2.1c: each evidence atom passed to the writer must carry
    its pre-assigned `[^{sid}-N]` marker in the rendered ev_view so the
    writer can't pick a wrong number (the post-process synthesis safety
    net uses the marker-N ↔ atom-N mapping to recover missing defs)."""
    src = inspect.getsource(writer.write_section)
    # The ev_view construction must include a `marker` field for each atom.
    assert '"marker"' in src or "marker=" in src or "{sid}-{i" in src, (
        "ev_view must pre-assign each atom its [^{sid}-N] marker so the "
        "writer can't mismatch (Wave 2 §2.1c structural fix)."
    )


def test_reuse_guidance_uses_scoped_form_consistently():
    """Greptile PR #27 follow-up (2026-05-26): the REUSE bullets in BOTH
    the user-prompt CITATION CONTRACT and the system-prompt
    CLEANING_RESISTANT_RULE previously used bare `[^N]` as the example —
    while every other bullet around them used the scoped `[^{sid}-N]` /
    `[^{section_id}-N]` form. A writer LLM anchoring on the bare example
    would emit bare markers for repeated citations and have them stripped
    as orphans by footnote_normalize — silently dropping exactly the
    citations the PR was trying to preserve.

    Wave 2 §2.1c restructured the user-prompt contract; pin the scoped
    form on the SYSTEM prompt side (which still uses the PR #27
    phrasing) and the structural-numbering pattern on the user side."""
    src = inspect.getsource(writer.write_section)
    rule = writing_rules.CLEANING_RESISTANT_RULE

    # User prompt: REUSE must use the scoped `[^{sid}-N]` form (Wave 2
    # §2.1c made this structural via the pre-assigned `marker` field on
    # each atom). Bare `[^N]` examples would anchor the LLM toward
    # unscoped reused markers that footnote_normalize strips as orphans.
    assert "{sid}-N" in src or "[^{sid}-" in src, (
        "writer.write_section REUSE / contract must use the section-scoped "
        "`[^{sid}-N]` form — a bare `[^N]` example would anchor the LLM "
        "toward unscoped reused markers that footnote_normalize strips "
        "as orphans."
    )

    # System prompt: same requirement, with `{section_id}` template var.
    assert "reuses each `[^{section_id}-N]`" in rule, (
        "CLEANING_RESISTANT_RULE rule 3 REUSE clause must use the "
        "section-scoped `[^{section_id}-N]` form in its example — "
        "consistency with the rest of the rule prevents the LLM from "
        "inferring bare `[^N]` is acceptable for reused markers."
    )

    # Explicit anti-bare guidance on the system-prompt side.
    assert "stripped as orphans" in rule, (
        "CLEANING_RESISTANT_RULE REUSE bullet must spell out the orphan-"
        "stripping consequence so the LLM doesn't infer bare `[^N]` is "
        "tolerated."
    )


def test_length_ceiling_docstring_does_not_hardcode_stale_multiplier():
    """Greptile PR #27 follow-up (2026-05-26): the `length_ceiling`
    docstring previously hard-coded "Bumped 2.2x post-#1" and told
    callers to compute "length_ceiling(domain) / 2.2" to recover the W9
    baseline. When `_LENGTH_TARGET_MULT` jumped 2.2 → 4.0 the docstring's
    advice silently went stale (would return 1.8× too high a value).

    Fix: docstring references the constant rather than hardcoding the
    number, so future multiplier bumps stay in sync automatically."""
    doc = writing_rules.length_ceiling.__doc__ or ""
    # The stale hard-coded "2.2" must be gone.
    assert "/ 2.2" not in doc and "2.2x" not in doc and "2.2×" not in doc, (
        "length_ceiling docstring still references the stale 2.2× "
        "multiplier — must be updated to reference _LENGTH_TARGET_MULT "
        "by name so future calibration bumps don't silently invalidate "
        "the docstring's caller advice."
    )
    # Must reference the constant by name so the advice stays current.
    assert "_LENGTH_TARGET_MULT" in doc, (
        "length_ceiling docstring must reference the `_LENGTH_TARGET_MULT` "
        "constant by name so callers and the docstring stay in sync."
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
