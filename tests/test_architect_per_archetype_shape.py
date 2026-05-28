"""Wave 2 §1.2 (2026-05-26): per-archetype outline-shape preset.

The pre-Wave-2 architect spec produced a uniform 8-12 top-level × 3-6
subsections × 2-4 depth_seeds outline for every archetype. Qianfan
corpus profiling (10 reference docs, 2026-05-26) showed:
  - list-all (id=91, 14, 8): 63-81 H2, 0 H3, 0 H4+
  - explain-mechanism (id=56, 20, 89): 53-70 H2, 138-221 H3, 0 H4+
  - predict/trend (id=38): 58 H2, 115 H3, 0 H4+
  - ZERO of the 10 Qianfan docs use H4+ headings

Wave 2 §1.2 dispatches outline shape per archetype:
  - list-all: 30-80 top, 0-2 subs, 0 seeds (flat)
  - compare: 15-30 top, 2-5 subs, 0 seeds (moderate, no H4)
  - explain-mechanism: 8-14 top, 4-8 subs, 2-4 seeds (deep, H4 OK)
  - predict/trend/recommend: 8-12 top, 3-6 subs, 2-4 seeds (default)

These tests pin the per-archetype dispatch + per-archetype shortfall
emission + per-archetype retry-feedback interpolation.
"""

from deep_research.pipeline import architect


def test_bounds_for_archetype_returns_fresh_copy_not_mutable_reference():
    """Greptile PR #30 round-3 follow-up: `_bounds_for_archetype` must
    return a fresh copy, not a mutable reference to the module-level
    constant. Pre-fix a caller mutating the returned dict (e.g.
    `b = _bounds_for_archetype('predict'); b['top_min'] = 99`) would
    silently corrupt the constant for every subsequent call. Mirrors
    the `writing_rules.insight_distribution` fix from PR #30 round-2."""
    original = dict(architect._ARCHETYPE_OUTLINE_SHAPE["predict"])
    b = architect._bounds_for_archetype("predict")
    b["top_min"] = 999
    b["seed_max"] = 99
    # Module-level constant must be UNTOUCHED.
    assert architect._ARCHETYPE_OUTLINE_SHAPE["predict"] == original, (
        "_bounds_for_archetype returned a mutable reference — caller "
        "mutation corrupted the module-level constant. Wrap return in dict(...)."
    )
    # Subsequent call must return the uncorrupted values.
    b2 = architect._bounds_for_archetype("predict")
    assert b2 == original


def test_bounds_for_archetype_dispatches_correctly():
    """Each archetype with a preset must return its dispatched bounds.
    Unknown archetypes fall back to the DEFAULT shape."""
    list_all = architect._bounds_for_archetype("list-all")
    assert list_all["top_min"] == 30
    assert list_all["top_max"] == 80
    assert list_all["sub_max"] == 2
    assert list_all["seed_max"] == 0  # no H4 for list-all

    compare = architect._bounds_for_archetype("compare")
    assert compare["top_min"] == 15
    assert compare["seed_max"] == 0  # no H4 for compare

    explain = architect._bounds_for_archetype("explain-mechanism")
    assert explain["top_min"] == 8
    assert explain["sub_max"] == 8
    assert explain["seed_max"] == 4  # H4 OK for explain-mechanism

    predict = architect._bounds_for_archetype("predict")
    assert predict["top_min"] == 8
    assert predict["seed_max"] == 4

    # Unknown archetype falls back to DEFAULT.
    default = architect._bounds_for_archetype("unknown-archetype")
    assert default == architect._DEFAULT_OUTLINE_SHAPE


