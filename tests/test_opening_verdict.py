"""P3b-v5 PR-3: the opening front-loads a committed verdict for deliverable-bearing
archetypes. The Lunon-vs-Qianfan head-to-head showed Lunon often HAS the
ranking/prediction but buries it deep + hedged, so the pairwise judge perceives it
as absent (id14's present ranking + prediction scored 0.0). Stating it in the
opening re-places an existing deliverable — no new content, no Insight softening."""

from deep_research.writing_rules import opening_directive


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
