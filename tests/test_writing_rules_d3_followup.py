"""Tests for P2-Wave-2.5-D3 Greptile follow-up (PR #14)."""

from __future__ import annotations

from deep_research import writing_rules as wr

# --- Issue: writer user-message mandates [n] (was permissive "may also add") --


def test_writer_section_user_message_mandates_footnote_append(monkeypatch):
    """The evidence-injection paragraph must instruct the writer to APPEND a
    `[n]` marker after each citing sentence, NOT use permissive 'may also add'
    language that conflicted with the system-prompt F5 directive."""
    # Build the user-message string the same way write_section does, via a
    # minimal mock: we just verify the literal phrase in writer.py source.
    import deep_research.pipeline.writer as writer_mod

    source = open(writer_mod.__file__, encoding="utf-8").read()
    # Old permissive language must be gone.
    assert "you may also add a numeric [n]" not in source
    # New mandatory language must be present.
    assert "APPEND" in source
    assert "citation-density signal" in source


# --- Issue: _MATH_DOMAINS must include `finance` ----------------------------


def test_math_domains_includes_finance():
    """`finance` domain triggers the math-preservation rule via the domain
    path. Previously only `science` was in the tuple, while the rule body
    advertised 'quantitative finance' coverage — silent skip on finance
    tasks without LaTeX in the prompt."""
    assert "finance" in wr._MATH_DOMAINS
    assert "science" in wr._MATH_DOMAINS


def test_writer_system_finance_domain_fires_math_rule(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("explain-mechanism", "finance", "en", ["Valuation"])
    assert "MATH NOTATION" in sys


def test_is_math_bearing_finance_no_latex_now_true():
    """With finance in _MATH_DOMAINS, a finance task WITHOUT LaTeX in the
    prompt still triggers the rule (regression case from pre-D3-followup)."""
    assert wr._is_math_bearing("finance", ["Valuation methods"], "Use NPV to compare.") is True


# --- Issue: citation_strip_audit retention excludes References section ------


def test_citation_audit_retention_excludes_references_section():
    """A long References appendix MUST NOT drag retention below the 0.9 gate
    — the audit measures body-prose collapse from `[n]` strip, not the size
    of the references appendix.

    The pre-fix calculation included References in the denominator. For an
    article with a 5kB References block in a 30kB body, References alone is
    ~14% of total chars → before strip the audit already had less than 0.86
    retention possible, failing the 0.9 gate purely on bibliography length.
    """
    body = "# Title\n\nAccording to McKinsey 2024, the trend is X[1]. Reuters 2025 confirms[2]. " * 200
    references = "\n\n## References\n\n" + "\n".join(f"[{i}] Source {i}, URL." for i in range(1, 50))
    article = body + references
    audit = wr.citation_strip_audit(article)
    # Post-fix: retention must clear the 0.9 gate under realistic F5 density.
    assert audit["retention"] > 0.9
    assert audit["ok"] is True


def test_citation_audit_with_many_footnotes_still_passes():
    """An article with 300 [n] markers in dense citation prose should still
    pass the retention threshold (this is the F5-encouraged scenario)."""
    base_sentence = "According to Smith 2024, the data show X. "
    body = "# Title\n\n" + "".join(f"{base_sentence}[{i}] " for i in range(1, 301))
    audit = wr.citation_strip_audit(body)
    assert audit["retention"] >= 0.9
    assert audit["ok"] is True


def test_citation_audit_still_fails_when_body_dependent_on_markers():
    """The audit's core invariant — body becoming meaningless after `[n]`
    strip — must still fail. We simulate this by making `[n]` carry semantic
    load (very high ratio of markers to body words)."""
    pathological = "The reference[1] notes that[2] this[3] is[4] consistent[5]."
    audit = wr.citation_strip_audit(pathological)
    # Heavy `[n]` density on a short body — markers are ~25% of chars.
    assert audit["retention"] < 0.9
    assert audit["ok"] is False


def test_citation_audit_no_references_section_still_works():
    """Articles without a References section behave the same as before."""
    article = "# Title\n\nAccording to McKinsey 2024, the data shows X[1]. " * 50
    audit = wr.citation_strip_audit(article)
    assert audit["retention"] >= 0.9