def test_normalize_uses_list_all_bounds_for_list_all_archetype():
    """A list-all plan with the OLD default shape (8 top × 3 subs × 2 seeds)
    must now FAIL the audit because list-all wants 30+ flat top sections
    with no H4. Verifies the per-archetype dispatch is wired through."""
    plan = {
        "report_toc": [
            {
                "id": f"S{i + 1}",
                "title": "x",
                "subsections": [{"id": f"S{i + 1}.1", "title": "x", "depth_seeds": ["a", "b"]}],
                "depth_target": "broad",
            }
            for i in range(9)  # 9 top sections, valid for DEFAULT but not list-all
        ],
        "queries": [{"id": f"Q{i + 1}", "text": "q", "type": "factual"} for i in range(architect._QUERIES_MIN)],
        "entity_matrix": {"entities": ["e1", "e2", "e3", "e4", "e5"], "dimensions": ["d1", "d2", "d3", "d4"]},
    }
    architect._normalize(plan, archetype="list-all")
    audit = plan["_outline_audit"]
    # Top-section shortfall: 9 < 30
    assert any("top_sections=9<30" in s for s in audit["shortfalls"]), audit["shortfalls"]
    # Seed shortfall: each subsection has 2 seeds, but list-all expects 0
    assert any("seeds=2>0" in s for s in audit["shortfalls"]), audit["shortfalls"]


def test_normalize_uses_explain_mechanism_deeper_bounds():
    """explain-mechanism uses 8-14 / 4-8 / 2-4 (deeper than default).
    A plan with default-shape subsections (3 subs each) must trigger
    a subsection-count shortfall for explain-mechanism."""
    plan = {
        "report_toc": [
            {
                "id": f"S{i + 1}",
                "title": "x",
                "subsections": [
                    {"id": f"S{i + 1}.{j + 1}", "title": "x", "depth_seeds": ["a", "b"]} for j in range(3)
                ],  # 3 subs each — under explain-mechanism's 4 min
                "depth_target": "broad",
            }
            for i in range(10)
        ],
        "queries": [{"id": f"Q{i + 1}", "text": "q", "type": "factual"} for i in range(architect._QUERIES_MIN)],
    }
    architect._normalize(plan, archetype="explain-mechanism")
    audit = plan["_outline_audit"]
    # Subsection-count shortfall: 3 < 4 for each top section.
    assert any("subs=3<4" in s for s in audit["shortfalls"]), audit["shortfalls"]


def test_normalize_flat_archetype_accepts_zero_depth_seeds():
    """list-all subsections with `depth_seeds=[]` must NOT trigger the
    `subsections_missing_seeds` counter (which the default-shape path
    fires when seeds is empty). Flat archetypes treat empty seeds as
    correct, not as a shortfall."""
    plan = {
        "report_toc": [
            {
                "id": f"S{i + 1}",
                "title": "x",
                "subsections": [{"id": f"S{i + 1}.1", "title": "x", "depth_seeds": []}],
                "depth_target": "broad",
            }
            for i in range(architect._ARCHETYPE_OUTLINE_SHAPE["list-all"]["top_min"])
        ],
        "queries": [{"id": f"Q{i + 1}", "text": "q", "type": "factual"} for i in range(architect._QUERIES_MIN)],
        "entity_matrix": {"entities": ["e1", "e2", "e3", "e4", "e5"], "dimensions": ["d1", "d2", "d3", "d4"]},
    }
    architect._normalize(plan, archetype="list-all")
    audit = plan["_outline_audit"]
    # No shortfalls for seeds-empty under list-all's seed_max=0.
    assert all("seeds" not in s for s in audit["shortfalls"]), audit["shortfalls"]
    # And `subsections_missing_seeds` is only incremented for archetypes
    # where seeds ARE required; list-all skips it.
    assert audit["subsections_missing_seeds"] == 0


def test_normalize_audit_records_archetype_and_bounds():
    """The audit dict must record which archetype + bounds were used so
    downstream telemetry (drift log) can distinguish per-archetype runs
    without re-deriving them."""
    plan = {
        "report_toc": [],
        "queries": [],
    }
    architect._normalize(plan, archetype="list-all")
    audit = plan["_outline_audit"]
    assert audit.get("archetype") == "list-all"
    assert audit.get("bounds") == architect._ARCHETYPE_OUTLINE_SHAPE["list-all"]


