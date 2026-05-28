"""P3-W5.b (2026-05-27): writer LIMITATIONS CHAPTER CONTRACT directive tests.

The architect emits `plan["limitations_chapter"]` for predict / compare /
explain-mechanism / list-all archetypes (architect.py schema lines 180-210).
The writer's `limitations_block` (writer.py, after framing_block) must
inject a structural directive into the user prompt ONLY when the section
currently being written IS the limitations chapter (matched by title).
All other sections pass through unchanged.

Tests pin:
- directive renders on title match (with required & optional fields)
- directive absent when plan field is null / wrong type / empty sub-sections
- directive absent when section title doesn't match the artifact's title
- scenario_stress_test sub-block emits only when sst dict present
- complex sub_section objects preserved verbatim through JSON serialization
"""

from deep_research.pipeline import memory_bank, writer


def _bare_plan_with_limitations(lc, *, lim_section_id="S3", lim_title="Limitations"):
    """Construct a minimal plan with a limitations chapter at the named
    section. Two prior sections so the writer has prior context."""
    return {
        "report_title": "T",
        "report_toc": [
            {"id": "S1", "title": "Intro", "subsections": [{"id": "S1.1", "title": "Sub", "depth_seeds": []}]},
            {"id": "S2", "title": "Body", "subsections": [{"id": "S2.1", "title": "Sub", "depth_seeds": []}]},
            {
                "id": lim_section_id,
                "title": lim_title,
                "subsections": [{"id": f"{lim_section_id}.1", "title": "Sub", "depth_seeds": []}],
            },
        ],
        "acceptance_criteria": [],
        "queries": [],
        "limitations_chapter": lc,
    }


def _capture_writer_call(monkeypatch):
    captured = []

    def fake_llm_call(role, user, *, system, max_tokens, note, **kw):
        captured.append({"role": role, "user": user, "system": system})
        return "## body\n"

    monkeypatch.setattr(writer.llm, "call", fake_llm_call)
    return captured


def _call_writer(monkeypatch, plan, sid, *, archetype="predict", language="en"):
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


def _full_lc(**overrides):
    """Canonical 5-sub-section limitations chapter object (no
    scenario_stress_test by default)."""
    lc = {
        "title": "Limitations",
        "sub_sections": [
            {
                "id": "S3.1",
                "type": "data_granularity",
                "title": "Data Granularity",
                "content_directive": "Name a specific observable.",
            },
            {"id": "S3.2", "type": "scope_cap", "title": "Scope Cap", "content_directive": "Cite §1 scope verbatim."},
            {
                "id": "S3.3",
                "type": "time_validity",
                "title": "Time Validity",
                "content_directive": "Name a year boundary.",
            },
            {
                "id": "S3.4",
                "type": "sampling",
                "title": "Sampling",
                "content_directive": "Name an under-represented entity class.",
            },
            {
                "id": "S3.5",
                "type": "falsifiers",
                "title": "Falsifiers",
                "content_directive": "Name 2-3 specific observations.",
            },
        ],
        "scenario_stress_test": None,
    }
    lc.update(overrides)
    return lc


# ---------- presence / gating tests ----------


def test_limitations_chapter_directive_renders_on_title_match(monkeypatch):
    """When the section currently being written matches the
    limitations chapter title, the writer prompt MUST include
    LIMITATIONS CHAPTER CONTRACT + the 5 sub-section types verbatim."""
    plan = _bare_plan_with_limitations(_full_lc())
    captured = _call_writer(monkeypatch, plan, sid="S3")
    user = captured[0]["user"]
    assert "LIMITATIONS CHAPTER CONTRACT" in user, (
        f"limitations directive missing on the section that IS the limitations chapter; got: {user[:2000]}"
    )
    # All 5 sub-section TYPES appear in the JSON payload
    for t in ("data_granularity", "scope_cap", "time_validity", "sampling", "falsifiers"):
        assert t in user, f"sub-section type `{t}` missing from prompt; got: {user[:3000]}"


