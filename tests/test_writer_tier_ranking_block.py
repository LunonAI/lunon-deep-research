"""P3-W7.b (2026-05-27): writer TIER RANKING + SENSITIVITY CHECK CONTRACT tests.

The architect emits `plan["tier_ranking"]` (architect.py schema lines
153-179) for compare / predict archetypes with ≥5 entities and ≥4
rubric dimensions. The writer's `tier_ranking_block` must inject the
scoring-formula + weights + tiers + sensitivity-check contract into
the user prompt ONLY when the section currently being written IS the
tier-ranking chapter (matched by title).

Greptile pre-scan: `bool` is a subclass of `int`, so a naive
`isinstance(v, (int, float))` would silently admit `True`/`False` as
weight values OR perturbation_pp. Both filters explicitly exclude
bool.
"""

from deep_research.pipeline import memory_bank, writer


def _bare_plan_with_tier_ranking(tr, *, tr_section_id="S7", tr_title="Tier Ranking"):
    """Plan with a tier_ranking chapter at the named section."""
    return {
        "report_title": "T",
        "report_toc": [
            {"id": "S1", "title": "Intro", "subsections": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}]},
            {"id": "S2", "title": "Body", "subsections": [{"id": "S2.1", "title": "Sub", "depth_seeds": []}]},
            {
                "id": tr_section_id,
                "title": tr_title,
                "subsections": [{"id": f"{tr_section_id}.1", "title": "Sub", "depth_seeds": []}],
            },
        ],
        "acceptance_criteria": [],
        "queries": [],
        "tier_ranking": tr,
    }


def _capture_writer_call(monkeypatch):
    captured = []

    def fake_llm_call(role, user, *, system, max_tokens, note, **kw):
        captured.append({"role": role, "user": user, "system": system})
        return "## body\n"

    monkeypatch.setattr(writer.llm, "call", fake_llm_call)
    return captured


def _call_writer(monkeypatch, plan, sid, *, archetype="compare", language="en"):
    captured = _capture_writer_call(monkeypatch)
    bank = memory_bank.MemoryBank()
    section = next(s for s in plan["report_toc"] if s["id"] == sid)
    writer.write_section(
        plan=plan,
        unit={"id": sid, "title": section["title"], "depth": "broad", "subs": section["subsections"]},
        bank=bank,
        prior_titles=[s["title"] for s in plan["report_toc"]],
        archetype=archetype,
        prompt="test",
        language=language,
        domain="default",
    )
    return captured


def _full_tr(**overrides):
    """Canonical tier_ranking with 3 weights + 3 tiers + sensitivity check."""
    tr = {
        "title": "Tier Ranking",
        "scoring_formula": "S_final = Σ(weight_i × dim_i)",
        "weights": {"R-1": 0.4, "R-2": 0.35, "R-3": 0.25},
        "tiers": [
            {"name": "Tier 1", "threshold": ">=8.0"},
            {"name": "Tier 2", "threshold": ">=6.0"},
            {"name": "Tier 3", "threshold": "<6.0"},
        ],
        "sensitivity_check": {"perturbation_pp": 10, "report": "rank_stability"},
    }
    tr.update(overrides)
    return tr


# ---------- presence / gating ----------


def test_tier_ranking_directive_renders_on_title_match(monkeypatch):
    """When the section being written IS the tier_ranking chapter, the
    writer prompt MUST include TIER RANKING + SENSITIVITY CHECK CONTRACT
    + weights + tiers + scoring_formula verbatim."""
    plan = _bare_plan_with_tier_ranking(_full_tr())
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    assert "TIER RANKING + SENSITIVITY CHECK CONTRACT" in user, f"directive missing; got: {user[:2000]}"
    assert "S_final = Σ(weight_i × dim_i)" in user
    for rubric_id in ("R-1", "R-2", "R-3"):
        assert rubric_id in user, f"rubric id `{rubric_id}` missing from prompt; got: {user[:3000]}"
    for tier in ("Tier 1", "Tier 2", "Tier 3"):
        assert tier in user, f"tier name `{tier}` missing"


def test_tier_ranking_directive_absent_on_non_tier_section(monkeypatch):
    """Non-tier sections (S1, S2) must NOT receive the directive."""
    plan = _bare_plan_with_tier_ranking(_full_tr())
    for sid in ("S1", "S2"):
        captured = _call_writer(monkeypatch, plan, sid=sid)
        user = captured[0]["user"]
        assert "TIER RANKING + SENSITIVITY CHECK CONTRACT" not in user, (
            f"directive leaked into non-tier section {sid}; got: {user[:2000]}"
        )


