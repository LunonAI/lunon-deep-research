"""Unit tests for P2-Wave-2.5-D3 — F5 footnote relaxation + F6 math preservation.

F5: `CLEANING_RESISTANT_RULE` now ENCOURAGES `[n]` markers alongside inline
source names (was: "allowed ONLY for cost-free fact support" → dropped them).

F6: `_MATH_PRESERVATION_RULE` fires in writer_system when the task is in a
math-bearing domain (`science`) or the prompt/TOC contains LaTeX markup.
"""

import re

from deep_research import writing_rules as wr

# --- F5: footnote-marker relaxation -----------------------------------------


def test_cleaning_resistant_rule_now_encourages_footnotes():
    rule = wr.CLEANING_RESISTANT_RULE
    assert "ENCOURAGED" in rule
    assert "50-300 footnote markers" in rule
    # The pre-D3 "ONLY for pure fact support that is cost-free" framing is gone.
    assert "cost-free" not in rule


def test_cleaning_resistant_rule_keeps_load_bearing_invariant():
    """The non-negotiable rule (sentence stands after [n] strip) MUST stay —
    relaxing the encouragement does not relax the cleaning-resistance guarantee."""
    rule = wr.CLEANING_RESISTANT_RULE
    assert "LOAD-BEARING rule" in rule
    assert "Every sentence must read complete after all [n]" in rule


def test_cleaning_resistant_rule_recommends_references_section():
    rule = wr.CLEANING_RESISTANT_RULE
    assert "References" in rule or "参考文献" in rule


# --- F6: math preservation --------------------------------------------------


def test_writer_system_math_rule_fires_on_science_domain(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("explain-mechanism", "science", "en", ["Equilibrium"])
    assert "MATH NOTATION" in sys
    assert "\\mathbb{R}" in sys  # LaTeX cheat-sheet present


def test_writer_system_math_rule_quiet_for_default_domain(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("compare", "default", "en", ["A", "B"])
    assert "MATH NOTATION" not in sys


def test_writer_system_math_rule_fires_when_toc_has_latex(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("compare", "default", "en", ["Probability $P(X)$", "Distribution $f(x)$"])
    assert "MATH NOTATION" in sys


def test_writer_system_math_rule_fires_when_prompt_has_latex(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system(
        "predict",
        "default",
        "en",
        ["A"],
        prompt="Compute $\\sum_{i=1}^n x_i$ for the auction.",
    )
    assert "MATH NOTATION" in sys


def test_writer_system_math_rule_fires_on_mathbb_in_prompt(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system(
        "explain-mechanism",
        "default",
        "en",
        ["A"],
        prompt="A function f from \\mathbb{R} to \\mathbb{R}_+ with property P.",
    )
    assert "MATH NOTATION" in sys


def test_math_rule_includes_display_math_guidance(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("explain-mechanism", "science", "en", ["A"])
    assert "Display math" in sys
    assert "$$...$$" in sys


def test_math_rule_warns_against_inventing_equations(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("explain-mechanism", "science", "en", ["A"])
    assert "Do NOT invent equations" in sys


# --- _is_math_bearing helper ------------------------------------------------


def test_is_math_bearing_explicit_science_domain():
    assert wr._is_math_bearing("science", ["A"], "") is True


def test_is_math_bearing_finance_domain_only_if_latex_present():
    # finance isn't a default math-domain — falls back to LaTeX detection.
    assert wr._is_math_bearing("finance", ["A"], "Use NPV to compare.") is False
    assert wr._is_math_bearing("finance", ["A"], "Compute $\\sum x_i$.") is True


def test_is_math_bearing_short_dollar_pairs_dont_false_positive():
    """A `$5` price tag is NOT LaTeX. Our regex requires 2+ chars between
    dollar signs to avoid the false-positive on currency."""
    assert wr._is_math_bearing("default", ["Cost is $5"], "Compare $5 vs $10") is False


# --- prompt kwarg backward-compat -------------------------------------------


def test_writer_system_prompt_kwarg_defaults_to_empty(monkeypatch):
    """Existing callers without `prompt=` arg must still work; math-rule
    falls back to domain + TOC heuristic."""
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("compare", "default", "en", ["A", "B"])
    # No math markers in domain/TOC/(empty)prompt → math-rule absent.
    assert "MATH NOTATION" not in sys


# --- integration: F5 + F6 ---------------------------------------------------


def test_writer_system_includes_both_f5_footnotes_and_f6_math_when_applicable(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("explain-mechanism", "science", "en", ["Probability"])
    # F5: footnote encouragement present.
    assert "ENCOURAGED" in sys
    assert "50-300 footnote markers" in sys
    # F6: math rule present.
    assert "MATH NOTATION" in sys


def test_math_rule_lists_common_latex_macros(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("explain-mechanism", "science", "en", ["A"])
    # Spot-check several macros from the cheat-sheet.
    for macro in ("\\mathbb{R}", "\\sum", "\\int", "\\partial", "\\geq", "\\leq"):
        assert macro in sys, f"missing {macro} in math rule"


def test_math_marker_regex_robust_to_paragraph_text():
    """The detection regex must not over-fire on prose with currency or %."""
    benign = "We saw a 25% increase, costing $5 per unit, across 2023-2024."
    assert not re.search(wr._MATH_MARKUP_RE, benign)
