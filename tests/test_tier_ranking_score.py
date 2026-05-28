"""P3b-OPT3 (2026-05-27): architect-side tier-ranking scoring tests.

The scorer replaces writer hallucination: LLM judgment (per-dimension scores)
+ Python arithmetic (S_final + tier). These tests cover the scorer's None
fall-throughs, output shape, deterministic rounding/bucketing, the architect
integration (attach + fail-soft), and the writer rendering pre-scored values
vs falling back to the compute directive.
"""

from deep_research.pipeline import memory_bank, tier_ranking_score, writer


def _plan(**overrides):
    p = {
        "tier_ranking": {
            "title": "Tier Ranking",
            "scoring_formula": "S_final = Σ(weight_i × dim_i)",
            "weights": {"R-1": 0.5, "R-2": 0.3, "R-3": 0.2},
            "tiers": [
                {"name": "Tier 1", "threshold": ">=8.0"},
                {"name": "Tier 2", "threshold": ">=6.0"},
                {"name": "Tier 3", "threshold": "<6.0"},
            ],
            "sensitivity_check": {"perturbation_pp": 10},
        },
        "entity_matrix": {"entities": ["Alpha", "Beta", "Gamma"], "dimensions": []},
        "framing_chapter": {
            "published_rubric_items": [
                {"id": "R-1", "label": "Research output", "weight": 0.5},
                {"id": "R-2", "label": "Funding", "weight": 0.3},
                {"id": "R-3", "label": "Collaboration", "weight": 0.2},
            ]
        },
    }
    p.update(overrides)
    return p


def _mock_scores(monkeypatch, payload):
    """Patch the scorer's LLM call to return a fixed per-entity score map."""
    monkeypatch.setattr(tier_ranking_score.llm, "call_json", lambda *a, **k: payload)


# ---------- scorer None fall-throughs ----------


def test_returns_none_when_no_tier_ranking(monkeypatch):
    p = _plan(tier_ranking=None)
    assert tier_ranking_score.score_entities(p, "en") is None


def test_returns_none_when_empty_entity_matrix(monkeypatch):
    p = _plan(entity_matrix={"entities": []})
    assert tier_ranking_score.score_entities(p, "en") is None


def test_returns_none_when_no_weights(monkeypatch):
    p = _plan()
    p["tier_ranking"]["weights"] = {}
    assert tier_ranking_score.score_entities(p, "en") is None


def test_returns_none_on_malformed_llm_response(monkeypatch):
    _mock_scores(monkeypatch, "not a dict")
    assert tier_ranking_score.score_entities(_plan(), "en") is None


def test_returns_none_when_llm_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(tier_ranking_score.llm, "call_json", boom)
    assert tier_ranking_score.score_entities(_plan(), "en") is None


# ---------- scorer output shape + math ----------


def test_output_shape(monkeypatch):
    _mock_scores(
        monkeypatch,
        {
            "Alpha": {"R-1": 9.0, "R-2": 8.0, "R-3": 7.0},
            "Beta": {"R-1": 6.0, "R-2": 6.0, "R-3": 6.0},
            "Gamma": {"R-1": 3.0, "R-2": 4.0, "R-3": 5.0},
        },
    )
    out = tier_ranking_score.score_entities(_plan(), "en")
    assert isinstance(out, list) and len(out) == 3
    for e in out:
        assert set(e.keys()) == {"name", "dimension_scores", "S_final", "tier"}


def test_s_final_arithmetic_and_2dp(monkeypatch):
    # weights sum to 1.0 already; S_final = 0.5*9 + 0.3*8 + 0.2*7 = 8.30
    _mock_scores(monkeypatch, {"Alpha": {"R-1": 9.0, "R-2": 8.0, "R-3": 7.0}})
    p = _plan(entity_matrix={"entities": ["Alpha"]})
    out = tier_ranking_score.score_entities(p, "en")
    assert out[0]["S_final"] == 8.30
    # round() yields a float with <=2 decimals
    assert round(out[0]["S_final"], 2) == out[0]["S_final"]


def test_weights_renormalized_when_not_summing_to_one(monkeypatch):
    # weights 5/3/2 (sum 10) → normalized 0.5/0.3/0.2. All dims = 8 → S_final 8.00.
    _mock_scores(monkeypatch, {"Alpha": {"R-1": 8.0, "R-2": 8.0, "R-3": 8.0}})
    p = _plan(entity_matrix={"entities": ["Alpha"]})
    p["tier_ranking"]["weights"] = {"R-1": 5, "R-2": 3, "R-3": 2}
    out = tier_ranking_score.score_entities(p, "en")
    assert out[0]["S_final"] == 8.00


