"""Unit tests for P3-W4 — contrarian-vs-causal_chain co-firing disambiguation.

W3 smoke (2026-05-26) showed contrarian rate going 37.3% → 52.8% while
causal_chain went 0% → 27.8% — co-fire on prose like "Despite the standard
reading that X, Y leads to Z" (contrarian frame + 2+ causal markers).
The W3-smoke hypothesis (verified): rate inflation is detector noise.

P3-W4 resolves by classifying co-firing leaves as causal_chain ONLY.
Tests pin: co-fire → causal_chain only; pure contrarian (no chain) →
contrarian; pure causal_chain (no contrarian frame) → causal_chain.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from p2_writer_compliance import _classify_leaf_elements  # noqa: E402


def test_co_firing_leaf_classified_as_causal_chain_only():
    """Prose: contrarian frame + 2+ causal markers → causal_chain only."""
    leaf = (
        "Despite the standard reading, monetary tightening leads to "
        "lower asset prices, which results in reduced consumer spending, "
        "which in turn causes GDP contraction."
    )
    out = _classify_leaf_elements(leaf)
    assert out["causal_chain"] is True, f"expected causal_chain=True; got {out}"
    assert out["contrarian"] is False, f"co-fire should suppress contrarian; got {out}"


def test_pure_contrarian_no_chain_keeps_contrarian():
    """Pure contrarian framing (no multi-step causal): contrarian fires alone."""
    leaf = (
        "Despite the prevailing consensus, the data shows the trend is "
        "actually reversing. Recent surveys contradict the established view."
    )
    out = _classify_leaf_elements(leaf)
    # Verify causal_chain doesn't fire (no 2+ chain markers).
    assert out["causal_chain"] is False, f"unexpected causal_chain on pure-contrarian leaf: {out}"
    assert out["contrarian"] is True, f"contrarian should fire on pure-contrarian leaf: {out}"


def test_pure_causal_chain_no_contrarian_frame_keeps_causal_chain():
    """Multi-step causal without contrarian frame: causal_chain only."""
    leaf = (
        "Policy X reduces input demand, which leads to producer surplus "
        "compression, which results in capacity exits, which causes "
        "supply-side contraction."
    )
    out = _classify_leaf_elements(leaf)
    assert out["causal_chain"] is True
    assert out["contrarian"] is False


def test_single_step_causation_does_not_fire_causal_chain_or_contrarian():
    """A single 'leads to' does NOT cross the ≥2 markers bar."""
    leaf = "Tightening leads to asset-price compression."
    out = _classify_leaf_elements(leaf)
    assert out["causal_chain"] is False
    # No contrarian frame either.
    assert out["contrarian"] is False


def test_other_elements_unaffected_by_disambiguation():
    """Forward_looking / quant / alternative / problem_tradeoff are
    orthogonal to the contrarian-vs-causal_chain disambiguation."""
    leaf = (
        "Despite the consensus, by 2027 deployment will reach 30%-50% range. "
        "An alternative interpretation focuses on tradeoffs between cost "
        "and quality, which leads to capacity reduction, which causes "
        "price increases."
    )
    out = _classify_leaf_elements(leaf)
    # causal_chain fires (≥2 markers), so contrarian suppressed.
    assert out["causal_chain"] is True
    assert out["contrarian"] is False
    # Other elements unaffected.
    assert out["forward_looking"] is True
    assert out["quant"] is True
    assert out["alternative"] is True
