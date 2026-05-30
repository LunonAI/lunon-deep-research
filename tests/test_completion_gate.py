"""L1 (2026-05-29): chapter-completion gate helpers.

The inner loop accepted a section on grounding + quality score but never on
COMPLETENESS, so thin-but-coherent chapters passed (the "hollow late chapter"
failure vs Qianfan — id38 §5 = 185 chars vs a multi-thousand-token target).
These pin the completeness helpers that now gate acceptance + drive the
expand-retry + the hollow-chapter telemetry.
"""

from deep_research import orchestrate as o


def test_approx_tokens_en_and_cjk():
    # EN ~4 chars/token; CJK ~1.6 chars/token.
    assert 40 <= o._approx_tokens("x" * 200) <= 60
    assert o._approx_tokens("研究背景与方法" * 10) > o._approx_tokens("x" * 70)  # CJK denser per char


def test_approx_tokens_counts_cjk_extension_a():
    """Greptile PR #69 round-1: CJK Extension A ideographs (U+3400–U+4DBF) are
    billed at the dense CJK rate (~1.6 chars/token), not the sparse ~4 chars/token
    'other' rate — matching cjk_despace._CJK. Before the fix an Ext-A char was
    counted as 'other' and `_approx_tokens` matched the EN baseline exactly."""
    # 16 Ext-A ideographs vs 16 ASCII chars: CJK rate must yield a higher estimate.
    assert o._approx_tokens("㐀㐁㐂㐃㐄㐅㐆㐇㐈㐉㐊㐋㐌㐍㐎㐏") > o._approx_tokens("x" * 16)


def test_approx_tokens_strips_heading_lines():
    body = "## 1 Heading That Is Quite Long And Wordy\n\nshort body."
    # Heading line excluded → count reflects body only, not the long heading.
    assert o._approx_tokens(body) < o._approx_tokens("## h\n\n" + "word " * 100)


def test_section_too_thin_severe_shortfall_flagged():
    assert o._section_too_thin("x" * 185, 1200) is True  # the id38 §5 case


def test_section_full_length_not_thin():
    assert o._section_too_thin("word " * 1200, 1200) is False


def test_section_too_thin_guards_zero_expected():
    # No declared target → never flagged (avoid false positives on untargeted units).
    assert o._section_too_thin("x" * 10, 0) is False
    assert o._section_too_thin("x" * 10, None) is False


def test_section_just_above_half_not_thin():
    # 0.5x is the bar; a section at ~0.6x its target is NOT flagged (only SEVERE
    # shortfalls fire, so legitimately-concise sections aren't churned).
    text = "word " * 760  # ~760 tokens vs 1200 target = 0.63x
    assert o._section_too_thin(text, 1200) is False


def test_expand_feedback_directs_full_development():
    fb = o._expand_feedback(1500)
    assert "COMPLETENESS" in fb and "1500" in fb
    assert "stub" in fb.lower() and "expand" in fb.lower()


def test_expected_tok_for_default_when_no_scaffold():
    assert o._expected_tok_for(None, "S1") == 1200


def test_scaffold_section_effective_length_fallback():
    """Greptile PR #69 round-2: ScaffoldSection.effective_length_tokens is the
    SINGLE source of truth for the None/0→1200 fallback that both
    orchestrate._expected_tok_for and validation.run rely on for int-safe
    `int(0.7 * …)` arithmetic."""
    from deep_research.state import ScaffoldSection

    def sec(v):
        return ScaffoldSection(section_id="S1", title="T", expected_length_tokens=v)

    assert sec(None).effective_length_tokens == 1200
    assert sec(0).effective_length_tokens == 1200
    assert sec(900).effective_length_tokens == 900
    # The arithmetic that previously crashed on a None target is now safe.
    assert int(0.7 * sec(None).effective_length_tokens) == 840


