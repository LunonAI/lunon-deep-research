"""Unit tests for deep_research.pipeline.memory_bank (P2-Wave-1-B).

Covers:
- `assign_primary_sections()` — determinism, single-section short-circuit,
  multi-section token-overlap scoring, tie-break by TOC order, idempotency.
- `for_section_pruned()` — mode=off equivalence with `for_section()`,
  soft-mode placeholder generation, hard-mode omission, parent-promotion
  preserved, defensive fallback when primary not assigned.
"""

from deep_research.pipeline.memory_bank import MemoryBank


def _bank_with_eids(rows: list[dict]) -> MemoryBank:
    """Helper: rows = list of {section_ids, text, source_name, ...}."""
    b = MemoryBank()
    for r in rows:
        b.add(
            source_name=r.get("source_name", ""),
            url=r.get("url", ""),
            title=r.get("title", ""),
            text=r.get("text", ""),
            query_id=r.get("query_id", ""),
            section_ids=r["section_ids"],
            specialist=r.get("specialist", ""),
            language=r.get("language", "en"),
        )
    return b


# --- assign_primary_sections ----------------------------------------------


def test_assign_single_section_eid():
    b = _bank_with_eids([{"section_ids": ["1"], "text": "anything"}])
    b.assign_primary_sections({"report_toc": [{"id": "1", "title": "Intro"}]})
    eid = next(iter(b._items))
    assert b._items[eid]["primary_section_id"] == "1"


def test_assign_no_section_eid_gets_none():
    b = _bank_with_eids([{"section_ids": [], "text": "orphan"}])
    b.assign_primary_sections({"report_toc": []})
    eid = next(iter(b._items))
    assert b._items[eid]["primary_section_id"] is None


def test_assign_multi_section_picks_best_overlap():
    plan = {
        "report_toc": [
            {"id": "1", "title": "Auction Theory", "subsections": []},
            {"id": "2", "title": "Game Mechanics", "subsections": []},
            {"id": "3", "title": "Equilibrium Analysis", "subsections": []},
        ]
    }
    b = _bank_with_eids(
        [
            {
                "section_ids": ["1", "2", "3"],
                "text": "The equilibrium analysis of the auction is complex.",
                "source_name": "Author 2024",
            }
        ]
    )
    b.assign_primary_sections(plan)
    eid = next(iter(b._items))
    # "equilibrium" token aligns with section 3 most; section 1 also has "auction"
    # Token overlap: §1{"auction", "theory"} & eid{auction, equilibrium, analysis, complex} = {auction} → 1
    # §3{"equilibrium", "analysis"} & eid = {equilibrium, analysis} → 2
    # §2{"game", "mechanics"} & eid = {} → 0
    # Highest score = §3.
    assert b._items[eid]["primary_section_id"] == "3"


def test_assign_tie_break_by_toc_order():
    plan = {
        "report_toc": [
            {"id": "A", "title": "Foo Bar", "subsections": []},
            {"id": "B", "title": "Bar Foo", "subsections": []},  # same tokens as A
        ]
    }
    b = _bank_with_eids([{"section_ids": ["A", "B"], "text": "foo bar quux", "source_name": ""}])
    b.assign_primary_sections(plan)
    eid = next(iter(b._items))
    # Both score identically (foo+bar in both); tie → first in TOC = A.
    assert b._items[eid]["primary_section_id"] == "A"


def test_assign_idempotency():
    plan = {"report_toc": [{"id": "1", "title": "X"}, {"id": "2", "title": "Y"}]}
    b = _bank_with_eids([{"section_ids": ["1", "2"], "text": "y matches"}])
    b.assign_primary_sections(plan)
    eid = next(iter(b._items))
    first = b._items[eid]["primary_section_id"]
    # Run again
    b.assign_primary_sections(plan)
    assert b._items[eid]["primary_section_id"] == first


def test_assign_subsection_titles_contribute_to_overlap():
    plan = {
        "report_toc": [
            {"id": "1", "title": "Intro", "subsections": ["Auction mechanics"]},
            {"id": "2", "title": "Game Theory", "subsections": []},
        ]
    }
    b = _bank_with_eids([{"section_ids": ["1", "2"], "text": "auction design and mechanics"}])
    b.assign_primary_sections(plan)
    eid = next(iter(b._items))
    # Section 1's subsection "Auction mechanics" overlaps with text; §2 has no overlap.
    assert b._items[eid]["primary_section_id"] == "1"


# --- for_section_pruned ----------------------------------------------------


def test_for_section_pruned_off_equals_for_section():
    plan = {"report_toc": [{"id": "1", "title": "X"}]}
    b = _bank_with_eids([{"section_ids": ["1"], "text": "anything"}])
    b.assign_primary_sections(plan)
    pruned = b.for_section_pruned("1", mode="off")
    legacy = b.for_section("1")
    assert pruned == legacy


