"""Unit tests for P3-W4 — mermaid block validation + repair.

P3-W4 opts the writer into emitting mermaid diagrams (Qianfan corpus-
wide pattern, 10/11 articles). The post-pass defends against the 4
common LLM-mermaid failure modes:
  1. Unclosed code fence
  2. Invalid diagram type (first line not timeline/graph/etc.)
  3. Markdown formatting inside node labels (parser breaks)
  4. (out of scope: decorative duplication — semantic, caught by reviewer)
"""

from deep_research.pipeline.mermaid_validate import repair


def test_repair_valid_timeline_block_passes_unchanged():
    """Well-formed timeline: no repairs, n_blocks_valid = 1."""
    text = (
        "Some prose.\n\n"
        "```mermaid\n"
        "timeline\n"
        "  title Quantum milestones\n"
        "  1994 : Shor algorithm\n"
        "  2019 : Quantum supremacy\n"
        "```\n\n"
        "More prose."
    )
    out, stats = repair(text)
    assert stats["n_blocks_found"] == 1
    assert stats["n_blocks_valid"] == 1
    assert stats["n_blocks_markdown_stripped"] == 0
    assert stats["n_blocks_fence_repaired"] == 0
    assert stats["n_blocks_stripped_invalid_type"] == 0
    assert "timeline" in out


def test_repair_valid_graph_block_passes_unchanged():
    """`graph LR` and `flowchart` syntax are valid."""
    text = "```mermaid\ngraph LR\n  A[Input] --> B[Process]\n  B --> C[Output]\n```"
    out, stats = repair(text)
    assert stats["n_blocks_valid"] == 1
    assert "graph LR" in out


def test_repair_strips_markdown_in_node_labels():
    """`**bold**` / `*italic*` / `[^N]` / `[link](url)` inside node labels
    get stripped — the mermaid parser breaks on them."""
    text = (
        "```mermaid\n"
        "graph LR\n"
        "  A[**Bold label**] --> B[*Italic* label]\n"
        "  B --> C[Link [click](http://x)]\n"
        "  C --> D[Footnote [^1] ref]\n"
        "```"
    )
    out, stats = repair(text)
    assert stats["n_blocks_markdown_stripped"] == 1
    assert "**Bold label**" not in out
    assert "Bold label" in out
    assert "*Italic*" not in out
    assert "[^1]" not in out


def test_repair_closes_unclosed_fence():
    """A mermaid block without terminating triple-backtick gets one
    appended."""
    text = "Body text.\n\n```mermaid\ntimeline\n  2025 : event\n  2026 : event\n"  # missing closing ```
    out, stats = repair(text)
    assert stats["n_blocks_fence_repaired"] == 1
    assert out.endswith("```")


def test_repair_strips_invalid_diagram_type():
    """A mermaid block whose first non-blank line is not a valid diagram
    type → entire block removed."""
    text = "Before.\n\n```mermaid\nnonsense_diagram_type\n  unrelated content\n```\n\nAfter."
    out, stats = repair(text)
    assert stats["n_blocks_stripped_invalid_type"] == 1
    assert "nonsense_diagram_type" not in out
    assert "Before." in out
    assert "After." in out


def test_repair_handles_multiple_blocks_independently():
    """An article with 3 mermaid blocks: each repaired independently."""
    text = (
        "```mermaid\n"
        "timeline\n"
        "  1994 : Shor\n"
        "```\n\n"
        "```mermaid\n"
        "graph LR\n"
        "  A[**bold**] --> B[clean]\n"
        "```\n\n"
        "```mermaid\n"
        "invalid_type_here\n"
        "  whatever\n"
        "```"
    )
    out, stats = repair(text)
    assert stats["n_blocks_found"] == 3
    assert stats["n_blocks_valid"] == 2  # first 2 pass; third stripped
    assert stats["n_blocks_markdown_stripped"] == 1
    assert stats["n_blocks_stripped_invalid_type"] == 1


def test_repair_idempotent():
    """Running repair twice produces the same output."""
    text = "```mermaid\ngraph LR\n  A[**bold**] --> B[clean]\n```"
    out_1, _ = repair(text)
    out_2, stats_2 = repair(out_1)
    assert out_1 == out_2
    # Second pass finds nothing to strip.
    assert stats_2["n_blocks_markdown_stripped"] == 0


def test_repair_handles_empty_input_gracefully():
    """Empty string → no crash, no blocks found."""
    out, stats = repair("")
    assert out == ""
    assert stats["n_blocks_found"] == 0


def test_repair_handles_none_input_gracefully():
    """None → None passthrough."""
    out, stats = repair(None)
    assert out is None
    assert stats["n_blocks_found"] == 0


def test_repair_preserves_non_mermaid_code_blocks():
    """A ```python` / ```bash` / etc. code block is NOT a mermaid block;
    repair leaves it alone."""
    text = "Some prose.\n\n```python\ndef foo(): pass\n```\n\n```mermaid\ngraph LR\n  A --> B\n```"
    out, stats = repair(text)
    assert stats["n_blocks_found"] == 1  # only the mermaid block
    assert "def foo(): pass" in out


def test_repair_returns_required_stats_keys():
    """Pin the stats dict keys."""
    _, stats = repair("body")
    expected = {
        "n_blocks_found",
        "n_blocks_valid",
        "n_blocks_markdown_stripped",
        "n_blocks_fence_repaired",
        "n_blocks_stripped_invalid_type",
    }
    assert set(stats.keys()) == expected, f"got {set(stats.keys())}"


def test_repair_sequence_diagram_valid():
    """`sequenceDiagram` is a valid mermaid type."""
    text = "```mermaid\nsequenceDiagram\n  A->>B: Message\n```"
    out, stats = repair(text)
    assert stats["n_blocks_valid"] == 1
    assert "sequenceDiagram" in out