def test_expected_tok_for_falls_back_when_length_unset():
    """Greptile PR #69 round-2: a scaffold section whose expected_length_tokens is
    unset (None) or zero falls back to the 1200 default, honoring the `-> int`
    return contract — it must never leak None to arithmetic callers like the
    `int(0.7 * expected_tok)` length-target line in _write_with_guide."""
    from deep_research.state import Scaffold, ScaffoldSection

    sc_none = Scaffold(sections=[ScaffoldSection(section_id="S1", title="T", expected_length_tokens=None)])
    assert o._expected_tok_for(sc_none, "S1") == 1200
    sc_zero = Scaffold(sections=[ScaffoldSection(section_id="S1", title="T", expected_length_tokens=0)])
    assert o._expected_tok_for(sc_zero, "S1") == 1200
    # A real positive target is returned unchanged.
    sc_900 = Scaffold(sections=[ScaffoldSection(section_id="S1", title="T", expected_length_tokens=900)])
    assert o._expected_tok_for(sc_900, "S1") == 900


def test_validation_length_walk_safe_on_unset_target():
    """Greptile PR #69 round-2: validation.run's section-length walk reads the
    target through ScaffoldSection.effective_length_tokens, so a section with an
    unset (None) expected_length_tokens no longer crashes the `int(0.7 * …)`
    arithmetic — it is graded against the 1200 floor (min_tok 840) like any other."""
    from deep_research.pipeline import validation
    from deep_research.state import DesignGuide, Scaffold, ScaffoldSection

    inp = validation.ValidationInput(
        article="# Report\n\n## Intro\n\nShort body only.\n",
        plan={},
        scaffold=Scaffold(sections=[ScaffoldSection(section_id="S1", title="Intro", expected_length_tokens=None)]),
        design_guide=DesignGuide(),
        language="en",
        domain="default",
        task_id="test",
    )
    out = validation.run(inp)  # pre-fix: TypeError on int(0.7 * None)
    short = [f for f in out.failures if f.get("check") == "section_min_length"]
    assert short, "the thin Intro section should be flagged short"
    assert short[0]["detail"][0]["min_tok"] == 840  # = int(0.7 * 1200) → fallback applied


def test_thin_and_ungrounded_section_gets_expand_directive(monkeypatch):
    """Greptile PR #69 round-2: a section that fails grounding AND is hollow must
    hear BOTH signals. Drive the inner loop with grounding forced to fail and a
    persistently-thin draft, then assert the rewrite feedback combines the
    grounding text with the COMPLETENESS/expand directive. Pre-fix the grounding-
    fail branch rewrote on grounding-only feedback and `continue`d, so the expand
    directive was unreachable on that path."""
    from deep_research.state import PipelineState, Scaffold, ScaffoldSection

    captured = []

    monkeypatch.setattr(o.writer, "outline_units", lambda plan: [{"id": "S1", "title": "T"}])
    monkeypatch.setattr(o.grounding, "check", lambda *a, **k: {"ok": False})
    monkeypatch.setattr(o.grounding, "feedback_text", lambda g: "GROUNDFB")

    def fake_write(u, plan, bank, query, language, archetype, domain, prior_titles, guide, scaffold, *, task_id=None, feedback=""):
        captured.append(feedback)
        return "Too short.", {}  # well below the 1200-token target → always thin

    monkeypatch.setattr(o, "_write_with_guide", fake_write)

    class _Bank:
        def for_section(self, sid, max_blocks=40):
            return []

    s = PipelineState(
        query="q",
        language="en",
        archetype={"archetype": "x"},  # not 'explain-mechanism' → skip CAPEL branch
        domain="default",
        spec={},
        plan={},
        scaffold=Scaffold(sections=[ScaffoldSection(section_id="S1", title="T", expected_length_tokens=1200)]),
        memory_bank=_Bank(),
        task_id=None,
    )

    o._run_section_loop(s, "q", "en")

    rewrite_fbs = [fb for fb in captured if fb]  # the initial-draft call passes feedback=""
    assert rewrite_fbs, "no rewrite feedback captured"
    assert any(
        "GROUNDFB" in fb and "COMPLETENESS" in fb and "1200" in fb for fb in rewrite_fbs
    ), f"grounding-fail rewrite never combined grounding + expand directive: {rewrite_fbs}"
    # And the section is still flagged hollow in completion telemetry.
    assert s.completion_stats["n_hollow_final"] == 1
    # L1b smoking gun: the per-section record carries the routed evidence count
    # (0 here → the _Bank returns []), the chapter position, and the thinness
    # ratio — so the dev6 can attribute hollowness to research starvation
    # (empty slice) vs writer-budget (full slice).
    secs = s.completion_stats["sections"]
    assert len(secs) == 1
    rec = secs[0]
    assert rec["section"] == "S1" and rec["idx"] == 0
    assert rec["evidence_blocks"] == 0  # _Bank.for_section → []
    assert rec["final_thin"] is True
    assert rec["thin_ratio"] is not None and rec["thin_ratio"] < o._COMPLETION_MIN_RATIO


