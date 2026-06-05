"""Phase 3: formulaic-connective redundancy clamp. The judge flagged "重复使用
'究其根本''由此可以预见'等句式"; id-38 shipped 142 vs Qianfan ~5. These pin: repeats
are capped, the CLAUSE survives (only the marker + comma go), citations/numbers
are never touched, mid-sentence uses are left alone, EN is a no-op, idempotent.
"""

import re

from deep_research.pipeline import density_clamp as dc


def test_caps_repeated_opener_keeps_clause():
    art = "".join(f"由此可以预见，第{i}段的市场将增长。\n\n" for i in range(1, 8))
    out, st = dc.clamp_connectives(art, language="zh")
    # only _KEEP_PER_PHRASE kept; the rest stripped but the clause survives
    assert out.count("由此可以预见") == dc._KEEP_PER_PHRASE
    assert st["stripped"] == 7 - dc._KEEP_PER_PHRASE
    for i in range(1, 8):
        assert f"第{i}段的市场将增长。" in out  # every clause intact


def test_never_strips_citations_or_numbers():
    art = "".join(f"值得注意的是，2024年增长了{i}5%[^S1-{i}]。\n\n" for i in range(1, 6))
    cites_before = len(re.findall(r"\[\^[^\]]+\]", art))
    out, _ = dc.clamp_connectives(art, language="zh")
    assert len(re.findall(r"\[\^[^\]]+\]", out)) == cites_before  # citations preserved
    for i in range(1, 6):
        assert f"{i}5%" in out  # numbers preserved


def test_mid_sentence_use_is_kept():
    # 值得注意的是 not at a sentence boundary → left alone
    art = "这一发现值得注意的是其普适性。\n\n" * 6
    out, st = dc.clamp_connectives(art, language="zh")
    assert out == art and st["stripped"] == 0


def test_super_phrase_clamped_before_subphrase():
    # 由此可以预见 (super) vs 可以预见 (sub): super handled first, no double strip
    art = "".join(f"由此可以预见，结论{i}成立。\n\n" for i in range(1, 6))
    out, _ = dc.clamp_connectives(art, language="zh")
    # kept occurrences keep the full super-phrase intact (sub not separately stripped)
    assert out.count("由此可以预见") == dc._KEEP_PER_PHRASE


def test_en_is_noop():
    art = "Notably, the market grew.\n\n" * 6
    out, st = dc.clamp_connectives(art, language="en")
    assert out == art and st["stripped"] == 0


def test_idempotent():
    art = "".join(f"究其根本，原因{i}在于成本。\n\n" for i in range(1, 8))
    out1, _ = dc.clamp_connectives(art, language="zh")
    out2, st2 = dc.clamp_connectives(out1, language="zh")
    assert out1 == out2 and st2["stripped"] == 0


def test_protected_range_safe():
    # an opener inside a fenced code block must not be touched
    art = "```\n由此可以预见，code line 1\n由此可以预见，code line 2\n由此可以预见，code 3\n```\n\n正文。\n"
    out, st = dc.clamp_connectives(art, language="zh")
    assert out == art and st["stripped"] == 0


def test_kill_switch(monkeypatch):
    monkeypatch.setattr(dc, "_ENABLED", False)
    art = "由此可以预见，A。\n\n" * 6
    out, st = dc.clamp_connectives(art, language="zh")
    assert out == art and st["stripped"] == 0