def test_tier_assignment_top(monkeypatch):
    _mock_scores(monkeypatch, {"Alpha": {"R-1": 9.0, "R-2": 9.0, "R-3": 9.0}})
    p = _plan(entity_matrix={"entities": ["Alpha"]})
    out = tier_ranking_score.score_entities(p, "en")
    assert out[0]["S_final"] == 9.00 and out[0]["tier"] == "Tier 1"


def test_tier_assignment_bottom(monkeypatch):
    _mock_scores(monkeypatch, {"Alpha": {"R-1": 4.0, "R-2": 4.0, "R-3": 4.0}})
    p = _plan(entity_matrix={"entities": ["Alpha"]})
    out = tier_ranking_score.score_entities(p, "en")
    assert out[0]["S_final"] == 4.00 and out[0]["tier"] == "Tier 3"


def test_bool_weights_filtered(monkeypatch):
    # A True weight (bool subclass of int) must be dropped, not treated as 1.
    _mock_scores(monkeypatch, {"Alpha": {"R-1": 8.0, "R-2": 8.0}})
    p = _plan(entity_matrix={"entities": ["Alpha"]})
    p["tier_ranking"]["weights"] = {"R-1": 0.5, "R-2": 0.5, "R-bad": True}
    out = tier_ranking_score.score_entities(p, "en")
    # R-bad dropped → normalized 0.5/0.5 → S_final 8.00, no crash
    assert out[0]["S_final"] == 8.00
    assert "R-bad" not in out[0]["dimension_scores"]


def test_threshold_parser():
    assert tier_ranking_score._parse_threshold(">=8.0") == (">=", 8.0)
    assert tier_ranking_score._parse_threshold("<6.0") == ("<", 6.0)
    assert tier_ranking_score._parse_threshold("garbage") is None


def test_entity_with_missing_dimension_is_skipped(monkeypatch):
    """Greptile PR #51 P1: a partial LLM response missing a weight dimension
    must NOT silently substitute 0.0 (which would deflate S_final and make the
    table arithmetically inconsistent). The entity is skipped instead."""
    _mock_scores(
        monkeypatch,
        {
            "Alpha": {"R-1": 9.0, "R-2": 8.0, "R-3": 7.0},  # complete
            "Beta": {"R-1": 9.0, "R-2": 8.0},  # missing R-3 → skip
        },
    )
    out = tier_ranking_score.score_entities(_plan(entity_matrix={"entities": ["Alpha", "Beta"]}), "en")
    names = [e["name"] for e in out]
    assert names == ["Alpha"], f"Beta (missing R-3) should be skipped; got {names}"


def test_all_entities_missing_dimensions_returns_none(monkeypatch):
    """If every entity is partial, scored is empty → None (writer falls back)."""
    _mock_scores(monkeypatch, {"Alpha": {"R-1": 9.0}, "Beta": {"R-2": 8.0}})
    assert tier_ranking_score.score_entities(_plan(entity_matrix={"entities": ["Alpha", "Beta"]}), "en") is None


def test_writer_falls_back_when_all_scored_entries_malformed(monkeypatch):
    """Greptile PR #51 P2: a non-empty entities_scored whose entries are ALL
    malformed (no usable name) must fall through to the compute directive, not
    emit 'PRE-COMPUTED SCORES []' with a verbatim-render instruction."""
    tr = _tr_with_scores()
    tr["entities_scored"] = [{"bogus": 1}, {"name": ""}]  # all fail the inner guard
    plan = _bare_plan_with_tier_ranking(tr)
    user = _call_writer(monkeypatch, plan, "S7")[0]["user"]
    assert "PRE-COMPUTED SCORES" not in user, "empty display must not emit the render directive"
    assert "TIER RANKING + SENSITIVITY CHECK CONTRACT" in user
    assert "2 DECIMAL PLACES" in user  # the compute fallback's precision rule


# ---------- architect integration ----------