def test_limitations_chapter_directive_absent_on_non_limitations_section(monkeypatch):
    """Non-limitations sections (S1, S2) must NOT receive the directive
    even though the plan carries a limitations_chapter — the chapter
    contract is a per-section payload, not a global one."""
    plan = _bare_plan_with_limitations(_full_lc())
    for sid in ("S1", "S2"):
        captured = _call_writer(monkeypatch, plan, sid=sid)
        user = captured[0]["user"]
        assert "LIMITATIONS CHAPTER CONTRACT" not in user, (
            f"limitations directive leaked into non-limitations section {sid}; got: {user[:2000]}"
        )


def test_limitations_chapter_directive_absent_when_plan_field_missing(monkeypatch):
    """A plan without `limitations_chapter` key (back-compat with
    pre-P3-W5 plans, OR a trend archetype where the chapter is
    optional) fires no directive on any section."""
    plan = _bare_plan_with_limitations(_full_lc())
    plan.pop("limitations_chapter")
    captured = _call_writer(monkeypatch, plan, sid="S3")
    user = captured[0]["user"]
    assert "LIMITATIONS CHAPTER CONTRACT" not in user, (
        f"limitations directive fired with no plan field; got: {user[:2000]}"
    )


def test_limitations_chapter_directive_absent_when_plan_field_null(monkeypatch):
    """Architect emits `limitations_chapter: None` for trend / recommend
    archetypes; this is distinct from key absent. Writer must treat
    both as "no chapter" and skip the directive."""
    plan = _bare_plan_with_limitations(_full_lc())
    plan["limitations_chapter"] = None
    captured = _call_writer(monkeypatch, plan, sid="S3")
    user = captured[0]["user"]
    assert "LIMITATIONS CHAPTER CONTRACT" not in user


def test_limitations_chapter_directive_absent_when_sub_sections_empty(monkeypatch):
    """Empty `sub_sections` array → no directive. The architect may
    emit a chapter object with title but empty sub_sections if a
    malformed run produced no usable sub-sections; writer must not
    render an empty directive."""
    plan = _bare_plan_with_limitations(_full_lc(sub_sections=[]))
    captured = _call_writer(monkeypatch, plan, sid="S3")
    user = captured[0]["user"]
    assert "LIMITATIONS CHAPTER CONTRACT" not in user


def test_limitations_chapter_directive_absent_on_title_mismatch(monkeypatch):
    """When `unit['title']` doesn't match `limitations_chapter.title`,
    the directive must not render. This is the safety net against
    title drift between architect plan and TOC; a renamed chapter
    silently disables the directive rather than mis-rendering."""
    plan = _bare_plan_with_limitations(_full_lc(title="Limitations of Method"))
    # Section S3 has title "Limitations" (from _bare_plan default);
    # plan says the limitations chapter is titled "Limitations of Method".
    captured = _call_writer(monkeypatch, plan, sid="S3")
    user = captured[0]["user"]
    assert "LIMITATIONS CHAPTER CONTRACT" not in user, (
        f"directive fired despite title mismatch (unit title='Limitations' vs plan title='Limitations of Method'); got: {user[:2000]}"
    )


# ---------- scenario_stress_test conditional tests ----------


def test_scenario_stress_test_block_absent_when_sst_null(monkeypatch):
    """The `scenario_stress_test` sub-block is predict-archetype-only;
    when sst is None (default), the directive omits it."""
    plan = _bare_plan_with_limitations(_full_lc())
    captured = _call_writer(monkeypatch, plan, sid="S3")
    user = captured[0]["user"]
    assert "SCENARIO STRESS TEST" not in user, f"sst block fired with null scenario_stress_test; got: {user[:3000]}"


def test_scenario_stress_test_block_present_with_defaults_when_sst_empty_dict(monkeypatch):
    """Greptile-style edge case: empty dict `{}` is truthy-distinct from
    None. The architect may emit `{}` when scenarios couldn't be
    enumerated; per writer.py guard `isinstance(sst, dict)` admits empty
    dicts, and the directive inside falls back to safe defaults if
    scenarios/recompute_target are absent. Tightest contract: empty dict
    produces a directive with DEFAULT scenarios + default
    recompute_target — the block IS present, with defaults."""
    plan = _bare_plan_with_limitations(_full_lc(scenario_stress_test={}))
    captured = _call_writer(monkeypatch, plan, sid="S3")
    user = captured[0]["user"]
    # Empty dict IS a dict → block emits with defaults.
    assert "SCENARIO STRESS TEST" in user
    # Default scenarios ["base", "optimistic", "pessimistic"] used.
    assert "base" in user and "optimistic" in user and "pessimistic" in user


