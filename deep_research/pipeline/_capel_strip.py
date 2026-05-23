"""P2-Wave-2-A: CAPEL countdown-marker post-strip.

CAPEL (arXiv 2508.13805) instructs the writer to emit inline countdown
markers `<N>word<N-1>word...<0>` so the model is forced to count down to
the target length. This module strips the markers from the writer's output
before downstream nodes (grounding, inner_loop, refiner, validation) ever
see the text.

Strip is fail-soft: if the writer never used markers, the regex finds
nothing and the original text is returned. Violation = back-to-back
markers like `<5><4>` with no intervening content token; we count these
so a high violation rate surfaces in drift telemetry without blocking
the pipeline.
"""

from __future__ import annotations

import re

# CAPEL marker token: `<` then 1-5 digits then `>`. Tight digit range to
# avoid colliding with markdown-like patterns or sentinel angle-bracket
# constructs the writer might legitimately emit.
_MARKER_RE = re.compile(r"<\d{1,5}>")
# Two markers with only whitespace between them = violation (paper's hard
# rule: an intervening content token is required between markers).
_BACK_TO_BACK_RE = re.compile(r"<\d{1,5}>\s*<\d{1,5}>")
# Collapse runs of >=2 whitespace left after removing adjacent markers.
_DOUBLED_WS_RE = re.compile(r"[ \t]{2,}")


def strip_capel_markers(text: str) -> tuple[str, dict]:
    """Strip CAPEL markers from writer output.

    Returns (stripped_text, stats):
        n_markers_stripped: total markers removed.
        n_violations: count of back-to-back marker pairs (no intervening
            token) — a model-compliance metric, not a fatal condition.
    """
    if not text:
        return text, {"n_markers_stripped": 0, "n_violations": 0}
    n_violations = len(_BACK_TO_BACK_RE.findall(text))
    # Replace each marker with a single space — handles `the<899>quick`
    # (no surrounding whitespace) without gluing the words together.
    stripped, n_stripped = _MARKER_RE.subn(" ", text)
    # Collapse any runs of horizontal whitespace introduced by adjacent
    # marker stripping. Newlines are preserved so paragraph structure is
    # untouched.
    stripped = _DOUBLED_WS_RE.sub(" ", stripped)
    return stripped, {"n_markers_stripped": n_stripped, "n_violations": n_violations}
