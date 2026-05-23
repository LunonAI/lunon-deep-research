"""Unit tests for P2-Wave-2.5-D1 writer_system rewrite.

Three things to verify:
  1. "LENGTH SERVES SUBSTANCE" replaces "CONCISENESS IS A FIRST-CLASS GOAL".
  2. The new forbidden-phrases list (evidence-boundary meta-commentary) appears.
  3. The article-level length target propagates from depth_tier into the prompt.
"""

from deep_research import writing_rules as wr


def test_writer_system_no_longer_says_conciseness_is_first_class(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")  # avoid G auto-fire path
    sys = wr.writer_system("compare", "default", "en", ["A", "B"])
    assert "CONCISENESS IS A FIRST-CLASS GOAL" not in sys
    assert "LENGTH SERVES SUBSTANCE" in sys


def test_writer_system_en_includes_word_benchmark_envelope(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("explain-mechanism", "science", "en", ["A", "B"], depth_tier="comprehensive")
    # EN: 30k-80k WORDS envelope (top-of-leaderboard EN comprehensive band).
    assert "30,000-80,000 words" in sys


def test_writer_system_zh_uses_zh_benchmark_envelope(monkeypatch):
    """Greptile follow-up (PR #12): ZH must NOT receive the EN-word range —
    ZH gets a CJK-char band roughly 2× the EN-word band, matching the
    length_target language doubling. Previously the prompt contained
    both "30,000-80,000 CJK characters" (EN band reused) AND a numeric
    target of ~117,000 — directly contradictory."""
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("explain-mechanism", "default", "zh", ["A"], depth_tier="comprehensive")
    assert "60,000-160,000" in sys  # ZH CJK char band
    assert "30,000-80,000 words" not in sys  # EN-word band MUST be absent for ZH


def test_writer_system_emits_explicit_tier_label(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("compare", "default", "en", ["A"], depth_tier="deep")
    assert "depth tier for this task is `deep`" in sys


def test_writer_system_falls_back_to_archetype_default_when_no_tier(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("recommend", "default", "en", ["A"])
    # recommend defaults to standard.
    assert "depth tier for this task is `standard`" in sys


def test_writer_system_zh_uses_cjk_char_unit(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("compare", "default", "zh", ["A"], depth_tier="deep")
    assert "CJK characters" in sys


# --- F2: forbidden-phrases list ---------------------------------------------


def test_writer_system_forbids_supplied_atoms_phrase(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("compare", "default", "en", ["A"])
    assert "supplied atoms do not establish" in sys
    assert "evidence-boundary meta-commentary" in sys.lower() or "FORBIDDEN" in sys


def test_writer_system_forbids_zh_evidence_disclaimers(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("list-all", "default", "zh", ["A"])
    # ZH-specific forbidden phrases must be named in the prompt so the writer
    # knows to avoid them.
    assert "本节证据未直接命中" in sys
    assert "本节不作断言" in sys


def test_writer_system_includes_confident_expert_voice(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("predict", "default", "en", ["A"])
    assert "CONFIDENT EXPERT MODE" in sys
    assert "paranoid restraint is the failure mode" in sys


def test_writer_system_drops_old_tight_archetype_conditional_policy(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    sys = wr.writer_system("explain-mechanism", "default", "en", ["A"])
    # The old "TIGHT ARCHETYPE-CONDITIONAL POLICY" framing is gone.
    assert "TIGHT ARCHETYPE-CONDITIONAL POLICY" not in sys


# --- D1 + Wave-2 G/A interaction --------------------------------------------


def test_writer_system_still_supports_g_suppress_dedup(monkeypatch, tmp_path):
    """G's _DEDUP_RULE suppression must still work alongside D1 changes."""
    monkeypatch.setenv("DR_CAPEL_G", "on")
    sys = wr.writer_system("list-all", "default", "en", ["A"], suppress_dedup=True)
    assert "CROSS-SECTION NON-REDUNDANCY" not in sys


def test_writer_system_target_scales_with_tier(monkeypatch):
    monkeypatch.setenv("DR_CAPEL_G", "off")
    s_compact = wr.writer_system("recommend", "default", "en", ["A"], depth_tier="compact")
    s_comp = wr.writer_system("explain-mechanism", "default", "en", ["A"], depth_tier="comprehensive")
    # The numeric target in the prompt text grows with tier — extract via
    # the "approximately N words" pattern.
    import re

    def _extract_target(text: str) -> int:
        m = re.search(r"approximately ([\d,]+)\s+words", text)
        assert m, f"no target in prompt: {text[:500]}"
        return int(m.group(1).replace(",", ""))

    assert _extract_target(s_compact) < _extract_target(s_comp)