def _stub_llm_plan_with_tier():
    """Minimal normalize-able plan (with a tier_ranking dict) for stubbing the
    architect LLM, so build()'s real attachment path can fire."""
    return {
        "report_toc": [{"id": "S1", "title": "T", "subsections": [{"id": "S1.1", "title": "s", "depth_seeds": []}]}],
        "acceptance_criteria": [],
        "queries": [],
        "tier_ranking": {
            "title": "Tier Ranking",
            "weights": {"R-1": 1.0},
            "tiers": [{"name": "T1", "threshold": ">=8.0"}],
        },
    }


def test_architect_survives_scorer_exception(monkeypatch):
    """A scorer exception is swallowed by build()'s try/except — the REAL
    build() still returns a valid plan with no entities_scored attached."""
    from deep_research.pipeline import architect

    def boom(*a, **k):
        raise RuntimeError("scorer crashed")

    monkeypatch.setattr(architect.tier_ranking_score, "score_entities", boom)
    monkeypatch.setattr(architect.llm, "call_json", lambda *a, **k: _stub_llm_plan_with_tier())
    plan = architect.build("p", "en", "predict", [], {}, [])
    assert "entities_scored" not in plan["tier_ranking"]


def test_architect_skips_attachment_when_scorer_returns_none(monkeypatch):
    """Scorer returning None → REAL build() leaves tier_ranking without an
    entities_scored key (writer then falls back to the compute directive)."""
    from deep_research.pipeline import architect

    monkeypatch.setattr(architect.tier_ranking_score, "score_entities", lambda *a, **k: None)
    monkeypatch.setattr(architect.llm, "call_json", lambda *a, **k: _stub_llm_plan_with_tier())
    plan = architect.build("p", "en", "predict", [], {}, [])
    assert "entities_scored" not in plan["tier_ranking"]


# ---------- writer rendering ----------


def _bare_plan_with_tier_ranking(tr, *, sid="S7", title="Tier Ranking"):
    return {
        "report_title": "T",
        "report_toc": [
            {"id": "S1", "title": "Intro", "subsections": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}]},
            {"id": sid, "title": title, "subsections": [{"id": f"{sid}.1", "title": "Sub", "depth_seeds": []}]},
        ],
        "acceptance_criteria": [],
        "queries": [],
        "tier_ranking": tr,
    }


def _call_writer(monkeypatch, plan, sid):
    captured = []

    def fake_llm_call(role, user, *, system, max_tokens, note):
        captured.append({"user": user})
        return "## body\n"

    monkeypatch.setattr(writer.llm, "call", fake_llm_call)
    bank = memory_bank.MemoryBank()
    section = next(s for s in plan["report_toc"] if s["id"] == sid)
    writer.write_section(
        plan=plan,
        unit={"id": sid, "title": section["title"], "depth": "broad", "subs": section["subsections"]},
        bank=bank,
        prior_titles=[s["title"] for s in plan["report_toc"]],
        archetype="compare",
        prompt="test",
        language="en",
        domain="default",
    )
    return captured


def _tr_with_scores():
    return {
        "title": "Tier Ranking",
        "scoring_formula": "S_final = Σ(weight_i × dim_i)",
        "weights": {"R-1": 0.5, "R-2": 0.5},
        "tiers": [{"name": "Tier 1", "threshold": ">=8.0"}, {"name": "Tier 2", "threshold": "<8.0"}],
        "sensitivity_check": {"perturbation_pp": 10},
        "entities_scored": [
            {"name": "Alpha", "dimension_scores": {"R-1": 9.0, "R-2": 8.0}, "S_final": 8.5, "tier": "Tier 1"},
        ],
    }


def test_writer_renders_pre_scored_values_2dp(monkeypatch):
    """When entities_scored is present, the writer prompt carries the verbatim
    2-decimal values + the 'render verbatim' directive."""
    plan = _bare_plan_with_tier_ranking(_tr_with_scores())
    user = _call_writer(monkeypatch, plan, "S7")[0]["user"]
    assert "PRE-COMPUTED SCORES" in user
    assert "render" in user.lower() and "verbatim" in user.lower()
    # 8.5 (float) must be formatted to "8.50" so the 2-decimal validator passes.
    assert "8.50" in user, f"S_final not formatted to 2dp; got prompt slice: {user[user.find('PRE-COMPUTED') :][:400]}"
    assert "9.00" in user  # dimension score 9.0 → "9.00"