def test_tier_ranking_directive_absent_when_plan_field_null(monkeypatch):
    """Architect emits `tier_ranking: None` for list-all / trend (not
    applicable archetypes); writer skips the directive."""
    plan = _bare_plan_with_tier_ranking(_full_tr())
    plan["tier_ranking"] = None
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    assert "TIER RANKING + SENSITIVITY CHECK CONTRACT" not in user


def test_tier_ranking_directive_absent_on_title_mismatch(monkeypatch):
    """Title drift → directive skipped."""
    plan = _bare_plan_with_tier_ranking(_full_tr(title="Sector Rankings"))
    # S7 title = "Tier Ranking" (plan default); tr.title = "Sector Rankings"
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    assert "TIER RANKING + SENSITIVITY CHECK CONTRACT" not in user


def test_tier_ranking_directive_absent_when_weights_empty(monkeypatch):
    """Empty weights dict → no directive (the architect produced an
    incomplete chapter; writer must not render a degenerate one)."""
    plan = _bare_plan_with_tier_ranking(_full_tr(weights={}))
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    assert "TIER RANKING + SENSITIVITY CHECK CONTRACT" not in user


def test_tier_ranking_directive_absent_when_tiers_empty(monkeypatch):
    """Empty tiers list → no directive (a scoring scheme without tiers
    is meaningless for the chapter; writer skips)."""
    plan = _bare_plan_with_tier_ranking(_full_tr(tiers=[]))
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    assert "TIER RANKING + SENSITIVITY CHECK CONTRACT" not in user


# ---------- bool-subclass-of-int filters (W7 PR #43 round-3 regression bar) ----------


def test_tier_ranking_directive_excludes_bool_weight_values(monkeypatch):
    """Greptile pre-scan from W7 PR #43 round-3: `True`/`False` would
    silently pass `isinstance(v, (int, float))` because bool is a
    subclass of int. Filter must explicitly exclude bool to prevent
    a malformed plan with `weights={'R-1': True}` from being rendered
    as a numeric weight."""
    plan = _bare_plan_with_tier_ranking(_full_tr(weights={"R-1": True, "R-2": False, "R-3": 0.5}))
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    # Directive should still fire — there's 1 valid numeric weight.
    assert "TIER RANKING + SENSITIVITY CHECK CONTRACT" in user
    # The bool weights should NOT appear in the JSON-serialized payload.
    # We can verify by checking the serialized dict has only R-3.
    assert '"R-3": 0.5' in user
    # Greptile PR #47 round-4: assert BOTH forbidden JSON fragments
    # directly. The prior `A or B` form was logically weak — `or`
    # short-circuits true on either leg, so a regression that only
    # dropped one of the two bool weights (e.g., filtered `R-1` but
    # leaked `R-2`) would still satisfy the assertion. Two explicit
    # `not in` checks force both weights to be excluded.
    weights_idx = user.find("Weights")
    rules_after = user[weights_idx : weights_idx + 500] if weights_idx >= 0 else ""
    assert '"R-1": true' not in rules_after, f"bool `R-1: True` leaked into weights payload: {rules_after}"
    assert '"R-2": false' not in rules_after, f"bool `R-2: False` leaked into weights payload: {rules_after}"


def test_tier_ranking_directive_falls_back_perturbation_pp_when_bool(monkeypatch):
    """Same bool-subclass guard on `perturbation_pp`. A malformed plan
    with `sensitivity_check.perturbation_pp = True` falls back to the
    default `10`, not the integer `1` (True coerces to 1)."""
    tr = _full_tr(sensitivity_check={"perturbation_pp": True, "report": "rank_stability"})
    plan = _bare_plan_with_tier_ranking(tr)
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    # Default 10pp used, not 1pp from bool-as-int coercion.
    assert "±10pp" in user
    assert "±1pp" not in user


def test_tier_ranking_directive_uses_explicit_perturbation_pp(monkeypatch):
    """A real int perturbation_pp overrides the default. The active
    perturbation appears in the operative directive lines (heading
    anchor + recompute instruction). The historical Qianfan-corpus
    reference line in the preamble (`q3 §8.1 ... with ±10pp
    sensitivity`) is hardcoded and is NOT affected by the override —
    that's intentional, since it's a corpus citation, not the
    operative perturbation."""
    tr = _full_tr(sensitivity_check={"perturbation_pp": 15, "report": "rank_stability"})
    plan = _bare_plan_with_tier_ranking(tr)
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    assert "±15pp" in user, f"explicit perturbation_pp=15 not interpolated into directive; got: {user[:3000]}"


