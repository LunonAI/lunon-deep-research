"""A1 (2026-05-29): pin that the echoable scaffolding literals the gemini
leaderboard judge flagged as leaking into prose are NOT present as verbatim,
copy-able template sentences in the writer prompts.

Root cause (Wave 0 diagnosis): the writer prompts injected complete example
sentences — `"Per the rubric this entity is strong on R-2, fails R-1/R-3…"`
(rubric verdict) and `"Where one might expect X, the system resolves into Y
because Z"` (insight resolution clause) — which the writer echoed VERBATIM into
body prose. On the gemini judge this cost readability (id37 +0.5 "show-off
scaffolding"; the R-N / publish / instantiate tokens showed up in ZH prose).
The directives must describe the SHAPE in the writer's own words, never hand it
a sentence to copy. This is a source-string pin so a future edit can't silently
re-introduce an echoable template.
"""

import inspect

from deep_research import writing_rules as wr
from deep_research.pipeline import writer

_WRITER_SRC = inspect.getsource(writer)

# Verbatim, copy-able template fragments that must never appear in the prompts.
_FORBIDDEN = (
    "Where one might expect",
    "Per the rubric this",
    "strong on R-2",
    "resolves into Y because Z",
)


def test_no_echoable_scaffolding_in_writer_source():
    for s in _FORBIDDEN:
        assert s not in _WRITER_SRC, f"echoable scaffolding literal still in writer prompts: {s!r}"


def test_no_echoable_scaffolding_in_insight_min():
    assert "Where one might expect" not in wr._INSIGHT_MIN


def test_rubric_verdict_directive_kept_but_sanitized():
    """The Insight-earning comparative-verdict requirement must SURVIVE (we win
    Insight on the leaderboard — don't regress it); only the echoable literal +
    the R-N/'per the rubric' scaffolding tokens are removed, and the verdict is
    required to be its own sentence (A4 de-stacking)."""
    assert "COMPARATIVE VERDICT" in _WRITER_SRC
    assert "human-readable LABEL" in _WRITER_SRC
    assert "own sentence" in _WRITER_SRC.lower()
