"""Phase 1 A1-REAL: post-generation thematic chapter grouping. Matches Qianfan's
~11 H1 / entities-as-H2 shape WITHOUT touching generation (round-5 group-and-nest
regressed because it grouped at generation time → budget collapse + template
fragmentation). These pin: content/template byte-identical, every entity & framing
chapter preserved, the numbering_fix interaction yields the Qianfan shape, and every
fail-soft path returns the article unchanged.
"""

import collections
import re

from deep_research.pipeline import chapter_grouping as cg
from deep_research.pipeline import numbering_fix as nf

_FAT = "A substantial body paragraph with well over ten words of real content so collapse never fires. "


def _article(n_entities=16, framing=True):
    ents = [f"Hero {i}" for i in range(1, n_entities + 1)]
    art = "# Roster Report\n\n"
    if framing:
        art += f"## 1 Research Framework and Methodology\n\n{_FAT * 2}\n\n"
    start = 2 if framing else 1
    body = "**Signature techniques.** " + _FAT * 2 + "\n\n"
    for i, name in enumerate(ents, start=start):
        art += f"## {i} {name}\n\n{body}"
    plan = {"title": "Roster report", "entity_matrix": {"entities": ents}}
    return art, plan, ents


def _fake_groups(labels, count):
    return lambda topic, titles, *, model: [{"title": t, "count": count} for t in labels]


def test_grouping_applied_and_preserves_everything(monkeypatch):
    art, plan, ents = _article(16)
    monkeypatch.setattr(cg, "_call_grouper", _fake_groups(["Faction A", "Faction B", "Faction C", "Faction D"], 4))
    out, st = cg.group_into_chapters(art, language="en", plan=plan, archetype="list-all")
    assert st["applied"] is True and st["n_chapters"] == 4 and st["n_entities"] == 16
    # every entity + framing preserved; bold template byte-identical (1 per entity)
    assert all(e in out for e in ents)
    assert "Research Framework" in out
    assert out.count("**Signature techniques.**") == 16
    # group headers inserted at ##, entities demoted to ###
    assert "## Faction A" in out and "### Hero 1" in out


def test_numbering_fix_yields_qianfan_shape(monkeypatch):
    art, plan, _ = _article(16)
    monkeypatch.setattr(cg, "_call_grouper", _fake_groups(["A", "B", "C", "D"], 4))
    out, _ = cg.group_into_chapters(art, language="en", plan=plan, archetype="list-all")
    o = nf.run(out, flatten_max_depth=3)
    c = collections.Counter(len(m) for m in re.findall(r"(?m)^(#{1,6})\s", o.article))
    # title + framework + 4 groups = 6 H1; 16 entities at H2; no H3
    assert c[1] == 6 and c[2] == 16 and c[3] == 0
    assert o.promotion_skipped is False  # 6 promotable <= cap, promotion fires


def test_noop_wrong_archetype(monkeypatch):
    art, plan, _ = _article(16)
    monkeypatch.setattr(cg, "_call_grouper", _fake_groups(["A", "B", "C", "D"], 4))
    out, st = cg.group_into_chapters(art, language="en", plan=plan, archetype="explain-mechanism")
    assert out == art and st["applied"] is False


def test_noop_too_few_entities(monkeypatch):
    art, plan, _ = _article(8)
    monkeypatch.setattr(cg, "_call_grouper", _fake_groups(["A", "B"], 4))
    out, st = cg.group_into_chapters(art, language="en", plan=plan, archetype="list-all")
    assert out == art and st["applied"] is False and "too-small" in st["reason"]


def test_noop_grouper_failed(monkeypatch):
    art, plan, _ = _article(16)
    monkeypatch.setattr(cg, "_call_grouper", lambda *a, **k: None)
    out, st = cg.group_into_chapters(art, language="en", plan=plan, archetype="list-all")
    assert out == art and st["reason"] == "grouper-failed"


def test_noop_counts_mismatch(monkeypatch):
    art, plan, _ = _article(16)
    # 4 chapters x 3 = 12 != 16 entities
    monkeypatch.setattr(cg, "_call_grouper", _fake_groups(["A", "B", "C", "D"], 3))
    out, st = cg.group_into_chapters(art, language="en", plan=plan, archetype="list-all")
    assert out == art and st["reason"] == "counts-mismatch"


def test_noop_group_count_out_of_band(monkeypatch):
    art, plan, _ = _article(16)
    # 16 chapters of 1 → over _MAX_GROUPS
    monkeypatch.setattr(cg, "_call_grouper", lambda topic, titles, *, model: [{"title": f"C{i}", "count": 1} for i in range(16)])
    out, st = cg.group_into_chapters(art, language="en", plan=plan, archetype="list-all")
    assert out == art and "out-of-band" in st["reason"]


def test_kill_switch(monkeypatch):
    art, plan, _ = _article(16)
    monkeypatch.setattr(cg, "_ENABLED", False)
    monkeypatch.setattr(cg, "_call_grouper", _fake_groups(["A", "B", "C", "D"], 4))
    out, st = cg.group_into_chapters(art, language="en", plan=plan, archetype="list-all")
    assert out == art and st["applied"] is False


def test_no_entity_matrix_is_noop(monkeypatch):
    art, _, _ = _article(16)
    monkeypatch.setattr(cg, "_call_grouper", _fake_groups(["A", "B", "C", "D"], 4))
    out, st = cg.group_into_chapters(art, language="en", plan={"title": "x"}, archetype="list-all")
    assert out == art and st["applied"] is False
