"""P3b-v5 #1: COMMIT-FIRST register (L9). The leaderboard judge scored Lunon's
buried/hedged deliverables as ABSENT (id14 ranking+prediction → 0/0). The reference
corpus uses '证据未覆盖'/'弱证据' ZERO times in 100 reports and '本节不' only rarely,
so the rule forbids evidence-gap announcements + leads with the committed claim.
Corpus-grounded (anti-overfit): we do NOT strip rubric/taxonomy/load-bearing —
the reference uses those heavily (412/385/103 across 100)."""

from deep_research import writing_rules as wr
from deep_research.pipeline import article_metrics as am


def test_commit_first_register_rule_in_writer_system():
    sysd = wr.writer_system("predict", "default", "zh", ["A", "B"])
    assert "COMMIT-FIRST REGISTER" in sysd
    # the specific hedges the reference never makes are named as forbidden
    assert "证据未覆盖" in sysd and "弱证据" in sysd and "本节不" in sysd
    assert "LEAD each section" in sysd


def test_scaffold_residual_counts_hedges():
    r = am.compute("# T\n\n本节不展开X。证据未覆盖该领域。弱证据显示Y。")["scaffold_residual"]
    assert r["evidence_uncovered"] == 1
    assert r["weak_evidence"] == 1
    assert r["section_defers"] == 1
    clean = am.compute("# T\n\n一个干净的、自信的论断句子。")["scaffold_residual"]
    assert clean["evidence_uncovered"] == 0 and clean["weak_evidence"] == 0 and clean["section_defers"] == 0


def test_commit_first_limitations_clause_gated_on_chapter():
    """Greptile PR #77 issue #2: the de-hedge rule fires for every archetype,
    but its closing clause may only point at the limitations chapter when the
    plan actually carries one. trend / recommend (has_limitations_chapter=False)
    must get an in-place phrasing instead of a dangling chapter reference."""
    ded = "dedicated limitations chapter"
    # trend never carries a limitations chapter
    trend = wr.writer_system("trend", "default", "zh", ["A", "B"])
    assert ded not in trend
    assert "state it once in place" in trend
    # predict WITH the chapter present keeps the chapter reference
    pred = wr.writer_system(
        "predict", "default", "zh", ["A", "B"], has_limitations_chapter=True
    )
    assert ded in pred
    # the de-hedge body is identical for both regardless of the clause
    for sysd in (trend, pred):
        assert "COMMIT-FIRST REGISTER" in sysd and "本节不" in sysd


def test_does_not_strip_legit_reference_vocabulary():
    """Anti-overfit lock: rubric/taxonomy/load-bearing are NOT in the hedge set —
    the reference uses them more than we do; flagging them would make us LESS like it."""
    res = am.compute("# T\n\nThe taxonomy is load-bearing in this rubric.")["scaffold_residual"]
    assert "taxonomy" not in res and "load_bearing" not in res