def test_format_retry_feedback_interpolates_per_archetype_bounds():
    """The retry feedback string must reference the right per-archetype
    bounds — if a list-all plan fails the audit, the LLM retry feedback
    should say '30-80 top sections' (list-all bounds), NOT '8-12 top
    sections' (default bounds). PR #23's source-of-truth invariant
    must be archetype-aware."""
    audit = {
        "n_top_sections": 5,
        "n_subsections_total": 0,
        "n_seeds_total": 0,
        "shortfalls": ["top_sections=5<30"],
    }
    feedback = architect._format_retry_feedback(audit, archetype="list-all")
    assert "30-80 top sections" in feedback, feedback
    # And the flat-archetype caller gets the "no H4 leaves" rider.
    assert "FLAT" in feedback or "ZERO depth_seeds" in feedback


def test_format_retry_feedback_falls_back_to_default_when_archetype_none():
    """Back-compat: calling _format_retry_feedback without archetype
    must produce the same string the pre-Wave-2 caller would have seen
    (uses default 8-12 / 3-6 / 2-4 bounds)."""
    audit = {
        "n_top_sections": 5,
        "n_subsections_total": 0,
        "n_seeds_total": 0,
        "shortfalls": ["top_sections=5<8"],
    }
    feedback = architect._format_retry_feedback(audit)
    assert "8-12 top sections" in feedback, feedback


def test_writer_system_interpolates_per_archetype_subsection_bounds():
    """Wave 2 PR #30 self-review: the system prompt's STRUCTURAL CAPS
    block must reflect per-archetype `sub_min-sub_max` when
    `outline_shape` is provided. Pre-fix it hardcoded "3-6 subsections"
    which contradicted list-all's `0-2` user-prompt bounds. Pin both
    that the hardcoded value is GONE and the per-archetype value
    appears."""
    from deep_research.pipeline.architect import _bounds_for_archetype
    from deep_research.writing_rules import writer_system

    # list-all preset: 0-2 subsections, seed_max=0 (flat, no H4)
    list_all_bounds = _bounds_for_archetype("list-all")
    sys_la = writer_system("list-all", "default", "en", ["A", "B"], task_id=None, outline_shape=list_all_bounds)
    # System prompt must mention list-all's 0-2 sub range (not the
    # hardcoded "3-6 subsections" pre-fix).
    assert f"{list_all_bounds['sub_min']}-{list_all_bounds['sub_max']} subsections" in sys_la
    # And FLAT outline language must be present for seed_max==0 archetypes.
    assert "FLAT" in sys_la or "no H4" in sys_la.lower()
    # The system prompt must NOT carry the pre-fix hardcoded "3-6
    # subsections" string for flat archetypes (where bounds are 0-2).
    assert "3-6 subsections per major section" not in sys_la

    # explain-mechanism preset: 4-8 subsections, seed_max=4 (deep, H4 OK)
    explain_bounds = _bounds_for_archetype("explain-mechanism")
    sys_ex = writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=None, outline_shape=explain_bounds)
    assert f"{explain_bounds['sub_min']}-{explain_bounds['sub_max']} subsections" in sys_ex
    # Deep archetype must allow `#### N.N.N` headings — no FLAT language.
    assert "#### N.N.N" in sys_ex or "H4 leaf" in sys_ex


def test_writer_system_falls_back_to_default_when_outline_shape_none():
    """Back-compat: `writer_system(..., outline_shape=None)` must
    produce the historical 3-6 / 4-level prompt so any pre-Wave-2
    caller that doesn't yet thread bounds through stays unbroken."""
    from deep_research.writing_rules import writer_system

    sys = writer_system("explain-mechanism", "default", "en", ["A", "B"], task_id=None)
    # Default 3-6 subsections phrasing must appear.
    assert "3-6 subsections per major section" in sys


