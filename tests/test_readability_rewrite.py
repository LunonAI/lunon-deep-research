"""Readability-rewrite pipeline stage: the validated full-100 readability lever,
now wired into orchestrate. LLM is mocked (no network) — we test the guards that
keep it fail-soft and fact-preserving."""

from deep_research.pipeline import readability_rewrite as rr


def test_applies_valid_shrink(monkeypatch):
    orig = "# Long Report\n\n" + ("This is a verbose sentence with detail. " * 400)
    tight = "# Long Report\n\n" + ("Tight sentence. " * 240)  # ~0.25x, within [0.10,1.05]
    monkeypatch.setattr(rr.llm, "call", lambda *a, **k: tight)
    out = rr.rewrite(orig, "en")
    assert out["applied"] is True
    assert out["article"] == tight.strip()  # stage strips surrounding whitespace
    assert 0.10 < out["stats"]["ratio"] < 1.05


def test_reverts_on_growth(monkeypatch):
    orig = "# R\n\n" + ("content " * 200)
    monkeypatch.setattr(rr.llm, "call", lambda *a, **k: orig + ("more " * 300))
    out = rr.rewrite(orig, "en")
    assert out["applied"] is False and out["stats"]["reason"] == "grew" and out["article"] == orig


def test_reverts_on_over_summarization(monkeypatch):
    orig = "# R\n\n" + ("content sentence here. " * 400)
    monkeypatch.setattr(rr.llm, "call", lambda *a, **k: "Too short.")  # <0.10x
    out = rr.rewrite(orig, "en")
    assert out["applied"] is False and out["stats"]["reason"] == "over-summarized" and out["article"] == orig


def test_reverts_on_empty_output(monkeypatch):
    orig = "# R\n\n" + ("x " * 200)
    monkeypatch.setattr(rr.llm, "call", lambda *a, **k: "   ")
    out = rr.rewrite(orig, "en")
    assert out["applied"] is False and out["article"] == orig


def test_failsoft_on_exception(monkeypatch):
    orig = "# R\n\n" + ("x " * 200)

    def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(rr.llm, "call", boom)
    out = rr.rewrite(orig, "en")
    assert out["applied"] is False and out["article"] == orig and "err:" in out["stats"]["reason"]


def test_reverts_on_numeric_spine_loss(monkeypatch):
    orig = "# R\n\n" + ("The headline figure is 1.77万亿美元 in context. " * 100)
    tight = "# R\n\n" + ("Tightened without the figure. " * 30)  # drops the spine literal
    monkeypatch.setattr(rr.llm, "call", lambda *a, **k: tight)
    out = rr.rewrite(orig, "zh", numeric_spine={"resolved": {"literal": "1.77万亿美元"}})
    assert out["applied"] is False and out["stats"]["reason"] == "spine-lost" and out["article"] == orig


def test_keeps_spine_when_present(monkeypatch):
    orig = "# R\n\n" + ("The figure 1.77万亿美元 recurs. " * 100)
    tight = "# R\n\n精炼：核心数字 1.77万亿美元 保留。" * 20
    monkeypatch.setattr(rr.llm, "call", lambda *a, **k: tight)
    out = rr.rewrite(orig, "zh", numeric_spine={"resolved": {"literal": "1.77万亿美元"}})
    assert out["applied"] is True and "1.77万亿美元" in out["article"]


def test_language_routes_to_zh_prompt(monkeypatch):
    seen = {}

    def cap(role, user, system="", **k):
        seen["system"] = system
        return "# R\n\n精炼内容。" * 20

    monkeypatch.setattr(rr.llm, "call", cap)
    rr.rewrite("# R\n\n" + ("原始很长的内容。" * 200), "zh")
    assert seen["system"] == rr._SYS_ZH


def test_empty_input_noop():
    out = rr.rewrite("   ", "en")
    assert out["applied"] is False and out["stats"]["reason"] == "empty-input"
