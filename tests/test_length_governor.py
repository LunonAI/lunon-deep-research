"""Length governor tests (item 21; decision #5).

Pins `writing_rules.length_ceiling()` — the per-domain × per-language soft word
target that feeds init_format's token budget.

round 4 (2026-05-31): length_ceiling gained a per-LANGUAGE multiplier. The dev8
measurement vs the #1 model (reference EN ~9.5k words / ZH ~13.5k chars; us
EN 48k / ZH 70k; the reference EN ~80k / ZH ~110k) showed the short reference is what
we already beat and the longest model (the reference) is #1, so we target the reference's
length per language: EN 6.5×, ZH 8.0× the catalog median. These pin the new
behavior so a future accidental revert is caught.
"""

import pytest

from deep_research import writing_rules as wr


def test_length_ceiling_applies_per_language_multiplier():
    """length_ceiling(domain, lang) = domain median × per-language multiplier.
    Pin that the EN multiplier is applied (not the bare median)."""
    med = wr._en_domain_medians()["_overall"]
    got = wr.length_ceiling("_overall", "en")
    assert got == int(med * wr._length_mult_for("en")), f"length_ceiling('_overall','en')={got} should be median×6.5"


def test_zh_target_is_longer_than_en():
    """ZH targets the reference's longer profile, so its ceiling must exceed EN's for
    the same domain (the whole point of the per-language split)."""
    en = wr.length_ceiling("_overall", "en")
    zh = wr.length_ceiling("_overall", "zh")
    assert zh > en, f"zh ceiling ({zh}) must exceed en ({en})"


def test_default_language_is_en():
    """Back-compat: a positional-domain caller (no language) gets the EN target."""
    assert wr.length_ceiling("_overall") == wr.length_ceiling("_overall", "en")


def test_length_ceiling_domain_specific():
    """Domain-specific medians resolve to positive ints (relative shape kept)."""
    got_finance = wr.length_ceiling("finance", "en")
    got_overall = wr.length_ceiling("_overall", "en")
    assert isinstance(got_finance, int) and got_finance > 0
    assert isinstance(got_overall, int) and got_overall > 0


def test_length_ceiling_overall_fallback():
    """Unknown domain falls back to the _overall median (same language)."""
    assert wr.length_ceiling("nonexistent_domain_xyz", "zh") == wr.length_ceiling("_overall", "zh")


def test_per_language_mult_env_override(monkeypatch):
    """DR_LENGTH_MULT_<LANG> overrides the built-in per-language multiplier so a
    dev run can re-calibrate or BACK OFF the length dial without a redeploy."""
    monkeypatch.setenv("DR_LENGTH_MULT_ZH", "10")
    assert wr._length_mult_for("zh") == 10.0
    monkeypatch.delenv("DR_LENGTH_MULT_ZH", raising=False)
    assert wr._length_mult_for("zh") == wr._LENGTH_TARGET_MULT_BY_LANG["zh"]


def test_per_language_mult_env_override_malformed_falls_back(monkeypatch):
    """A non-numeric override falls back to the built-in multiplier rather than
    crashing (mirrors the int_env fail-soft posture)."""
    monkeypatch.setenv("DR_LENGTH_MULT_EN", "lots")
    assert wr._length_mult_for("en") == wr._LENGTH_TARGET_MULT_BY_LANG["en"]


@pytest.mark.parametrize("lang,expected", [("en", 6.5), ("zh", 8.0)])
def test_per_language_mult_constants(lang, expected):
    """Pin the calibrated per-language multipliers. A change here shifts every
    article's length budget for that language — must be deliberate."""
    assert wr._LENGTH_TARGET_MULT_BY_LANG[lang] == expected