def test_ends_mid_sentence_detector():
    # complete prose tail → not flagged
    assert o._ends_mid_sentence("A full sentence ends here.") is False
    assert o._ends_mid_sentence("一个完整的句子。") is False
    # truncated mid-sentence → flagged
    assert o._ends_mid_sentence("This sentence just stops with no") is True
    # unclosed code fence → flagged
    assert o._ends_mid_sentence("intro\n\n```python\nx = 1") is True
    # structural tails (table row / heading / list) are NOT prose → not flagged
    assert o._ends_mid_sentence("| col a | col b |") is False
    assert o._ends_mid_sentence("## A heading") is False
    assert o._ends_mid_sentence("") is False
    # ordered-list + '+' bullet tails are structural too (Greptile PR #70)
    assert o._ends_mid_sentence("3. last numbered point") is False
    assert o._ends_mid_sentence("3) last numbered point") is False
    assert o._ends_mid_sentence("+ a plus bullet") is False


def test_is_cut_generation_distinguishes_cut_from_under_production():
    """PR-A: a CUT draft (mid-sentence AND severely thin) is re-rolled; a
    thin-but-sentence-complete draft is genuine under-production (left for the
    expand path); a full draft is neither."""
    expected = 1200
    assert o._is_cut_generation("This section abruptly stops with no", expected) is True
    # thin but sentence-complete → NOT a cut (expand path handles it)
    assert o._is_cut_generation("A complete but short sentence.", expected) is False
    # full + complete → not a cut
    assert o._is_cut_generation(("word " * 2000).strip() + ".", expected) is False


def test_cut_draft_is_rerolled_fresh(monkeypatch):
    """PR-A: the inner loop re-rolls an obviously-CUT first draft (stream-drop
    stub) FRESH before the grounding/score loop, so a truncated stub never ships;
    `trunc_retries` records how many re-rolls fired."""
    from deep_research.state import PipelineState, Scaffold, ScaffoldSection

    # Pin the module-level constant so the test is self-contained regardless of
    # DR_TRUNC_RETRY_CAP in the caller's environment (0 = kill-switch would make
    # the while-loop never fire and fail the assertions below).
    monkeypatch.setattr(o, "_TRUNC_RETRY_CAP", 2)

    full = ("word " * 2000).strip() + "."  # complete, well above the 0.5×1200 floor
    drafts = iter(["This first draft was cut off mid", full])  # stub, then full

    monkeypatch.setattr(o.writer, "outline_units", lambda plan: [{"id": "S1", "title": "T"}])
    monkeypatch.setattr(o.grounding, "check", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(o.inner_loop, "score_section", lambda *a, **k: {"ok": True, "min_score": 9.0, "fail": []})

    calls = {"n": 0}

    def fake_write(*a, **k):
        calls["n"] += 1
        return next(drafts), {}

    monkeypatch.setattr(o, "_write_with_guide", fake_write)

    class _Bank:
        def for_section(self, sid, max_blocks=40):
            return [1, 2, 3]

    s = PipelineState(
        query="q", language="en", archetype={"archetype": "x"}, domain="default",
        spec={}, plan={},
        scaffold=Scaffold(sections=[ScaffoldSection(section_id="S1", title="T", expected_length_tokens=1200)]),
        memory_bank=_Bank(), task_id=None,
    )

    sections, _, _ = o._run_section_loop(s, "q", "en")

    assert calls["n"] >= 2, "the cut first draft should have triggered a fresh re-roll"
    assert sections[0] == full, "the full re-rolled draft must replace the cut stub"
    rec = s.completion_stats["sections"][0]
    assert rec["trunc_retries"] >= 1
    assert s.completion_stats["n_hollow_final"] == 0  # the full draft is not hollow


def test_specialist_timeout_default_raised():
    """PR-A / #19: the specialist wall-clock default is 1200s (was 240) so a
    single research call under contention is essentially never falsely dropped."""
    from deep_research.pipeline import orchestrator as orch

    assert orch._SPECIALIST_TIMEOUT_DEFAULT_S == 1200
