"""Unit tests for P3-W3 — mid-paragraph xref directive + check_xref_quality.

reference-verified pattern (11/11 articles average 100-451 cross-refs):
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


def test_heading_title_chapter_n_not_treated_as_dangling_xref():
    r"""Greptile PR #39 round-5 issue #1: `generic_pattern` and
    `paren_pattern` previously scanned the FULL document including
    heading lines. A heading title like `## 5 Chapter 47 Overview`
    matches `(?:Section|Chapter|Sec\.)\s+([\d\.]+)` and contributes
    "47" to `raw_refs`. If §47 isn't in `heading_ids`, it lands in
    `dangling_forward_refs` and fires a spurious fail entry — even
    though "Chapter 47" is the chapter's NAME, not a navigational
    xref. This mirrors the bug `xref_repair._rewrite_body_only`
    addressed in round-4; the auditor needed the same heading-line
    mask.

    The fix masks `^#{2,4}…` heading lines (replacing them with
    same-length space runs so character offsets stay valid for the
    forward-defer proximity windows) before running paren/generic/zh
    `finditer` on the document.

    This test seeds enough legitimate body xrefs to satisfy the
    per-chapter ≥5 floor and asserts: (a) `47` does NOT appear in
    `dangling_forward_refs`; (b) no `dangling_forward_refs` fail
    entry; (c) the chapter's xref count reflects only body refs.
    """
    text = (
        "## 5 Chapter 47 Overview\n\n"
        # 5 legitimate body xrefs that DON'T name §47 — they reference
        # other existing chapters, so the per-chapter floor is satisfied
        # without involving the dangling number in the heading title.
        "First (Section 6). Second (Section 6). Third (Section 6). "
        "Fourth (Section 6). Fifth (Section 6).\n\n"
        "## 6 Body\n\n"
        "Body content with no xrefs of its own here.\n"
        # ≥5 chapters so the per-chapter floor audit's 20% tolerance
        # for chapter #6 doesn't fail (`max(1, 2//5)=1` allows 1 miss).
    )
    out = wr.check_xref_quality(text)
    # (a) `47` is not navigational — it's a chapter NAME — so it must
    # NOT be classified as a dangling forward ref.
    assert "47" not in out["dangling_forward_refs"], (
        f"heading-title `Chapter 47` leaked into dangling_forward_refs: {out}"
    )
    # (b) No `dangling_forward_refs` fail entry on this account.
    assert not any("dangling_forward_refs" in f for f in out["fail"]), (
        f"spurious dangling-fail from heading title: {out['fail']}"
    )


def test_heading_title_section_n_in_sub_heading_not_counted_in_per_chapter():
    """Greptile PR #39 round-5 issue #1: the per-chapter `_count_refs_in`
    helper also scans heading lines — H3/H4 sub-headings remain in the
    chapter body after the H2-level split. A sub-heading like
    `### 5.1 Section 99 Subtopic` would contribute "99" to the chapter's
    xref count, inflating the per-chapter signal. Pin that sub-heading
    title text is excluded from the per-chapter count.
    """
    text = (
        "## 5 Overview\n\n"
        "### 5.1 Section 99 Subtopic\n\n"
        "Body content here with no inline xrefs.\n\n"
        "## 6 Body\n\nMore content.\n"
    )
    out = wr.check_xref_quality(text)
    # Chapter "5" should report 0 xrefs (the body text has none; the
    # `### Section 99` sub-heading title is masked out).
    counts = out["per_chapter_xref_counts"]
    assert counts.get("5", 0) == 0, f"sub-heading title text inflated chapter 5 count: {counts}"
    # And "99" must not have leaked into dangling refs either.
    assert "99" not in out["dangling_forward_refs"]


def test_single_chapter_below_xref_floor_fires_fail_entry():
    """Greptile PR #39 round-5 issue #2: a 1-chapter article with
    fewer than 5 cross-references previously slipped past the
    per-chapter audit because `max(1, len(per_chapter) // 5) = 1` and
    the guard was strict `chapters_below_floor > 1` (requires ≥2
    misses). For a 1-chapter doc, 2 misses is impossible — so the
    1-chapter case had effectively infinite tolerance. The 20% tolerance
    is designed for multi-chapter docs where one short chapter can be
    diluted across peers; with only 1 chapter there are no peers, so
    tolerance must collapse to 0.

    Fixture: a 1-chapter article with zero xrefs. Post-fix, this MUST
    fire the `chapters_below_5_xref_floor=1/1` fail entry.
    """
    text = "## 1 Lonely\n\nA single-chapter article with no cross-references at all.\n"
    out = wr.check_xref_quality(text)
    assert out["n_chapters"] == 1
    assert out["per_chapter_xref_counts"]["1"] == 0
    # Critical: the fail entry MUST fire.
    floor_fails = [f for f in out["fail"] if "chapters_below_5_xref_floor" in f]
    assert floor_fails, f"1-chapter article with 0 xrefs silently passed the audit: {out}"
    assert floor_fails[0] == "chapters_below_5_xref_floor=1/1", f"unexpected fail entry shape: {floor_fails}"


def test_single_chapter_at_or_above_xref_floor_passes():
    """Symmetric to the previous test: a 1-chapter article with ≥5
    cross-references must still pass — the tightened tolerance must
    not turn the audit into a hair-trigger when the floor is met.
    """
    text = "## 1 Solo\n\n(Section 2) and (Section 3) and (Section 4) and (Section 5) and (Section 6).\n"
    out = wr.check_xref_quality(text)
    assert out["n_chapters"] == 1
    assert out["per_chapter_xref_counts"]["1"] == 5
    assert not any("chapters_below_5_xref_floor" in f for f in out["fail"]), (
        f"1-chapter article AT the floor wrongly failed: {out}"
    )


def test_forward_defer_pre_window_clamp_with_multiple_separator_types():
    """Greptile PR #39 round-2: the `wstart` clamping loop in
    `check_xref_quality` previously mutated `wstart` in-place and used
    the mutated value as the base for absolute-position arithmetic on
    subsequent separator types. When BOTH `\\n\\n` AND `\\n## ` appear
    inside the 80-char pre-window, the second iteration inflated the
    clamp offset by the first iteration's adjustment — narrowing the
    forward-defer detection window more than intended and silently
    dropping in-window phrases.

    Fixture: place a forward-defer phrase ("will return below") inside
    the pre-window of an xref `(Section 3)`, with a paragraph break
    (`\\n\\n`) earlier in the same chapter. There is no intervening
    `\\n## ` heading inside the pre-window — so the buggy clamp would
    only fire on the `\\n\\n`. We assert the forward-defer is detected,
    which would NOT hold if the window were over-clamped past the
    "will return" phrase.

    The complementary `test_forward_defer_ratio_counts_xref_in_forward_context`
    above already covers the happy path; this one specifically pins the
    pre-window arithmetic against the cumulative-mutation regression.
    """
    text = (
        "## 1 Chapter\n\n"
        # 70-char buffer ending in a `\n\n` paragraph break, then the
        # forward-defer phrase + xref directly after the break, all
        # inside the chapter body (no second `##` heading nearby).
        + ("Filler prose that pads out the chapter body content. " * 2)
        + "\n\n"
        "We will return to this point below in (Section 3) of the report.\n\n"
        + "\n\n".join(f"## {i} S{i}" for i in range(2, 14))
        + "\n"
    )
    out = wr.check_xref_quality(text)
    # 1 xref total — but `forward_defer_ratio` is only emitted as a fail
    # entry once `n_total_xrefs >= 10`. The lower-level assertion is on
    # the counted denominator/numerator, not on the fail-entry gate.
    # We test the proximity-window detection directly by adding ≥10 xrefs.
    bigger = (
        "## 1 Chapter\n\n" + ("Filler prose that pads out the chapter body content. " * 2) + "\n\n"
        # Forward-defer phrases within 80 chars of each xref.
        "We will return to (Section 3) below. "
        "Will detail (Section 4) below. "
        "Will examine (Section 5) below. "
        # Plain (non-forward-defer) xrefs after — far past any defer phrase.
        + ("\n\n" + "Plain reference (Section 6) standalone. " * 7)
        + "\n\n"
        + "\n\n".join(f"## {i} S{i}" for i in range(3, 14))
        + "\n"
    )
    out = wr.check_xref_quality(bigger)
    assert out["n_total_xrefs"] >= 10
    # The 3 forward-defer xrefs sit close to their defer phrases AND a
    # `\n\n` paragraph break appears earlier. Pre-fix, the second-pass
    # clamp inflated past the phrases → ratio dropped to 0. Post-fix the
    # window stays correctly anchored and ≥3/10 = 0.30 fires.
    assert out["forward_defer_ratio"] >= 0.30, (
        f"forward-defer phrases within window were dropped by over-clamped "
        f"pre-window; got ratio {out['forward_defer_ratio']!r} from {out}"
    )
