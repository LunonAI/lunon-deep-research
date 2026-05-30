"""P3b-v5 PR-3: the opening front-loads a committed verdict for deliverable-bearing
archetypes. The Lunon-vs-Qianfan head-to-head showed Lunon often HAS the
ranking/prediction but buries it deep + hedged, so the pairwise judge perceives it
as absent (id14's present ranking + prediction scored 0.0). Stating it in the
opening re-places an existing deliverable — no new content, no Insight softening."""

from deep_research.writing_rules import check_opening, opening_directive

# A deliverable opening that front-loads the committed verdict (element 5) plus
# the four base elements (thesis / quantified scope / contrarian / date anchor).
_VERDICT_OPENING = (
    "Snowflake leads, then Databricks and BigQuery; despite the common claim that "
    "all three converge, our 2026 benchmark of 12 workloads shows a 30% cost gap "
    "that persists through 2030."
)
# Same four base elements, but the verdict is DEFERRED ('this report assesses…'),
# not committed — the exact buried/hedged failure mode PR-3 targets.
_DEFERRAL_OPENING = (
    "This report assesses three cloud data warehouses across cost, performance, and "
    "ecosystem. We examine 12 workloads measured in 2026 and discuss the tradeoffs "
    "each presents through 2030, despite the common framing that one size fits all."
)


def test_verdict_clause_fires_for_deliverable_archetypes():
    for a in ("compare", "predict", "recommend", "list-all"):
        assert "COMMITTED ONE-SENTENCE VERDICT" in opening_directive(a), a


def test_verdict_clause_absent_for_non_deliverable_archetypes():
    # explain-mechanism / trend / default have no single headline verdict to commit
    for a in ("explain-mechanism", "trend", "trend-qual", ""):
        assert "COMMITTED ONE-SENTENCE VERDICT" not in opening_directive(a), a


def test_base_opening_contract_preserved():
    # the existing THESIS/SCOPE/CONTRARIAN/DATE contract is unchanged for all
    d = opening_directive("compare")
    assert "THESIS" in d and "QUANTIFIED SCOPE" in d and "CONTRARIAN" in d and "DATE ANCHOR" in d
    # back-compat: callable with no archetype (defaults to no verdict clause)
    assert "THESIS" in opening_directive()


# Greptile PR #76: check_opening must validate the verdict it instructs, so a
# deliverable draft that omits the front-loaded verdict cannot silently "accept".


def test_check_opening_flags_missing_verdict_for_deliverable_archetypes():
    for a in ("compare", "predict", "recommend", "list-all"):
        r = check_opening(_DEFERRAL_OPENING, a)
        assert "committed_verdict" in r["missing"], a
        # a missing verdict must escalate past silent accept
        assert r["within_300"] is False and r["action"] == "regen_opening", a


def test_check_opening_accepts_committed_verdict_for_deliverable_archetypes():
    for a in ("compare", "predict", "recommend", "list-all"):
        r = check_opening(_VERDICT_OPENING, a)
        assert "committed_verdict" not in r["missing"], a
        assert r["ok"] and r["action"] == "accept", a


def test_check_opening_does_not_require_verdict_for_non_deliverable_archetypes():
    # trend / explain-mechanism have no single headline verdict — the deferral
    # opening (no committed verdict) must still pass cleanly.
    for a in ("trend", "explain-mechanism", "trend-qual"):
        r = check_opening(_DEFERRAL_OPENING, a)
        assert "committed_verdict" not in r["missing"], a
        assert r["ok"], a


def test_check_opening_backcompat_no_archetype_arg_unchanged():
    # The no-arg call (default archetype="") must behave exactly as before the
    # verdict element existed: verdict is never required.
    r = check_opening(_DEFERRAL_OPENING)
    assert "committed_verdict" not in r["missing"]
    assert set(r["missing"]).issubset({"thesis", "quantified_scope", "contrarian", "date_anchor"})


def test_check_opening_verdict_zh_coverage():
    zh_verdict = (
        "在 2026 年的 30 项基准中，方案A领先，其次是B和C；尽管普遍认为三者趋同，"
        "成本差距将保持至 2030 年，达到 30%。"
    )
    zh_deferral = (
        "本文将系统评估三种云数据仓库，从成本、性能与生态三个维度展开。我们考察了 "
        "2026 年的 12 项工作负载，并讨论其在 2030 年前的权衡；尽管普遍认为方案趋同。"
    )
    assert "committed_verdict" not in check_opening(zh_verdict, "compare")["missing"]
    assert "committed_verdict" in check_opening(zh_deferral, "compare")["missing"]


def test_verdict_archetypes_are_valid_classifier_outputs():
    # Cross-module invariant (pins the highest-value risk): every
    # _VERDICT_ARCHETYPES entry must be a string the classifier can actually
    # emit, else the verdict check silently never fires for that archetype. A
    # future rename of a classifier literal ("list-all" -> "list_all") trips this.
    from deep_research import archetype as arch
    from deep_research.writing_rules import _VERDICT_ARCHETYPES

    assert set(_VERDICT_ARCHETYPES) <= set(arch.ARCHETYPES)


def test_check_opening_verdict_recall_diverse_phrasings():
    # Diverse but genuine front-loaded verdicts must register — a false negative
    # would force a wasteful opening regen on an already-compliant draft.
    tail = " despite the common claim of parity, our 2026 benchmark shows a 30% gap through 2030."
    cases = [
        ("compare", "Claude edges out GPT-4 and Gemini on 12 axes;" + tail),
        ("compare", "The verdict — Rust is safer than C++ and Go;" + tail),
        ("compare", "Our ranking: (1) Vercel (2) Netlify (3) Cloudflare;" + tail),
        ("list-all", "Topping the list of 40 tools is the Dyson V15, ahead of Shark;" + tail),
        ("recommend", "We'd pick the Sony A7 IV over Canon and Nikon;" + tail),
        ("recommend", "在 2026 年的评估中，首推大疆，优于其余两家；尽管普遍认为趋同，到 2030 年仍领先，份额达 40%。"),
    ]
    for a, t in cases:
        assert "committed_verdict" not in check_opening(t, a)["missing"], (a, t)