def test_for_section_pruned_without_assign_falls_back_to_legacy():
    """Defensive: if assign_primary_sections was never called, soft/hard still
    return the legacy evidence (do not crash)."""
    b = _bank_with_eids([{"section_ids": ["1"], "text": "anything"}])
    # NOT calling assign_primary_sections
    out_soft = b.for_section_pruned("1", mode="soft")
    out_hard = b.for_section_pruned("1", mode="hard")
    legacy = b.for_section("1")
    assert out_soft == legacy
    assert out_hard == legacy


def test_for_section_pruned_soft_returns_placeholder_for_non_primary():
    plan = {
        "report_toc": [
            {"id": "1", "title": "Auction"},
            {"id": "2", "title": "Game Theory"},
        ]
    }
    b = _bank_with_eids(
        [
            {"section_ids": ["1", "2"], "text": "game theory and strategy", "source_name": "Foo"},
            {"section_ids": ["2"], "text": "purely about §2", "source_name": "Bar"},
        ]
    )
    b.assign_primary_sections(plan)
    # First eid → primary should be §2 (token match "game theory")
    # Second eid → primary is §2 (only section_id)
    # When fetching for §1: first eid appears in by_section[1] but its primary is §2 → placeholder.
    # Second eid is NOT in by_section[1] → not returned.
    out = b.for_section_pruned("1", mode="soft")
    placeholders = [x for x in out if x.get("placeholder")]
    fulls = [x for x in out if not x.get("placeholder")]
    assert len(placeholders) == 1
    assert placeholders[0]["source_name"] == "Foo"
    assert placeholders[0].get("text", "") == ""
    assert placeholders[0]["primary_section_id"] == "2"
    assert len(fulls) == 0  # eid had primary §2, not primary for §1


def test_for_section_pruned_hard_omits_non_primary():
    plan = {
        "report_toc": [
            {"id": "1", "title": "Auction"},
            {"id": "2", "title": "Game Theory"},
        ]
    }
    b = _bank_with_eids(
        [
            {"section_ids": ["1", "2"], "text": "game theory and strategy", "source_name": "Foo"},
        ]
    )
    b.assign_primary_sections(plan)
    out_hard = b.for_section_pruned("1", mode="hard")
    out_soft = b.for_section_pruned("1", mode="soft")
    # Hard: non-primary entries omitted. Should be empty (no primary-for-§1 eids).
    assert out_hard == []
    # Soft: same entries but as placeholders. Should be 1.
    assert len(out_soft) == 1
    assert out_soft[0].get("placeholder") is True


def test_for_section_pruned_parent_promotion_preserved():
    """An eid primary to §1 should appear FULL when fetching for §1.1
    (parent-promotion rule), not as placeholder."""
    plan = {
        "report_toc": [
            {"id": "1", "title": "Auction"},
            {"id": "1.1", "title": "First-price"},
        ]
    }
    b = _bank_with_eids([{"section_ids": ["1"], "text": "general auction background", "source_name": "Foo"}])
    b.assign_primary_sections(plan)
    out = b.for_section_pruned("1.1", mode="soft")
    # eid is primary to §1, parent of §1.1 → should be FULL block (not placeholder).
    assert len(out) == 1
    assert out[0].get("placeholder") is None
    assert out[0]["source_name"] == "Foo"
    assert out[0]["text"] == "general auction background"


def test_for_section_pruned_sibling_primary_is_placeholder():
    """An eid primary to §1.2 should appear as PLACEHOLDER when fetched for §1.1
    (sibling, not parent/child)."""
    plan = {
        "report_toc": [
            {"id": "1", "title": "Auction"},
            {"id": "1.1", "title": "First-price"},
            {"id": "1.2", "title": "Second-price"},
        ]
    }
    b = _bank_with_eids([{"section_ids": ["1.1", "1.2"], "text": "second-price specifics", "source_name": "Foo"}])
    b.assign_primary_sections(plan)
    # eid token "second-price specifics" → §1.2 wins overlap.
    eid = next(iter(b._items))
    assert b._items[eid]["primary_section_id"] == "1.2"
    out = b.for_section_pruned("1.1", mode="soft")
    placeholders = [x for x in out if x.get("placeholder")]
    fulls = [x for x in out if not x.get("placeholder")]
    assert len(placeholders) == 1
    assert len(fulls) == 0


def test_for_section_pruned_max_blocks_respected():
    plan = {"report_toc": [{"id": "1", "title": "X"}]}
    b = _bank_with_eids([{"section_ids": ["1"], "text": f"row {i}"} for i in range(60)])
    b.assign_primary_sections(plan)
    out = b.for_section_pruned("1", max_blocks=10, mode="off")
    assert len(out) == 10


if __name__ == "__main__":
    import sys

    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for f in funcs:
        try:
            f()
            print(f"PASS {f.__name__}")
        except AssertionError as e:
            failed.append((f.__name__, e))
            print(f"FAIL {f.__name__}: {e}")
        except Exception as e:
            failed.append((f.__name__, e))
            print(f"ERROR {f.__name__}: {e}")
    if failed:
        sys.exit(1)
    print(f"\n{len(funcs)} tests passed")
