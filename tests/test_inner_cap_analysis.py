"""P3b-OPT2 (2026-05-27): unit coverage for scripts/inner_cap_ab_analysis.py.

The analysis script decides whether INNER_CAP can drop from 3 to 2. It lives in
scripts/ (not a package), so we load it via importlib. These tests pin the
decision logic against the edge cases Greptile flagged across review rounds:
degraded i==2 exclusion, the reached_idx2 denominator, and the "no score
evidence → not safe" guard.
"""

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "inner_cap_ab_analysis.py"
_spec = importlib.util.spec_from_file_location("inner_cap_ab_analysis", _SCRIPT)
analysis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analysis)


def _write_drift(tmp_path, sections):
    """sections: list of (section_id, iters-list). One task per line."""
    p = tmp_path / "drift.jsonl"
    lines = [json.dumps({"inner_loop_trajectory": [{"section": sid, "iters": iters}]}) for sid, iters in sections]
    p.write_text("\n".join(lines) + "\n")
    return p


def _it(i, *, g=True, scored=True, ok=False, ms=5.0, degraded=False):
    return {"i": i, "grounding_ok": g, "scored": scored, "score_ok": ok, "min_score": ms, "degraded": degraded}


def test_never_reached_i2_is_safe(tmp_path):
    """No section runs a 3rd pass → cap=2 behavior-identical → safe."""
    p = _write_drift(tmp_path, [("S1", [_it(0, ok=True, ms=8.0)])])
    r = analysis.analyze(p)
    assert r["reached_idx2"] == 0
    assert r["cap2_safe"] is True


def test_degraded_i2_excluded(tmp_path):
    """A degraded i==2 (synthetic pass) is excluded from reached/benefit."""
    iters = [_it(0, ok=False), _it(1, ok=False), _it(2, ok=True, ms=10.0, degraded=True)]
    p = _write_drift(tmp_path, [("S1", iters)])
    r = analysis.analyze(p)
    assert r["degraded_idx2_excluded"] == 1
    assert r["reached_idx2"] == 0
    assert r["benefited_from_idx2"] == 0


def test_no_score_pairs_is_not_safe(tmp_path):
    """Reached i==2 but i==1 grounding-failed (no score pair) → no score
    evidence → cap2_safe False even though benefit_rate is 0. (Greptile r4.)"""
    iters = [
        _it(0, g=False, scored=False, ok=None, ms=None),
        _it(1, g=False, scored=False, ok=None, ms=None),
        _it(2, ok=False, ms=5.0),
    ]
    p = _write_drift(tmp_path, [("S1", iters)])
    r = analysis.analyze(p)
    assert r["reached_idx2"] == 1
    assert r["n_score_gain_samples"] == 0
    assert r["cap2_safe"] is False, "no score evidence must NOT be treated as safe"


def test_genuine_benefit_keeps_cap3(tmp_path):
    """The 3rd pass flips a section to passing → high benefit_rate → not safe."""
    iters = [_it(0, ok=False, ms=4.0), _it(1, ok=False, ms=4.5), _it(2, ok=True, ms=7.0)]
    p = _write_drift(tmp_path, [("S1", iters)])
    r = analysis.analyze(p)
    assert r["reached_idx2"] == 1
    assert r["benefited_from_idx2"] == 1
    assert r["benefit_rate"] == 1.0
    assert r["cap2_safe"] is False


def test_wasteful_3rd_pass_is_safe(tmp_path):
    """Many sections reach i==2, none flip to passing, scores barely move →
    cap=2 empirically safe (with real score-pair evidence)."""
    sections = []
    for n in range(20):
        # i==1 scored-but-failing (gives a score pair), i==2 still failing, ~flat
        iters = [_it(0, ok=False, ms=5.0), _it(1, ok=False, ms=5.0), _it(2, ok=False, ms=5.05)]
        sections.append((f"S{n}", iters))
    p = _write_drift(tmp_path, sections)
    r = analysis.analyze(p)
    assert r["reached_idx2"] == 20
    assert r["benefit_rate"] == 0.0
    assert r["n_score_gain_samples"] == 20
    assert r["mean_score_gain_at_idx2"] < analysis.SCORE_GAIN_THRESHOLD
    assert r["cap2_safe"] is True