def test_writer_section_threads_archetype_bounds_into_system_prompt(monkeypatch):
    """Wave 2 PR #30 self-review: `writer.write_section` must fetch the
    per-archetype outline bounds + pass them to `writer_system` so the
    system prompt and the user-prompt OUTLINE SHAPE block both
    reference the same archetype-specific values."""
    captured_sys: list[str] = []

    def fake_llm_call(role, user, *, system, max_tokens, note, **kw):
        captured_sys.append(system)
        return "synthetic body content"

    from deep_research.pipeline import writer as writer_module

    monkeypatch.setattr(writer_module.llm, "call", fake_llm_call)
    # Minimal plan + bank structure so write_section can run end-to-end.
    plan = {"report_toc": [{"id": "S1", "title": "Intro"}], "queries": []}
    unit = {"id": "S1", "title": "Intro", "depth": "broad", "subs": []}

    class _FakeBank:
        def for_section(self, sid):
            return []

    writer_module.write_section(
        unit,
        plan,
        _FakeBank(),
        prompt="test",
        language="en",
        archetype="list-all",
        domain="default",
        prior_titles=["Intro"],
    )
    assert captured_sys, "write_section did not call llm.call with a system prompt"
    sys_prompt = captured_sys[0]
    # The system prompt must carry the list-all per-archetype bounds
    # (FLAT phrasing for seed_max=0 archetype).
    assert "FLAT" in sys_prompt or "no H4" in sys_prompt.lower(), (
        "write_section did not thread list-all's seed_max=0 outline_shape "
        "to writer_system (system prompt missing FLAT/no-H4 wording)"
    )


def test_build_injects_per_archetype_outline_block_into_user_prompt(monkeypatch):
    """Wave 2 §1.2: the architect's user prompt must carry the per-
    archetype OUTLINE SHAPE override block so the LLM sees the right
    bounds upfront (not just on retry). Pin both that the block is
    present AND that it interpolates the dispatched bounds for the
    given archetype."""
    captured_users: list[str] = []

    def fake_call_json(*_args, user=None, **kw):
        # Capture the user prompt regardless of positional/keyword
        # binding; in deep_research.llm.call_json the signature is
        # (note, user, ...) so check both.
        if isinstance(user, str):
            captured_users.append(user)
        elif len(_args) >= 2 and isinstance(_args[1], str):
            captured_users.append(_args[1])
        # Return a plan that passes the audit (use default shape since
        # we're not testing audit behavior here).
        return {
            "report_toc": [
                {
                    "id": f"S{i + 1}",
                    "title": "x",
                    "subsections": [{"id": f"S{i + 1}.{j + 1}", "title": "x", "depth_seeds": []} for j in range(2)],
                    "depth_target": "broad",
                }
                for i in range(architect._ARCHETYPE_OUTLINE_SHAPE["list-all"]["top_min"])
            ],
            "queries": [{"id": f"Q{i + 1}", "text": "q", "type": "factual"} for i in range(architect._QUERIES_MIN)],
            "entity_matrix": {"entities": ["e1", "e2", "e3", "e4", "e5"], "dimensions": ["d1", "d2", "d3", "d4"]},
        }

    monkeypatch.setattr(architect.llm, "call_json", fake_call_json)
    architect.build("p", "en", "list-all", [], {}, [])
    assert captured_users, "architect.build did not call llm.call_json with a user prompt"
    user_prompt = captured_users[0]
    # Must include the OUTLINE SHAPE FOR THIS ARCHETYPE block.
    assert "OUTLINE SHAPE FOR THIS ARCHETYPE" in user_prompt
    # And the bounds must be interpolated from the list-all preset
    # (not the default).
    assert "30-80 top-level sections" in user_prompt, user_prompt[:2000]
    # The "FLAT" / "no H4" wording must be present for archetypes with seed_max=0.
    assert "FLAT" in user_prompt or "ZERO depth_seeds" in user_prompt
