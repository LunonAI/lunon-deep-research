"""Unit tests for P3-W4 — _MERMAID_DIRECTIVE wired into writer prompt."""

from deep_research import writing_rules as wr


def test_mermaid_directive_present_in_module():
    """Pin the constant exists with load-bearing semantics."""
    assert "_MERMAID_DIRECTIVE" in dir(wr)
    rule = wr._MERMAID_DIRECTIVE
    assert "SEMANTIC DIAGRAM DIRECTIVE" in rule
    # Four diagram shapes enumerated.
    assert "timeline" in rule
    assert "dependency" in rule
    assert "decision tree" in rule
    assert "multi-stage process" in rule
    # Forbidden forms enumerated.
    assert "FORBIDDEN" in rule
    assert "**bold**" in rule


def test_writer_system_includes_mermaid_directive():
    """The directive must be in the writer's middle_block."""
    sys = wr.writer_system("predict", "default", "en", ["S1", "S2"])
    assert "SEMANTIC DIAGRAM DIRECTIVE" in sys


def test_mermaid_directive_enumerates_valid_diagram_types():
    """The directive lists the valid mermaid diagram-type keywords —
    drift would let the writer emit invalid types (parser breaks)."""
    rule = wr._MERMAID_DIRECTIVE
    # Pin the 5 most common types the writer is likely to use.
    for kw in ("timeline", "graph", "flowchart", "sequenceDiagram", "stateDiagram"):
        assert kw in rule, f"{kw} missing from valid-types list in directive"