def test_tier_ranking_directive_accepts_float_perturbation_pp(monkeypatch):
    """Greptile PR #47 round-2: `perturbation_pp` emitted as a float
    (e.g. `10.0` from a JSON deserializer that doesn't distinguish
    int from int-valued float) was previously silently rejected by
    `isinstance(raw_pp, int)` and fell back to the default 10 with
    no signal. Post-fix, floats are int-coerced so the directive
    interpolates a clean integer (`±15pp` not `±15.0pp`).

    Fixture: explicit `15.0` float — pre-fix would silently fall back
    to 10 (no signal); post-fix uses 15 and interpolates `±15pp`.
    """
    tr = _full_tr(sensitivity_check={"perturbation_pp": 15.0, "report": "rank_stability"})
    plan = _bare_plan_with_tier_ranking(tr)
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    # The active perturbation must be 15 (from the float), not 10 (default).
    assert "±15pp" in user, f"float perturbation_pp=15.0 not int-coerced + interpolated; got: {user[:3000]}"
    # And the malformed float-as-string form must NOT leak through.
    assert "±15.0pp" not in user, f"float should int-coerce; the .0 leaked into the directive: {user[:3000]}"


def test_tier_ranking_directive_falls_back_perturbation_pp_when_string(monkeypatch):
    """Symmetric to the float case: a non-numeric perturbation_pp
    (e.g. `"ten"`) falls back to the default 10 — the type guard now
    accepts only `int` and `float` (with explicit bool exclusion)."""
    tr = _full_tr(sensitivity_check={"perturbation_pp": "ten", "report": "rank_stability"})
    plan = _bare_plan_with_tier_ranking(tr)
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    assert "±10pp" in user, f"non-numeric perturbation_pp should fall back to 10; got: {user[:3000]}"


# ---------- content / contract checks ----------


def test_tier_ranking_directive_includes_2_decimal_precision_rule(monkeypatch):
    """The 2-decimal precision rule is the most-mistakable signal —
    Lunon's pre-W7.b writer often emitted 1-decimal scores (7.5)."""
    plan = _bare_plan_with_tier_ranking(_full_tr())
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    assert "2 DECIMAL PLACES" in user or "2 decimal" in user.lower()
    # The example values 7.45, 6.32, 8.81 SHOULD appear as concrete
    # exemplars
    assert "7.45" in user or "6.32" in user


def test_tier_ranking_directive_includes_computational_not_narrative_rule(monkeypatch):
    """The sensitivity check must be computational (actual recomputed
    S_final), not narrative. This is the Lunon-specific failure mode
    the directive's pre-W7.b absence allowed."""
    plan = _bare_plan_with_tier_ranking(_full_tr())
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    assert "COMPUTATIONAL" in user or "computational" in user.lower()
    assert "hallucinat" in user.lower() or "narrative" in user.lower()


def test_tier_ranking_directive_handles_non_dict_sensitivity(monkeypatch):
    """A malformed `sensitivity_check` (e.g., list) must not crash;
    falls back to default ±10pp (sensitivity present in spirit)."""
    plan = _bare_plan_with_tier_ranking(_full_tr(sensitivity_check=["bad"]))
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    assert "TIER RANKING + SENSITIVITY CHECK CONTRACT" in user
    assert "±10pp" in user  # default


def test_tier_ranking_directive_handles_missing_scoring_formula(monkeypatch):
    """When the architect doesn't supply a scoring_formula, fall back to
    the default `S_final = Σ(weight_i × dim_i)` so the directive still
    fires with a sensible default."""
    tr = _full_tr()
    tr.pop("scoring_formula")
    plan = _bare_plan_with_tier_ranking(tr)
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    assert "S_final = Σ(weight_i × dim_i)" in user


def test_tier_ranking_directive_handles_non_dict_weights(monkeypatch):
    """Malformed `weights` (e.g., list, str) must not crash; treat as
    empty → directive skipped."""
    plan = _bare_plan_with_tier_ranking(_full_tr(weights=[("R-1", 0.5)]))
    captured = _call_writer(monkeypatch, plan, sid="S7")
    user = captured[0]["user"]
    assert "TIER RANKING + SENSITIVITY CHECK CONTRACT" not in user
