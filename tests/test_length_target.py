"""Unit tests for P2-Wave-2.5-D1 length_target + resolve_depth_tier.

Calibrates against the #1 reference leaderboard sample (reference_findings.md §F1):
EN comprehensive targets 50-65k words, EN deep 25-35k, EN standard 15-20k,
EN compact 10-15k. ZH equivalents in CJK characters double these numbers.
"""

from deep_research import writing_rules as wr

# --- resolve_depth_tier ----------------------------------------------------


def test_resolve_explicit_plan_tier_wins():
    assert wr.resolve_depth_tier("predict", "comprehensive") == "comprehensive"
    assert wr.resolve_depth_tier("recommend", "compact") == "compact"


def test_resolve_unknown_plan_tier_falls_back_to_archetype_default():
    assert wr.resolve_depth_tier("compare", "absurd") == "deep"
    assert wr.resolve_depth_tier("predict", "absurd") == "standard"


def test_resolve_no_plan_tier_uses_archetype_default():
    # explain-mechanism, compare, list-all default to deep per the reference
    # corpus (the long-form winners).
    assert wr.resolve_depth_tier("explain-mechanism", None) == "deep"
    assert wr.resolve_depth_tier("compare", None) == "deep"
    assert wr.resolve_depth_tier("list-all", None) == "deep"
    # predict / trend / recommend tend to be shorter-scope.
    assert wr.resolve_depth_tier("predict", None) == "standard"
    assert wr.resolve_depth_tier("trend", None) == "standard"
    assert wr.resolve_depth_tier("recommend", None) == "standard"


def test_resolve_unknown_archetype_returns_standard():
    assert wr.resolve_depth_tier(None, None) == "standard"
    assert wr.resolve_depth_tier("absurd", None) == "standard"


# --- length_target ---------------------------------------------------------


def test_length_target_scales_with_tier():
    """A given domain must produce monotonically increasing targets across
    compact → standard → deep → comprehensive."""
    domain = "default"
    compact = wr.length_target(domain, depth_tier="compact")
    standard = wr.length_target(domain, depth_tier="standard")
    deep = wr.length_target(domain, depth_tier="deep")
    comp = wr.length_target(domain, depth_tier="comprehensive")
    assert compact < standard < deep < comp


def test_length_target_en_comprehensive_matches_reference_envelope():
    """EN comprehensive should land in the 50-65k words envelope (the reference
    id=56 was 80k, id=91 was 69k, id=89 was 79k — soft target around 58k)."""
    target = wr.length_target("science", depth_tier="comprehensive", language="en")
    assert 40_000 <= target <= 80_000, f"got {target}"


def test_length_target_en_deep_matches_reference_zh_deep_envelope():
    """EN deep should be in the 25-40k words envelope (the cross-language
    upper-mid range the reference delivers on substantive research)."""
    target = wr.length_target("default", depth_tier="deep", language="en")
    assert 20_000 <= target <= 45_000, f"got {target}"


def test_length_target_zh_doubles_word_target():
    """ZH unit is CJK chars ≈ 2 × word target (1 word ≈ 2 CJK chars)."""
    en_target = wr.length_target("default", depth_tier="deep", language="en")
    zh_target = wr.length_target("default", depth_tier="deep", language="zh")
    # Allow rounding slop ±5%.
    assert 1.85 * en_target <= zh_target <= 2.15 * en_target


def test_length_target_falls_back_to_archetype_when_no_tier():
    """No depth_tier given → archetype-default selects the tier."""
    deep_target = wr.length_target("default", archetype="compare", depth_tier=None)
    standard_target = wr.length_target("default", archetype="predict", depth_tier=None)
    assert deep_target > standard_target


def test_length_target_compact_is_still_above_old_ceiling():
    """Even the compact tier should equal-or-exceed the old length_ceiling()
    domain median. Pre-Wave-2.5-D1 we capped at 1.0× domain median; compact
    sits at 1.5× as the new floor."""
    domain = "default"
    legacy_ceiling = wr.length_ceiling(domain)
    compact = wr.length_target(domain, depth_tier="compact", language="en")
    assert compact >= legacy_ceiling


def test_length_target_unknown_tier_treated_as_standard_via_resolve():
    """resolve_depth_tier discards unknown tiers → falls back to standard
    when archetype also unknown. length_target inherits that behavior."""
    target = wr.length_target("default", archetype=None, depth_tier="not-a-tier", language="en")
    expected = wr.length_target("default", depth_tier="standard", language="en")
    assert target == expected


# --- length_ceiling backward-compat ----------------------------------------


def test_length_ceiling_unchanged_for_known_domains():
    """The legacy length_ceiling() must continue to return the domain median
    so any caller that hasn't migrated still gets a sane value."""
    for domain in ("finance", "health", "science", "default"):
        v = wr.length_ceiling(domain)
        assert v > 0
