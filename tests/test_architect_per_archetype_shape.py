"""Wave 2 §1.2 (2026-05-26): per-archetype outline-shape preset.

The pre-Wave-2 architect spec produced a uniform 8-12 top-level × 3-6
subsections × 2-4 depth_seeds outline for every archetype. the reference
corpus profiling (10 reference docs, 2026-05-26) showed:
  - list-all (id=91, 14, 8): 63-81 H2, 0 H3, 0 H4+
  - explain-mechanism (id=56, 20, 89): 53-70 H2, 138-221 H3, 0 H4+
  - predict/trend (id=38): 58 H2, 115 H3, 0 H4+
  - ZERO of the 10 reference docs use H4+ headings

Wave 2 §1.2 dispatches outline shape per archetype:
  - list-all: 30-80 top, 0-2 subs, 0 seeds (flat)
  - compare: 15-30 top, 2-5 subs, 0 seeds (moderate, no H4)
  - explain-mechanism: 8-14 top, 4-8 subs, 2-4 seeds (deep, H4 OK)
  - predict/trend/recommend: 8-12 top, 3-6 subs, 2-4 seeds (default)

These tests pin the per-archetype dispatch + per-archetype shortfall
emission + per-archetype retry-feedback interpolation.
"""

from deep_research.pipeline import architect


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