def test_writer_falls_back_to_compute_when_no_scores(monkeypatch):
    """No entities_scored → the writer reverts to the pre-PR compute directive
    (no PRE-COMPUTED SCORES block, but still the tier-ranking contract)."""
    tr = _tr_with_scores()
    del tr["entities_scored"]
    plan = _bare_plan_with_tier_ranking(tr)
    user = _call_writer(monkeypatch, plan, "S7")[0]["user"]
    assert "PRE-COMPUTED SCORES" not in user
    assert "TIER RANKING + SENSITIVITY CHECK CONTRACT" in user
    assert "2 DECIMAL PLACES" in user  # the compute directive's precision rule


def test_writer_sensitivity_uses_normalized_weights(monkeypatch):
    """Greptile PR #51 round-2: in the pre-scored path the sensitivity directive
    must hand the writer NORMALIZED weights (summing to 1.0), matching the
    pre-computed S_final baseline — NOT the raw architect weights, which may not
    sum to 1.0 and would reintroduce an inconsistent sensitivity baseline."""
    tr = _tr_with_scores()
    tr["weights"] = {"R-1": 5, "R-2": 5}  # raw, sum=10 → normalized 0.5/0.5
    plan = _bare_plan_with_tier_ranking(tr)
    user = _call_writer(monkeypatch, plan, "S7")[0]["user"]
    assert "NORMALIZED weights" in user
    # The normalized values (0.5/0.5) appear for the sensitivity baseline.
    assert '"R-1": 0.5' in user and '"R-2": 0.5' in user


def test_writer_skips_entry_with_non_numeric_s_final(monkeypatch):
    """Greptile PR #51 round-2: an entry with a valid name but a non-numeric
    S_final must be skipped, not rendered as literal `null` (which the verbatim
    directive would tell the writer to copy, failing the 2-decimal validator).
    With one good + one bad entry, only the good one reaches the prompt."""
    tr = _tr_with_scores()
    tr["entities_scored"] = [
        {"name": "Alpha", "dimension_scores": {"R-1": 9.0, "R-2": 8.0}, "S_final": 8.5, "tier": "Tier 1"},
        {"name": "Bad", "dimension_scores": {"R-1": 7.0}, "S_final": None, "tier": "Tier 2"},
    ]
    plan = _bare_plan_with_tier_ranking(tr)
    user = _call_writer(monkeypatch, plan, "S7")[0]["user"]
    assert "PRE-COMPUTED SCORES" in user  # Alpha is valid → render path fires
    assert "8.50" in user and "Alpha" in user
    assert "null" not in user, "non-numeric S_final must not reach the prompt as null"
    assert '"name": "Bad"' not in user


def test_writer_falls_back_when_all_entries_have_bad_s_final(monkeypatch):
    """If every entry has a non-numeric S_final, display empties → the writer
    falls through to the compute directive (no PRE-COMPUTED SCORES block)."""
    tr = _tr_with_scores()
    tr["entities_scored"] = [{"name": "Bad", "dimension_scores": {"R-1": 7.0}, "S_final": None, "tier": "Tier 2"}]
    plan = _bare_plan_with_tier_ranking(tr)
    user = _call_writer(monkeypatch, plan, "S7")[0]["user"]
    assert "PRE-COMPUTED SCORES" not in user
    assert "TIER RANKING + SENSITIVITY CHECK CONTRACT" in user


def test_build_forwards_task_id_and_attaches_scores(monkeypatch):
    """Through the REAL build(): task_id is forwarded to score_entities (for the
    per-task ledger note) AND the non-None result is attached to
    plan['tier_ranking']['entities_scored']. Covers both the task_id plumbing
    (Greptile #51 r2) and the attachment guard (Greptile #51 r3) in one shot —
    a regression in either is caught because build() is actually invoked."""
    from deep_research.pipeline import architect

    captured = {}
    sentinel = [{"name": "Alpha", "dimension_scores": {"R-1": 8.0}, "S_final": 8.0, "tier": "Tier 1"}]

    def fake_score(plan, language, task_id=None):
        captured["task_id"] = task_id
        return sentinel

    monkeypatch.setattr(architect.tier_ranking_score, "score_entities", fake_score)
    monkeypatch.setattr(architect.llm, "call_json", lambda *a, **k: _stub_llm_plan_with_tier())
    plan = architect.build("p", "en", "predict", [], {}, [], task_id=42)
    assert captured["task_id"] == 42
    assert plan["tier_ranking"]["entities_scored"] == sentinel
