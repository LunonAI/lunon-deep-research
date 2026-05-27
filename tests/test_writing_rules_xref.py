"""Unit tests for P3-W3 — mid-paragraph xref directive + check_xref_quality.

Qianfan-verified pattern (11/11 articles average 100-451 cross-refs):
mid-paragraph attached to factual claims, NOT chapter-opening templates.
W3 smoke confirmed §12.A rewrite reduced "Building on §X" to 0%; P3-W3
installs the POSITIVE directive (≥5 xrefs/chapter, ≥40% parenthetical,
≤30% forward-defer).
"""

from deep_research import writing_rules as wr


def test_mid_paragraph_xref_rule_present_in_module():
    """Pin the constant exists with the load-bearing semantics."""
    assert "_MID_PARAGRAPH_XREF_RULE" in dir(wr)
    rule = wr._MID_PARAGRAPH_XREF_RULE
    assert "MID-CHAPTER CROSS-REFERENCE" in rule
    assert "AT LEAST 5" in rule
    assert "40%" in rule  # parenthetical-ratio target
    assert "30%" in rule  # forward-defer ratio cap


def test_writer_system_includes_xref_rule():
    """The rule must be in the writer's middle_block — without this
    the directive isn't sent to the LLM."""
    sys = wr.writer_system("predict", "default", "en", ["S1", "S2"])
    assert "MID-CHAPTER CROSS-REFERENCE" in sys


def test_check_xref_quality_counts_parenthetical_refs():
    """Parenthetical `(Section X.Y)` refs counted."""
    text = "## 1 Intro\n\nFirst (Section 2.1) and second (§3) and Chapter 4. End."
    out = wr.check_xref_quality(text)
    assert out["n_parenthetical"] >= 2, f"got {out}"


def test_check_xref_quality_per_chapter_counts():
    """Per-chapter counts split correctly on `## N` boundaries."""
    text = (
        "## 1 First\n\nClaim per (Section 2.1). Forward (Section 3.1).\n\n"
        "## 2 Second\n\nNo refs here.\n\n"
        "## 3 Third\n\nSee (Section 1) and (Section 2)."
    )
    out = wr.check_xref_quality(text)
    counts = out["per_chapter_xref_counts"]
    assert "1" in counts and counts["1"] >= 2, f"got {counts}"
    assert "2" in counts and counts["2"] == 0
    assert "3" in counts and counts["3"] >= 2


def test_check_xref_quality_detects_opening_template_violation():
    """Chapter-opening 'Building on §X' triggers violation count."""
    text = "## 2 Foo\n\nBuilding on §1 established earlier, this section continues."
    out = wr.check_xref_quality(text)
    assert out["opening_template_violations"] == 1, f"got {out}"


def test_check_xref_quality_detects_dangling_forward_ref():
    """A §N where N is not in the heading set is flagged."""
    text = "## 1 Intro\n\nSee (Section 47) for details (this is dangling).\n\n## 2 Body\n\nSee (Section 1.2)."
    out = wr.check_xref_quality(text)
    assert "47" in out["dangling_forward_refs"], f"got {out}"


def test_check_xref_quality_legitimate_refs_not_flagged():
    """References to existing chapters/sections must NOT be flagged."""
    text = "## 1 Intro\n\nSee (Section 2).\n\n## 2 Body\n\nReferenced earlier (Section 1)."
    out = wr.check_xref_quality(text)
    assert out["dangling_forward_refs"] == [], f"got {out}"


def test_check_xref_quality_parenthetical_ratio_computed():
    """Ratio = parenthetical / total."""
    text = (
        "## 1 Intro\n\n"
        "(Section 2) and (Section 3) and (Section 4) and (Section 5) "
        "plus Section 6, Chapter 7, Section 8, Chapter 9.\n\n"
        "## 2 Body\n\n## 3 X\n\n## 4 Y\n\n## 5 Z\n\n## 6 W\n\n## 7 V\n\n## 8 U\n\n## 9 T\n\n"
    )
    out = wr.check_xref_quality(text)
    # 4 parenthetical, total >= 8 (parenthetical + bare); ratio = 0.5
    assert out["parenthetical_ratio"] >= 0.40, f"got ratio {out['parenthetical_ratio']}: {out}"


def test_check_xref_quality_empty_article_returns_ok():
    """Empty article: no chapters → no failures (per-chapter floor doesn't fire)."""
    out = wr.check_xref_quality("")
    assert out["n_chapters"] == 0


