"""Post-hoc refiner (p1-checklist items 20, 26; technique 14b — highest-ROI).

GPT-5.5 SINGLE pass, adapted from AI-Q rewrite_report.py REWRITE_PROMPT (10
numbered expansion instructions). Archetype-aware. min-ratio 0.70 guard (revert
to the input if the rewrite is < 70% of input length). Receives draft + per-
section criteria scores + failing-criterion rationales, NO raw evidence
(item 26 context boundary). De-hedge pass folded in (judge penalizes hedging
~25.6% at equal content, v4 §2.9).
"""

import re

from .. import llm
from .. import writing_rules as wr
from ..text_metrics import approx_tokens

# Adapted from AI-Q REWRITE_PROMPT (aiq_teardown.md §6) — generalized, NOT
# overfit to the 100 tasks (v4 §4.5 repro-risk note).
_SYSTEM = (
    """You are an expert research-report editor. Your PRIMARY job (per \
the W9 judge analysis: we lose 81% of Readability criteria) is to make the \
article CONCISE, STRUCTURED, and FREE OF CROSS-SECTION REPETITION. The judge \
explicitly cited "excessive length", "repetitive across sections", "inconsistent \
section numbering", and "duplicated headings" in 65% of the worst losses.

APPLY IN ORDER OF PRIORITY:

A. NUMBERING CONSISTENCY (HARD): use ONE numbering scheme throughout
   (1, 1.1, 1.1.1). NEVER duplicate numbers. NEVER skip (no 1.4→5→6→1.7).
   If numbering is broken, RENUMBER the whole document in place.

B. CROSS-SECTION DEDUPLICATION (HARD): if a driver, caveat, mechanism, or
   summary claim appears in multiple sections, KEEP IT IN THE SECTION WHERE
   IT BELONGS and DELETE the duplicates. Reference briefly ('as covered in §2')
   if needed but never restate.

C. TRIM SCAFFOLDING + CAVEATS: cut "In this section we will…", "It is worth
   noting", "as discussed above", over-hedged disclaimers, and methodological
   meta-commentary. Keep the substance, kill the filler.

D. LENGTH DISCIPLINE: bias toward SHORTER, denser prose. Do NOT add length
   for its own sake. If a paragraph can be cut in half without losing
   information, cut it.

E. SUBSTANCE PRESERVATION (don't break what works): keep all source
   attributions; preserve quantitative claims, named entities, causal chains
   that are unique to one section; do NOT remove factual content.

F. THEN polish: quantify evaluative claims, deepen entity detail WHERE it
   doesn't already exist, de-hedge where evidence in the text supports a
   direct statement.

Length may decrease 10-20% — that's GOOD, not a bug. Preserve the position-1
opening verbatim. Obey the source-attribution rule below.

# History: GEPA cycle 1 (universal pruning) and cycle 2 (cross-section dedup +
# numbering) both reverted on tiny dev slices, but W9 actual judge analysis
# (n=2238 criteria) revealed the Readability problem was 5× larger than
# we'd estimated and is the dominant gap. Cycle 3 (this version) leans harder
# into the actual judge-cited fixes with conciseness reframed as primary, not
# secondary to growth. Validated alongside writer-side changes.

"""
    + wr.CLEANING_RESISTANT_RULE
)

# A whole-article rewrite must RETURN the whole article. The min-ratio<0.70
# revert floor below means the smallest non-reverted output is 0.70×the draft;
# if even that exceeds the output budget the model can only truncate/summarize
# and the pass is a GUARANTEED revert — but still bills the full input + ~3.5min
# (id=91 smoke: 65k words ≈ 97k out-tokens → paid $0.96 + 207s for a no-op).
# Skip when 0.70×draft can't fit, so we only skip genuinely-doomed calls and
# never one that could prune-to-fit. (Section-wise or deterministic dedupe is
# the path to actually deduping reference-length articles — deferred, evidence-gated.)
_MAX_OUT_TOKENS = 32000
_REVERT_RATIO = 0.70
_TOK = 4  # legacy chars-per-token heuristic (non-CJK rate); test-only — the skip
# estimate now uses the CJK-aware text_metrics.approx_tokens (see below).


