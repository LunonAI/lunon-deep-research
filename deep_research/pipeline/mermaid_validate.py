"""P3-W4 (2026-05-27): lightweight mermaid block validation + repair.

The Qianfan-verified pattern (10/11 articles, 1-19 mermaid blocks each)
shows semantic diagrams are a corpus-wide engine move. P3-W4 opts the
writer in via `_MERMAID_DIRECTIVE`. This post-pass defends against the
4 common LLM-mermaid failure modes:

  1. Unclosed code fence: ```mermaid ... (no terminating ```)
  2. Invalid diagram type (first non-blank line not one of
     timeline / graph / flowchart / sequenceDiagram / stateDiagram /
     pie / gantt)
  3. Markdown formatting inside node labels (`**bold**`, `*italic*`,
     `[^N]` footnote refs, `[link](url)`) — mermaid parser breaks
  4. Decorative duplication detection is out of scope (semantic, not
     syntactic — caught by reviewer rather than parser)

Repairs (in priority order):
  - Markdown-in-node strip: remove `**`, `*`, `[^N]`, `` ` `` inside `[...]`
    or `(...)` node label brackets.
  - Unclosed fence: append a closing triple-backtick when missing.
  - Invalid diagram type: strip the entire block (better than a malformed
    rendering — would otherwise show raw mermaid syntax in the article).

Idempotent. Fail-soft on bad input.

Library choice: rolled local rather than pinning `mermaid-validator`
(GitHub lvy010, 2026) because the latter requires `mermaid-cli` which
needs npm + Node.js + headless Chromium — too heavy a runtime dep for
4 syntactic checks. If the corpus survey demonstrates the local strip
under-fires, swap to the library in a follow-up.
"""

import re

_VALID_DIAGRAM_TYPES = (
    "timeline",
    "graph",
    "flowchart",
    "sequenceDiagram",
    "stateDiagram",
    "stateDiagram-v2",
    "classDiagram",
    "erDiagram",
    "journey",
    "gantt",
    "pie",
    "requirementDiagram",
    "gitGraph",
    "C4Context",
    "mindmap",
)

# Match a fenced mermaid block. Capture: (1) inner content, (2) terminating
# fence (may be empty if unclosed at EOF).
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)(```|\Z)", re.DOTALL)


def _strip_markdown_in_node_labels(content: str) -> tuple[str, int]:
    """Inside mermaid content, strip markdown that breaks the parser.

    Two passes:
      1. Whole-content strip of footnote refs `[^N]` and markdown links
         `[text](url)` — these break the parser regardless of whether
         they're inside or outside a node label, and they're easy to
         identify unambiguously.
      2. Inside `[...]` and `(...)` node labels, strip `**bold**`,
         `*italic*`, and `` `code` `` markdown.

    Returns (cleaned_content, 1 if any change else 0). The `n_strips`
    return is an indicator (0/1) rather than count to match the stats
    semantic of "this block needed repair" — finer per-strip counts
    don't add downstream signal.
    """
    original = content

    # Pass 1: whole-content strips for unambiguous patterns. Footnote
    # refs `[^N]` are always wrong inside a mermaid block — there's no
    # cite-resolution in the diagram renderer. Markdown links
    # `[text](url)` → `text` strip mirrors the same logic.
    content = re.sub(r"\[\^[^\]]+\]", "", content)
    content = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", content)

    # Pass 2: emphasis markdown inside label brackets. We process
    # `[...]` and `(...)` separately. NB: post-pass-1, footnote and
    # link patterns are gone — pass 2 only needs to strip emphasis
    # and code spans.
    def _clean_label(m: re.Match) -> str:
        body = m.group(1)
        cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", body)
        cleaned = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", cleaned)
        cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
        return f"{m.group(0)[0]}{cleaned}{m.group(0)[-1]}"

    content = re.sub(r"\[([^\[\]\n]+)\]", _clean_label, content)
    content = re.sub(r"\(([^\(\)\n]+)\)", _clean_label, content)
    n = 1 if content != original else 0
    return content, n


def _first_meaningful_line(content: str) -> str:
    for line in content.splitlines():
        s = line.strip()
        if s and not s.startswith("%%"):  # %% is mermaid comment
            return s
    return ""


def _is_valid_diagram_type(content: str) -> bool:
    first = _first_meaningful_line(content)
    if not first:
        return False
    for kw in _VALID_DIAGRAM_TYPES:
        # First token (case-sensitive for mermaid keywords). `flowchart LR`,
        # `graph TB`, etc. all start with the keyword.
        if first == kw or first.startswith(f"{kw} ") or first.startswith(f"{kw}\t"):
            return True
    return False


def repair(text: str | None) -> tuple[str | None, dict]:
    """Validate + repair every mermaid block in `text`.

    Returns (repaired_text, stats):
      {
        "n_blocks_found": int,
        "n_blocks_valid": int,
        "n_blocks_markdown_stripped": int,
        "n_blocks_fence_repaired": int,
        "n_blocks_stripped_invalid_type": int,
      }

    Passthrough for `None` / non-`str` / empty input — `(text, zero_stats)` —
    so the post-pass can be wired into the orchestrator unconditionally
    without a `None` guard at the call site.
    """
    stats = {
        "n_blocks_found": 0,
        "n_blocks_valid": 0,
        "n_blocks_markdown_stripped": 0,
        "n_blocks_fence_repaired": 0,
        "n_blocks_stripped_invalid_type": 0,
    }
    if not isinstance(text, str) or not text:
        return text, stats

    def _process(m: re.Match) -> str:
        stats["n_blocks_found"] += 1
        content = m.group(1) or ""
        terminator = m.group(2) or ""
        # Repair 1: markdown-in-node-labels strip.
        cleaned, n_stripped = _strip_markdown_in_node_labels(content)
        if n_stripped > 0:
            stats["n_blocks_markdown_stripped"] += 1
            content = cleaned
        # Repair 2: invalid diagram type → strip entire block.
        if not _is_valid_diagram_type(content):
            stats["n_blocks_stripped_invalid_type"] += 1
            return ""  # remove the malformed block
        # Repair 3: unclosed fence → append closing triple-backtick.
        if terminator != "```":
            stats["n_blocks_fence_repaired"] += 1
            terminator = "```"
        stats["n_blocks_valid"] += 1
        return f"```mermaid\n{content}{terminator}"

    repaired = _MERMAID_BLOCK_RE.sub(_process, text)
    return repaired, stats