def test_check_xref_quality_returns_required_keys():
    """Pin the result-dict keys — downstream consumers depend on these."""
    out = wr.check_xref_quality("## 1 Hi\n")
    expected_keys = {
        "ok",
        "n_chapters",
        "per_chapter_xref_counts",
        "opening_template_violations",
        "dangling_forward_refs",
        "n_parenthetical",
        "n_total_xrefs",
        "parenthetical_ratio",
        "forward_defer_ratio",
        "fail",
    }
    assert set(out.keys()) == expected_keys, f"got {set(out.keys())}"


def test_check_xref_quality_zh_refs_counted():
    """ZH 第X章 references contribute to the total count."""
    text = "## 1 引言\n\n详见第2章。承接第3章的论述。\n\n## 2 主体\n\n## 3 结论\n\n"
    out = wr.check_xref_quality(text)
    assert out["n_total_xrefs"] >= 2, f"got {out}"


def test_forward_defer_ratio_ignores_non_xref_phrase_occurrences():
    """Greptile PR #39 round-2 issue #3: `forward_defer_ratio` previously
    divided RAW phrase counts (anywhere in the document) by xref counts,
    mixing incompatible units. A document with 6 standalone "below"
    occurrences in non-xref contexts plus 5 actual xrefs scored 1.2
    and spuriously failed. The fix counts xrefs that have a forward-
    defer phrase within ±80 chars — the same unit on both sides.

    Fixture: 10 xrefs, NONE in a forward-defer window; plus 6 isolated
    "below" tokens placed far from any xref. Old behavior: 6/10 = 0.6
    (FAIL). New behavior: 0/10 = 0.0 (PASS).
    """
    isolated_belows = " ".join(["The fuselage extends below the wing."] * 6)
    text = (
        "## 1 X\n\n" + isolated_belows + "\n\n"
        "## 2 Y\n\n"
        "First (Section 3). Second (Section 4). Third (Section 5). Fourth (Section 6). "
        "Fifth (Section 7). Sixth (Section 8). Seventh (Section 9). Eighth (Section 10). "
        "Ninth (Section 11). Tenth (Section 12).\n\n" + "\n\n".join(f"## {i} S{i}" for i in range(3, 13)) + "\n"
    )
    out = wr.check_xref_quality(text)
    assert out["n_total_xrefs"] >= 10, f"expected ≥10 xrefs: {out}"
    assert out["forward_defer_ratio"] == 0.0, (
        f"isolated 'below' phrases must not contribute when not near an xref: {out}"
    )
    assert not any("forward_defer_ratio" in f for f in out["fail"]), f"spurious forward_defer failure: {out['fail']}"


def test_forward_defer_ratio_counts_xref_in_forward_context():
    """Symmetric check: when a forward-defer phrase IS within the
    proximity window of an xref, that xref counts toward the ratio.
    Fixture: 10 xrefs, 4 of them adjacent to "will return" / "below".
    Ratio should be 4/10 = 0.4 (above the 0.30 cap → fail entry)."""
    text = (
        "## 1 X\n\n"
        "We will return to this in (Section 3). The argument below in (Section 4) extends. "
        "Will detail (Section 5) below. As discussed (Section 6) below. "
        "Plain reference (Section 7). Another plain ref (Section 8). "
        "Plain (Section 9). Plain (Section 10). Plain (Section 11). Plain (Section 12).\n\n"
        + "\n\n".join(f"## {i} S{i}" for i in range(3, 13))
        + "\n"
    )
    out = wr.check_xref_quality(text)
    assert out["n_total_xrefs"] >= 10
    # 4 of the 10 xrefs are within ±80 chars of a forward-defer phrase →
    # ratio ≈ 0.4 (must be > 0.30 to fire the fail entry).
    assert out["forward_defer_ratio"] >= 0.30, f"xrefs in forward-defer context not detected: {out}"
    assert any("forward_defer_ratio" in f for f in out["fail"]), f"expected forward_defer fail entry: {out['fail']}"


def test_forward_defer_ratio_zero_when_no_xrefs():
    """Edge case: no xrefs at all → ratio is 0.0 (n_total denominator
    guard), and no fail entry fires (denominator <10 → check skipped
    by the existing `n_total >= 10` gate)."""
    text = "## 1 Hi\n\nNo cross-references in this body. Just plain prose.\n"
    out = wr.check_xref_quality(text)
    assert out["forward_defer_ratio"] == 0.0
    assert not any("forward_defer_ratio" in f for f in out["fail"])
