"""round 10: chunked ZH register pass. The old whole-article call no-opped on
long ZH (truncate → fail 0.85 guard). Now: short ZH = one call; long ZH = per
top-chapter, reassembled, with guards that revert any chunk dropping a
number/citation/the numeric-spine literal. These tests pin the chunking
correctness (esp. the preamble-not-dropped identity) + every guard.
"""

from deep_research.pipeline import zh_writer_pass as z

_MARKER = "待润色正文（保持编号、数字、引用标记不变）："
_SPINE = "约11万条/年"
_NS = {"resolved": {"literal": _SPINE}}


def _body_of(user: str) -> str:
    """Extract the chunk body the harness sent (after the marker + optional spine clause)."""
    after = user.split(_MARKER, 1)[1].lstrip()
    if after.startswith("（"):
        after = after.split("）", 1)[1]
    return after.lstrip("\n")


def _patch(monkeypatch, fake):
    monkeypatch.setattr(z.config, "model_for", lambda role: "test-zh-model")
    monkeypatch.setattr(z.openrouter_client, "raw_call", fake)


def _long_article() -> str:
    title = "# 中国地铁受电弓碳滑板年用量分析\n\n"
    abstract = "本报告核心数字为" + _SPINE + "。" + ("摘要正文是因为如此。" * 500) + "详见[^A-1]。\n\n"
    # one DISTINCT marker per chapter (so dropping it removes it from the set
    # without shrinking the chunk past the 0.85 length guard).
    chaps = "".join(
        f"## {i} 第{i}章标题\n\n" + (f"第{i}章正文是因为内容。" * 1100) + f"关键数据见[^S{i}-1]。\n\n" for i in range(1, 9)
    )
    art = title + abstract + chaps
    assert len(art) >= z._CHUNK_THRESHOLD_CHARS, len(art)
    return art


def test_zh_writer_dropped_is_noop(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(z.config, "model_for", lambda role: "")
    monkeypatch.setattr(z.openrouter_client, "raw_call", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1))
    r = z.zh_pass("短文。" * 10, "p")
    assert r["applied"] is False and r["reason"] == "zh_writer dropped" and calls["n"] == 0


def test_short_zh_uses_single_call(monkeypatch):
    calls = {"n": 0}

    def fake(model, user, **kw):
        calls["n"] += 1
        return _body_of(user), {}

    _patch(monkeypatch, fake)
    r = z.zh_pass("# 标题\n\n这是一段较短的中文报告正文。" * 50, "p")  # < 80k
    assert calls["n"] == 1 and r["stats"]["mode"] == "single"


def test_long_zh_chunks_per_chapter(monkeypatch):
    calls = {"n": 0}

    def fake(model, user, **kw):
        calls["n"] += 1
        return _body_of(user), {}

    _patch(monkeypatch, fake)
    r = z.zh_pass(_long_article(), "p", numeric_spine=_NS)
    assert r["stats"]["mode"] == "chunked"
    assert r["stats"]["n_units"] == 9  # preamble + 8 chapters
    assert calls["n"] >= 9  # one call per unit


def test_chunk_reassembly_is_lossless_identity(monkeypatch):
    """THE critical test: an identity polish must round-trip to the EXACT article
    (catches the preamble/abstract-drop bug, since _top_chapters excludes it)."""
    _patch(monkeypatch, lambda model, user, **kw: (_body_of(user), {}))
    art = _long_article()
    r = z.zh_pass(art, "p", numeric_spine=_NS)
    assert r["article"] == art  # byte-identical: preamble + every chapter preserved
    assert r["stats"]["n_reverted"] == 0


def test_heading_lines_never_sent_to_model(monkeypatch):
    seen = []

    def fake(model, user, **kw):
        seen.append(user)
        return _body_of(user), {}

    _patch(monkeypatch, fake)
    z.zh_pass(_long_article(), "p", numeric_spine=_NS)
    # no chunk body sent to the model may start with a chapter/title heading line
    for u in seen:
        body = _body_of(u)
        assert not body.lstrip().startswith("#"), body[:40]


def test_spine_literal_survives_mutating_polish(monkeypatch):
    """A chunk that mutates the headline figure is reverted → the literal stays."""
    _patch(monkeypatch, lambda model, user, **kw: (_body_of(user).replace(_SPINE, "约11万"), {}))
    art = _long_article()
    r = z.zh_pass(art, "p", numeric_spine=_NS)
    assert _SPINE in r["article"]  # preamble chunk (holds the spine) reverted
    assert "spine-mutated" in r["stats"]["revert_reasons"]


def test_citation_marker_loss_reverts_chunk(monkeypatch):
    _patch(monkeypatch, lambda model, user, **kw: (_body_of(user).replace("[^S1-1]", ""), {}))
    art = _long_article()
    r = z.zh_pass(art, "p", numeric_spine=_NS)
    assert "[^S1-1]" in r["article"]  # chapter 1 reverted
    assert "citation-lost" in r["stats"]["revert_reasons"]


def test_truncated_chunk_reverts(monkeypatch):
    _patch(monkeypatch, lambda model, user, **kw: (_body_of(user)[: len(_body_of(user)) // 3], {}))
    art = _long_article()
    r = z.zh_pass(art, "p", numeric_spine=_NS)
    # every chunk shrank past 0.85 → all reverted → ship original
    assert r["article"] == art
    assert all(x == "short" for x in r["stats"]["revert_reasons"])


def test_fail_soft_on_exception(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("provider down")

    _patch(monkeypatch, boom)
    art = _long_article()
    r = z.zh_pass(art, "p", numeric_spine=_NS)
    # per-chunk exception reverts each chunk; article unchanged, task never fails
    assert r["article"] == art


def test_split_freezes_only_own_heading_keeps_subheading(monkeypatch):
    # Greptile #101 issue 1: a stacked sub-heading stays in the body (context),
    # only the chunk's OWN chapter heading is frozen out.
    head, body = z._split_leading_headings("## 1 章\n### 1.1 小节\n\n正文")
    assert head == "## 1 章\n"
    assert body == "### 1.1 小节\n\n正文"
    head2, body2 = z._split_leading_headings("## 1 章\n\n### 1.1 小节\n\n正文")
    assert head2 == "## 1 章\n\n" and body2.startswith("### 1.1")
    head3, body3 = z._split_leading_headings("无标题正文。")  # no heading
    assert head3 == "" and body3 == "无标题正文。"


def test_drop_echoed_heading_only_strips_exact_duplicate():
    # Greptile #101 issue 2: a model echo of the frozen heading is dropped, but a
    # legitimate in-body sub-heading is NOT.
    head = "## 1 第一章\n\n"
    assert z._drop_echoed_heading("## 1 第一章\n\n正文。", head) == "正文。"
    assert z._drop_echoed_heading("### 1.1 小节\n\n正文。", head) == "### 1.1 小节\n\n正文。"
    assert z._drop_echoed_heading("正文。", head) == "正文。"
    assert z._drop_echoed_heading("正文。", "") == "正文。"  # no frozen heading → untouched


def test_register_proxies_logged(monkeypatch):
    _patch(monkeypatch, lambda model, user, **kw: (_body_of(user).replace("是因为", "由于"), {}))
    art = _long_article()
    r = z.zh_pass(art, "p", numeric_spine=_NS)
    pre, post = r["stats"]["proxies_pre"], r["stats"]["proxies_post"]
    assert pre["shi_yinwei"] > 0 and post["shi_yinwei"] < pre["shi_yinwei"]  # 是因为 dropped