def refine(draft: str, *, archetype: str, language: str, section_scores=None, failing_rationales=None) -> dict:
    # round 10 (2026-06-03): use the CJK-aware estimator, not len//4. The old
    # `len(draft)//4` UNDER-counted CJK ~2.6x, so a ~110k-char ZH draft estimated
    # ~27.5k tok and PASSED the skip check → the refiner RAN (billed input + ~3.5min)
    # then REVERTED at the 0.70 floor (can't regenerate ~68k CJK tokens within the
    # 32000 output cap) — a paid no-op on ~half the benchmark (every long ZH task).
    # approx_tokens gives ~68k for the same draft → 68k×0.7=47.8k > 32000 → it now
    # SKIPS honestly (free, no wasted call). Semantically correct too: the refiner
    # is a PRUNING pass we do NOT want on an already-under-length ZH article.
    est_out_tokens = approx_tokens(draft)
    if est_out_tokens * _REVERT_RATIO > _MAX_OUT_TOKENS:
        return {
            "article": draft,
            "applied": False,
            "ratio": 1.0,
            "reason": f"skip: draft ~{est_out_tokens}tok exceeds rewrite output budget {_MAX_OUT_TOKENS}",
        }
    emphasis = wr.refiner_emphasis(archetype)
    feedback = ""
    if section_scores:
        feedback += f"\n\nPER-SECTION CRITERIA SCORES:\n{section_scores}"
    if failing_rationales:
        feedback += (
            "\n\nFAILING-CRITERION RATIONALES (fix these specifically, "
            f"no raw evidence is provided — improve from the feedback):"
            f"\n{failing_rationales}"
        )
    user = (
        f"LANGUAGE: {language}\nARCHETYPE EMPHASIS: {emphasis}\n"
        f"{feedback}\n\nREPORT TO ENHANCE (return ONLY the full enhanced "
        f"report, same language, no preamble):\n\n{draft}"
    )

    # Refiner is ENHANCEMENT, not load-bearing — same fail-soft pattern as
    # zh_writer_pass. If gpt-5.5 server-side takes >timeout (5% observed
    # rate, max seen 854s), ship the pre-refiner draft instead of crashing
    # the whole task. The draft already passed grounding + inner_loop.
    # Timeout raised 600→750s to cover p95 of observed durations.
    # Retries reduced 3→2 so worst-case wasted time is 1500s not 1800s.
    try:
        out = llm.call(
            "refiner",
            user,
            system=_SYSTEM,
            max_tokens=_MAX_OUT_TOKENS,
            effort="medium",
            seed=None,
            note="refiner",
            timeout=750,
            max_retries=2,
        )
    except Exception as e:  # noqa: BLE001
        return {
            "article": draft,
            "applied": False,
            "ratio": 1.0,
            "reason": f"refiner-error (raw shipped): {type(e).__name__}: {str(e)[:80]}",
        }
    out = out.strip()
    in_len, out_len = len(draft), len(out)
    ratio = out_len / max(1, in_len)
    # GEPA cycle-3 (W9-judge-evidence-driven): min-ratio relaxed to 0.70.
    # W9 judge analysis (n=2238 criteria, 81% Readability loss rate, 7/10
    # worst losses cite "excessive length") proves the refiner SHOULD prune.
    # 0.70 floor still catches catastrophic refiner collapse but allows the
    # 10-30% pruning the judge wants.
    if ratio < _REVERT_RATIO:
        return {
            "article": draft,
            "applied": False,
            "ratio": round(ratio, 3),
            "reason": f"min-ratio<{_REVERT_RATIO} revert",
        }
    return {"article": out, "applied": True, "ratio": round(ratio, 3), "reason": "ok"}


def strip_meta(text: str) -> str:
    """Light pre-clean: drop obvious model meta-lines before refining."""
    return re.sub(r"(?im)^\s*(here is|below is|i have written|as an? ai)\b.*$", "", text).strip()