def test_scenario_stress_test_block_renders_with_explicit_scenarios(monkeypatch):
    """When `scenario_stress_test.scenarios` is populated, those exact
    scenario labels must appear in the writer prompt verbatim."""
    plan = _bare_plan_with_limitations(
        _full_lc(
            scenario_stress_test={
                "scenarios": ["low-uptake", "median", "high-uptake"],
                "recompute_target": "tier_ranking",
            }
        )
    )
    captured = _call_writer(monkeypatch, plan, sid="S3")
    user = captured[0]["user"]
    assert "SCENARIO STRESS TEST" in user
    for s in ("low-uptake", "median", "high-uptake"):
        assert s in user, f"scenario `{s}` missing; got: {user[:3000]}"


def test_scenario_stress_test_block_handles_non_dict_gracefully(monkeypatch):
    """A malformed `scenario_stress_test` (e.g., list instead of dict)
    must NOT crash the writer. Falls back to no sst block (defensive
    isinstance check). Greptile pre-scan: empty truthy check fails."""
    plan = _bare_plan_with_limitations(_full_lc(scenario_stress_test=["base", "alt"]))
    captured = _call_writer(monkeypatch, plan, sid="S3")
    user = captured[0]["user"]
    # Main directive still fires (the chapter contract is independent
    # of the sst sub-block).
    assert "LIMITATIONS CHAPTER CONTRACT" in user
    # But the sst block does NOT fire on non-dict input.
    assert "SCENARIO STRESS TEST" not in user


# ---------- complex-object preservation ----------


def test_limitations_sub_sections_preserved_in_json_payload(monkeypatch):
    """The architect's per-sub-section `content_directive` must reach
    the writer (otherwise the directive's structure-only payload would
    let the writer LLM invent its own content). Pin verbatim survival."""
    custom_directive = "MUST cite the §1.2 R-3 transparency-criterion verbatim."
    lc = _full_lc()
    lc["sub_sections"][4]["content_directive"] = custom_directive
    plan = _bare_plan_with_limitations(lc)
    captured = _call_writer(monkeypatch, plan, sid="S3")
    user = captured[0]["user"]
    assert custom_directive in user, f"content_directive lost in serialization; got: {user[:3000]}"


def test_limitations_block_appears_after_framing_block_in_prompt(monkeypatch):
    """Ordering invariant: `{framing_block}` precedes `{limitations_block}`
    in the user-prompt assembly so the limitations chapter can reference
    the §1 framing's rubric items by id (R-N) that were just published."""
    plan = _bare_plan_with_limitations(_full_lc())
    # Add a minimal framing_chapter so both blocks fire on §1 vs §3.
    plan["framing_chapter"] = {
        "title": "Framework",
        "sub_sections": [{"id": "S1.1", "type": "scope", "title": "Scope", "content_directive": "..."}],
        "published_vocabulary": ["term1"],
        "published_rubric_items": [{"id": "R-1", "label": "Quality", "weight": 1.0}],
    }
    plan["report_toc"][0]["title"] = "Framework"  # so S1 also matches framing
    # Call S3 (limitations chapter); S1 framing block is the "downstream
    # consumer" (NAMED TERM BANK), and limitations comes after.
    captured = _call_writer(monkeypatch, plan, sid="S3")
    user = captured[0]["user"]
    tb_pos = user.find("NAMED TERM BANK")
    lim_pos = user.find("LIMITATIONS CHAPTER CONTRACT")
    assert tb_pos >= 0 and lim_pos >= 0, f"both blocks must render on S3; got positions tb={tb_pos}, lim={lim_pos}"
    assert tb_pos < lim_pos, (
        f"NAMED TERM BANK (downstream framing consumer) must precede LIMITATIONS CHAPTER CONTRACT "
        f"so limitations can reference the rubric items by id; got tb={tb_pos}, lim={lim_pos}"
    )
